"""The console: what it shows, what it can change, and who may reach it."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from pharness.console import ConsoleApi, build_console_app, new_token
from pharness.core.approvals import Outcome
from pharness.core.policy.engine import Request
from pharness.core.policy.tiers import Tier
from pharness.runtime import build_runtime


@pytest.fixture
def scene(tmp_path: Path, monkeypatch):
    project = tmp_path / "proj" / "src"
    project.mkdir(parents=True)
    (project / "app.ts").write_text("export const x = 1\n", encoding="utf-8")

    config = tmp_path / "config.toml"
    config.write_text(
        "[[workspace]]\n"
        'alias = "shop"\n'
        f'path = "{(tmp_path / "proj").as_posix()}"\n'
        'allow_commands = ["echo allowed"]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    runtime = build_runtime(config, interactive_prompts=False)
    api = ConsoleApi(runtime)
    token = new_token()
    # TestClient calls itself "testclient" by default, which is not loopback --
    # and the console refuses anything that is not.
    http = TestClient(build_console_app(api, token), client=("127.0.0.1", 5000))
    return runtime, api, http, token


@pytest.fixture
def client(scene):
    _, _, http, token = scene
    http.headers.update({"x-pharness-token": token})
    return http


# -- who may reach it ----------------------------------------------------------


def test_the_console_needs_its_token(scene):
    _, _, http, _ = scene
    assert http.get("/api/status").status_code == 401
    assert http.get("/api/status", headers={"x-pharness-token": "wrong"}).status_code == 401


def test_the_page_itself_needs_the_token(scene):
    _, _, http, token = scene
    assert http.get("/").status_code == 401
    page = http.get(f"/?token={token}")
    assert page.status_code == 200
    assert token in page.text  # the page carries it forward for its own calls


def test_a_request_from_elsewhere_is_refused(scene):
    """The console hands permissions out and takes them back; it stays local."""
    _, api, _, token = scene
    app = build_console_app(api, token)
    remote = TestClient(app, client=("10.1.2.3", 5000))
    response = remote.get("/api/status", headers={"x-pharness-token": token})
    assert response.status_code == 403
    assert "local only" in response.json()["error"]


# -- what it shows -------------------------------------------------------------


def test_status_reports_the_shape_of_things(client):
    body = client.get("/api/status").json()
    assert body["workspaces"] == 1
    assert body["audit_intact"] is True
    assert body["can_prompt"] is False  # nothing here can ask


def test_projects_show_their_permissions(client):
    [workspace] = client.get("/api/workspaces").json()
    assert workspace["alias"] == "shop"
    assert workspace["mode"] == "auto-edit"
    assert workspace["allow_commands"] == ["echo allowed"]


def test_activity_can_be_narrowed_to_refusals(scene, client):
    runtime, *_ = scene
    workspace = runtime.registry.get("shop")
    for command in ("echo allowed", "rm -rf /"):
        runtime.gateway.call(
            Request("chat", "shell", None, Tier.EXEC_OTHER, {"command": command}, command),
            workspace,
            lambda: runtime.shell(workspace).exec("echo allowed", 5),
        )

    everything = client.get("/api/activity", params={"limit": 20}).json()
    refused = client.get("/api/activity", params={"limit": 20, "decision": "deny"}).json()
    assert len(everything) >= 2
    assert refused and all(row["decision"] == "deny" for row in refused)


def test_doctor_reports_checks(client):
    checks = client.get("/api/doctor").json()
    assert checks and all({"ok", "label", "level"} <= set(check) for check in checks)


# -- what it can change --------------------------------------------------------


def test_elevation_is_granted_bounded_and_recorded(scene, client):
    runtime, *_ = scene
    granted = client.post("/api/elevate", json={"alias": "shop", "minutes": 30}).json()
    assert granted["expires_at"]

    status = client.get("/api/status").json()
    assert status["elevated"][0]["alias"] == "shop"
    assert 0 < status["elevated"][0]["expires_in_sec"] <= 30 * 60

    assert runtime.audit.read()[-1]["event"]["disposition"] == "elevated"

    client.post("/api/revoke-elevation", json={"alias": "shop"})
    assert client.get("/api/status").json()["elevated"] == []


def test_a_waiting_request_can_be_answered_from_the_console(scene, client):
    """The console is a second place to answer, alongside the window."""
    runtime, *_ = scene
    runtime.queue._timeout = 10

    class Silent:
        name = "test"
        interactive = True

        def present(self, request, respond):
            return None

        def withdraw(self, request_id):
            return None

        def notify(self, title, body):
            return None

    runtime.queue._notifier = Silent()
    workspace = runtime.registry.get("shop")
    answers: list = []

    threading.Thread(
        target=lambda: answers.append(
            runtime.gateway.call(
                Request(
                    "chat", "shell", None, Tier.EXEC_OTHER, {"command": "echo later"}, "echo later"
                ),
                workspace,
                lambda: runtime.shell(workspace).exec("echo later", 5),
            )
        ),
        daemon=True,
    ).start()

    deadline = time.monotonic() + 5
    while not client.get("/api/pending").json() and time.monotonic() < deadline:
        time.sleep(0.05)

    [pending] = client.get("/api/pending").json()
    assert "echo later" in pending["payload"]  # the literal request, not a summary

    result = client.post(
        "/api/answer", json={"request_id": pending["id"], "outcome": Outcome.ONCE.value}
    ).json()
    assert result["ok"]

    deadline = time.monotonic() + 5
    while not answers and time.monotonic() < deadline:
        time.sleep(0.05)
    assert answers and answers[0].ok


def test_answering_something_that_already_went_away(client):
    assert not client.post("/api/answer", json={"request_id": "a999", "outcome": "once"}).json()[
        "ok"
    ]


def test_a_nonsense_outcome_is_refused(client):
    body = client.post("/api/answer", json={"request_id": "a1", "outcome": "obviously-not"}).json()
    assert not body["ok"]


def test_remembered_permissions_can_be_taken_back(scene, client):
    """A permission nobody can find again is a permission nobody can revoke."""
    runtime, *_ = scene
    from pharness.core.policy.rules import Rule

    runtime.engine.remember(Rule(action="allow", tool="shell", workspace="shop", reason="test"))
    [rule] = client.get("/api/rules").json()
    assert rule["tool"] == "shell"

    assert client.post("/api/forget-rule", json={"index": rule["index"]}).json()["ok"]
    assert client.get("/api/rules").json() == []


def test_changes_can_be_put_back_from_the_console(scene, client):
    runtime, *_ = scene
    workspace = runtime.registry.get("shop")
    runtime.files(workspace).apply_patch(
        "--- a/src/app.ts\n+++ b/src/app.ts\n@@ -1 +1 @@\n"
        "-export const x = 1\n+export const x = 2\n"
    )

    [checkpoint] = client.get("/api/checkpoints", params={"alias": "shop"}).json()
    assert checkpoint["changes"][0]["path"] == "src/app.ts"

    undone = client.post("/api/undo", json={"alias": "shop", "checkpoint": checkpoint["id"]}).json()
    assert undone["ok"]
    assert "const x = 1" in (workspace.root / "src" / "app.ts").read_text(encoding="utf-8")


def test_the_stop_button_clears_everything(scene, client):
    runtime, *_ = scene
    import sys

    runtime.process.spawn(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        runtime.registry.get("shop").root,
        runtime.env,
    )
    assert client.get("/api/processes").json()

    result = client.post("/api/emergency-stop").json()
    assert result["stopped"] >= 1
    assert runtime.audit.read()[-1]["event"]["disposition"] == "emergency_stop"


def test_bad_arguments_are_reported_not_raised(client):
    assert client.get("/api/checkpoints", params={"alias": "nope"}).status_code == 500
    assert client.post("/api/undo", json={}).status_code == 400


def test_the_page_is_self_contained(scene):
    """No build step and no CDN: a console that needs a toolchain stops working
    the day the toolchain does."""
    _, _, http, token = scene
    page = http.get(f"/?token={token}").text
    assert "<script" in page and "</script>" in page
    assert "http://" not in page.split("<script>")[0].replace("http://127.0.0.1", "")
    assert json.dumps  # keeps the import honest

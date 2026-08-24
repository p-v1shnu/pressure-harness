"""Project runners. Scripts are driven with the current interpreter so the
suite does not depend on node being installed."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from pharness.adapters import select
from pharness.core.config import ContextSettings, parse_config
from pharness.core.env import build_env
from pharness.core.tools import ProcessTools, ProjectTools
from pharness.core.workspace import WorkspaceRegistry


def make_tools(root: Path, scripts: dict[str, str]) -> ProjectTools:
    adapters = select()
    registry = WorkspaceRegistry.from_config(
        parse_config({"workspace": [{"alias": "p", "path": str(root), "scripts": scripts}]}),
        adapters.paths,
    )
    return ProjectTools(
        workspace=registry.get("p"),
        process=adapters.process_factory(root / ".logs"),
        context=ContextSettings(),
        env=build_env(os.environ, adapters.platform),
    )


@pytest.fixture
def project(tmp_path: Path) -> ProjectTools:
    root = tmp_path / "proj"
    root.mkdir()
    return make_tools(
        root,
        {
            "test": f"{sys.executable} -c print('tests_passed')",
            "lint": f"{sys.executable} -c raise_SystemExit(1)",
            "dev": f"{sys.executable} -u -c "
            "import_time;__import__('time');print('serving',flush=True)",
        },
    )


def test_configured_script_beats_detection(tmp_path: Path):
    """The user's mapping is a decision; detection is a guess."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "package.json").write_text(
        json.dumps({"scripts": {"test": "npm-would-run-this"}}), encoding="utf-8"
    )
    tools = make_tools(root, {"test": f"{sys.executable} --version"})
    argv, why = tools.resolve("test")
    assert argv[0] == sys.executable
    assert "configured" in why


def test_package_manager_comes_from_the_lockfile(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}), encoding="utf-8")
    (root / "pnpm-lock.yaml").write_text("", encoding="utf-8")

    tools = make_tools(root, {})
    assert tools.package_manager() == "pnpm"
    argv, _ = tools.resolve("test")
    assert argv[:2] == ["pnpm", "test"]


def test_resolution_reports_what_will_actually_run(project: ProjectTools):
    """`npm test` is only as safe as package.json, so the real command is shown."""
    result = project.run("test")
    assert result.ok
    assert sys.executable in result.text
    assert "configured for this workspace" in result.text
    assert "tests_passed" in result.text


def test_a_failing_task_is_reported_as_a_failure(project: ProjectTools):
    result = project.run("lint")
    assert not result.ok
    assert result.meta["exit_code"] != 0


def test_undefined_task_says_how_to_define_it(project: ProjectTools):
    result = project.run("build")
    assert not result.ok
    assert "workspace.scripts" in result.text


def test_unknown_task_name_is_refused(project: ProjectTools):
    assert not project.run("deploy").ok


def test_dev_must_go_through_start_dev(project: ProjectTools):
    assert not project.run("dev").ok


def test_describe_lists_every_task(project: ProjectTools):
    text = project.describe().text
    assert "test" in text and "typecheck" in text


def test_timeout_is_reported_without_hanging(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    tools = make_tools(root, {"test": f"{sys.executable} -c __import__('time').sleep(30)"})
    result = tools.run("test", timeout_sec=0.5)
    assert not result.ok and "timed out" in result.text


def test_start_dev_spawns_and_can_be_stopped(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    code = "import time,sys\nwhile True:\n    print('serving',flush=True)\n    time.sleep(0.05)\n"
    (root / "server.py").write_text(code, encoding="utf-8")
    tools = make_tools(root, {"dev": f"{sys.executable} -u server.py"})

    started = tools.start_dev()
    assert started.ok
    process_tools = ProcessTools(tools.process, ContextSettings())

    deadline = time.monotonic() + 5
    while "serving" not in process_tools.logs(started.meta["process_id"]).text:
        assert time.monotonic() < deadline, "dev server produced no output"
        time.sleep(0.05)

    assert "running" in process_tools.list().text
    assert process_tools.stop(started.meta["process_id"]).ok
    assert "exited" in process_tools.list().text


def test_start_dev_without_a_dev_script(project: ProjectTools, tmp_path: Path):
    root = tmp_path / "empty"
    root.mkdir()
    assert not make_tools(root, {}).start_dev().ok


def test_dev_reports_the_address_the_server_printed(tmp_path: Path):
    """Opening the page two seconds early looks exactly like a broken change."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "server.py").write_text(
        "import time\nprint('  Local:   http://localhost:5173/', flush=True)\n"
        "while True: time.sleep(0.1)\n",
        encoding="utf-8",
    )
    tools = make_tools(root, {"dev": f"{sys.executable} -u server.py"})

    started = tools.start_dev()
    try:
        assert started.meta["url"] == "http://localhost:5173"
        assert "serving at" in started.text
    finally:
        tools.process.stop_all()


def test_dev_says_so_when_no_address_appears(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "quiet.py").write_text("import time\nwhile True: time.sleep(0.1)\n", encoding="utf-8")
    tools = make_tools(root, {"dev": f"{sys.executable} -u quiet.py"})

    started = tools.start_dev()
    try:
        assert started.meta["url"] is None
        assert "no address printed" in started.text
    finally:
        tools.process.stop_all()


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("  ➜  Local:   http://localhost:5173/", "http://localhost:5173"),
        ("ready - started server on http://127.0.0.1:3000", "http://127.0.0.1:3000"),
        ("Listening on http://[::1]:8080/", "http://[::1]:8080"),
        ("compiled successfully", None),
    ],
)
def test_url_detection(line: str, expected: str | None):
    from pharness.core.tools.project import URL_IN_OUTPUT

    match = URL_IN_OUTPUT.search(line)
    assert (match.group(0).rstrip("/.,") if match else None) == expected

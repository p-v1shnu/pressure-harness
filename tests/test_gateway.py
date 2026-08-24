"""The single path a tool call takes: decide, ask, run, record.

These are the tests that say the policy engine is a control rather than advice.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from pharness.adapters import select
from pharness.adapters.shared.notifier import NullNotifier
from pharness.core.approvals import ApprovalQueue, Outcome
from pharness.core.audit import AuditLog
from pharness.core.config import ContextSettings, parse_config
from pharness.core.env import build_env
from pharness.core.gateway import Gateway
from pharness.core.policy.engine import PolicyEngine, Request
from pharness.core.policy.tiers import Tier
from pharness.core.tools.results import ToolResult
from pharness.core.tools.shell import ShellTools
from pharness.core.workspace import WorkspaceRegistry


class Answering:
    name = "test"
    interactive = True

    def __init__(self, outcome: Outcome = Outcome.ONCE) -> None:
        self.outcome = outcome
        self.presented: list = []

    def present(self, request, respond) -> None:
        self.presented.append(request)
        threading.Thread(
            target=lambda: respond(self.outcome, "answered in a test"), daemon=True
        ).start()

    def withdraw(self, request_id: str) -> None:
        return None

    def notify(self, title: str, body: str) -> None:
        return None


@pytest.fixture
def scene(tmp_path: Path):
    adapters = select()
    root = tmp_path / "proj"
    root.mkdir()

    registry = WorkspaceRegistry.from_config(
        parse_config(
            {
                "workspace": [
                    {
                        "alias": "p",
                        "path": str(root),
                        "allow_commands": ["echo hello"],
                    }
                ]
            }
        ),
        adapters.paths,
    )
    workspace = registry.get("p")
    env = build_env(os.environ, adapters.platform)
    shell = ShellTools(
        workspace,
        adapters.process_factory(tmp_path / "logs"),
        ContextSettings(),
        env,
        adapters.platform,
    )
    audit = AuditLog(tmp_path / "audit.jsonl")

    def build(notifier, **queue_kwargs) -> Gateway:
        return Gateway(
            PolicyEngine(adapters.shell),
            ApprovalQueue(notifier, timeout_sec=queue_kwargs.pop("timeout_sec", 5), **queue_kwargs),
            audit,
        )

    return build, workspace, shell, audit


def request_for(command: str, session: str = "chat") -> Request:
    return Request(
        session_id=session,
        tool="shell",
        declared_tier=Tier.EXEC_OTHER,
        payload={"command": command},
        command_line=command,
    )


def test_allowlisted_commands_run_without_a_prompt(scene):
    """The 95% case. If this prompts, people stop reading prompts."""
    build, workspace, shell, _ = scene
    notifier = Answering()
    gateway = build(notifier)

    result = gateway.call(request_for("echo hello"), workspace, lambda: shell.exec("echo hello"))
    assert result.ok and "hello" in result.text
    assert notifier.presented == []


def test_other_commands_are_asked_about_then_run(scene):
    build, workspace, shell, _ = scene
    notifier = Answering(Outcome.ONCE)
    gateway = build(notifier)

    result = gateway.call(request_for("echo other"), workspace, lambda: shell.exec("echo other"))
    assert result.ok and len(notifier.presented) == 1


def test_a_refusal_stops_the_tool_from_running(scene):
    build, workspace, _, _ = scene
    ran = []
    gateway = build(Answering(Outcome.DENY))

    result = gateway.call(
        request_for("echo nope"), workspace, lambda: ran.append(1) or ToolResult("ran")
    )
    assert not result.ok and ran == []
    assert "refused" in result.text


def test_forbidden_commands_are_never_even_asked_about(scene):
    """No approval path exists for tier 5, so no prompt is shown (PRD 10.3)."""
    build, workspace, _, _ = scene
    notifier = Answering(Outcome.ONCE)
    gateway = build(notifier)

    result = gateway.call(
        request_for("rm -rf /"), workspace, lambda: ToolResult("should never run")
    )
    assert not result.ok
    assert notifier.presented == []


def test_remembering_stops_the_second_prompt(scene):
    build, workspace, shell, _ = scene
    notifier = Answering(Outcome.REMEMBER)
    gateway = build(notifier)

    for _ in range(3):
        gateway.call(request_for("echo twice"), workspace, lambda: shell.exec("echo twice"))
    assert len(notifier.presented) == 1


def test_remembering_does_not_widen_to_other_commands(scene):
    """An approval is bound to the payload, not to the tool (PRD 10.7)."""
    build, workspace, shell, _ = scene
    notifier = Answering(Outcome.REMEMBER)
    gateway = build(notifier)

    gateway.call(request_for("echo one"), workspace, lambda: shell.exec("echo one"))
    gateway.call(request_for("echo two"), workspace, lambda: shell.exec("echo two"))
    assert len(notifier.presented) == 2


def test_session_approval_does_not_reach_another_conversation(scene):
    build, workspace, shell, _ = scene
    notifier = Answering(Outcome.SESSION)
    gateway = build(notifier)

    gateway.call(request_for("echo a", "chat-1"), workspace, lambda: shell.exec("echo a"))
    gateway.call(request_for("echo a", "chat-1"), workspace, lambda: shell.exec("echo a"))
    assert len(notifier.presented) == 1

    gateway.call(request_for("echo a", "chat-2"), workspace, lambda: shell.exec("echo a"))
    assert len(notifier.presented) == 2


def test_an_unattended_machine_refuses(scene):
    build, workspace, shell, _ = scene
    gateway = build(NullNotifier(), timeout_sec=30)

    result = gateway.call(
        request_for("echo unattended"), workspace, lambda: shell.exec("echo unattended")
    )
    assert not result.ok


def test_everything_is_recorded_including_refusals(scene):
    """A refusal is the entry worth having (PRD 10.9)."""
    build, workspace, shell, audit = scene
    gateway = build(Answering(Outcome.DENY))

    gateway.call(request_for("echo hello"), workspace, lambda: shell.exec("echo hello"))
    gateway.call(request_for("echo denied"), workspace, lambda: ToolResult("never"))
    gateway.call(request_for("rm -rf /"), workspace, lambda: ToolResult("never"))

    dispositions = [entry["event"]["disposition"] for entry in audit.read()]
    assert dispositions == ["ran", "deny", "denied"]
    assert audit.verify().intact


def test_the_audit_entry_carries_the_decision_and_the_rule(scene):
    build, workspace, shell, audit = scene
    gateway = build(Answering())
    gateway.call(request_for("echo hello"), workspace, lambda: shell.exec("echo hello"))

    event = audit.read()[-1]["event"]
    assert event["tier"] == "T2"
    assert event["rule"] == "mode-auto-edit"
    assert event["digest"]


def test_a_crashing_tool_is_still_recorded(scene):
    build, workspace, _, audit = scene
    gateway = build(Answering())

    def explode() -> ToolResult:
        raise RuntimeError("tool blew up")

    with pytest.raises(RuntimeError):
        gateway.call(request_for("echo hello"), workspace, explode)

    assert audit.read()[-1]["event"]["disposition"] == "error"

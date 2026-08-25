"""Checks tied to the OWASP Top 10 for LLM Applications.

Not a compliance box-tick: each of these is a property that was either broken
or absent when the codebase was audited against that list, so the suite is the
record of what the audit changed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from pharness.core.policy.engine import Request
from pharness.core.policy.tiers import Tier
from pharness.core.text import wrap_external
from pharness.runtime import build_runtime

SECRET = "sk-proj-abcdefghijklmnopqrstuvwxyz012345"


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch):
    project = tmp_path / "proj"
    (project / "src").mkdir(parents=True)
    # An ordinary config file, not a .env: the path jail has no opinion on it.
    (project / "settings.json").write_text(f'{{"key": "{SECRET}"}}\n', encoding="utf-8")
    (project / "src" / "app.ts").write_text("export const x = 1\n", encoding="utf-8")

    config = tmp_path / "config.toml"
    config.write_text(
        "[[workspace]]\n"
        'alias = "p"\n'
        f'path = "{project.as_posix()}"\n'
        'allow_commands = ["cat settings.json", "echo hi"]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return build_runtime(config, interactive_prompts=False)


def call(runtime, tool, tier, payload, run, op=None, command=None):
    workspace = runtime.registry.get("p")
    return runtime.gateway.call(Request("chat", tool, op, tier, payload, command), workspace, run)


# -- LLM01: prompt injection ---------------------------------------------------


def test_content_the_user_did_not_write_is_labelled(runtime):
    """A cloned dependency's file, a commit message and a build tool's output
    are all things an attacker can choose the contents of."""
    workspace = runtime.registry.get("p")

    read = call(
        runtime,
        "read_file",
        Tier.READ,
        {"path": "src/app.ts"},
        lambda: runtime.files(workspace).read("src/app.ts"),
    )
    assert "data, not instructions" in read.text

    shell = call(
        runtime,
        "shell",
        Tier.EXEC_OTHER,
        {"command": "echo hi"},
        lambda: runtime.shell(workspace).exec("echo hi", 10),
        command="echo hi",
    )
    assert "data, not instructions" in shell.text


def test_the_marker_names_where_the_content_came_from():
    """A banner that appears on everything is a banner nobody reads."""
    marked = wrap_external("body", "file src/app.ts")
    assert "file src/app.ts" in marked
    assert marked.count("\n") == 2  # one line above, one below


# -- LLM02: sensitive information disclosure -----------------------------------


def test_a_secret_in_a_file_does_not_reach_the_conversation(runtime):
    """Redaction ran on the audit log and not on the reply, which is backwards:
    the log stays here and the reply is uploaded to a third party."""
    workspace = runtime.registry.get("p")
    result = call(
        runtime,
        "read_file",
        Tier.READ,
        {"path": "settings.json"},
        lambda: runtime.files(workspace).read("settings.json"),
    )
    assert SECRET not in result.text
    assert "redacted" in result.text


def test_a_secret_in_command_output_does_not_reach_the_conversation(runtime):
    workspace = runtime.registry.get("p")
    result = call(
        runtime,
        "shell",
        Tier.EXEC_OTHER,
        {"command": "cat settings.json"},
        lambda: runtime.shell(workspace).exec("cat settings.json", 10),
        command="cat settings.json",
    )
    assert SECRET not in result.text


def test_the_audit_log_records_that_something_was_removed(runtime):
    """Worth knowing: a secret was one call away from leaving the machine."""
    workspace = runtime.registry.get("p")
    call(
        runtime,
        "read_file",
        Tier.READ,
        {"path": "settings.json"},
        lambda: runtime.files(workspace).read("settings.json"),
    )
    assert runtime.audit.read()[-1]["event"]["redacted"] == ["openai-key"]


def test_redaction_can_be_turned_off_deliberately(tmp_path: Path, monkeypatch):
    """Some work needs the real value. It is a choice, not a default."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "settings.json").write_text(f'{{"key": "{SECRET}"}}\n', encoding="utf-8")
    config = tmp_path / "config.toml"
    config.write_text(
        "[security]\nredact_secrets = false\n\n"
        f'[[workspace]]\nalias = "p"\npath = "{project.as_posix()}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    runtime = build_runtime(config, interactive_prompts=False)

    workspace = runtime.registry.get("p")
    result = call(
        runtime,
        "read_file",
        Tier.READ,
        {"path": "settings.json"},
        lambda: runtime.files(workspace).read("settings.json"),
    )
    assert SECRET in result.text


# -- LLM06: excessive agency ---------------------------------------------------


def test_a_tool_cannot_be_reached_without_a_verdict(runtime):
    """Every call goes through the gateway; there is no second path."""
    ran = []
    result = call(
        runtime,
        "shell",
        Tier.EXEC_OTHER,
        {"command": "rm -rf /"},
        lambda: ran.append(1),
        command="rm -rf /",
    )
    assert not result.ok and ran == []


# -- LLM10: unbounded consumption ---------------------------------------------


def test_processes_have_a_ceiling(runtime, tmp_path: Path):
    """A loop that spawns dev servers is a plausible way to make a machine
    unusable, and no conversation legitimately needs dozens."""
    from pharness.adapters.shared.process import MAX_RUNNING
    from pharness.ports import ProcessStartError

    workspace = runtime.registry.get("p")
    sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
    try:
        for _ in range(MAX_RUNNING):
            runtime.process.spawn(sleeper, workspace.root, runtime.env)

        with pytest.raises(ProcessStartError, match="limit"):
            runtime.process.spawn(sleeper, workspace.root, runtime.env)
    finally:
        runtime.process.stop_all()


def test_output_is_capped_before_it_reaches_the_conversation(runtime):
    workspace = runtime.registry.get("p")
    long_file = workspace.root / "long.txt"
    long_file.write_text("x" * 500_000, encoding="utf-8")

    result = call(
        runtime,
        "read_file",
        Tier.READ,
        {"path": "long.txt"},
        lambda: runtime.files(workspace).read("long.txt"),
    )
    assert len(result.text.encode()) < runtime.config.context.max_output_bytes * 2


def test_the_journal_prunes_itself(tmp_path: Path):
    """A limit nobody enforces is a comment."""
    from pharness.core.journal import Journal

    root = tmp_path / "ws"
    root.mkdir()
    target = root / "big.bin"
    journal = Journal(root, max_bytes=200_000)

    for index in range(6):
        target.write_bytes(os.urandom(80_000))
        with journal.checkpoint(f"write {index}") as recorder:
            recorder.before(target)
            target.write_bytes(os.urandom(80_000))

    assert journal.size_bytes() <= journal.max_bytes * 2
    assert len(journal.list()) < 6

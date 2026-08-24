"""The shell tool. Small by design: the judging already happened."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pharness.adapters import select
from pharness.core.config import ContextSettings, parse_config
from pharness.core.env import build_env
from pharness.core.tools.shell import ShellTools
from pharness.core.workspace import WorkspaceRegistry


@pytest.fixture
def shell(tmp_path: Path) -> ShellTools:
    adapters = select()
    root = tmp_path / "proj"
    root.mkdir()
    registry = WorkspaceRegistry.from_config(
        parse_config({"workspace": [{"alias": "p", "path": str(root)}]}), adapters.paths
    )
    return ShellTools(
        workspace=registry.get("p"),
        process=adapters.process_factory(tmp_path / "logs"),
        context=ContextSettings(),
        env=build_env(os.environ, adapters.platform),
        platform=adapters.platform,
    )


def test_runs_a_command_and_shows_it(shell: ShellTools):
    result = shell.exec("echo hello")
    assert result.ok
    assert result.text.startswith("$ echo hello")
    assert "hello" in result.text


def test_a_failing_command_is_a_failed_result(shell: ShellTools):
    result = shell.exec("exit 3")
    assert not result.ok and result.meta["exit_code"] == 3


def test_empty_commands_are_refused(shell: ShellTools):
    assert not shell.exec("   ").ok


def test_runs_in_the_workspace(shell: ShellTools):
    (shell.workspace.root / "marker.txt").write_text("x", encoding="utf-8")
    listing = "Get-ChildItem -Name" if shell.platform == "windows" else "ls"
    assert "marker.txt" in shell.exec(listing).text


def test_output_is_capped(shell: ShellTools):
    """Long output is the normal case, not the exceptional one (PRD 11)."""
    shell.context = ContextSettings(max_output_bytes=512)
    many_lines = (
        '1..5000 | ForEach-Object { "line $_" }'
        if shell.platform == "windows"
        else "i=1; while [ $i -le 5000 ]; do echo line $i; i=$((i+1)); done"
    )
    result = shell.exec(many_lines, timeout_sec=60)
    assert len(result.text.encode()) < 900


def test_a_hanging_command_times_out(shell: ShellTools):
    result = shell.exec("sleep 30", timeout_sec=0.5)
    assert not result.ok and result.meta.get("timed_out")

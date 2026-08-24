"""Git tools against a real repository."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from pharness.adapters import select
from pharness.core.config import ContextSettings, parse_config
from pharness.core.env import build_env
from pharness.core.tools import GitTools
from pharness.core.workspace import WorkspaceRegistry

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def make_git_tools(root: Path) -> GitTools:
    adapters = select()
    env = build_env(os.environ, adapters.platform)
    registry = WorkspaceRegistry.from_config(
        parse_config({"workspace": [{"alias": "p", "path": str(root)}]}), adapters.paths
    )
    return GitTools(
        workspace=registry.get("p"),
        process=adapters.process_factory(root / ".logs"),
        context=ContextSettings(),
        env=env,
    )


@pytest.fixture
def repo(tmp_path: Path) -> GitTools:
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.js").write_text("console.log('hi')\n", encoding="utf-8")

    tools = make_git_tools(root)
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "test@example.invalid"),
        ("config", "user.name", "Test"),
    ):
        assert tools._run(*args).ok
    return tools


def test_not_a_repository_is_said_plainly(tmp_path: Path):
    tools = make_git_tools(tmp_path)
    result = tools.status()
    assert not result.ok and "not a git repository" in result.text


def test_status_before_any_commit_names_the_branch(repo: GitTools):
    """`rev-parse HEAD` has no answer yet, which is exactly when a project starts."""
    result = repo.status()
    assert result.ok
    assert "main" in result.text
    assert result.meta["dirty"] >= 1


def test_commit_requires_something_staged(repo: GitTools):
    result = repo.commit("nothing here")
    assert not result.ok and "nothing is staged" in result.text


def test_commit_requires_a_message(repo: GitTools):
    repo.add(["."])
    assert not repo.commit("   ").ok


def test_add_then_commit(repo: GitTools):
    assert repo.add(["."]).ok
    result = repo.commit("first commit")
    assert result.ok and result.meta["commit"]

    after = repo.status()
    assert "clean" in after.text and after.meta["dirty"] == 0


def test_flag_shaped_paths_are_refused(repo: GitTools):
    """`git add --exec=...` would be a command, not a file."""
    assert not repo.add(["--exec=evil"]).ok
    assert not repo.add([]).ok


def test_diff_summarises_before_showing_everything(repo: GitTools):
    """A 4000-line diff in the conversation costs its budget on every later turn."""
    repo.add(["."])
    repo.commit("first")
    (repo.workspace.root / "src" / "app.js").write_text(
        "console.log('changed')\n", encoding="utf-8"
    )

    summary = repo.diff()
    assert summary.meta.get("summary") is True
    assert "src/app.js" in summary.text
    assert "console.log" not in summary.text  # the contents are not in a --stat

    detail = repo.diff("src/app.js")
    assert "console.log('changed')" in detail.text


def test_diff_of_a_clean_tree_says_so(repo: GitTools):
    repo.add(["."])
    repo.commit("first")
    assert "no changes" in repo.diff().text


def test_log_and_show(repo: GitTools):
    repo.add(["."])
    repo.commit("a message that appears in the log")
    assert "a message that appears in the log" in repo.log().text
    assert repo.show().ok


def test_branches_lists_the_current_branch(repo: GitTools):
    repo.add(["."])
    repo.commit("first")
    assert "main" in repo.branches().text


def test_stash_sets_work_aside_recoverably(repo: GitTools):
    """The reason `git stash` is offered and `reset --hard` is refused."""
    repo.add(["."])
    repo.commit("first")
    target = repo.workspace.root / "src" / "app.js"
    target.write_text("work in progress\n", encoding="utf-8")

    assert repo.stash("wip").ok
    assert target.read_text(encoding="utf-8") == "console.log('hi')\n"
    assert repo._run("stash", "list").stdout.strip()


def test_git_output_is_capped(repo: GitTools):
    repo.context = ContextSettings(max_output_bytes=512)
    for index in range(200):
        (repo.workspace.root / f"file{index}.txt").write_text(
            f"content {index}\n" * 50, encoding="utf-8"
        )
    repo.add(["."])
    repo.commit("many files")
    (repo.workspace.root / "file0.txt").write_text("changed\n", encoding="utf-8")

    detail = repo.diff("file0.txt")
    assert len(detail.text.encode()) <= 700  # cap plus the truncation note


def test_no_shell_is_involved(repo: GitTools):
    """A branch or file name cannot become a second command."""
    hostile = repo.workspace.root / "weird; touch pwned.txt"
    hostile.write_text("x\n", encoding="utf-8")
    repo.add(["weird; touch pwned.txt"])
    assert not (repo.workspace.root / "pwned.txt").exists()
    assert sys.executable  # keeps the import used on every platform

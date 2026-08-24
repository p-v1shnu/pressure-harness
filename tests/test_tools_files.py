"""File tools end to end: jail, journal and byte budget together."""

from __future__ import annotations

from pathlib import Path

import pytest

from pharness.adapters.posix.paths import PosixPaths
from pharness.core.config import ContextSettings, parse_config
from pharness.core.journal import Journal
from pharness.core.policy.path_jail import PathJail
from pharness.core.tools import FileTools
from pharness.core.workspace import WorkspaceRegistry

PATCH = """--- a/src/app.ts
+++ b/src/app.ts
@@ -1,3 +1,3 @@
 export function login() {
-  return null
+  return { ok: true }
 }
"""


@pytest.fixture
def tools(tmp_path: Path) -> FileTools:
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.ts").write_text(
        "export function login() {\n  return null\n}\n", encoding="utf-8"
    )
    (root / ".env").write_text("API_SECRET=value123456\n", encoding="utf-8")

    registry = WorkspaceRegistry.from_config(
        parse_config({"workspace": [{"alias": "p", "path": str(root)}]}), PosixPaths()
    )
    return FileTools(
        workspace=registry.get("p"),
        jail=PathJail.with_app_dirs(PosixPaths()),
        journal=Journal(root),
        context=ContextSettings(),
    )


def test_read_returns_numbered_lines(tools: FileTools):
    result = tools.read("src/app.ts")
    assert result.ok
    assert "1  export function login()" in result.text


def test_read_refuses_paths_outside_the_workspace(tools: FileTools):
    assert not tools.read("../outside.txt").ok


def test_read_refuses_credential_files(tools: FileTools):
    result = tools.read(".env")
    assert not result.ok and "secrets" in result.text


def test_read_missing_file_says_so_plainly(tools: FileTools):
    assert not tools.read("nope.ts").ok


def test_read_of_a_huge_file_returns_an_outline(tools: FileTools):
    """Returning 5000 lines would spend the conversation's whole budget at once."""
    body = "\n".join(f"const v{i} = {i}" for i in range(3000))
    tools.write("big.ts", body + "\n")

    result = tools.read("big.ts")
    assert result.meta["outline"] is True
    assert "too many to return at once" in result.text

    ranged = tools.read("big.ts", offset=10, limit=5)
    assert ranged.meta.get("outline") is None
    assert "11  const v10" in ranged.text


def test_write_creates_a_file(tools: FileTools):
    assert tools.write("src/new.ts", "export const n = 1\n").ok
    assert tools.read("src/new.ts").text.endswith("export const n = 1")


def test_write_will_not_replace_by_accident(tools: FileTools):
    """ "Write this file" is how work nobody read gets discarded."""
    result = tools.write("src/app.ts", "clobbered\n")
    assert not result.ok and "already exists" in result.text


def test_write_replaces_when_asked_deliberately(tools: FileTools):
    assert tools.write("src/app.ts", "replaced\n", create_only=False).ok


def test_write_refuses_when_the_file_moved_on(tools: FileTools):
    result = tools.write("src/app.ts", "new\n", create_only=False, expected_sha="0" * 64)
    assert not result.ok and "changed since it was read" in result.text


def test_write_preserves_crlf(tools: FileTools):
    root = tools.workspace.root
    (root / "crlf.txt").write_bytes(b"alpha\r\nbeta\r\n")
    tools.write("crlf.txt", "alpha\nBETA\n", create_only=False)
    assert (root / "crlf.txt").read_bytes() == b"alpha\r\nBETA\r\n"


def test_patch_dry_run_changes_nothing(tools: FileTools):
    before = (tools.workspace.root / "src" / "app.ts").read_text(encoding="utf-8")
    result = tools.apply_patch(PATCH, dry_run=True)
    assert result.ok and "Would apply" in result.text
    assert (tools.workspace.root / "src" / "app.ts").read_text(encoding="utf-8") == before


def test_patch_applies_and_can_be_undone(tools: FileTools):
    result = tools.apply_patch(PATCH)
    assert result.ok
    assert "return { ok: true }" in tools.read("src/app.ts").text

    tools.journal.undo(result.meta["checkpoint"])
    assert "return null" in tools.read("src/app.ts").text


def test_patch_outside_the_workspace_is_refused(tools: FileTools):
    escaping = PATCH.replace("a/src/app.ts", "a/../../evil.ts").replace(
        "b/src/app.ts", "b/../../evil.ts"
    )
    assert not tools.apply_patch(escaping).ok


def test_a_patch_that_fails_partway_writes_nothing(tools: FileTools):
    """All or nothing: the first file must not land when the second cannot."""
    tools.write("src/other.ts", "first line\n")
    checkpoints_before = len(tools.journal.list())
    good_then_bad = PATCH + (
        "--- a/src/other.ts\n"
        "+++ b/src/other.ts\n"
        "@@ -1,1 +1,1 @@\n"
        "-content that is not there\n"
        "+replacement\n"
    )

    result = tools.apply_patch(good_then_bad)
    assert not result.ok
    assert "return null" in tools.read("src/app.ts").text
    assert len(tools.journal.list()) == checkpoints_before


def test_patch_creating_a_new_file(tools: FileTools):
    create = "--- /dev/null\n+++ b/src/fresh.ts\n@@ -0,0 +1,2 @@\n+alpha\n+beta\n"
    assert tools.apply_patch(create).ok
    assert "alpha" in tools.read("src/fresh.ts").text


def test_unreadable_patch_is_reported_clearly(tools: FileTools):
    result = tools.apply_patch("this is not a diff")
    assert not result.ok and "could not read the patch" in result.text

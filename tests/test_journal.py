"""The journal: undo, undo of undo, and rollback when something fails."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from pharness.core.journal import Journal, JournalError


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.txt").write_text("original\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def journal(workspace: Path) -> Journal:
    return Journal(workspace)


def test_a_checkpoint_records_what_changed(journal: Journal, workspace: Path):
    with journal.checkpoint("edit and create") as recorder:
        recorder.before(workspace / "src" / "a.txt")
        (workspace / "src" / "a.txt").write_text("changed\n", encoding="utf-8")
        recorder.before(workspace / "src" / "b.txt")
        (workspace / "src" / "b.txt").write_text("new\n", encoding="utf-8")

    [checkpoint] = journal.list()
    actions = {change.path: change.action for change in checkpoint.changes}
    assert actions == {"src/a.txt": "modify", "src/b.txt": "create"}


def test_untouched_files_are_not_recorded(journal: Journal, workspace: Path):
    """A checkpoint full of no-ops makes the history useless to read."""
    with journal.checkpoint("touch nothing") as recorder:
        recorder.before(workspace / "src" / "a.txt")

    assert journal.list() == ()


def test_undo_restores_both_edits_and_creations(journal: Journal, workspace: Path):
    with journal.checkpoint("edit and create") as recorder:
        recorder.before(workspace / "src" / "a.txt")
        (workspace / "src" / "a.txt").write_text("changed\n", encoding="utf-8")
        recorder.before(workspace / "src" / "b.txt")
        (workspace / "src" / "b.txt").write_text("new\n", encoding="utf-8")

    journal.undo()

    assert (workspace / "src" / "a.txt").read_text(encoding="utf-8") == "original\n"
    assert not (workspace / "src" / "b.txt").exists()


def test_undo_is_itself_undoable(journal: Journal, workspace: Path):
    """Undo would otherwise be the one irreversible operation in the system."""
    with journal.checkpoint("edit") as recorder:
        recorder.before(workspace / "src" / "a.txt")
        (workspace / "src" / "a.txt").write_text("changed\n", encoding="utf-8")

    undo = journal.undo()
    assert undo.undoes == "0001"
    assert (workspace / "src" / "a.txt").read_text(encoding="utf-8") == "original\n"

    journal.undo(undo.id)
    assert (workspace / "src" / "a.txt").read_text(encoding="utf-8") == "changed\n"


def test_undo_preserves_work_done_by_hand_in_between(journal: Journal, workspace: Path):
    """Undoing must not silently discard whatever the user did meanwhile."""
    with journal.checkpoint("edit") as recorder:
        recorder.before(workspace / "src" / "a.txt")
        (workspace / "src" / "a.txt").write_text("agent edit\n", encoding="utf-8")

    (workspace / "src" / "a.txt").write_text("human edit\n", encoding="utf-8")

    undo = journal.undo("0001")
    assert (workspace / "src" / "a.txt").read_text(encoding="utf-8") == "original\n"

    # The human's version was captured by the undo's own checkpoint.
    journal.undo(undo.id)
    assert (workspace / "src" / "a.txt").read_text(encoding="utf-8") == "human edit\n"


def test_a_failure_mid_checkpoint_rolls_everything_back(journal: Journal, workspace: Path):
    """A patch that fails on its third file must not leave two files rewritten."""
    with pytest.raises(RuntimeError), journal.checkpoint("will fail") as recorder:
        recorder.before(workspace / "src" / "a.txt")
        (workspace / "src" / "a.txt").write_text("half applied\n", encoding="utf-8")
        recorder.before(workspace / "src" / "created.txt")
        (workspace / "src" / "created.txt").write_text("half\n", encoding="utf-8")
        raise RuntimeError("boom")

    assert (workspace / "src" / "a.txt").read_text(encoding="utf-8") == "original\n"
    assert not (workspace / "src" / "created.txt").exists()
    assert journal.list() == ()


def test_undoing_nothing_is_an_error(journal: Journal):
    with pytest.raises(JournalError, match="nothing to undo"):
        journal.undo()


def test_unknown_checkpoint_is_an_error(journal: Journal):
    with pytest.raises(JournalError, match="no checkpoint"):
        journal.undo("9999")


def test_prune_drops_old_checkpoints(workspace: Path, now: datetime):
    moment = {"value": now}
    journal = Journal(workspace, clock=lambda: moment["value"])

    with journal.checkpoint("old") as recorder:
        recorder.before(workspace / "src" / "a.txt")
        (workspace / "src" / "a.txt").write_text("v2\n", encoding="utf-8")

    moment["value"] = now + timedelta(days=30)
    with journal.checkpoint("recent") as recorder:
        recorder.before(workspace / "src" / "a.txt")
        (workspace / "src" / "a.txt").write_text("v3\n", encoding="utf-8")

    removed = journal.prune(keep_days=14)
    assert removed == ["0001"]
    assert [c.id for c in journal.list()] == ["0002"]

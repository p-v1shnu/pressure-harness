"""Pre-image journal and checkpoints — the undo behind every write (PRD 10.8).

Rules leak. This is the net under them: before a tool changes anything, the
previous bytes are copied aside, so a bad edit is a mistake to reverse rather
than a loss to explain. Overwriting destroys data just as thoroughly as
deleting, which is why refusing to delete is not on its own enough.

The journal lives inside the workspace at `.pharness/journal/` and is denied to
every tool by the path jail, so the model cannot read its own history or quietly
drop it.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

JOURNAL_DIRNAME = ".pharness"
Action = Literal["create", "modify", "delete"]
Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class JournalError(Exception):
    pass


@dataclass(frozen=True)
class FileChange:
    path: str
    """Workspace-relative, POSIX separators, so a checkpoint is portable."""
    action: Action
    pre_sha: str | None
    pre_blob: str | None
    post_sha: str | None


@dataclass(frozen=True)
class Checkpoint:
    id: str
    ts: str
    label: str
    changes: tuple[FileChange, ...] = ()
    undoes: str | None = None
    """Set when this checkpoint is itself the undo of another one."""

    @property
    def summary(self) -> str:
        counts: dict[str, int] = {}
        for change in self.changes:
            counts[change.action] = counts.get(change.action, 0) + 1
        words = {"create": "created", "modify": "modified", "delete": "deleted"}
        detail = ", ".join(f"{n} {words[action]}" for action, n in sorted(counts.items()))
        return f"{self.id}  {self.label}  ({detail or 'no changes'})"


class Recorder:
    """Collects pre-images for one checkpoint.

    If the block raises, everything captured is put back before the exception
    propagates: a patch that fails halfway must not leave half a patch on disk.
    """

    def __init__(self, journal: Journal, label: str, undoes: str | None = None) -> None:
        self._journal = journal
        self._label = label
        self._undoes = undoes
        self._captured: dict[Path, tuple[str | None, str | None]] = {}
        self._committed = False

    def before(self, path: Path) -> None:
        """Snapshot `path` as it is now. Must be called before touching it."""
        if path in self._captured:
            return
        if path.exists():
            data = path.read_bytes()
            blob = self._journal._store_blob(self._label_id, data)
            self._captured[path] = (sha256_bytes(data), blob)
        else:
            self._captured[path] = (None, None)

    @property
    def _label_id(self) -> str:
        return self._journal._pending_id

    def rollback(self) -> None:
        for path, (pre_sha, blob) in self._captured.items():
            if pre_sha is None:
                path.unlink(missing_ok=True)
            elif blob is not None:
                path.write_bytes(self._journal._read_blob(self._label_id, blob))

    def __enter__(self) -> Recorder:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.rollback()
            self._journal._discard_pending()
            return False
        self._commit()
        return False

    def _commit(self) -> None:
        if self._committed:
            return
        self._committed = True

        changes: list[FileChange] = []
        for path, (pre_sha, blob) in sorted(self._captured.items()):
            exists = path.exists()
            post_sha = sha256_bytes(path.read_bytes()) if exists else None
            if pre_sha == post_sha:
                continue  # nothing actually changed; do not clutter the history
            action: Action = (
                "create" if pre_sha is None else ("delete" if post_sha is None else "modify")
            )
            changes.append(
                FileChange(
                    path=self._journal.relative(path),
                    action=action,
                    pre_sha=pre_sha,
                    pre_blob=blob,
                    post_sha=post_sha,
                )
            )

        if not changes:
            self._journal._discard_pending()
            return
        self._journal._write_checkpoint(self._label, tuple(changes), self._undoes)


@dataclass
class Journal:
    root: Path
    """The workspace root. The journal lives under it."""
    clock: Clock = utc_now
    _pending: str | None = field(default=None, init=False, repr=False)

    @property
    def dir(self) -> Path:
        return self.root / JOURNAL_DIRNAME / "journal"

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    # -- writing -----------------------------------------------------------

    def checkpoint(self, label: str, undoes: str | None = None) -> Recorder:
        self._pending = self._next_id()
        (self.dir / self._pending / "blobs").mkdir(parents=True, exist_ok=True)
        return Recorder(self, label, undoes)

    @property
    def _pending_id(self) -> str:
        if self._pending is None:
            raise JournalError("no checkpoint is open")
        return self._pending

    def _store_blob(self, checkpoint_id: str, data: bytes) -> str:
        digest = sha256_bytes(data)
        target = self.dir / checkpoint_id / "blobs" / digest
        if not target.exists():
            target.write_bytes(data)
        return digest

    def _read_blob(self, checkpoint_id: str, blob: str) -> bytes:
        return (self.dir / checkpoint_id / "blobs" / blob).read_bytes()

    def _write_checkpoint(
        self, label: str, changes: tuple[FileChange, ...], undoes: str | None
    ) -> Checkpoint:
        checkpoint = Checkpoint(
            id=self._pending_id,
            ts=self.clock().isoformat(),
            label=label,
            changes=changes,
            undoes=undoes,
        )
        meta = self.dir / checkpoint.id / "meta.json"
        meta.write_text(
            json.dumps(
                {**asdict(checkpoint), "changes": [asdict(c) for c in changes]},
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        self._pending = None
        return checkpoint

    def _discard_pending(self) -> None:
        if self._pending:
            shutil.rmtree(self.dir / self._pending, ignore_errors=True)
            self._pending = None

    def _next_id(self) -> str:
        existing = [p.name for p in self.dir.glob("*") if p.is_dir()] if self.dir.exists() else []
        return f"{len(existing) + 1:04d}"

    # -- reading and undoing ------------------------------------------------

    def list(self) -> tuple[Checkpoint, ...]:
        if not self.dir.exists():
            return ()
        out: list[Checkpoint] = []
        for entry in sorted(self.dir.iterdir()):
            meta = entry / "meta.json"
            if not meta.is_file():
                continue
            raw = json.loads(meta.read_text(encoding="utf-8"))
            out.append(
                Checkpoint(
                    id=raw["id"],
                    ts=raw["ts"],
                    label=raw["label"],
                    changes=tuple(FileChange(**c) for c in raw["changes"]),
                    undoes=raw.get("undoes"),
                )
            )
        return tuple(out)

    def get(self, checkpoint_id: str) -> Checkpoint:
        for checkpoint in self.list():
            if checkpoint.id == checkpoint_id:
                return checkpoint
        raise JournalError(f"no checkpoint {checkpoint_id!r}")

    def latest(self) -> Checkpoint | None:
        checkpoints = self.list()
        return checkpoints[-1] if checkpoints else None

    def undo(self, checkpoint_id: str | None = None) -> Checkpoint:
        """Put a checkpoint's files back, and journal the undo itself.

        Undoing is recorded as a new checkpoint rather than erasing the old one,
        so it can be undone in turn. Without that, undo would be the one
        destructive operation in a system built around not having any -- and it
        would silently discard whatever the user changed by hand in between.
        """
        target = self.get(checkpoint_id) if checkpoint_id else self.latest()
        if target is None:
            raise JournalError("there is nothing to undo")

        with self.checkpoint(f"undo of {target.id} ({target.label})", undoes=target.id) as recorder:
            for change in target.changes:
                path = self.root / change.path
                recorder.before(path)

                if change.action == "create":
                    # It did not exist before the checkpoint. Removing it now is
                    # safe precisely because this undo is itself journaled.
                    path.unlink(missing_ok=True)
                elif change.pre_blob is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(self._read_blob(target.id, change.pre_blob))

        return self.get(self._latest_id())

    def _latest_id(self) -> str:
        latest = self.latest()
        if latest is None:
            raise JournalError("checkpoint disappeared while undoing")
        return latest.id

    # -- housekeeping -------------------------------------------------------

    def size_bytes(self) -> int:
        if not self.dir.exists():
            return 0
        return sum(p.stat().st_size for p in self.dir.rglob("*") if p.is_file())

    def prune(self, keep_days: int = 14, max_bytes: int = 500 * 1024 * 1024) -> list[str]:
        """Drop old checkpoints. Returns the ids removed.

        Age first, then size, oldest first -- a journal that grows without limit
        eventually gets deleted wholesale by an irritated user, which is worse
        than pruning it here.
        """
        removed: list[str] = []
        now = self.clock()

        for checkpoint in self.list():
            age_days = (now - datetime.fromisoformat(checkpoint.ts)).days
            if age_days > keep_days:
                shutil.rmtree(self.dir / checkpoint.id, ignore_errors=True)
                removed.append(checkpoint.id)

        while self.size_bytes() > max_bytes:
            remaining = self.list()
            if not remaining:
                break
            oldest = remaining[0]
            shutil.rmtree(self.dir / oldest.id, ignore_errors=True)
            removed.append(oldest.id)

        return removed

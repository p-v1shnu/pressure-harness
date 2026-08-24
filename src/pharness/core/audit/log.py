"""Hash-chained append-only audit log (PRD 10.9).

Each line carries the hash of the line before it, so removing or editing an
entry after the fact is detectable rather than invisible. That matters because
the log is the only account of what happened while nobody was watching, and
anything able to rewrite it quietly is able to rewrite the story.

JSONL rather than a database: it survives a half-written line, it can be read
with any tool, and an operator can eyeball it without our software.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pharness.core.audit.redact import Redactor

GENESIS = "0" * 64
Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def _digest(seq: int, ts: str, prev: str, event: Mapping[str, Any]) -> str:
    material = json.dumps(
        {"seq": seq, "ts": ts, "prev": prev, "event": event},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ChainStatus:
    entries: int
    intact: bool
    broken_at: int | None = None
    detail: str = ""

    @property
    def summary(self) -> str:
        if self.intact:
            return f"{self.entries} entries, chain intact"
        return f"chain broken at entry {self.broken_at}: {self.detail}"


class AuditLog:
    def __init__(
        self,
        path: Path,
        clock: Clock = utc_now,
        redactor: Redactor | None = None,
    ) -> None:
        self._path = Path(path)
        self._clock = clock
        self._redactor = redactor
        self._seq, self._head = self._read_head()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def head(self) -> str:
        return self._head

    def _read_head(self) -> tuple[int, str]:
        if not self._path.exists():
            return 0, GENESIS
        last: dict[str, Any] | None = None
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    try:
                        last = json.loads(line)
                    except json.JSONDecodeError:
                        # A torn final line from a hard shutdown. Keep the last
                        # good entry as the head; verify() will report the tear.
                        continue
        if not last:
            return 0, GENESIS
        return int(last.get("seq", 0)), str(last.get("hash", GENESIS))

    def append(self, event: Mapping[str, Any]) -> str:
        """Add one entry and return its hash.

        Flushed and fsynced before returning: an audit entry that is still in a
        buffer when the machine dies is an audit entry that never existed.
        """
        payload = dict(event)
        if self._redactor is not None:
            payload = _redact_event(payload, self._redactor)

        seq = self._seq + 1
        ts = self._clock().isoformat()
        entry_hash = _digest(seq, ts, self._head, payload)
        record = {"seq": seq, "ts": ts, "prev": self._head, "event": payload, "hash": entry_hash}

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=True, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

        self._seq, self._head = seq, entry_hash
        return entry_hash

    def read(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        out: list[dict[str, Any]] = []
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def tail(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.read()[-limit:]

    def verify(self) -> ChainStatus:
        """Recompute the whole chain. Used by the console's integrity indicator."""
        if not self._path.exists():
            return ChainStatus(0, True)

        prev = GENESIS
        expected_seq = 1
        count = 0

        with self._path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                count += 1
                try:
                    record = json.loads(raw)
                except json.JSONDecodeError as exc:
                    return ChainStatus(count, False, expected_seq, f"unreadable line ({exc})")

                seq = record.get("seq")
                if seq != expected_seq:
                    return ChainStatus(count, False, expected_seq, f"sequence jumped to {seq}")
                if record.get("prev") != prev:
                    return ChainStatus(count, False, expected_seq, "previous hash does not match")

                recomputed = _digest(seq, record.get("ts", ""), prev, record.get("event", {}))
                if recomputed != record.get("hash"):
                    return ChainStatus(count, False, expected_seq, "entry was modified")

                prev = record["hash"]
                expected_seq += 1

        return ChainStatus(count, True)


def _redact_event(event: dict[str, Any], redactor: Redactor) -> dict[str, Any]:
    kinds: list[str] = []

    def walk(value: Any) -> Any:
        if isinstance(value, str):
            result = redactor.redact(value)
            kinds.extend(result.kinds)
            return result.text
        if isinstance(value, Mapping):
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    out = walk(event)
    if kinds:
        out["_redacted"] = sorted(set(kinds))
    return out

"""The audit log has to make tampering visible, not merely unlikely."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from pharness.core.audit import AuditLog, Redactor


def clock_from(start: datetime):
    state = {"n": 0}

    def tick() -> datetime:
        state["n"] += 1
        return start + timedelta(seconds=state["n"])

    return tick


def test_empty_log_is_intact(tmp_path: Path):
    status = AuditLog(tmp_path / "audit.jsonl").verify()
    assert status.intact and status.entries == 0


def test_entries_chain_and_verify(tmp_path: Path, now: datetime):
    log = AuditLog(tmp_path / "audit.jsonl", clock=clock_from(now))
    for index in range(5):
        log.append({"tool": "shell", "decision": "ask", "seq_hint": index})

    status = log.verify()
    assert status.intact and status.entries == 5

    records = log.read()
    assert [r["seq"] for r in records] == [1, 2, 3, 4, 5]
    assert records[0]["prev"] == "0" * 64
    assert all(records[i]["prev"] == records[i - 1]["hash"] for i in range(1, 5))


def test_reopening_continues_the_same_chain(tmp_path: Path, now: datetime):
    path = tmp_path / "audit.jsonl"
    AuditLog(path, clock=clock_from(now)).append({"event": "first"})
    reopened = AuditLog(path, clock=clock_from(now))
    reopened.append({"event": "second"})
    assert reopened.verify().intact
    assert [r["seq"] for r in reopened.read()] == [1, 2]


def test_editing_an_entry_is_detected(tmp_path: Path, now: datetime):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path, clock=clock_from(now))
    for decision in ("ask", "deny", "allow"):
        log.append({"decision": decision})

    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["event"]["decision"] = "allow"  # a denial quietly turned into an approval
    lines[1] = json.dumps(record, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    status = AuditLog(path).verify()
    assert not status.intact
    assert status.broken_at == 2
    assert "modified" in status.detail


def test_removing_an_entry_is_detected(tmp_path: Path, now: datetime):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path, clock=clock_from(now))
    for index in range(4):
        log.append({"index": index})

    lines = path.read_text(encoding="utf-8").splitlines()
    del lines[1]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    status = AuditLog(path).verify()
    assert not status.intact and status.broken_at == 2


def test_denials_are_recorded_too(tmp_path: Path, now: datetime):
    """A refusal is the most informative entry in the log (PRD 10.9)."""
    log = AuditLog(tmp_path / "audit.jsonl", clock=clock_from(now))
    log.append({"tool": "shell", "decision": "deny", "rule": "tier-5", "reason": "deletes data"})
    assert log.read()[0]["event"]["decision"] == "deny"


def test_secrets_never_reach_the_log(tmp_path: Path, now: datetime):
    log = AuditLog(
        tmp_path / "audit.jsonl",
        clock=clock_from(now),
        redactor=Redactor(),
    )
    log.append({"command": "deploy --token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"})

    written = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345" not in written
    assert "redacted:github-token" in written
    assert log.read()[0]["event"]["_redacted"] == ["github-token"]


def test_torn_final_line_does_not_break_appending(tmp_path: Path, now: datetime):
    """A hard shutdown mid-write must not stop the log from being usable."""
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path, clock=clock_from(now))
    log.append({"event": "good"})
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"seq": 2, "partial": tr')

    reopened = AuditLog(path, clock=clock_from(now))
    reopened.append({"event": "after the tear"})
    assert not reopened.verify().intact  # the tear is reported, not hidden

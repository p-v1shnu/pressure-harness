"""User-defined allow and deny rules, and the payload hash they bind to.

An approval is bound to the exact payload that was shown, never to a
description of it: approving `git push origin feature` must not silently cover
`git push --force origin main` (PRD 10.7). The hash is what makes that
binding real.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

Action = Literal["allow", "deny"]


def payload_hash(tool: str, op: str | None, payload: Mapping[str, Any]) -> str:
    """A stable fingerprint of exactly what was requested.

    Canonical JSON with sorted keys, so the same request hashes the same way
    across processes and restarts -- a remembered approval has to survive both
    or it is not a remembered approval.
    """
    material = {
        "tool": tool,
        "op": op,
        "payload": _canonical(payload),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


@dataclass(frozen=True)
class Rule:
    """One remembered decision.

    Rules are always reviewable and removable from the console (PRD 12.1):
    a permission the user cannot find again is a permission they cannot revoke.
    """

    action: Action
    reason: str = ""
    tool: str | None = None
    workspace: str | None = None
    command_prefix: str | None = None
    exact_payload: str | None = None
    expires_at: datetime | None = None
    session_id: str | None = None
    """Set when the user chose "for this session" rather than "remember"."""

    def active_at(self, now: datetime) -> bool:
        return self.expires_at is None or now < self.expires_at

    def matches(
        self,
        *,
        tool: str,
        workspace: str | None,
        command_line: str | None,
        digest: str,
        session_id: str,
        now: datetime,
    ) -> bool:
        if not self.active_at(now):
            return False
        if self.session_id is not None and self.session_id != session_id:
            return False
        if self.workspace is not None and self.workspace != workspace:
            return False
        if self.tool is not None and self.tool != tool:
            return False

        if self.exact_payload is not None:
            return self.exact_payload == digest

        if self.command_prefix is not None:
            if command_line is None:
                return False
            return _command_matches(command_line, self.command_prefix)

        # A rule with neither a payload nor a command scopes to the tool and
        # workspace it named. One with none of the three would match
        # everything, which is the "allow all" button we refuse to build.
        return self.tool is not None or self.workspace is not None


def _command_matches(command_line: str, prefix: str) -> bool:
    """Token-wise prefix match, so `npm test` cannot be satisfied by `npm testing`."""
    actual = command_line.split()
    tokens = prefix.split()
    return bool(tokens) and actual[: len(tokens)] == tokens


def first_match(
    rules: Sequence[Rule],
    *,
    action: Action,
    tool: str,
    workspace: str | None,
    command_line: str | None,
    digest: str,
    session_id: str,
    now: datetime,
) -> Rule | None:
    for rule in rules:
        if rule.action != action:
            continue
        if rule.matches(
            tool=tool,
            workspace=workspace,
            command_line=command_line,
            digest=digest,
            session_id=session_id,
            now=now,
        ):
            return rule
    return None

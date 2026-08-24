"""The approval queue (PRD 10.7).

Three properties this has to get right, and each of them is a failure mode
someone has shipped:

* the user approves the exact payload, never a description of it, so an
  approval is bound to a hash of what was actually requested;
* an unattended machine refuses rather than waits, so every request expires;
* a flood of prompts is itself an attack, because a person asked twenty
  questions a minute starts clicking allow without reading -- so past a rate
  limit, requests are refused instead of asked.

There is deliberately no "approve everything" outcome. Widening permission is a
decision made in the console, in advance, with a clock on it.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from pharness.core.policy.tiers import Tier

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def _duration(seconds: float) -> str:
    return f"{seconds:.1f}s" if seconds < 10 else f"{seconds:.0f}s"


class Outcome(StrEnum):
    ONCE = "once"
    """Allow this exact request, this time only."""
    SESSION = "session"
    """Allow it for the rest of this conversation."""
    REMEMBER = "remember"
    """Allow this exact payload from now on, until the rule is removed."""
    DENY = "deny"
    TIMED_OUT = "timed_out"
    RATE_LIMITED = "rate_limited"

    @property
    def approved(self) -> bool:
        return self in (Outcome.ONCE, Outcome.SESSION, Outcome.REMEMBER)


@dataclass(frozen=True)
class ApprovalRequest:
    """Everything the prompt shows. `payload` is the literal request."""

    id: str
    session_id: str
    workspace: str
    tool: str
    op: str | None
    tier: Tier
    reason: str
    digest: str
    payload: Mapping[str, Any]
    created_at: datetime
    expires_at: datetime

    def seconds_left(self, now: datetime) -> float:
        return max(0.0, (self.expires_at - now).total_seconds())

    def render(self) -> str:
        """The text a prompt shows. The payload is quoted, never summarised."""
        lines = [
            f"workspace: {self.workspace}    tool: {self.tool}"
            + (f".{self.op}" if self.op else "")
            + f"    tier: {self.tier.label}",
            f"reason: {self.reason}",
            "",
        ]
        for key, value in self.payload.items():
            text = value if isinstance(value, str) else repr(value)
            lines.append(f"{key}:")
            lines.extend(f"    {line}" for line in str(text).splitlines() or [""])
        return "\n".join(lines)


@dataclass
class Decision:
    outcome: Outcome
    note: str = ""
    decided_at: datetime | None = None


@dataclass
class _Pending:
    request: ApprovalRequest
    event: threading.Event = field(default_factory=threading.Event)
    decision: Decision | None = None


class ApprovalQueue:
    def __init__(
        self,
        notifier,
        timeout_sec: float = 120.0,
        rate_limit_per_minute: int = 10,
        clock: Clock = utc_now,
    ) -> None:
        self._notifier = notifier
        self._timeout = timeout_sec
        self._rate_limit = rate_limit_per_minute
        self._clock = clock
        self._lock = threading.RLock()
        self._pending: dict[str, _Pending] = {}
        self._recent: list[datetime] = []
        self._history: list[tuple[ApprovalRequest, Decision]] = []
        self._counter = 0

    # -- asking ------------------------------------------------------------

    def ask(
        self,
        *,
        session_id: str,
        workspace: str,
        tool: str,
        op: str | None,
        tier: Tier,
        reason: str,
        digest: str,
        payload: Mapping[str, Any],
    ) -> Decision:
        """Put a request to the user and block until it is answered or expires."""
        now = self._clock()

        if self._rate_limited(now):
            decision = Decision(
                Outcome.RATE_LIMITED,
                f"more than {self._rate_limit} approval prompts in a minute; "
                "refusing the rest rather than burying you in dialogs",
                now,
            )
            refused = self._build(
                session_id, workspace, tool, op, tier, reason, digest, payload, now
            )
            with self._lock:
                self._history.append((refused, decision))
            return decision

        request = self._build(session_id, workspace, tool, op, tier, reason, digest, payload, now)
        pending = _Pending(request)

        with self._lock:
            self._pending[request.id] = pending
            self._recent.append(now)

        if not getattr(self._notifier, "interactive", False):
            # Nothing can answer, so do not pretend to wait for the full timeout.
            decision = Decision(
                Outcome.DENY,
                "no interactive prompt is available on this machine",
                self._clock(),
            )
            self._settle(request.id, decision)
            return decision

        self._notifier.present(
            request, lambda outcome, note="": self._respond(request.id, outcome, note)
        )

        answered = pending.event.wait(timeout=self._timeout)
        if not answered:
            # An unattended machine must fail closed (PRD 10.7).
            self._notifier.withdraw(request.id)
            decision = Decision(
                Outcome.TIMED_OUT,
                f"no answer within {_duration(self._timeout)}, so it was refused",
                self._clock(),
            )
            self._settle(request.id, decision)
            return decision

        assert pending.decision is not None
        return pending.decision

    def _build(
        self, session_id, workspace, tool, op, tier, reason, digest, payload, now
    ) -> ApprovalRequest:
        with self._lock:
            self._counter += 1
            request_id = f"a{self._counter}"
        return ApprovalRequest(
            id=request_id,
            session_id=session_id,
            workspace=workspace,
            tool=tool,
            op=op,
            tier=tier,
            reason=reason,
            digest=digest,
            payload=dict(payload),
            created_at=now,
            expires_at=now + timedelta(seconds=self._timeout),
        )

    def _rate_limited(self, now: datetime) -> bool:
        cutoff = now - timedelta(minutes=1)
        with self._lock:
            self._recent = [stamp for stamp in self._recent if stamp > cutoff]
            return len(self._recent) >= self._rate_limit

    # -- answering ---------------------------------------------------------

    def _respond(self, request_id: str, outcome: Outcome, note: str = "") -> None:
        self._settle(request_id, Decision(outcome, note, self._clock()))

    def respond(self, request_id: str, outcome: Outcome, note: str = "") -> bool:
        """Answer from the console or the CLI. False if it is no longer pending."""
        return self._settle(request_id, Decision(outcome, note, self._clock()))

    def _settle(self, request_id: str, decision: Decision) -> bool:
        with self._lock:
            pending = self._pending.pop(request_id, None)
            if pending is None:
                return False
            pending.decision = decision
            self._history.append((pending.request, decision))
        pending.event.set()
        return True

    def deny_all(self, note: str = "cancelled") -> int:
        """Used by the emergency button: nothing is left hanging."""
        with self._lock:
            ids = list(self._pending)
        for request_id in ids:
            self._settle(request_id, Decision(Outcome.DENY, note, self._clock()))
        return len(ids)

    # -- inspection --------------------------------------------------------

    def pending(self) -> tuple[ApprovalRequest, ...]:
        with self._lock:
            return tuple(item.request for item in self._pending.values())

    def history(self) -> tuple[tuple[ApprovalRequest, Decision], ...]:
        with self._lock:
            return tuple(self._history)

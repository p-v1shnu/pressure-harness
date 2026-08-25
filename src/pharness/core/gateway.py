"""The single path from a tool call to a tool running.

Everything a model asks for goes: decide, maybe ask the user, run, record. No
tool is reachable another way, which is what makes the policy engine a control
rather than a suggestion (PRD 6.1).

The order matters. Deciding happens before anything runs; asking happens outside
the conversation; recording happens whatever the outcome, including refusals --
those are the entries worth having (PRD 10.9).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace as _replace

from pharness.core.approvals import ApprovalQueue, Outcome
from pharness.core.audit import AuditLog, Redactor
from pharness.core.policy.engine import Decision, PolicyEngine, Request, Verdict
from pharness.core.policy.rules import Rule
from pharness.core.tools.results import ToolResult
from pharness.core.workspace import Clock, Workspace, utc_now

Runner = Callable[[], ToolResult]


@dataclass
class Gateway:
    engine: PolicyEngine
    queue: ApprovalQueue
    audit: AuditLog
    clock: Clock = utc_now
    redactor: Redactor | None = None
    """Applied to every result before it leaves.

    The audit log was redacted first and the conversation was not, which is
    backwards: the log stays on this machine, and the conversation is uploaded
    to a third party the moment a tool returns (PRD 10.5).
    """

    def call(self, request: Request, workspace: Workspace, run: Runner) -> ToolResult:
        now = self.clock()
        verdict = self.engine.decide(request, workspace, now)

        if verdict.decision is Decision.DENY:
            return self._refuse(request, workspace, verdict, verdict.reason, "denied")

        if verdict.decision is Decision.ASK:
            decision = self.queue.ask(
                session_id=request.session_id,
                workspace=workspace.alias,
                tool=request.tool,
                op=request.op,
                tier=verdict.tier,
                reason=verdict.reason,
                digest=verdict.digest,
                payload=request.payload,
            )
            if not decision.outcome.approved:
                refusal = {
                    Outcome.DENY: "you refused this request",
                    Outcome.TIMED_OUT: "the approval prompt went unanswered",
                    Outcome.RATE_LIMITED: "too many approval prompts at once",
                }.get(decision.outcome, "not approved")
                detail = f"{refusal} ({decision.note})" if decision.note else refusal
                return self._refuse(request, workspace, verdict, detail, str(decision.outcome))
            self._remember(request, workspace, verdict, decision.outcome)

        return self._run(request, workspace, verdict, run)

    # -- internals ---------------------------------------------------------

    def _remember(
        self, request: Request, workspace: Workspace, verdict: Verdict, outcome: Outcome
    ) -> None:
        """Turn "for this session" or "remember" into a rule.

        Both are bound to the payload hash rather than to the tool, so
        approving one command never widens into approving a family of them
        (PRD 10.7).
        """
        if outcome is Outcome.ONCE:
            return
        scope = (
            "for this conversation" if outcome is Outcome.SESSION else "and chose to remember it"
        )
        self.engine.remember(
            Rule(
                action="allow",
                reason=f"you approved this {scope}",
                tool=request.tool,
                workspace=workspace.alias,
                exact_payload=verdict.digest,
                session_id=request.session_id if outcome is Outcome.SESSION else None,
            )
        )

    def _refuse(
        self,
        request: Request,
        workspace: Workspace,
        verdict: Verdict,
        message: str,
        disposition: str,
    ) -> ToolResult:
        self._record(request, workspace, verdict, disposition, message)
        return ToolResult.failure(message, tier=verdict.tier.label, rule=verdict.rule)

    def _run(
        self, request: Request, workspace: Workspace, verdict: Verdict, run: Runner
    ) -> ToolResult:
        started = self.clock()
        try:
            result = run()
        except Exception as exc:
            self._record(request, workspace, verdict, "error", f"{type(exc).__name__}: {exc}")
            raise

        removed: tuple[str, ...] = ()
        if self.redactor is not None and result.text:
            redaction = self.redactor.redact(result.text)
            if redaction.changed:
                result = _replace(result, text=redaction.text)
                removed = redaction.kinds

        duration = (self.clock() - started).total_seconds()
        # Every byte here is pasted into the conversation and re-sent with every
        # later message. Counting it is the only way to know whether the quota
        # this project exists to protect is actually being protected (PRD 11).
        self._record(
            request,
            workspace,
            verdict,
            "ran" if result.ok else "failed",
            result.text[:200],
            duration_sec=round(duration, 3),
            output_bytes=len(result.text.encode("utf-8")),
            redacted=list(removed) or None,
        )
        return result

    def _record(
        self,
        request: Request,
        workspace: Workspace,
        verdict: Verdict,
        disposition: str,
        detail: str,
        **extra: object,
    ) -> None:
        self.audit.append(
            {
                "session": request.session_id,
                "workspace": workspace.alias,
                "tool": request.tool,
                "op": request.op,
                "tier": verdict.tier.label,
                "decision": verdict.decision.value,
                "rule": verdict.rule,
                "disposition": disposition,
                "reason": verdict.reason,
                "digest": verdict.digest,
                "detail": detail,
                **extra,
            }
        )

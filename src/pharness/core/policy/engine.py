"""The decision point. Every tool call passes through here (PRD 6.1).

Order is fixed and first match wins (PRD 10.3):

    1. tier 5            -- refused outright, no approval path
    2. user deny rules
    3. user allow rules
    4. the workspace's mode
    5. anything left      -- ask

Step 5 is the default, not step 4: a request that matches nothing is asked
about rather than allowed. Fail closed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from pharness.core.config import Mode
from pharness.core.policy.commands import CommandAnalysis, Finding, classify
from pharness.core.policy.rules import Rule, first_match, payload_hash
from pharness.core.policy.tiers import Tier
from pharness.core.workspace import Workspace
from pharness.ports import ShellPort


class Decision(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True)
class Request:
    """One tool call, as the policy engine sees it."""

    session_id: str
    tool: str
    op: str | None = None
    declared_tier: Tier = Tier.READ
    """The tier the tool catalogue assigns to this op (PRD 8.2)."""
    payload: Mapping[str, Any] = field(default_factory=dict)
    command_line: str | None = None
    """Set for tools that run a command, so it can be parsed and classified."""


@dataclass(frozen=True)
class Verdict:
    decision: Decision
    tier: Tier
    reason: str
    rule: str
    """Which step decided, so the audit log and the prompt can say why."""
    digest: str
    findings: tuple[Finding, ...] = ()
    analysis: CommandAnalysis | None = None

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW


# What each mode does with each tier (PRD 10.2). Absent means deny.
_MODE_TABLE: dict[Mode, dict[Tier, Decision]] = {
    Mode.READ_ONLY: {
        Tier.READ: Decision.ALLOW,
    },
    Mode.AUTO_EDIT: {
        Tier.READ: Decision.ALLOW,
        Tier.WRITE: Decision.ALLOW,
        Tier.EXEC_ALLOWED: Decision.ALLOW,
        Tier.EXEC_OTHER: Decision.ASK,
        Tier.EGRESS: Decision.ASK,
    },
    Mode.FULL_ACCESS: {
        Tier.READ: Decision.ALLOW,
        Tier.WRITE: Decision.ALLOW,
        Tier.EXEC_ALLOWED: Decision.ALLOW,
        Tier.EXEC_OTHER: Decision.ALLOW,
        Tier.EGRESS: Decision.ALLOW,
    },
}


class PolicyEngine:
    def __init__(
        self,
        shell: ShellPort,
        rules: Sequence[Rule] = (),
        file_exists: Callable[[str], bool] | None = None,
    ) -> None:
        self._shell = shell
        self._rules = list(rules)
        self._file_exists = file_exists

    @property
    def rules(self) -> tuple[Rule, ...]:
        return tuple(self._rules)

    def remember(self, rule: Rule) -> None:
        """Record a decision the user made. Newest first, so it wins."""
        self._rules.insert(0, rule)

    def forget(self, rule: Rule) -> None:
        if rule in self._rules:
            self._rules.remove(rule)

    def decide(self, request: Request, workspace: Workspace, now: datetime) -> Verdict:
        digest = payload_hash(request.tool, request.op, request.payload)

        analysis: CommandAnalysis | None = None
        tier = request.declared_tier
        findings: tuple[Finding, ...] = ()
        reason = f"{request.tool} is tier {tier.label}"

        if request.command_line is not None:
            analysis = classify(
                request.command_line,
                shell=self._shell,
                allow_commands=workspace.config.allow_commands,
                file_exists=self._file_exists,
            )
            findings = analysis.findings
            reason = analysis.top_reason
            tier = _combine_tiers(tier, analysis)

        # 1. Forbidden outright. Checked before any rule, so no stored approval
        #    and no mode can reach past it.
        if tier is Tier.FORBIDDEN:
            return Verdict(Decision.DENY, tier, reason, "tier-5", digest, findings, analysis)

        # git push is gated by the workspace on top of its tier.
        if tier is Tier.EGRESS and _is_push(request) and not workspace.may_push(now):
            return Verdict(
                Decision.DENY,
                tier,
                "pushing is turned off for this workspace",
                "workspace-git-push",
                digest,
                findings,
                analysis,
            )

        common = {
            "tool": request.tool,
            "workspace": workspace.alias,
            "command_line": request.command_line,
            "digest": digest,
            "session_id": request.session_id,
            "now": now,
        }

        # 2. Deny rules.
        denied = first_match(self._rules, action="deny", **common)
        if denied:
            return Verdict(
                Decision.DENY,
                tier,
                denied.reason or "denied by a rule you set",
                "user-deny",
                digest,
                findings,
                analysis,
            )

        # 3. Allow rules.
        allowed = first_match(self._rules, action="allow", **common)
        if allowed:
            return Verdict(
                Decision.ALLOW,
                tier,
                allowed.reason or "allowed by a rule you set",
                "user-allow",
                digest,
                findings,
                analysis,
            )

        # 4. The workspace's mode.
        mode = workspace.effective_mode(now)
        decision = _MODE_TABLE[mode].get(tier)
        if decision in (Decision.ALLOW, Decision.ASK):
            return Verdict(decision, tier, reason, f"mode-{mode.value}", digest, findings, analysis)
        if decision is None and mode is Mode.READ_ONLY:
            return Verdict(
                Decision.DENY,
                tier,
                f"workspace {workspace.alias!r} is read-only",
                "mode-read-only",
                digest,
                findings,
                analysis,
            )

        # 5. Nothing matched. Ask rather than assume.
        return Verdict(Decision.ASK, tier, reason, "default-ask", digest, findings, analysis)


def _combine_tiers(declared: Tier, analysis: CommandAnalysis) -> Tier:
    """Merge the tool's declared tier with what its command turned out to be.

    An allowlist hit is the one thing that can lower a tier, and it is why
    `shell` is usable at all: without it every `npm test` would prompt, and a
    user who is prompted constantly stops reading the prompts (PRD 10.7).
    Otherwise the declared tier is a floor that findings can only raise.
    """
    if analysis.matched_allowlist:
        return analysis.tier
    return max(declared, analysis.tier)


def _is_push(request: Request) -> bool:
    if request.tool == "git" and request.op == "push":
        return True
    return bool(request.command_line and "push" in request.command_line.split())

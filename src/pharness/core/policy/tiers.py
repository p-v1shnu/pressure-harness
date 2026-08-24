"""Risk tiers (PRD 10.3).

Ordered, so combining findings is `max()`: a command line is as risky as the
riskiest thing in it. That is the only safe way to combine -- an allowlisted
`npm test` next to an `rm -rf` must not average out to allowed.
"""

from __future__ import annotations

from enum import IntEnum


class Tier(IntEnum):
    READ = 0
    """Reads only. Auto-allowed in every mode above read-only."""

    WRITE = 1
    """Writes inside a workspace, recorded in the journal so it can be undone."""

    EXEC_ALLOWED = 2
    """Runs a command the user has allowlisted for this workspace."""

    EXEC_OTHER = 3
    """Runs anything else, including every interpreter invocation."""

    EGRESS = 4
    """Sends data off the machine: git push, fetching outside the allowlist."""

    FORBIDDEN = 5
    """Never permitted, with no approval path. See PRD 10.3."""

    @property
    def label(self) -> str:
        return f"T{int(self)}"

    @property
    def needs_approval(self) -> bool:
        return self in (Tier.EXEC_OTHER, Tier.EGRESS)

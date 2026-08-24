"""Registered workspaces and per-session state.

Two separate acts, and conflating them is the mistake to avoid: the user
*authorises* a directory once, outside any conversation; the model only ever
*selects* from what was authorised (PRD 9.1). Nothing here can add a workspace.

Active selection is per session, not global, because two conversations run at
once and a single global pointer means one of them silently writes into the
other's project (PRD 9.3).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pharness.core.config import Config, Mode, WorkspaceConfig
from pharness.core.errors import WorkspaceError
from pharness.ports import PathsPort

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Grant:
    """A temporary elevation. Always has an expiry -- see PRD 10.2."""

    mode: Mode
    expires_at: datetime

    def active_at(self, now: datetime) -> bool:
        return now < self.expires_at


@dataclass
class Workspace:
    alias: str
    root: Path
    config: WorkspaceConfig
    grant: Grant | None = None
    scope_warning: str | None = None
    """Set when the authorised directory is broader than it should be."""

    def effective_mode(self, now: datetime) -> Mode:
        if self.grant and self.grant.active_at(now):
            return self.grant.mode
        return self.config.mode

    def grant_full_access(self, ttl_minutes: int, now: datetime) -> Grant:
        """Elevate for a bounded window.

        People turn this on mid-task and forget it, so expiry is not optional
        and there is no API to grant it indefinitely.
        """
        if ttl_minutes <= 0:
            raise WorkspaceError("full access must have a positive lifetime")
        self.grant = Grant(Mode.FULL_ACCESS, now + timedelta(minutes=ttl_minutes))
        return self.grant

    def revoke_grant(self) -> None:
        self.grant = None

    def may_write(self, now: datetime) -> bool:
        return self.effective_mode(now) in (Mode.AUTO_EDIT, Mode.FULL_ACCESS)

    def may_execute(self, now: datetime) -> bool:
        return self.effective_mode(now) in (Mode.AUTO_EDIT, Mode.FULL_ACCESS)

    def may_push(self, now: datetime) -> bool:
        return self.config.git_push and self.may_write(now)


class WorkspaceRegistry:
    """The authorised set. Read-only from the model's point of view."""

    def __init__(self, workspaces: list[Workspace]) -> None:
        self._by_alias = {w.alias: w for w in workspaces}

    @classmethod
    def from_config(cls, config: Config, paths: PathsPort) -> WorkspaceRegistry:
        built: list[Workspace] = []
        for entry in config.workspaces:
            root = paths.resolve(Path(entry.path))
            built.append(
                Workspace(
                    alias=entry.alias,
                    root=root,
                    config=entry,
                    scope_warning=paths.broad_scope_reason(root),
                )
            )
        return cls(built)

    def __len__(self) -> int:
        return len(self._by_alias)

    def aliases(self) -> tuple[str, ...]:
        return tuple(self._by_alias)

    def all(self) -> tuple[Workspace, ...]:
        return tuple(self._by_alias.values())

    def warnings(self) -> tuple[str, ...]:
        """Scope warnings for the Doctor screen (PRD 12.1)."""
        return tuple(
            f"{w.alias} is {w.scope_warning}" for w in self._by_alias.values() if w.scope_warning
        )

    def get(self, alias: str) -> Workspace:
        try:
            return self._by_alias[alias]
        except KeyError:
            raise WorkspaceError(
                f"no workspace named {alias!r}. Available: "
                f"{', '.join(self.aliases()) or 'none registered yet'}. "
                "Only the owner can add one, from the console on this machine."
            ) from None

    def sole(self) -> Workspace | None:
        """The single workspace, when there is exactly one, else None."""
        if len(self._by_alias) == 1:
            return next(iter(self._by_alias.values()))
        return None


@dataclass
class Sessions:
    """Which workspace each conversation is working in."""

    registry: WorkspaceRegistry
    clock: Clock = utc_now
    _active: dict[str, str] = field(default_factory=dict)

    def use(self, session_id: str, alias: str) -> Workspace:
        workspace = self.registry.get(alias)
        self._active[session_id] = alias
        return workspace

    def active(self, session_id: str) -> Workspace | None:
        alias = self._active.get(session_id)
        return self.registry.get(alias) if alias else self.registry.sole()

    def resolve(self, session_id: str, requested: str | None = None) -> Workspace:
        """Pick the workspace for one tool call.

        An explicit `workspace` argument always wins; otherwise the session's
        selection is used; otherwise the sole registered workspace. With several
        registered and none selected, refuse rather than guess -- guessing here
        writes into the wrong project.
        """
        if requested:
            return self.registry.get(requested)

        workspace = self.active(session_id)
        if workspace is not None:
            return workspace

        if len(self.registry) == 0:
            raise WorkspaceError(
                "no workspaces are registered. The owner adds one from the console on this machine."
            )
        raise WorkspaceError(
            "no workspace selected for this conversation. Choose one of: "
            f"{', '.join(self.registry.aliases())}"
        )

    def forget(self, session_id: str) -> None:
        self._active.pop(session_id, None)

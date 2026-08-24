"""Workspace selection, per-session isolation, and expiring elevation."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from pharness.core.config import Mode
from pharness.core.errors import WorkspaceError
from pharness.core.workspace import Sessions, WorkspaceRegistry


def test_unknown_alias_lists_what_is_available(registry: WorkspaceRegistry):
    with pytest.raises(WorkspaceError) as excinfo:
        registry.get("nope")
    message = str(excinfo.value)
    assert "proj" in message and "locked" in message
    assert "owner" in message  # tells the model who can add one, and where


def test_two_sessions_do_not_share_a_selection(registry: WorkspaceRegistry):
    sessions = Sessions(registry)
    sessions.use("chat-a", "proj")
    sessions.use("chat-b", "locked")
    assert sessions.active("chat-a").alias == "proj"
    assert sessions.active("chat-b").alias == "locked"


def test_ambiguous_selection_is_refused_not_guessed(registry: WorkspaceRegistry):
    sessions = Sessions(registry)
    with pytest.raises(WorkspaceError, match="no workspace selected"):
        sessions.resolve("fresh-chat")


def test_sole_workspace_needs_no_selection(project, registry: WorkspaceRegistry):
    from pharness.adapters.posix.paths import PosixPaths
    from pharness.core.config import parse_config

    single = WorkspaceRegistry.from_config(
        parse_config({"workspace": [{"alias": "only", "path": str(project)}]}), PosixPaths()
    )
    assert Sessions(single).resolve("fresh-chat").alias == "only"


def test_explicit_argument_beats_session_selection(registry: WorkspaceRegistry):
    sessions = Sessions(registry)
    sessions.use("chat", "proj")
    assert sessions.resolve("chat", "locked").alias == "locked"


def test_read_only_workspace_cannot_write(registry: WorkspaceRegistry, now: datetime):
    locked = registry.get("locked")
    assert locked.effective_mode(now) is Mode.READ_ONLY
    assert not locked.may_write(now)
    assert not locked.may_execute(now)


def test_full_access_expires_on_its_own(registry: WorkspaceRegistry, now: datetime):
    workspace = registry.get("proj")
    workspace.grant_full_access(120, now)

    assert workspace.effective_mode(now) is Mode.FULL_ACCESS
    assert workspace.effective_mode(now + timedelta(minutes=119)) is Mode.FULL_ACCESS
    # The point of the TTL: nobody has to remember to turn it off.
    assert workspace.effective_mode(now + timedelta(minutes=121)) is Mode.AUTO_EDIT


def test_full_access_needs_a_positive_lifetime(registry: WorkspaceRegistry, now: datetime):
    with pytest.raises(WorkspaceError):
        registry.get("proj").grant_full_access(0, now)


def test_push_needs_both_the_flag_and_write_permission(registry: WorkspaceRegistry, now: datetime):
    assert not registry.get("proj").may_push(now)  # git_push defaults to off

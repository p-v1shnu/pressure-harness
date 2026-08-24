"""Property tests for the parts a targeted test cannot cover exhaustively.

The path jail and the command classifier are the two places where being wrong
once is enough, so they are checked against generated input rather than only
against cases someone thought of (PRD 16, non-functional requirements).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pharness.adapters.posix.paths import PosixPaths
from pharness.adapters.posix.shell import PosixShell
from pharness.adapters.windows.shell import WindowsShell
from pharness.core.errors import PathJailError
from pharness.core.policy.commands import Tier, classify, program_key
from pharness.core.policy.path_jail import PathJail
from pharness.ports import ShellParseError

# Characters chosen to hit quoting, chaining, substitution and redirection.
SHELL_ALPHABET = st.sampled_from(
    list("abcdeimnprstuvxz01 \t") + list("'\"`$();|&<>*\\/.-=^{}[]!#~,:@")
)
COMMAND_TEXT = st.text(alphabet=SHELL_ALPHABET, max_size=60)

# Deliberately heavy on separators, dots and drive-letter syntax: those are the
# ingredients of every traversal attempt.
PATH_TEXT = st.text(alphabet=st.sampled_from([*list("abcsrp./\\: .~C"), "\x00"]), max_size=40)

FUZZ = settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


@pytest.fixture(params=[PosixShell(), WindowsShell()], ids=["posix", "windows"])
def shell(request: pytest.FixtureRequest):
    return request.param


@given(COMMAND_TEXT)
@FUZZ
def test_classify_never_raises(shell, text: str):
    """A crash in the classifier is a bypass: the call would never reach a verdict."""
    verdict = classify(text, shell=shell, allow_commands=["npm test"])
    assert isinstance(verdict.tier, Tier)


@given(COMMAND_TEXT)
@FUZZ
def test_parse_either_refuses_or_returns_well_formed_commands(shell, text: str):
    try:
        commands = shell.parse(text)
    except ShellParseError:
        return  # refusing is always an acceptable answer
    for command in commands:
        assert command.argv
        assert all(isinstance(argument, str) for argument in command.argv)


@given(COMMAND_TEXT)
@FUZZ
def test_appending_a_destructive_command_is_never_auto_allowed(shell, text: str):
    r"""Whatever the prefix is, `; rm -rf /` on the end must not sail through.

    This is the invariant an allowlist-by-first-word check fails.

    Stated as "never auto-allowed" rather than "always forbidden" because of a
    case the fuzzer found: a prefix ending in an escape character (`\` in POSIX,
    `^` in cmd) escapes the separator, so the line becomes one command named `;`
    with `rm -rf /` as its arguments. Nothing destructive runs -- the command
    does not exist -- and the honest verdict is "ask", not "forbidden". What must
    never happen is ALLOW.
    """
    combined = f"{text}; rm -rf /"
    verdict = classify(combined, shell=shell, allow_commands=["npm test"])
    assert verdict.tier >= Tier.EXEC_OTHER

    ran_rm = any(program_key(c.argv[0]) == "rm" for c in verdict.commands if c.argv)
    if ran_rm:
        assert verdict.tier is Tier.FORBIDDEN


@given(COMMAND_TEXT)
@FUZZ
def test_allowlisted_verdicts_are_never_compound(shell, text: str):
    """Reaching EXEC_ALLOWED means exactly one command and no interpreter."""
    verdict = classify(text, shell=shell, allow_commands=["npm test", "git status"])
    if verdict.tier is Tier.EXEC_ALLOWED:
        assert len(verdict.commands) == 1
        assert verdict.matched_allowlist is not None


@given(PATH_TEXT)
@FUZZ
def test_path_jail_never_returns_a_path_outside_the_workspace(tmp_path: Path, text: str):
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True, exist_ok=True)
    workspace = _workspace(root)
    jail = PathJail.with_app_dirs(PosixPaths())

    try:
        resolved = jail.check(workspace, text)
    except PathJailError:
        return
    assert resolved == root or root in resolved.parents


@given(st.lists(st.sampled_from(["..", ".", "src", "a", "~", "%2e%2e"]), max_size=8))
@FUZZ
def test_traversal_sequences_cannot_escape(tmp_path: Path, parts: list[str]):
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True, exist_ok=True)
    workspace = _workspace(root)
    jail = PathJail.with_app_dirs(PosixPaths())

    candidate = "/".join(parts)
    if not candidate.strip():
        return
    try:
        resolved = jail.check(workspace, candidate)
    except PathJailError:
        return
    assert resolved == root or root in resolved.parents


def _workspace(root: Path):
    from pharness.adapters.posix.paths import PosixPaths as P
    from pharness.core.config import parse_config
    from pharness.core.workspace import WorkspaceRegistry

    config = parse_config({"workspace": [{"alias": "ws", "path": str(root)}]})
    return WorkspaceRegistry.from_config(config, P()).get("ws")

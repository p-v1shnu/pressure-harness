"""Child environments are built, not inherited."""

from __future__ import annotations

import pytest

from pharness.core.env import ALWAYS_BLOCKED, build_env

PARENT = {
    "PATH": "/usr/bin",
    "HOME": "/home/dev",
    "NODE_ENV": "test",
    "SystemRoot": r"C:\Windows",
    "AWS_SECRET_ACCESS_KEY": "leak-me",
    "OPENAI_API_KEY": "sk-leak",
    "MY_APP_TOKEN": "leak-too",
    "LD_PRELOAD": "/tmp/evil.so",
}


def test_secrets_are_not_forwarded():
    """The default of passing the parent environment through hands every key over."""
    env = build_env(PARENT, "posix")
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "OPENAI_API_KEY" not in env
    assert "MY_APP_TOKEN" not in env


def test_essentials_are_kept():
    env = build_env(PARENT, "posix")
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/home/dev"
    assert env["NODE_ENV"] == "test"


def test_windows_needs_its_own_variables():
    """Programs fail confusingly without SystemRoot, which is worse than loudly."""
    assert "SystemRoot" in build_env(PARENT, "windows")
    assert "SystemRoot" not in build_env(PARENT, "posix")


@pytest.mark.parametrize("dangerous", sorted(ALWAYS_BLOCKED))
def test_loader_variables_are_blocked_even_when_allowlisted(dangerous: str):
    """These change what a program is, not how it behaves."""
    env = build_env({**PARENT, dangerous: "value"}, "posix", extra_allow=(dangerous,))
    assert dangerous not in env


def test_extra_allowlist_lets_a_project_variable_through():
    env = build_env(PARENT, "posix", extra_allow=("MY_APP_TOKEN",))
    assert env["MY_APP_TOKEN"] == "leak-too"


def test_overrides_win():
    env = build_env(PARENT, "posix", overrides={"NODE_ENV": "production"})
    assert env["NODE_ENV"] == "production"


def test_interactive_prompts_are_turned_off():
    """A child waiting for a keystroke hangs the tool call until it times out."""
    env = build_env(PARENT, "posix")
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_PAGER"] == "cat"
    assert env["CI"] == "1"


def test_lookup_is_case_insensitive_like_windows():
    env = build_env({"systemroot": r"C:\Windows", "PATH": "x"}, "windows")
    assert env.get("systemroot") == r"C:\Windows"

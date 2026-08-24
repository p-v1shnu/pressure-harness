"""Errors the core raises. None of them carry a payload verbatim.

Denial messages are shown to the model, so they name what is allowed rather
than echoing what was attempted -- an echoed path or command is a small
exfiltration channel back into the conversation.
"""

from __future__ import annotations


class PharnessError(Exception):
    """Base class for everything this package raises deliberately."""


class ConfigError(PharnessError):
    """Configuration is missing, malformed, or unsafe."""


class WorkspaceError(PharnessError):
    """The requested workspace does not exist or is not usable."""


class PathJailError(PharnessError):
    """A path is outside every registered workspace, or is otherwise forbidden."""


class PolicyDenied(PharnessError):
    """The policy engine refused an action outright (tier T5)."""

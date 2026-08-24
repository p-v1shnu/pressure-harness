"""Parsing a command line the way the platform's shell would.

The single most security-critical difference between platforms (PRD 14.4):
quoting and chaining rules for cmd/PowerShell and for POSIX shells have almost
nothing in common, so a denylist written against one does not hold against the
other. Parsing is a port; classification of what was parsed is core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class ShellParseError(Exception):
    """Raised when a command line cannot be parsed with confidence.

    The core treats this as a denial. Fail closed: an unparseable command is
    never handed to the platform to interpret (PRD 10.4).
    """


@dataclass(frozen=True)
class ParsedCommand:
    """One simple command extracted from a possibly compound command line."""

    argv: tuple[str, ...]
    raw: str
    overwrite_targets: tuple[str, ...] = field(default=())
    """Files this segment truncates through output redirection."""

    @property
    def program(self) -> str:
        return self.argv[0] if self.argv else ""


@runtime_checkable
class ShellPort(Protocol):
    """Splits a command line into the simple commands it would actually run."""

    name: str

    def parse(self, command: str) -> tuple[ParsedCommand, ...]:
        """Split `command` into every simple command it would execute.

        Must expand chaining and grouping — `&&`, `||`, `;`, `|`, newlines,
        command substitution — so the caller sees each segment separately.
        Raises ShellParseError rather than guessing.
        """

    def interpreter_payloads(self, cmd: ParsedCommand) -> tuple[str, ...]:
        """Return code strings `cmd` would hand to an interpreter.

        `bash -c "..."`, `powershell -Command "..."`, `python -c "..."` are
        escape hatches around any allowlist; the core needs to see the payload
        to classify the call honestly.
        """

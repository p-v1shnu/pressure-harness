"""macOS shell parser — declared, not implemented (M9).

zsh and bash quoting is close enough to the POSIX adapter that this will
likely delegate to it, but that is a decision for M9 with contract tests in
hand rather than an assumption baked in now.
"""

from __future__ import annotations

from pharness.ports.shell import ParsedCommand

_TODO = "macOS support lands in M9; see PRD 14.4"


class MacOSShell:
    name = "macos"

    def parse(self, command: str) -> tuple[ParsedCommand, ...]:
        raise NotImplementedError(_TODO)

    def interpreter_payloads(self, cmd: ParsedCommand) -> tuple[str, ...]:
        raise NotImplementedError(_TODO)

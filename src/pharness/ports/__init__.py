"""Contracts between the OS-agnostic core and the per-platform adapters.

Nothing here imports from `pharness.core` or `pharness.adapters` — these are
declarations only (PRD section 14.1). CI enforces that with import-linter, so a
stray platform import in `core/` fails the build rather than being discovered
at port time.
"""

from pharness.ports.browser import BrowserPort
from pharness.ports.paths import PathsPort
from pharness.ports.process import CompletedProcess, ProcessHandle, ProcessPort
from pharness.ports.shell import ParsedCommand, ShellParseError, ShellPort

__all__ = [
    "BrowserPort",
    "CompletedProcess",
    "ParsedCommand",
    "PathsPort",
    "ProcessHandle",
    "ProcessPort",
    "ShellParseError",
    "ShellPort",
]

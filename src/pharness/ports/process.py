"""Spawning, streaming and killing child processes.

Windows and POSIX disagree about almost everything here: process groups versus
job objects, signals versus `taskkill`, and which environment variables a
program cannot start without. The core asks for "run this" and lets the adapter
decide how (PRD 14.4).

Two shapes, because two things are needed. `run` is for commands that finish --
git, a test suite, a build -- and returns everything at once. `spawn` is for a
dev server that keeps going, and returns a handle to watch and later stop.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


class ProcessStartError(Exception):
    """A process could not be started at all.

    Distinct from a process that ran and failed: "npm is not installed" and
    "the tests failed" need different answers, and collapsing them into one
    error makes both harder to act on.
    """


@dataclass(frozen=True)
class CompletedProcess:
    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_sec: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    @property
    def combined(self) -> str:
        parts = [part for part in (self.stdout.rstrip(), self.stderr.rstrip()) if part]
        return "\n".join(parts)


@runtime_checkable
class ProcessHandle(Protocol):
    """A process that is still running, or has finished but not been forgotten."""

    id: str
    pid: int
    argv: tuple[str, ...]

    def is_running(self) -> bool: ...

    def exit_code(self) -> int | None: ...

    def tail(self, lines: int = 50) -> str:
        """Recent output. The full log stays on disk, out of the conversation."""

    def stop(self, timeout_sec: float = 5.0) -> int | None:
        """Terminate the process and every child it started.

        Killing only the named process leaves the actual dev server running and
        the port still bound, which looks exactly like a bug in our software.
        """


@runtime_checkable
class ProcessPort(Protocol):
    name: str

    def run(
        self,
        argv: Sequence[str],
        cwd: Path,
        env: Mapping[str, str],
        timeout_sec: float = 120.0,
    ) -> CompletedProcess:
        """Run to completion with exactly `env` -- never the caller's own.

        An inherited environment carries credentials into every child process
        (PRD 10.5), so the environment is built explicitly, not passed through.
        """

    def spawn(
        self,
        argv: Sequence[str],
        cwd: Path,
        env: Mapping[str, str],
        label: str = "",
    ) -> ProcessHandle:
        """Start a long-running process and return immediately."""

    def get(self, process_id: str) -> ProcessHandle | None: ...

    def list_running(self) -> tuple[ProcessHandle, ...]: ...

    def stop_all(self) -> int:
        """Stop everything we started. The emergency button depends on this."""

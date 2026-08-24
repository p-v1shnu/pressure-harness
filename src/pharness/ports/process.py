"""Spawning, streaming and killing child processes.

Windows needs job objects and `taskkill /T`; POSIX needs process groups and
signals. Implemented from M3 onwards; declared here so the core can be written
against it now.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class ProcessHandle(Protocol):
    pid: int

    def is_running(self) -> bool: ...

    def tail(self, lines: int) -> str:
        """Recent output. Full output stays on disk (PRD 11)."""

    def stop(self, timeout_sec: float = 5.0) -> int:
        """Terminate the process and every child it spawned. Returns exit code."""


@runtime_checkable
class ProcessPort(Protocol):
    name: str

    def spawn(
        self,
        argv: Sequence[str],
        cwd: Path,
        env: dict[str, str],
        shell_name: str | None = None,
    ) -> ProcessHandle:
        """Start a process with exactly `env` — never the caller's environment.

        Inherited environments leak credentials into child processes
        (PRD 10.5).
        """

    def list_running(self) -> tuple[ProcessHandle, ...]: ...

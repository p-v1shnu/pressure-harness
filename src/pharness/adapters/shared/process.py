"""Process management that is the same everywhere.

Output goes to a file rather than a pipe. Pipes deadlock when nobody drains
them, and a dev server that has been running for an hour has produced far more
output than belongs in memory -- let alone in a conversation. `tail` reads the
end of the file, which is the only part anyone wants (PRD 11).

What differs per platform -- how to start a process in its own group and how to
kill that whole group -- is left abstract here and filled in by each adapter.
"""

from __future__ import annotations

import subprocess
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from pathlib import Path

from pharness.ports.process import CompletedProcess

TAIL_BLOCK = 64 * 1024


class BaseHandle:
    def __init__(
        self,
        process_id: str,
        popen: subprocess.Popen[bytes],
        argv: Sequence[str],
        log_path: Path,
        label: str,
        killer,
    ) -> None:
        self.id = process_id
        self.pid = popen.pid
        self.argv = tuple(argv)
        self.label = label
        self.started_at = time.time()
        self._popen = popen
        self._log_path = log_path
        self._killer = killer

    def is_running(self) -> bool:
        return self._popen.poll() is None

    def exit_code(self) -> int | None:
        return self._popen.poll()

    def uptime_sec(self) -> float:
        return time.time() - self.started_at

    def tail(self, lines: int = 50) -> str:
        """Read the last `lines` of output without loading the whole log."""
        if not self._log_path.exists():
            return ""
        size = self._log_path.stat().st_size
        with self._log_path.open("rb") as handle:
            handle.seek(max(0, size - TAIL_BLOCK))
            block = handle.read()
        text = block.decode("utf-8", errors="replace")
        if size > TAIL_BLOCK:
            text = text.split("\n", 1)[-1]  # drop the partial first line
        return "\n".join(text.splitlines()[-lines:])

    def log_path(self) -> Path:
        return self._log_path

    def stop(self, timeout_sec: float = 5.0) -> int | None:
        if not self.is_running():
            return self._popen.poll()
        self._killer(self._popen, timeout_sec)
        try:
            return self._popen.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            return None


class BaseProcessAdapter(ABC):
    """Shared spawn/run/registry behaviour. Subclasses supply the OS specifics."""

    name = "base"

    def __init__(self, log_dir: Path) -> None:
        self._log_dir = Path(log_dir)
        self._handles: dict[str, BaseHandle] = {}
        self._counter = 0

    # -- platform specifics -------------------------------------------------

    @abstractmethod
    def _spawn_kwargs(self) -> dict:
        """Flags that put the child in its own group, so the group can be killed."""

    @abstractmethod
    def _kill_tree(self, popen: subprocess.Popen[bytes], timeout_sec: float) -> None:
        """Terminate the process and everything it started."""

    # -- shared -------------------------------------------------------------

    def run(
        self,
        argv: Sequence[str],
        cwd: Path,
        env: Mapping[str, str],
        timeout_sec: float = 120.0,
    ) -> CompletedProcess:
        started = time.monotonic()
        try:
            completed = subprocess.run(
                list(argv),
                cwd=str(cwd),
                env=dict(env),
                capture_output=True,
                timeout=timeout_sec,
                check=False,
                stdin=subprocess.DEVNULL,
                **self._spawn_kwargs(),
            )
        except subprocess.TimeoutExpired as expired:
            return CompletedProcess(
                argv=tuple(argv),
                exit_code=-1,
                stdout=_decode(expired.stdout),
                stderr=_decode(expired.stderr),
                duration_sec=time.monotonic() - started,
                timed_out=True,
            )
        except FileNotFoundError:
            return CompletedProcess(
                argv=tuple(argv),
                exit_code=127,
                stdout="",
                stderr=f"{argv[0]}: not found on PATH",
                duration_sec=time.monotonic() - started,
            )
        except OSError as exc:
            return CompletedProcess(
                argv=tuple(argv),
                exit_code=126,
                stdout="",
                stderr=f"could not start {argv[0]}: {exc}",
                duration_sec=time.monotonic() - started,
            )

        return CompletedProcess(
            argv=tuple(argv),
            exit_code=completed.returncode,
            stdout=_decode(completed.stdout),
            stderr=_decode(completed.stderr),
            duration_sec=time.monotonic() - started,
        )

    def spawn(
        self,
        argv: Sequence[str],
        cwd: Path,
        env: Mapping[str, str],
        label: str = "",
    ) -> BaseHandle:
        self._counter += 1
        process_id = f"p{self._counter}"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self._log_dir / f"{process_id}.log"

        # stdin is closed: a child that waits for input would hang forever with
        # nobody able to type at it.
        with log_path.open("wb") as sink:
            popen = subprocess.Popen(
                list(argv),
                cwd=str(cwd),
                env=dict(env),
                stdout=sink,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                **self._spawn_kwargs(),
            )

        handle = BaseHandle(process_id, popen, argv, log_path, label or argv[0], self._kill_tree)
        self._handles[process_id] = handle
        return handle

    def get(self, process_id: str) -> BaseHandle | None:
        return self._handles.get(process_id)

    def list_running(self) -> tuple[BaseHandle, ...]:
        return tuple(h for h in self._handles.values() if h.is_running())

    def list_all(self) -> tuple[BaseHandle, ...]:
        return tuple(self._handles.values())

    def stop_all(self) -> int:
        """Used by the emergency button, so it must not stop at the first failure."""
        stopped = 0
        for handle in self.list_running():
            try:
                handle.stop()
                stopped += 1
            except OSError:
                continue
        return stopped


def _decode(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    return raw.decode("utf-8", errors="replace")

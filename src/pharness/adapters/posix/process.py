"""Process management on POSIX: process groups and signals."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from pharness.adapters.shared.process import BaseProcessAdapter


class PosixProcess(BaseProcessAdapter):
    name = "posix"

    def __init__(self, log_dir: Path) -> None:
        super().__init__(log_dir)

    def _spawn_kwargs(self) -> dict:
        # Its own session, so signalling the group reaches every descendant.
        # A dev server usually spawns a bundler; killing only the parent leaves
        # the port bound and looks like our bug.
        return {"start_new_session": True}

    def _kill_tree(self, popen: subprocess.Popen[bytes], timeout_sec: float) -> None:
        try:
            group = os.getpgid(popen.pid)
        except ProcessLookupError:
            return

        os.killpg(group, signal.SIGTERM)

        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if popen.poll() is not None:
                return
            time.sleep(0.05)

        # Asked politely, waited, now insist.
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            return

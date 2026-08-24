"""Process management on Windows: process groups and `taskkill /T`.

`taskkill /T /F` rather than a job object because it is built in and needs no
extra dependency. A job object would be tidier and is the natural upgrade if
stray processes ever survive; this is the version that works today.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from pharness.adapters.shared.process import BaseProcessAdapter

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


class WindowsProcess(BaseProcessAdapter):
    name = "windows"

    def __init__(self, log_dir: Path) -> None:
        super().__init__(log_dir)

    def _spawn_kwargs(self) -> dict:
        # CREATE_NO_WINDOW keeps a console window from flashing up for every
        # command; the new process group is what makes the tree killable.
        return {"creationflags": CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW}

    def _kill_tree(self, popen: subprocess.Popen[bytes], timeout_sec: float) -> None:
        subprocess.run(
            ["taskkill", "/PID", str(popen.pid), "/T"],
            capture_output=True,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )

        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if popen.poll() is not None:
                return
            time.sleep(0.05)

        subprocess.run(
            ["taskkill", "/PID", str(popen.pid), "/T", "/F"],
            capture_output=True,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )

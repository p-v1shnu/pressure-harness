"""Finding and launching a browser.

Where Chrome lives, and what a user profile directory is called, differ per
platform; talking to it does not -- the DevTools Protocol is identical
everywhere, which is why only the discovery half is a port (PRD 14.4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class BrowserPort(Protocol):
    name: str

    def find_executable(self) -> Path | None:
        """Locate a Chromium-family browser, or None if there is not one."""

    def default_profile_dir(self, data_dir: Path) -> Path:
        """A profile directory of our own.

        Never the user's real profile: attaching to that would put their
        cookies and logged-in sessions within reach of whatever the model does
        next (PRD 10.5).
        """

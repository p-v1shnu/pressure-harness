"""Locating a Chromium-family browser.

The search order is the same idea everywhere -- an explicit setting, then the
usual install locations, then PATH -- so it lives here with a per-platform list
of places to look.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

WINDOWS_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)

MACOS_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)

POSIX_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")

WINDOWS_NAMES = ("chrome.exe", "msedge.exe")


class BrowserLocator:
    """Shared discovery. `platform` decides where to look."""

    def __init__(self, platform: str, environ: dict[str, str] | None = None) -> None:
        self.name = platform
        self._env = dict(os.environ if environ is None else environ)

    def find_executable(self) -> Path | None:
        override = self._env.get("PHARNESS_BROWSER")
        if override and Path(override).exists():
            return Path(override)

        candidates = {
            "windows": WINDOWS_CANDIDATES,
            "macos": MACOS_CANDIDATES,
        }.get(self.name, ())
        for candidate in candidates:
            if Path(candidate).exists():
                return Path(candidate)

        names = WINDOWS_NAMES if self.name == "windows" else POSIX_NAMES
        for name in names:
            found = shutil.which(name, path=self._env.get("PATH"))
            if found:
                return Path(found)

        # Playwright installs its own build; use it rather than reporting that
        # no browser exists on a machine that plainly has one.
        browsers_path = self._env.get("PLAYWRIGHT_BROWSERS_PATH")
        if browsers_path:
            root = Path(browsers_path)
            for pattern in ("chromium-*/chrome-linux/chrome", "chromium-*/chrome-win/chrome.exe"):
                matches = sorted(root.glob(pattern))
                if matches:
                    return matches[-1]
        return None

    def default_profile_dir(self, data_dir: Path) -> Path:
        return Path(data_dir) / "browser-profile"

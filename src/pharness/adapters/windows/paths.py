"""Windows path rules.

Written as pure string and PurePath logic so Linux and macOS CI can test it
(PRD 14.2). The only call that needs a real Windows filesystem is `resolve`,
which is where junction and reparse-point following happens.
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PureWindowsPath

_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]?")

_BROAD_DIRS = ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos", "OneDrive")

_SYSTEM_ROOTS = ("Windows", "Program Files", "Program Files (x86)", "ProgramData")


class WindowsPaths:
    name = "windows"

    def __init__(self, environ: dict[str, str] | None = None) -> None:
        self._env = dict(os.environ if environ is None else environ)

    # -- locations ---------------------------------------------------------

    def _profile(self) -> str:
        return self._env.get("USERPROFILE") or "C:\\Users\\Default"

    def config_dir(self) -> Path:
        base = self._env.get("APPDATA") or f"{self._profile()}\\AppData\\Roaming"
        return Path(base) / "PressureHarness"

    def data_dir(self) -> Path:
        base = self._env.get("LOCALAPPDATA") or f"{self._profile()}\\AppData\\Local"
        return Path(base) / "PressureHarness"

    # -- semantics ---------------------------------------------------------

    def resolve(self, path: Path) -> Path:
        return Path(path).resolve()

    def is_absolute_like(self, raw: str) -> bool:
        """`C:\\x`, `\\\\server\\share`, `\\x` and `/x` are all absolute here.

        A POSIX `Path` reads the first two as relative, which is exactly the
        kind of gap a path jail must not have.
        """
        if not raw:
            return False
        if _DRIVE_RE.match(raw):
            return True
        return raw[0] in ("\\", "/")

    def is_reserved_name(self, raw: str) -> bool:
        for part in re.split(r"[\\/]+", raw):
            if not part:
                continue
            # Reserved names stay reserved with an extension, and trailing dots
            # and spaces are stripped by the filesystem: "NUL.txt " is NUL.
            stem = part.split(".")[0].rstrip(" .").upper()
            if stem in _RESERVED:
                return True
        return False

    def paths_equal(self, a: Path, b: Path) -> bool:
        return str(a).casefold() == str(b).casefold()

    def broad_scope_reason(self, path: Path) -> str | None:
        p = PureWindowsPath(str(path))
        parts = p.parts

        if not parts:
            return None
        if len(parts) == 1 and _DRIVE_RE.match(parts[0]):
            return f"an entire drive ({parts[0]})"
        if len(parts) >= 2 and parts[1] in _SYSTEM_ROOTS:
            return f"a Windows system directory ({p})"

        profile = PureWindowsPath(self._profile())
        if _same(p, profile):
            return "your entire user profile"
        if _same(p.parent, profile) and p.name in _BROAD_DIRS:
            return f"a whole personal folder ({p.name})"
        if len(parts) == 3 and parts[1].casefold() == "users":
            return f"another user's whole profile ({p})"
        return None


def _same(a: PureWindowsPath, b: PureWindowsPath) -> bool:
    return str(a).casefold().rstrip("\\") == str(b).casefold().rstrip("\\")

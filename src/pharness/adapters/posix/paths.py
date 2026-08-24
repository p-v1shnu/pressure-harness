"""POSIX path rules (Linux and macOS).

Pure logic wherever possible, so the whole adapter can be exercised from any
platform's CI (PRD 14.2). The only genuinely platform-bound call is `resolve`.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

_BROAD_DIRS = ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Movies")


class PosixPaths:
    name = "posix"

    def __init__(self, environ: dict[str, str] | None = None, home: str | None = None) -> None:
        self._env = dict(os.environ if environ is None else environ)
        self._home = home or self._env.get("HOME", "/root")

    # -- locations ---------------------------------------------------------

    def config_dir(self) -> Path:
        base = self._env.get("XDG_CONFIG_HOME") or f"{self._home}/.config"
        return Path(base) / "pressure-harness"

    def data_dir(self) -> Path:
        base = self._env.get("XDG_DATA_HOME") or f"{self._home}/.local/share"
        return Path(base) / "pressure-harness"

    # -- semantics ---------------------------------------------------------

    def resolve(self, path: Path) -> Path:
        return Path(path).resolve()

    def is_absolute_like(self, raw: str) -> bool:
        return raw.startswith("/")

    def is_reserved_name(self, raw: str) -> bool:
        return False  # POSIX has no reserved device names in the filesystem namespace

    def paths_equal(self, a: Path, b: Path) -> bool:
        # macOS is case-insensitive by default and Linux is not. Comparing
        # exactly is the safe direction: it can only reject a match, never
        # wrongly accept one.
        return str(a) == str(b)

    def broad_scope_reason(self, path: Path) -> str | None:
        p = PurePosixPath(str(path))
        home = PurePosixPath(self._home)

        if str(p) == "/":
            return "the filesystem root"
        if len(p.parts) <= 2 and str(p).startswith("/"):
            return f"a top-level system directory ({p})"
        if p == home:
            return "your entire home directory"
        if p.parent == home and p.name in _BROAD_DIRS:
            return f"a whole personal folder ({p.name})"
        return None

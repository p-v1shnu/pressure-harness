"""Chooses the platform adapter once, at startup.

After this, nothing in `core/` needs to know which OS it is running on. The
capability set is what makes the tool registry runtime-built rather than a
fixed list, so a platform never advertises a tool it cannot perform
(PRD 14.3) -- advertising one costs quota and credibility every time the model
tries it and fails.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from pharness.ports import PathsPort, ShellPort


class UnsupportedPlatformError(RuntimeError):
    pass


@dataclass(frozen=True)
class Adapters:
    platform: str
    paths: PathsPort
    shell: ShellPort
    capabilities: frozenset[str]
    supported: bool
    """False for a platform that runs but is not a v1 target."""


# Capabilities the v1 tool catalogue (PRD 8.2) can be built from.
_CORE_CAPABILITIES = frozenset(
    {"files", "search", "patch", "git", "project", "process", "shell", "browser", "web_fetch"}
)


def select(platform: str | None = None) -> Adapters:
    key = platform or sys.platform

    if key.startswith("win"):
        from pharness.adapters.windows.paths import WindowsPaths
        from pharness.adapters.windows.shell import WindowsShell

        return Adapters(
            platform="windows",
            paths=WindowsPaths(),
            shell=WindowsShell(),
            capabilities=_CORE_CAPABILITIES,
            supported=True,
        )

    if key == "darwin":
        from pharness.adapters.macos.paths import MacOSPaths
        from pharness.adapters.macos.shell import MacOSShell

        return Adapters(
            platform="macos",
            paths=MacOSPaths(),
            shell=MacOSShell(),
            capabilities=frozenset(),
            supported=False,
        )

    if key.startswith("linux"):
        # Not a v1 target, but a real adapter: CI runs the core against it on
        # every push so path and encoding assumptions are caught early
        # (PRD 14.2).
        from pharness.adapters.posix.paths import PosixPaths
        from pharness.adapters.posix.shell import PosixShell

        return Adapters(
            platform="linux",
            paths=PosixPaths(),
            shell=PosixShell(),
            capabilities=_CORE_CAPABILITIES,
            supported=False,
        )

    raise UnsupportedPlatformError(f"no adapter for platform {key!r}")

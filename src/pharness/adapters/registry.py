"""Chooses the platform adapter once, at startup.

After this, nothing in `core/` needs to know which OS it is running on. The
capability set is what makes the tool registry runtime-built rather than a
fixed list, so a platform never advertises a tool it cannot perform
(PRD 14.3) -- advertising one costs quota and credibility every time the model
tries it and fails.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pharness.ports import BrowserPort, PathsPort, ProcessPort, ShellPort


class UnsupportedPlatformError(RuntimeError):
    pass


@dataclass(frozen=True)
class Adapters:
    platform: str
    paths: PathsPort
    shell: ShellPort
    process_factory: Callable[[Path], ProcessPort]
    """Built with a log directory rather than eagerly: where child process
    output lands is the caller's decision, and macOS has no implementation to
    construct yet."""
    browser: BrowserPort
    capabilities: frozenset[str]
    supported: bool
    """False for a platform that runs but is not a v1 target."""


# Capabilities the v1 tool catalogue (PRD 8.2) is built from.
#
# This lists what is implemented, not what is planned: the tool registry is
# built from it, and advertising a tool that cannot work costs quota and
# credibility every time the model tries it (PRD 14.3). `browser` and
# `web_fetch` join the set in M6.
_CORE_CAPABILITIES = frozenset(
    {"files", "search", "patch", "git", "project", "process", "shell", "web_fetch"}
)


def _capabilities(browser: BrowserPort) -> frozenset[str]:
    """Add `browser` only when there is actually a browser to drive.

    Whether Chrome is installed is a runtime fact, so it is answered at startup
    rather than assumed. A machine that gains a browser later gains the tool on
    the next start.
    """
    if browser.find_executable() is not None:
        return _CORE_CAPABILITIES | {"browser"}
    return _CORE_CAPABILITIES


def select_notifier(prefer_window: bool = True):
    """Pick the best way to ask the user on this machine.

    A window first, because the prompt has to appear whether or not a console
    is open (PRD 10.7). Falling back to the console keeps the CLI usable, and
    the null notifier -- which refuses everything -- is what an unattended
    machine gets, which is the correct answer there.
    """
    from pharness.adapters.shared.notifier import ConsoleNotifier, NullNotifier

    if prefer_window:
        from pharness.adapters.shared.notifier_tk import TkNotifier, tk_available

        if tk_available():
            return TkNotifier()

    console = ConsoleNotifier()
    return console if console.interactive else NullNotifier()


def select(platform: str | None = None) -> Adapters:
    key = platform or sys.platform

    if key.startswith("win"):
        from pharness.adapters.shared.browser import BrowserLocator
        from pharness.adapters.windows.paths import WindowsPaths
        from pharness.adapters.windows.process import WindowsProcess
        from pharness.adapters.windows.shell import WindowsShell

        browser = BrowserLocator("windows")
        return Adapters(
            platform="windows",
            paths=WindowsPaths(),
            shell=WindowsShell(),
            process_factory=WindowsProcess,
            browser=browser,
            capabilities=_capabilities(browser),
            supported=True,
        )

    if key == "darwin":
        from pharness.adapters.macos.paths import MacOSPaths
        from pharness.adapters.macos.shell import MacOSShell

        def _unavailable(_: Path) -> ProcessPort:
            raise NotImplementedError("macOS support lands in M9; see PRD 14.4")

        from pharness.adapters.shared.browser import BrowserLocator

        return Adapters(
            platform="macos",
            paths=MacOSPaths(),
            shell=MacOSShell(),
            process_factory=_unavailable,
            browser=BrowserLocator("macos"),
            capabilities=frozenset(),
            supported=False,
        )

    if key.startswith("linux"):
        # Not a v1 target, but a real adapter: CI runs the core against it on
        # every push so path and encoding assumptions are caught early
        # (PRD 14.2).
        from pharness.adapters.posix.paths import PosixPaths
        from pharness.adapters.posix.process import PosixProcess
        from pharness.adapters.posix.shell import PosixShell
        from pharness.adapters.shared.browser import BrowserLocator

        browser = BrowserLocator("linux")
        return Adapters(
            platform="linux",
            paths=PosixPaths(),
            shell=PosixShell(),
            process_factory=PosixProcess,
            browser=browser,
            capabilities=_capabilities(browser),
            supported=False,
        )

    raise UnsupportedPlatformError(f"no adapter for platform {key!r}")

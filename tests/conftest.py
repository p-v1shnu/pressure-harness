"""Shared fixtures.

The core is pure enough that most tests need no filesystem at all; the ones that
do get a real temporary directory rather than a mock, because the behaviour
under test is exactly what a real filesystem does with symlinks and `..`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pharness.adapters.posix.paths import PosixPaths
from pharness.adapters.posix.shell import PosixShell
from pharness.adapters.windows.paths import WindowsPaths
from pharness.adapters.windows.shell import WindowsShell
from pharness.core.config import parse_config
from pharness.core.policy.engine import PolicyEngine
from pharness.core.policy.path_jail import PathJail
from pharness.core.workspace import WorkspaceRegistry

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def posix_paths() -> PosixPaths:
    return PosixPaths(environ={"HOME": "/home/dev"}, home="/home/dev")


@pytest.fixture
def windows_paths() -> WindowsPaths:
    return WindowsPaths(
        environ={
            "USERPROFILE": r"C:\Users\dev",
            "APPDATA": r"C:\Users\dev\AppData\Roaming",
            "LOCALAPPDATA": r"C:\Users\dev\AppData\Local",
        }
    )


@pytest.fixture
def posix_shell() -> PosixShell:
    return PosixShell()


@pytest.fixture
def windows_shell() -> WindowsShell:
    return WindowsShell()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.ts").write_text("export const x = 1\n", encoding="utf-8")
    (root / ".env").write_text("SECRET_KEY=abc123456789\n", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("not yours\n", encoding="utf-8")
    return root


@pytest.fixture
def registry(project: Path) -> WorkspaceRegistry:
    config = parse_config(
        {
            "workspace": [
                {
                    "alias": "proj",
                    "path": str(project),
                    "allow_commands": ["npm test", "npm run build", "git status", "git diff"],
                },
                {"alias": "locked", "path": str(project), "mode": "read-only"},
            ]
        }
    )
    return WorkspaceRegistry.from_config(config, PosixPaths())


@pytest.fixture
def jail() -> PathJail:
    return PathJail.with_app_dirs(PosixPaths(environ={"HOME": "/home/dev"}, home="/home/dev"))


@pytest.fixture
def engine(posix_shell: PosixShell) -> PolicyEngine:
    return PolicyEngine(posix_shell)

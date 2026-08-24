"""One suite, run against every PathsPort implementation.

This is the mechanism that makes the macOS port a filling-in exercise rather
than a rewrite (PRD 14.2): when M9 implements the adapter, these tests already
say what it has to do. Running them on Linux against the Windows adapter is the
payoff for keeping the adapters pure.
"""

from __future__ import annotations

from pathlib import Path, PureWindowsPath

import pytest

from pharness.adapters.macos.paths import MacOSPaths
from pharness.adapters.posix.paths import PosixPaths
from pharness.adapters.windows.paths import WindowsPaths
from pharness.ports import PathsPort

IMPLEMENTED = [
    pytest.param(
        WindowsPaths(
            environ={
                "USERPROFILE": r"C:\Users\dev",
                "APPDATA": r"C:\Users\dev\AppData\Roaming",
                "LOCALAPPDATA": r"C:\Users\dev\AppData\Local",
            }
        ),
        id="windows",
    ),
    pytest.param(PosixPaths(environ={"HOME": "/home/dev"}, home="/home/dev"), id="posix"),
]


@pytest.fixture(params=IMPLEMENTED)
def paths(request: pytest.FixtureRequest) -> PathsPort:
    return request.param


def test_satisfies_the_protocol(paths: PathsPort):
    assert isinstance(paths, PathsPort)


def test_config_and_data_are_distinct_absolute_locations(paths: PathsPort):
    config, data = paths.config_dir(), paths.data_dir()
    assert config != data
    assert str(config) and str(data)


def test_resolve_is_idempotent(paths: PathsPort, tmp_path: Path):
    once = paths.resolve(tmp_path)
    assert paths.resolve(once) == once


def test_relative_paths_are_not_absolute_like(paths: PathsPort):
    for relative in ("src/app.ts", "a", "./b", "deep/nested/file.txt"):
        assert not paths.is_absolute_like(relative)


def test_posix_absolute_is_recognised_everywhere(paths: PathsPort):
    """Every platform must reject `/etc/passwd`, whatever its own syntax is."""
    assert paths.is_absolute_like("/etc/passwd")


def test_empty_string_is_not_absolute(paths: PathsPort):
    assert not paths.is_absolute_like("")


def test_paths_equal_is_reflexive(paths: PathsPort, tmp_path: Path):
    assert paths.paths_equal(tmp_path, tmp_path)
    assert not paths.paths_equal(tmp_path, tmp_path / "child")


def test_broad_scope_returns_a_reason_or_none(paths: PathsPort, tmp_path: Path):
    reason = paths.broad_scope_reason(tmp_path)
    assert reason is None or isinstance(reason, str)


# -- platform specifics, still worth pinning down ------------------------------


def test_windows_recognises_its_own_absolute_forms():
    paths = WindowsPaths(environ={})
    for absolute in (r"C:\Windows", "C:/Windows", r"\\server\share", r"\absolute", "/absolute"):
        assert paths.is_absolute_like(absolute), absolute


def test_windows_reserved_device_names():
    paths = WindowsPaths(environ={})
    for reserved in ("NUL", "nul.txt", r"src\CON", "COM1", "LPT9", "NUL. "):
        assert paths.is_reserved_name(reserved), reserved
    for ordinary in ("console.ts", "src/app.ts", "nullable.py", "comment.md"):
        assert not paths.is_reserved_name(ordinary), ordinary


def test_windows_paths_compare_case_insensitively():
    paths = WindowsPaths(environ={})
    assert paths.paths_equal(Path(r"C:\Work\App"), Path(r"c:\work\app"))


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        (r"C:\\", "entire drive"),
        (r"C:\Users\dev", "entire user profile"),
        (r"C:\Users\dev\Desktop", "personal folder"),
        (r"C:\Users\someone-else", "another user"),
        (r"C:\Windows\System32", "system directory"),
        (r"C:\Program Files", "system directory"),
        (r"D:\work\my-app", None),
    ],
)
def test_windows_flags_over_broad_workspaces(candidate: str, expected: str | None):
    """The failure seen in the reference tool: a whole drive as the project root."""
    paths = WindowsPaths(environ={"USERPROFILE": r"C:\Users\dev"})
    reason = paths.broad_scope_reason(PureWindowsPath(candidate))
    if expected is None:
        assert reason is None
    else:
        assert reason and expected in reason


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        ("/", "filesystem root"),
        ("/etc", "system directory"),
        ("/home/dev", "home directory"),
        ("/home/dev/Documents", "personal folder"),
        ("/home/dev/work/my-app", None),
    ],
)
def test_posix_flags_over_broad_workspaces(candidate: str, expected: str | None):
    paths = PosixPaths(environ={"HOME": "/home/dev"}, home="/home/dev")
    reason = paths.broad_scope_reason(Path(candidate))
    if expected is None:
        assert reason is None
    else:
        assert reason and expected in reason


def test_macos_adapter_is_declared_but_not_implemented():
    """Its contract for now is to fail loudly, not to half-work (PRD 14.5)."""
    paths = MacOSPaths()
    for call in (
        paths.config_dir,
        paths.data_dir,
        lambda: paths.resolve(Path("/tmp")),
        lambda: paths.is_absolute_like("/tmp"),
        lambda: paths.is_reserved_name("NUL"),
        lambda: paths.paths_equal(Path("/a"), Path("/a")),
        lambda: paths.broad_scope_reason(Path("/")),
    ):
        with pytest.raises(NotImplementedError, match="M9"):
            call()

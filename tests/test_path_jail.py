"""The path jail. Every case here is an escape someone will eventually try."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from pharness.core.errors import PathJailError
from pharness.core.policy.path_jail import PathJail
from pharness.core.workspace import WorkspaceRegistry


@pytest.fixture
def workspace(registry: WorkspaceRegistry):
    return registry.get("proj")


def symlinks_available(root: Path) -> bool:
    """Windows needs Developer Mode or elevation to create symlinks."""
    probe = root / ".symlink-probe"
    try:
        probe.symlink_to(root)
    except (OSError, NotImplementedError):
        return False
    probe.unlink()
    return True


needs_symlinks = pytest.mark.skipif(
    not symlinks_available(Path(tempfile.mkdtemp())),
    reason="this platform will not let us create symlinks",
)


@pytest.mark.parametrize(
    "relative",
    ["src/app.ts", "./src/app.ts", "src/../src/app.ts", "src/new-file.ts", "deep/nested/new.txt"],
)
def test_ordinary_paths_are_allowed(jail: PathJail, workspace, relative: str):
    assert jail.check(workspace, relative).is_relative_to(workspace.root)


@pytest.mark.parametrize(
    "relative",
    [
        "../outside.txt",
        "../../etc/passwd",
        "src/../../outside.txt",
        "/etc/passwd",
        "/tmp/anything",
    ],
)
def test_escapes_are_refused(jail: PathJail, workspace, relative: str):
    with pytest.raises(PathJailError):
        jail.check(workspace, relative)


@needs_symlinks
def test_symlink_pointing_outside_is_refused(jail: PathJail, workspace, tmp_path: Path):
    """The reason resolution happens before the containment check."""
    (workspace.root / "escape.txt").symlink_to(tmp_path / "outside.txt")
    with pytest.raises(PathJailError, match="outside workspace"):
        jail.check(workspace, "escape.txt")


@needs_symlinks
def test_symlink_staying_inside_is_allowed(jail: PathJail, workspace):
    (workspace.root / "alias.ts").symlink_to(workspace.root / "src" / "app.ts")
    assert jail.check(workspace, "alias.ts") == workspace.root / "src" / "app.ts"


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        (".env", "environment secrets"),
        (".env.production", "environment secrets"),
        (".ssh/id_rsa", "credentials"),
        (".aws/credentials", "credentials"),
        ("nested/.npmrc", "credentials"),
        (".git/config", "remote"),
        (".git/hooks/pre-commit", "hooks"),
        ("service-account.json", "credentials"),
    ],
)
def test_credential_paths_are_refused(jail: PathJail, workspace, relative: str, expected: str):
    with pytest.raises(PathJailError, match=expected):
        jail.check(workspace, relative)


def test_ordinary_git_files_stay_readable(jail: PathJail, workspace):
    """Only the dangerous parts of .git are off limits, not the whole directory."""
    assert jail.check(workspace, ".git/HEAD")
    assert jail.check(workspace, ".gitignore")


@pytest.mark.parametrize("relative", ["", "   ", " src/app.ts", "src/app.ts ", "src/\x00app.ts"])
def test_malformed_input_is_refused(jail: PathJail, workspace, relative: str):
    with pytest.raises(PathJailError):
        jail.check(workspace, relative)


def test_our_own_files_are_unreachable(workspace, tmp_path: Path):
    """No tool may edit the rules that constrain it (PRD 6.1)."""

    class Paths:
        name = "test"

        def config_dir(self):
            return workspace.root / "config-here"

        def data_dir(self):
            return workspace.root / "data-here"

        def resolve(self, path):
            return Path(path).resolve()

        def is_absolute_like(self, raw):
            return raw.startswith("/")

        def is_reserved_name(self, raw):
            return False

        def paths_equal(self, a, b):
            return str(a) == str(b)

        def broad_scope_reason(self, path):
            return None

    jail = PathJail.with_app_dirs(Paths())
    (workspace.root / "config-here").mkdir()
    with pytest.raises(PathJailError, match="Pressure Harness itself"):
        jail.check(workspace, "config-here/config.toml")

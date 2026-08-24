"""Confines every path a tool touches to an authorised workspace.

Resolution happens before containment, always: a symlink or a Windows junction
inside a workspace can point anywhere, so checking the literal string first and
opening the resolved path afterwards is the classic hole (PRD 10.3).

Known limitation, stated rather than papered over: resolving and then handing
the path to a caller leaves a window in which the filesystem could change
underneath us. Closing it needs open-then-verify at the syscall level, which is
platform work belonging to the file tools in M2; this class is the first gate,
not the only one.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from pharness.core.errors import PathJailError
from pharness.core.workspace import Workspace
from pharness.ports import PathsPort

# Directory names that hold credentials. Denied anywhere in a resolved path.
SECRET_DIRS = frozenset(
    {".ssh", ".aws", ".gnupg", ".azure", ".kube", ".docker", ".gcloud", ".pharness"}
)

# Exact file names that hold credentials.
SECRET_FILES = frozenset(
    {
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        ".netrc",
        "_netrc",
        ".npmrc",
        ".pypirc",
        ".git-credentials",
        "credentials",
        "credentials.json",
        "secrets.json",
        "service-account.json",
    }
)


def _is_env_file(name: str) -> bool:
    """`.env`, `.env.local`, `.env.production` and friends."""
    return name == ".env" or name.startswith(".env.")


def _git_internal_reason(parts: Sequence[str]) -> str | None:
    """Deny the parts of `.git` that are configuration or executable code.

    `.git/config` can point a remote anywhere, and `.git/hooks` runs on the next
    commit -- writing there is arbitrary code execution with no command to
    review.
    """
    for index, part in enumerate(parts):
        if part != ".git":
            continue
        rest = parts[index + 1 :]
        if rest[:1] == ("config",) or rest[:1] == ["config"]:
            return "git config can redirect a remote to another host"
        if rest and rest[0] == "hooks":
            return "git hooks run automatically, so writing one executes code later"
    return None


class PathJail:
    def __init__(self, paths: PathsPort, protected_dirs: Sequence[Path] = ()) -> None:
        self._paths = paths
        self._protected = tuple(paths.resolve(Path(p)) for p in protected_dirs)

    @classmethod
    def with_app_dirs(cls, paths: PathsPort) -> PathJail:
        """Protect our own config and audit log: no tool may reach them (PRD 6.1)."""
        return cls(paths, protected_dirs=(paths.config_dir(), paths.data_dir()))

    def check_absolute(self, workspace: Workspace, path: Path) -> Path:
        """Containment check for a path that is already absolute.

        Exists because not every way of naming a file goes through a relative
        string: a `file://` URL handed to the browser is an absolute path by
        the time anyone sees it, and it has to face the same rules or the jail
        only guards one door.
        """
        root = self._paths.resolve(workspace.root)
        resolved = self._paths.resolve(path)

        if not self._contains(root, resolved):
            raise PathJailError(f"that file is outside workspace {workspace.alias!r}")
        for protected in self._protected:
            if self._contains(protected, resolved):
                raise PathJailError(
                    "that path belongs to Pressure Harness itself and is never reachable"
                )

        relative = resolved.relative_to(root) if resolved != root else Path(".")
        reason = self.secret_reason(relative)
        if reason:
            raise PathJailError(f"refused: {reason}")
        return resolved

    def check(self, workspace: Workspace, raw: str) -> Path:
        """Return the resolved absolute path for `raw`, or raise PathJailError."""
        self._check_shape(raw)

        root = self._paths.resolve(workspace.root)
        resolved = self._paths.resolve(root / raw)

        if not self._contains(root, resolved):
            raise PathJailError(
                f"path is outside workspace {workspace.alias!r}. "
                "Paths must stay inside the authorised directory."
            )

        for protected in self._protected:
            if self._contains(protected, resolved):
                raise PathJailError(
                    "that path belongs to Pressure Harness itself and is never reachable"
                )

        relative = resolved.relative_to(root) if resolved != root else Path(".")
        reason = self.secret_reason(relative)
        if reason:
            raise PathJailError(f"refused: {reason}")

        return resolved

    def _check_shape(self, raw: str) -> None:
        if not raw or not raw.strip():
            raise PathJailError("path must not be empty")
        if raw != raw.strip():
            raise PathJailError("path must not have leading or trailing whitespace")
        if "\x00" in raw:
            raise PathJailError("path must not contain a null byte")
        if self._paths.is_absolute_like(raw):
            raise PathJailError(
                "absolute paths are not accepted; use a path relative to the workspace"
            )
        if self._paths.is_reserved_name(raw):
            raise PathJailError("that name is a reserved device name on this platform")

    def _contains(self, parent: Path, child: Path) -> bool:
        if self._paths.paths_equal(parent, child):
            return True
        return any(self._paths.paths_equal(parent, ancestor) for ancestor in child.parents)

    def secret_reason(self, relative: Path) -> str | None:
        """Why `relative` must not be read or written, or None if it is ordinary."""
        parts = PurePosixPath(relative.as_posix()).parts

        for part in parts:
            if part.lower() in SECRET_DIRS:
                return f"{part} holds credentials"

        name = parts[-1] if parts else ""
        if _is_env_file(name):
            return f"{name} holds environment secrets"
        if name.lower() in SECRET_FILES:
            return f"{name} holds credentials"

        return _git_internal_reason(parts)

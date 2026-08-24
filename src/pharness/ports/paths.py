"""Path semantics that differ per OS.

Drive letters, reserved device names, case sensitivity, symlinks versus
junctions, and where an application keeps its config are all platform
questions. The core asks them through this port instead of answering them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class PathsPort(Protocol):
    """Platform-specific path and location rules."""

    name: str

    def config_dir(self) -> Path:
        """Directory holding config.toml. Never reachable by any tool (PRD 10.3)."""

    def data_dir(self) -> Path:
        """Directory holding the audit log and other state."""

    def resolve(self, path: Path) -> Path:
        """Fully resolve `path`, following symlinks, junctions and reparse points.

        Resolution must happen before any containment check, otherwise a link
        inside a workspace can point outside it.
        """

    def is_absolute_like(self, raw: str) -> bool:
        """True if `raw` is absolute in this platform's eyes.

        Separate from `Path.is_absolute` because `C:\\x` and `\\\\server\\share`
        are absolute on Windows while a POSIX `Path` reads them as relative.
        """

    def is_reserved_name(self, raw: str) -> bool:
        """True if any component is a reserved device name (CON, NUL, COM1...)."""

    def paths_equal(self, a: Path, b: Path) -> bool:
        """Compare two resolved paths using this platform's case rules."""

    def broad_scope_reason(self, path: Path) -> str | None:
        """Explain why `path` is too broad to be a workspace, or None if it is fine.

        Guards against the failure mode observed in the reference tool, which had
        a whole drive registered as its project root (PRD 18).
        """

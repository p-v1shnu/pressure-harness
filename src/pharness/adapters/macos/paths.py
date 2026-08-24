"""macOS path rules — declared, not implemented (M9).

Shaped now so the seam is visible and contract tests have something to bind
to, but left unimplemented on purpose: an abstraction with only one consumer
has not been proven yet, and guessing at the second one is how the wrong
interface gets locked in (PRD 14.5).
"""

from __future__ import annotations

from pathlib import Path

_TODO = "macOS support lands in M9; see PRD 14.4 for what this adapter must handle"


class MacOSPaths:
    name = "macos"

    def config_dir(self) -> Path:
        raise NotImplementedError(_TODO)

    def data_dir(self) -> Path:
        raise NotImplementedError(_TODO)

    def resolve(self, path: Path) -> Path:
        raise NotImplementedError(_TODO)

    def is_absolute_like(self, raw: str) -> bool:
        raise NotImplementedError(_TODO)

    def is_reserved_name(self, raw: str) -> bool:
        raise NotImplementedError(_TODO)

    def paths_equal(self, a: Path, b: Path) -> bool:
        raise NotImplementedError(_TODO)

    def broad_scope_reason(self, path: Path) -> str | None:
        raise NotImplementedError(_TODO)

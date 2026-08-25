"""Reading and changing files inside an authorised workspace.

Every path goes through the jail, every change goes through the journal, and
every response goes through the byte budget. Those three are not optional
extras layered on top -- they are the reason these functions exist rather than
the model being handed a filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pharness.core.config import ContextSettings
from pharness.core.errors import PathJailError
from pharness.core.journal import Journal, sha256_bytes
from pharness.core.patch import AppliedFile, PatchError, apply_file_patch, parse_patch
from pharness.core.policy.path_jail import PathJail
from pharness.core.text import (
    BinaryFileError,
    outline,
    read_text_file,
    slice_lines,
    wrap_external,
)
from pharness.core.tools.results import ToolResult
from pharness.core.workspace import Workspace

LARGE_FILE_LINES = 2000


@dataclass(frozen=True)
class _PlannedWrite:
    """One file's new contents, computed but not yet written."""

    applied: AppliedFile
    target: Path


@dataclass
class FileTools:
    workspace: Workspace
    jail: PathJail
    journal: Journal
    context: ContextSettings

    # -- reading -----------------------------------------------------------

    def read(self, path: str, offset: int = 0, limit: int | None = None) -> ToolResult:
        try:
            target = self.jail.check(self.workspace, path)
        except PathJailError as exc:
            return ToolResult.failure(str(exc))

        if not target.exists():
            return ToolResult.failure(f"{path} does not exist")
        if target.is_dir():
            return ToolResult.failure(f"{path} is a directory")

        try:
            file = read_text_file(target)
        except BinaryFileError:
            size = target.stat().st_size
            return ToolResult.failure(f"{path} is a binary file ({size} bytes)")

        line_count = len(file.lines) - (1 if file.text.endswith("\n") else 0)

        # A big file with no range asked for gets a map instead of its contents:
        # returning 5000 lines would spend the whole conversation's budget on one
        # call, and the next thing the model needs is a range anyway (PRD 11).
        if limit is None and offset == 0 and line_count > LARGE_FILE_LINES:
            return ToolResult(
                text=(
                    f"{path} has {line_count} lines, too many to return at once.\n"
                    f"Top-level definitions:\n\n{outline(file)}\n\n"
                    "Read a range with offset and limit."
                ),
                meta={"path": path, "lines": line_count, "outline": True},
            )

        excerpt = slice_lines(file, offset, limit, self.context.max_output_bytes)
        text = wrap_external(excerpt.text, f"file {path}")
        if excerpt.next_offset is not None:
            text += f"\n\n[{line_count} lines total; continue from offset {excerpt.next_offset}]"

        return ToolResult(
            text=text,
            meta={
                "path": path,
                "lines": line_count,
                "truncated": excerpt.truncated,
                "next_offset": excerpt.next_offset,
            },
        )

    # -- writing -----------------------------------------------------------

    def write(
        self,
        path: str,
        content: str,
        create_only: bool = True,
        expected_sha: str | None = None,
    ) -> ToolResult:
        """Create a file, or replace one whose current contents are known.

        `create_only` defaults to true and overwriting must be asked for
        explicitly, because "write this file" is how a model accidentally
        discards work it never read.
        """
        try:
            target = self.jail.check(self.workspace, path)
        except PathJailError as exc:
            return ToolResult.failure(str(exc))

        if target.is_dir():
            return ToolResult.failure(f"{path} is a directory")

        exists = target.exists()
        if exists and create_only:
            return ToolResult.failure(
                f"{path} already exists. Patch it instead, or pass create_only=false "
                "to replace it deliberately."
            )

        newline = "\n"
        if exists:
            current = target.read_bytes()
            actual_sha = sha256_bytes(current)
            if expected_sha is not None and expected_sha != actual_sha:
                return ToolResult.failure(
                    f"{path} changed since it was read; not overwriting. Read it again first."
                )
            try:
                newline = read_text_file(target).newline
            except BinaryFileError:
                return ToolResult.failure(f"{path} is a binary file")

        body = content.replace("\n", newline) if newline != "\n" else content
        data = body.encode("utf-8")

        with self.journal.checkpoint(f"write_file {path}") as recorder:
            recorder.before(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        return ToolResult(
            text=f"{'Wrote' if exists else 'Created'} {path} ({len(data)} bytes)",
            meta={"path": path, "bytes": len(data), "sha256": sha256_bytes(data)},
        )

    # -- patching ----------------------------------------------------------

    def apply_patch(self, diff: str, dry_run: bool = False) -> ToolResult:
        """Apply a unified diff across one or more files, all or nothing."""
        try:
            patches = parse_patch(diff)
        except PatchError as exc:
            return ToolResult.failure(f"could not read the patch: {exc}")

        planned: list[_PlannedWrite] = []
        for patch in patches:
            try:
                target = self.jail.check(self.workspace, patch.path)
            except PathJailError as exc:
                return ToolResult.failure(str(exc))

            original: str | None = None
            if target.exists():
                try:
                    original = read_text_file(target).text
                except BinaryFileError:
                    return ToolResult.failure(f"{patch.path} is a binary file")

            try:
                applied = apply_file_patch(patch, original)
            except PatchError as exc:
                # Nothing has been written yet, so a failure here costs nothing:
                # the whole patch is computed before any of it lands.
                return ToolResult.failure(f"{patch.path}: {exc}")

            planned.append(_PlannedWrite(applied, target))

        summary = "\n".join(_describe(item.applied) for item in planned)
        if dry_run:
            return ToolResult(
                text=f"Would apply:\n{summary}",
                meta={"files": [item.applied.path for item in planned], "dry_run": True},
            )

        label = f"apply_patch ({len(planned)} file{'s' if len(planned) != 1 else ''})"
        with self.journal.checkpoint(label) as recorder:
            for item in planned:
                recorder.before(item.target)
                newline = read_text_file(item.target).newline if item.target.exists() else "\n"
                body = item.applied.text
                if newline != "\n":
                    body = body.replace("\n", newline)
                item.target.parent.mkdir(parents=True, exist_ok=True)
                item.target.write_bytes(body.encode("utf-8"))

        checkpoint = self.journal.latest()
        text = f"Applied:\n{summary}"
        if checkpoint is not None:
            text += f"\n\nCheckpoint {checkpoint.id} (undoable)"

        return ToolResult(
            text=text,
            meta={
                "files": [item.applied.path for item in planned],
                "checkpoint": checkpoint.id if checkpoint else None,
            },
        )


def _describe(applied: AppliedFile) -> str:
    action = "create" if applied.creates else "modify"
    note = f"  (shifted by {max(applied.offsets, key=abs)} lines)" if applied.shifted else ""
    return f"  {action} {applied.path}{note}"

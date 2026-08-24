"""Unified diff parsing and application.

Editing by patch rather than by whole-file rewrite matters for more than
elegance: a patch carries its own verification. Context lines say what the model
believed the file looked like, so if someone else changed it in the meantime the
patch fails instead of silently reverting their work.

Everything is applied in memory first and written only once every hunk in every
file has been placed. A patch that fails on its third file must not leave the
first two rewritten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
NO_NEWLINE = "\\ No newline at end of file"
SEARCH_WINDOW = 200


class PatchError(Exception):
    """The patch is malformed, or it does not fit the file it names."""


@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[tuple[str, str], ...]
    """(op, text) where op is ' ', '-' or '+'."""

    @property
    def context_and_removed(self) -> tuple[str, ...]:
        return tuple(text for op, text in self.lines if op in " -")

    @property
    def result_lines(self) -> tuple[str, ...]:
        return tuple(text for op, text in self.lines if op in " +")


@dataclass(frozen=True)
class FilePatch:
    path: str
    hunks: tuple[Hunk, ...]
    creates: bool = False
    deletes: bool = False
    no_final_newline: bool = False


@dataclass(frozen=True)
class AppliedFile:
    path: str
    text: str
    creates: bool
    offsets: tuple[int, ...]
    """How far each hunk moved from where the patch said it would be."""

    @property
    def shifted(self) -> bool:
        return any(offset != 0 for offset in self.offsets)


def _strip_prefix(path: str) -> str:
    path = path.strip()
    if path.startswith(('"', "'")) and path.endswith(('"', "'")):
        path = path[1:-1]
    for prefix in ("a/", "b/"):
        if path.startswith(prefix):
            return path[len(prefix) :]
    return path


def parse_patch(text: str) -> tuple[FilePatch, ...]:
    """Parse a unified diff into per-file patches."""
    lines = text.replace("\r\n", "\n").split("\n")
    files: list[FilePatch] = []

    index = 0
    while index < len(lines):
        line = lines[index]

        if not line.startswith("--- "):
            index += 1
            continue

        old_path = line[4:].split("\t")[0]
        if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
            raise PatchError(f"'--- {old_path}' is not followed by a '+++' line")
        new_path = lines[index + 1][4:].split("\t")[0]
        index += 2

        creates = old_path.strip() in ("/dev/null", "a//dev/null")
        deletes = new_path.strip() in ("/dev/null", "b//dev/null")
        path = _strip_prefix(new_path if not deletes else old_path)
        if not path:
            raise PatchError("patch names an empty path")

        hunks: list[Hunk] = []
        no_final_newline = False

        while index < len(lines) and lines[index].startswith("@@"):
            header = HUNK_HEADER.match(lines[index])
            if not header:
                raise PatchError(f"malformed hunk header: {lines[index]!r}")
            old_start, old_count, new_start, new_count = (
                int(header.group(1)),
                int(header.group(2) or 1),
                int(header.group(3)),
                int(header.group(4) or 1),
            )
            index += 1

            body: list[tuple[str, str]] = []
            seen_old = seen_new = 0
            last_op = " "
            while index < len(lines) and (seen_old < old_count or seen_new < new_count):
                current = lines[index]
                if current == NO_NEWLINE:
                    # The marker describes whichever side the preceding line
                    # belongs to. After a removed line it is about the old file
                    # and changes nothing about what we write.
                    no_final_newline = no_final_newline or last_op in " +"
                    index += 1
                    continue
                if current.startswith("@@") or current.startswith("--- "):
                    break
                op, content = (current[0], current[1:]) if current else (" ", "")
                if op not in " -+":
                    raise PatchError(f"unexpected line in hunk: {current!r}")
                body.append((op, content))
                last_op = op
                seen_old += op in " -"
                seen_new += op in " +"
                index += 1

            # The marker usually sits just past the end of the hunk body, where
            # the loop above has already stopped counting.
            if index < len(lines) and lines[index] == NO_NEWLINE:
                no_final_newline = no_final_newline or last_op in " +"
                index += 1

            if seen_old != old_count or seen_new != new_count:
                raise PatchError(
                    f"hunk at line {old_start} of {path} claims {old_count}/{new_count} lines "
                    f"but contains {seen_old}/{seen_new}"
                )
            hunks.append(Hunk(old_start, old_count, new_start, new_count, tuple(body)))

        if not hunks:
            raise PatchError(f"patch for {path} has no hunks")

        files.append(FilePatch(path, tuple(hunks), creates, deletes, no_final_newline))

    if not files:
        raise PatchError("no file headers found; expected a unified diff")
    return tuple(files)


def _locate(original: list[str], hunk: Hunk) -> int:
    """Find where this hunk's context actually sits. Returns a 0-based index.

    The stated position is tried first, then nearby positions, because a model
    counting lines is often a line or two out. What is never relaxed is the
    content: every context and removed line must match exactly, which is what
    stops a patch from being applied to the wrong place.
    """
    expected = list(hunk.context_and_removed)
    stated = max(0, hunk.old_start - 1)

    if not expected:
        return min(stated, len(original))

    def fits(at: int) -> bool:
        return at >= 0 and original[at : at + len(expected)] == expected

    if fits(stated):
        return stated

    for distance in range(1, SEARCH_WINDOW + 1):
        for candidate in (stated - distance, stated + distance):
            if fits(candidate):
                return candidate

    preview = expected[0][:60] if expected else ""
    raise PatchError(
        f"hunk at line {hunk.old_start} does not match the file "
        f"(looked for {preview!r}). The file may have changed since it was read."
    )


def apply_file_patch(patch: FilePatch, original: str | None) -> AppliedFile:
    """Apply one file's hunks to `original` (None when the file does not exist)."""
    if patch.deletes:
        raise PatchError(
            f"this patch deletes {patch.path}; deletion is not available "
            "(add the change another way, or remove the file yourself)"
        )
    if patch.creates and original not in (None, ""):
        raise PatchError(f"patch creates {patch.path} but that file already exists")
    if not patch.creates and original is None:
        raise PatchError(f"patch modifies {patch.path} but that file does not exist")

    had_final_newline = bool(original) and original.endswith("\n")
    lines = (original or "").split("\n")
    if lines and lines[-1] == "":
        lines.pop()

    offsets: list[int] = []
    drift = 0

    for hunk in patch.hunks:
        adjusted = Hunk(
            old_start=hunk.old_start + drift,
            old_count=hunk.old_count,
            new_start=hunk.new_start,
            new_count=hunk.new_count,
            lines=hunk.lines,
        )
        at = _locate(lines, adjusted)
        offsets.append(at - (adjusted.old_start - 1))

        removed = len(hunk.context_and_removed)
        replacement = list(hunk.result_lines)
        lines[at : at + removed] = replacement
        drift += len(replacement) - removed

    text = "\n".join(lines)
    keep_newline = had_final_newline or patch.creates
    if text and keep_newline and not patch.no_final_newline:
        text += "\n"

    return AppliedFile(patch.path, text, patch.creates, tuple(offsets))

"""Reading and writing text files, and shaping what goes back to the model.

Two concerns that look unrelated but are not:

* On disk, line endings and encodings must survive a round trip. A tool that
  silently rewrites every CRLF to LF turns a one-line change into a
  whole-file diff, which is worse than useless on Windows.
* On the way out, size is a budget. Every byte a tool returns is pasted into
  the conversation and re-sent with every later message, so truncation is a
  feature and the caps live here (PRD 11).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_MAX_BYTES = 8192
BINARY_SNIFF_BYTES = 8192
TRUNCATION_NOTE = "\n... [{omitted} bytes omitted of {total}; ask for a specific range] ...\n"


class BinaryFileError(Exception):
    """Raised when a text operation is asked for on a binary file."""


@dataclass(frozen=True)
class TextFile:
    """A file's contents, normalised to `\\n`, plus how to put it back."""

    text: str
    newline: str
    encoding: str
    had_final_newline: bool

    @property
    def lines(self) -> list[str]:
        return self.text.split("\n")

    def render(self, text: str | None = None) -> bytes:
        """Serialise `text` (or our own) back with the file's original conventions."""
        body = self.text if text is None else text
        if self.newline != "\n":
            body = body.replace("\n", self.newline)
        return body.encode(self.encoding)


def looks_binary(data: bytes) -> bool:
    """A null byte in the first block is the practical test everyone uses."""
    head = data[:BINARY_SNIFF_BYTES]
    if b"\x00" in head:
        return True
    if not head:
        return False
    # A high proportion of bytes that are neither printable nor whitespace.
    printable = sum(1 for byte in head if 32 <= byte < 127 or byte in (9, 10, 13, 12))
    return printable / len(head) < 0.7


def dominant_newline(data: bytes) -> str:
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    cr = data.count(b"\r") - crlf
    if crlf >= lf and crlf >= cr and crlf > 0:
        return "\r\n"
    if cr > lf:
        return "\r"
    return "\n"


def read_text_file(path: Path) -> TextFile:
    """Read `path` as text, or raise BinaryFileError.

    Decoding falls back to latin-1 rather than failing: a file with one stray
    byte should still be readable and, more importantly, still be writable
    without corrupting the rest of it.
    """
    data = path.read_bytes()
    if looks_binary(data):
        raise BinaryFileError(f"{path.name} is not a text file")

    newline = dominant_newline(data)
    try:
        text = data.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        text = data.decode("latin-1")
        encoding = "latin-1"

    if newline != "\n":
        text = text.replace(newline, "\n")

    return TextFile(
        text=text,
        newline=newline,
        encoding=encoding,
        had_final_newline=text.endswith("\n"),
    )


@dataclass(frozen=True)
class Excerpt:
    """Text bounded by a byte budget, with enough context to ask for more."""

    text: str
    total_bytes: int
    omitted_bytes: int
    next_offset: int | None = None

    @property
    def truncated(self) -> bool:
        return self.omitted_bytes > 0


def clamp(text: str, max_bytes: int = DEFAULT_MAX_BYTES) -> Excerpt:
    """Cut `text` to `max_bytes`, keeping the start and the end.

    Both ends, because the interesting parts of command output are the first
    lines and the last lines; the middle of a 200 KB log is where nothing is.
    """
    encoded = text.encode("utf-8", errors="replace")
    total = len(encoded)
    if total <= max_bytes:
        return Excerpt(text, total, 0)

    keep = max_bytes - len(TRUNCATION_NOTE) - 32
    if keep <= 0:
        return Excerpt(text[: max(0, max_bytes)], total, total - max_bytes)

    head_budget = keep * 2 // 3
    tail_budget = keep - head_budget
    head = encoded[:head_budget].decode("utf-8", errors="ignore")
    tail = encoded[total - tail_budget :].decode("utf-8", errors="ignore")
    omitted = total - len(head.encode("utf-8")) - len(tail.encode("utf-8"))

    note = TRUNCATION_NOTE.format(omitted=omitted, total=total)
    return Excerpt(head + note + tail, total, omitted)


def slice_lines(
    file: TextFile, offset: int = 0, limit: int | None = None, max_bytes: int = DEFAULT_MAX_BYTES
) -> Excerpt:
    """Return `limit` lines from `offset`, numbered, within the byte budget.

    Line numbers are included because the model's next move is usually a patch,
    and a patch needs to name lines.
    """
    lines = file.lines
    if lines and lines[-1] == "":
        lines = lines[:-1]

    start = max(0, offset)
    end = len(lines) if limit is None else min(len(lines), start + limit)
    width = len(str(end)) if end else 1

    rendered = "\n".join(f"{index + 1:>{width}}  {lines[index]}" for index in range(start, end))
    excerpt = clamp(rendered, max_bytes)

    next_offset = end if end < len(lines) else None
    return Excerpt(excerpt.text, excerpt.total_bytes, excerpt.omitted_bytes, next_offset)


def outline(file: TextFile, max_entries: int = 60) -> str:
    """A cheap structural sketch for a file too big to return whole.

    Deliberately language-agnostic: anything that looks like a definition at the
    start of a line. Good enough to pick a range to read, which is all it is for.
    """
    keywords = (
        "def ",
        "class ",
        "function ",
        "const ",
        "let ",
        "var ",
        "export ",
        "interface ",
        "type ",
        "struct ",
        "impl ",
        "fn ",
        "public ",
        "private ",
        "async ",
    )
    found: list[str] = []
    for number, line in enumerate(file.lines, start=1):
        stripped = line.lstrip()
        if not stripped or line[:1].isspace():
            continue
        if stripped.startswith(keywords):
            found.append(f"{number:>6}  {stripped[:100]}")
        if len(found) >= max_entries:
            found.append("   ...  (outline truncated)")
            break
    return "\n".join(found) if found else "(no top-level definitions found)"

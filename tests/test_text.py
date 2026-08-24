"""Text handling: what a round trip must preserve, and what a budget must cut."""

from __future__ import annotations

from pathlib import Path

import pytest

from pharness.core.text import (
    BinaryFileError,
    clamp,
    dominant_newline,
    looks_binary,
    outline,
    read_text_file,
    slice_lines,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"a\nb\n", "\n"),
        (b"a\r\nb\r\n", "\r\n"),
        (b"a\rb\r", "\r"),
        (b"no newline at all", "\n"),
        (b"mixed\r\nmostly\r\ncrlf\n", "\r\n"),
    ],
)
def test_newline_detection(raw: bytes, expected: str):
    assert dominant_newline(raw) == expected


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_round_trip_preserves_line_endings(tmp_path: Path, newline: bytes):
    """Rewriting every CRLF to LF turns a one-line change into a whole-file diff."""
    target = tmp_path / "file.txt"
    target.write_bytes(newline.join([b"alpha", b"beta", b"gamma", b""]))

    file = read_text_file(target)
    assert file.render() == target.read_bytes()
    assert file.lines[:3] == ["alpha", "beta", "gamma"]


def test_round_trip_of_edited_text_keeps_the_original_endings(tmp_path: Path):
    target = tmp_path / "file.txt"
    target.write_bytes(b"alpha\r\nbeta\r\n")
    file = read_text_file(target)
    assert file.render("alpha\nBETA\n") == b"alpha\r\nBETA\r\n"


def test_undecodable_bytes_still_read(tmp_path: Path):
    """One stray byte should not make a file unreadable, or unwritable."""
    target = tmp_path / "latin.txt"
    target.write_bytes(b"caf\xe9 au lait\n")
    file = read_text_file(target)
    assert "caf" in file.text
    assert file.encoding == "latin-1"
    assert file.render() == target.read_bytes()


def test_binary_files_are_refused(tmp_path: Path):
    target = tmp_path / "blob.bin"
    target.write_bytes(bytes(range(256)) * 4)
    assert looks_binary(target.read_bytes())
    with pytest.raises(BinaryFileError):
        read_text_file(target)


def test_empty_file_is_not_binary(tmp_path: Path):
    target = tmp_path / "empty.txt"
    target.write_bytes(b"")
    assert not looks_binary(b"")
    assert read_text_file(target).text == ""


def test_clamp_keeps_both_ends():
    """The head and the tail are where the information is; the middle is filler."""
    text = "START\n" + ("filler\n" * 5000) + "END"
    excerpt = clamp(text, 500)

    assert excerpt.truncated
    assert len(excerpt.text.encode()) <= 500
    assert excerpt.text.startswith("START")
    assert excerpt.text.rstrip().endswith("END")
    assert "omitted" in excerpt.text


def test_clamp_leaves_small_text_alone():
    excerpt = clamp("small", 500)
    assert excerpt.text == "small" and not excerpt.truncated


def test_slice_lines_numbers_and_paginates(tmp_path: Path):
    target = tmp_path / "many.txt"
    target.write_text("\n".join(f"line {i}" for i in range(100)) + "\n", encoding="utf-8")
    file = read_text_file(target)

    excerpt = slice_lines(file, offset=10, limit=5)
    assert "11  line 10" in excerpt.text
    assert "16  line 15" not in excerpt.text
    assert excerpt.next_offset == 15


def test_slice_lines_at_the_end_has_no_continuation(tmp_path: Path):
    target = tmp_path / "short.txt"
    target.write_text("one\ntwo\n", encoding="utf-8")
    assert slice_lines(read_text_file(target)).next_offset is None


def test_outline_finds_definitions(tmp_path: Path):
    target = tmp_path / "code.ts"
    target.write_text(
        "import x from 'y'\n\nexport function alpha() {\n  const inner = 1\n}\n\nclass Beta {}\n",
        encoding="utf-8",
    )
    result = outline(read_text_file(target))
    assert "export function alpha" in result
    assert "class Beta" in result
    assert "const inner" not in result  # indented, so not top level

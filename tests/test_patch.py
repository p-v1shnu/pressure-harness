"""The diff engine. Context matching is what makes a patch self-verifying."""

from __future__ import annotations

import pytest

from pharness.core.patch import PatchError, apply_file_patch, parse_patch

ORIGINAL = "line one\nline two\nline three\nline four\n"

SIMPLE = """--- a/src/app.ts
+++ b/src/app.ts
@@ -1,3 +1,4 @@
 line one
-line two
+line TWO
+line two and a half
 line three
"""

CREATE = """--- /dev/null
+++ b/new.txt
@@ -0,0 +1,2 @@
+alpha
+beta
"""


def test_simple_patch_applies():
    [patch] = parse_patch(SIMPLE)
    result = apply_file_patch(patch, ORIGINAL)
    assert result.text == "line one\nline TWO\nline two and a half\nline three\nline four\n"
    assert not result.shifted


def test_path_prefixes_are_stripped():
    [patch] = parse_patch(SIMPLE)
    assert patch.path == "src/app.ts"


def test_wrong_line_numbers_still_apply_when_content_matches():
    """Models miscount lines. Content is what must match, not arithmetic."""
    [patch] = parse_patch(SIMPLE)
    result = apply_file_patch(patch, "pad\npad\npad\n" + ORIGINAL)
    assert result.shifted and result.offsets == (3,)
    assert "line TWO" in result.text


def test_context_mismatch_is_refused():
    """The property that makes a patch safe: it fails when the file moved on."""
    [patch] = parse_patch(SIMPLE)
    with pytest.raises(PatchError, match="does not match"):
        apply_file_patch(patch, "something else entirely\n")


def test_new_file_creation():
    [patch] = parse_patch(CREATE)
    assert patch.creates
    assert apply_file_patch(patch, None).text == "alpha\nbeta\n"


def test_creating_over_an_existing_file_is_refused():
    [patch] = parse_patch(CREATE)
    with pytest.raises(PatchError, match="already exists"):
        apply_file_patch(patch, "existing\n")


def test_modifying_a_missing_file_is_refused():
    [patch] = parse_patch(SIMPLE)
    with pytest.raises(PatchError, match="does not exist"):
        apply_file_patch(patch, None)


def test_deletion_is_refused():
    """v1 has no delete path at all, and a diff is not a way around that."""
    diff = "--- a/gone.txt\n+++ /dev/null\n@@ -1 +0,0 @@\n-gone\n"
    [patch] = parse_patch(diff)
    with pytest.raises(PatchError, match="deletion is not available"):
        apply_file_patch(patch, "gone\n")


def test_multiple_files_in_one_patch():
    diff = SIMPLE + CREATE
    patches = parse_patch(diff)
    assert [p.path for p in patches] == ["src/app.ts", "new.txt"]


def test_multiple_hunks_track_their_own_drift():
    diff = """--- a/f.txt
+++ b/f.txt
@@ -1,2 +1,3 @@
 line one
+inserted early
 line two
@@ -3,2 +4,2 @@
 line three
-line four
+line FOUR
"""
    [patch] = parse_patch(diff)
    result = apply_file_patch(patch, ORIGINAL)
    assert result.text == "line one\ninserted early\nline two\nline three\nline FOUR\n"


def test_missing_final_newline_is_honoured():
    diff = "--- a/f.txt\n+++ b/f.txt\n@@ -1 +1 @@\n-a\n+b\n\\ No newline at end of file\n"
    [patch] = parse_patch(diff)
    assert apply_file_patch(patch, "a\n").text == "b"


@pytest.mark.parametrize(
    ("bad", "expected"),
    [
        ("not a diff", "no file headers"),
        ("--- a/x\n", "not followed by"),
        ("--- a/x\n+++ b/x\n@@ nonsense @@\n", "malformed hunk header"),
        ("--- a/x\n+++ b/x\n@@ -1,5 +1,5 @@\n ctx\n", "claims 5/5"),
        ("--- a/x\n+++ b/x\n", "no hunks"),
    ],
)
def test_malformed_patches_are_refused(bad: str, expected: str):
    with pytest.raises(PatchError, match=expected):
        parse_patch(bad)

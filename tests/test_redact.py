"""Redaction runs on everything heading back into the conversation."""

from __future__ import annotations

import pytest

from pharness.core.audit.redact import Redactor, shannon_entropy


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("key: sk-proj-abcdefghijklmnopqrstuvwxyz012345", "openai-key"),
        ("sk-ant-api03-abcdefghijklmnopqrstuvwxyz", "anthropic-key"),
        ("token=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345", "github-token"),
        ("github_pat_11ABCDEFG0abcdefghijkl_mnopqrstuvwxyz", "github-pat"),
        ("id = AKIAIOSFODNN7EXAMPLE", "aws-key-id"),
        ("xoxb-123456789012-abcdefghijkl", "slack-token"),
        ("key " + "AIza" + "Sy" + "B" * 33, "google-key"),  # AIza plus exactly 35 chars
        ("Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl", "jwt"),
        ("postgres://app:sup3rsecret@db:5432/x", "url-password"),
        ("API_SECRET=abcdefghijklmnop", "env-value"),
    ],
)
def test_known_secret_shapes_are_removed(text: str, kind: str):
    result = Redactor().redact(text)
    assert kind in result.kinds
    assert "redacted" in result.text


def test_private_key_block_is_removed_whole():
    text = "-----BEGIN RSA PRIVATE KEY-----\nabc\ndef\n-----END RSA PRIVATE KEY-----"
    result = Redactor().redact(text)
    assert result.kinds == ("private-key",)
    assert "abc" not in result.text


@pytest.mark.parametrize("text", ["PORT=3000", "DEBUG=true", "NODE_ENV=production", "count = 42"])
def test_ordinary_output_is_left_alone(text: str):
    """Over-redaction is a real cost: it teaches people to switch redaction off."""
    result = Redactor().redact(text)
    assert not result.changed
    assert result.text == text


def test_known_secret_values_are_masked_anywhere():
    redactor = Redactor(extra_secrets=["correct-horse-battery"])
    result = redactor.redact("the config said correct-horse-battery in three places")
    assert "correct-horse-battery" not in result.text
    assert "known-secret" in result.kinds


def test_short_strings_are_not_treated_as_secrets():
    assert not Redactor(extra_secrets=["abc"]).redact("abc everywhere").changed


def test_kinds_are_reported_without_the_values():
    result = Redactor().redact("token=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345")
    assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in "".join(result.kinds)


def test_entropy_scan_is_opt_in():
    random_looking = "Zm9vYmFyYmF6cXV1eGNvcmdlZ3JhdWx0d2FsZG8x2Fh"
    assert not Redactor().redact(random_looking).changed
    assert Redactor(entropy_scan=True).redact(random_looking).changed


def test_entropy_of_repetitive_text_is_low():
    assert shannon_entropy("aaaaaaaaaaaa") < 1.0
    assert shannon_entropy("aB3$xZ9!qW2#") > 3.0

"""Strips secrets from anything on its way back into the conversation.

Everything a tool returns is uploaded to a third party the moment it lands in
the chat, so this runs on the way out, not on the way in (PRD 10.5). It is a
net, not a guarantee: the real defence is that credential files are unreadable
in the first place (PRD 10.3, path jail).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

PLACEHOLDER = "[redacted:{kind}]"

# Ordered: longer, more specific patterns first, so a private key block is not
# nibbled at by a narrower rule.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private-key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}")),
    ("openai-key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("github-pat", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("aws-key-id", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("slack-token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")),
)

# Replace only the value, keeping the name: "the DATABASE_URL leaked" is useful
# to a reader, the URL itself is not.
_ASSIGNMENT = re.compile(
    r"""(?im)^(?P<name>[A-Z][A-Z0-9_]{2,})(?P<sep>\s*=\s*)(?P<value>["']?[^\s"']{8,}["']?)\s*$"""
)
_URL_CREDENTIALS = re.compile(
    r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<user>[^:/@\s]+):(?P<pw>[^@\s]{3,})@"
)

_SECRETISH_NAME = re.compile(
    r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|PRIVATE|AUTH|DSN|CONNECTION_STRING)"
)


@dataclass(frozen=True)
class RedactionResult:
    text: str
    kinds: tuple[str, ...]
    """What was removed, never what its value was."""

    @property
    def changed(self) -> bool:
        return bool(self.kinds)


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    length = len(value)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


class Redactor:
    def __init__(
        self,
        extra_secrets: Iterable[str] = (),
        *,
        entropy_scan: bool = False,
        entropy_threshold: float = 4.2,
        min_entropy_length: int = 32,
    ) -> None:
        # Longest first, so a secret that contains another is masked whole.
        self._extra = sorted({s for s in extra_secrets if len(s) >= 6}, key=len, reverse=True)
        self._entropy_scan = entropy_scan
        self._entropy_threshold = entropy_threshold
        self._min_entropy_length = min_entropy_length

    def redact(self, text: str) -> RedactionResult:
        kinds: list[str] = []
        out = text

        for secret in self._extra:
            if secret in out:
                out = out.replace(secret, PLACEHOLDER.format(kind="known-secret"))
                kinds.append("known-secret")

        for kind, pattern in _PATTERNS:
            out, count = pattern.subn(PLACEHOLDER.format(kind=kind), out)
            if count:
                kinds.append(kind)

        out, assigned = _redact_assignments(out)
        kinds.extend(assigned)

        masked_password = PLACEHOLDER.format(kind="url-password")
        out, urls = _URL_CREDENTIALS.subn(
            lambda m: f"{m.group('scheme')}{m.group('user')}:{masked_password}@",
            out,
        )
        if urls:
            kinds.append("url-password")

        if self._entropy_scan:
            out, entropic = self._redact_entropic(out)
            kinds.extend(entropic)

        return RedactionResult(out, tuple(dict.fromkeys(kinds)))

    def _redact_entropic(self, text: str) -> tuple[str, list[str]]:
        """Catch unknown token formats by how random they look.

        Off by default: minified bundles, hashes and base64 assets all look
        random, and a tool that mangles ordinary output teaches the user to turn
        redaction off entirely.
        """
        kinds: list[str] = []

        def replace(match: re.Match[str]) -> str:
            candidate = match.group(0)
            if shannon_entropy(candidate) >= self._entropy_threshold:
                kinds.append("high-entropy")
                return PLACEHOLDER.format(kind="high-entropy")
            return candidate

        pattern = re.compile(rf"\b[A-Za-z0-9+/_=-]{{{self._min_entropy_length},}}\b")
        return pattern.sub(replace, text), kinds


def _redact_assignments(text: str) -> tuple[str, list[str]]:
    kinds: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        if not _SECRETISH_NAME.search(name):
            return match.group(0)
        kinds.append("env-value")
        return f"{name}{match.group('sep')}{PLACEHOLDER.format(kind='env-value')}"

    return _ASSIGNMENT.sub(replace, text), kinds


def redact_all(values: Sequence[str], redactor: Redactor) -> tuple[list[str], tuple[str, ...]]:
    kinds: list[str] = []
    out: list[str] = []
    for value in values:
        result = redactor.redact(value)
        out.append(result.text)
        kinds.extend(result.kinds)
    return out, tuple(dict.fromkeys(kinds))

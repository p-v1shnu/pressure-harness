"""Windows command-line parser covering both PowerShell and cmd.exe.

The two dialects share almost no quoting rules with each other, let alone with
POSIX: PowerShell escapes with a backtick and has two distinct quote types,
cmd escapes with a caret. Rather than guess which shell will run a line, this
parser accepts the union of both syntaxes and errs toward finding more
commands, never fewer.

Pure string handling on purpose, so Linux and macOS CI test it too (PRD 14.2).
Fails closed (PRD 10.4).
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass

from pharness.ports.shell import ParsedCommand, ShellParseError

MAX_LENGTH = 8192
MAX_DEPTH = 5

_WORD_BREAK = " \t\n;|&()<>"

# How each interpreter takes code on its command line. These flags are the
# holes any first-word allowlist falls through -- the log line quoted in
# PRD 10.4 is exactly this shape.
#
# The distinction matters: PowerShell's -Command and cmd's /c swallow the whole
# rest of the line, while -c/-e on python and node take a single argument.
# Reading only the next token would under-report what PowerShell is about to run.


@dataclass(frozen=True)
class _InterpSpec:
    rest_of_line: frozenset[str] = frozenset()
    single_arg: frozenset[str] = frozenset()
    base64_arg: frozenset[str] = frozenset()

    @property
    def all_flags(self) -> frozenset[str]:
        return self.rest_of_line | self.single_arg | self.base64_arg


_POWERSHELL = _InterpSpec(
    rest_of_line=frozenset({"-command"}),
    base64_arg=frozenset({"-encodedcommand"}),
)
_CMD = _InterpSpec(rest_of_line=frozenset({"/c", "/k"}))
_PYTHON = _InterpSpec(single_arg=frozenset({"-c"}))
_NODE = _InterpSpec(single_arg=frozenset({"-e", "--eval", "-p", "--print"}))
_SCRIPT_E = _InterpSpec(single_arg=frozenset({"-e"}))

_INTERPRETERS: dict[str, _InterpSpec] = {
    "powershell": _POWERSHELL,
    "powershell.exe": _POWERSHELL,
    "pwsh": _POWERSHELL,
    "pwsh.exe": _POWERSHELL,
    "cmd": _CMD,
    "cmd.exe": _CMD,
    "python": _PYTHON,
    "python.exe": _PYTHON,
    "python3": _PYTHON,
    "py": _PYTHON,
    "node": _NODE,
    "node.exe": _NODE,
    "perl": _SCRIPT_E,
    "ruby": _SCRIPT_E,
}

# PowerShell's own eval: every argument is code.
_EVAL_ALIASES = {"invoke-expression", "iex"}

# Cmdlets that write a file given by -Path/-FilePath, truncating it.
_WRITE_CMDLETS = {"out-file", "set-content", "add-content", "tee-object"}
_PATH_FLAGS = {"-path", "-filepath", "-literalpath"}


@dataclass(frozen=True)
class _Tok:
    kind: str  # "word" | "op" | "redirect"
    text: str
    start: int
    end: int
    subs: tuple[str, ...] = ()


class WindowsShell:
    name = "windows"

    def parse(self, command: str) -> tuple[ParsedCommand, ...]:
        return _parse(command, depth=0)

    def interpreter_payloads(self, cmd: ParsedCommand) -> tuple[str, ...]:
        if not cmd.argv:
            return ()
        program = _program_key(cmd.argv[0])

        if program in _EVAL_ALIASES:
            return tuple(a for a in cmd.argv[1:] if a)

        spec = _INTERPRETERS.get(program)
        if spec is None:
            return ()

        payloads: list[str] = []
        rest = list(cmd.argv[1:])
        while rest:
            token = rest.pop(0)
            flag = _match_flag(token, spec.all_flags)
            if flag is None:
                continue

            if not rest:
                raise ShellParseError(f"{program} {token} with no payload to inspect")

            if flag in spec.rest_of_line:
                # -Command and /c take everything that follows, not one token.
                payloads.append(" ".join(rest))
                break

            value = rest.pop(0)
            payloads.append(_decode_base64_command(value) if flag in spec.base64_arg else value)

        return tuple(payloads)


def _match_flag(token: str, flags: frozenset[str]) -> str | None:
    """Resolve a token to one of `flags`, allowing PowerShell abbreviations.

    PowerShell accepts any unambiguous prefix, so -Comm, -Com and -C all mean
    -Command. Matching only full spellings would miss every abbreviated call.
    """
    lowered = token.lower()
    if lowered in flags:
        return lowered
    if not lowered.startswith("-") or len(lowered) < 2:
        return None
    matches = [f for f in flags if f.startswith("-") and f.startswith(lowered)]
    return matches[0] if len(matches) == 1 else None


def _decode_base64_command(payload: str) -> str:
    """Decode -EncodedCommand, which PowerShell reads as base64 UTF-16LE.

    Encoded payloads must be inspected, not waved through: the encoding exists
    to survive quoting, and it hides the command from anything reading the raw
    line. Undecodable input fails closed.
    """
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ShellParseError("could not decode -EncodedCommand payload") from exc
    for encoding in ("utf-16-le", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ShellParseError("could not decode -EncodedCommand payload")


def _program_key(argv0: str) -> str:
    return argv0.replace("/", "\\").rsplit("\\", 1)[-1].lower()


# ---------------------------------------------------------------- scanning


def _read_substitution(s: str, i: int, opener: str, closer: str) -> tuple[str, int]:
    depth = 1
    start = i
    while i < len(s):
        c = s[i]
        if c == "`":  # PowerShell escape
            i += 2
            continue
        if c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return s[start:i], i + 1
        i += 1
    raise ShellParseError("unterminated subexpression")


def _read_word(s: str, i: int) -> tuple[str, list[str], int]:
    out: list[str] = []
    subs: list[str] = []

    while i < len(s):
        c = s[i]
        pair = s[i : i + 2]

        if c in _WORD_BREAK:
            break
        if c == "^":  # cmd.exe escape
            if i + 1 >= len(s):
                raise ShellParseError("trailing caret escape")
            out.append(s[i + 1])
            i += 2
        elif c == "`":  # PowerShell escape
            if i + 1 >= len(s):
                raise ShellParseError("trailing backtick escape")
            out.append(s[i + 1])
            i += 2
        elif c == "'":
            # PowerShell literal string; '' is an escaped quote.
            i += 1
            while True:
                if i >= len(s):
                    raise ShellParseError("unterminated single quote")
                if s[i] == "'":
                    if s[i : i + 2] == "''":
                        out.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                out.append(s[i])
                i += 1
        elif c == '"':
            i += 1
            while True:
                if i >= len(s):
                    raise ShellParseError("unterminated double quote")
                if s[i] == "`" and i + 1 < len(s):
                    out.append(s[i + 1])
                    i += 2
                elif s[i] == '"':
                    if s[i : i + 2] == '""':
                        out.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                elif s[i : i + 2] in ("$(", "@("):
                    payload, i = _read_substitution(s, i + 2, "(", ")")
                    subs.append(payload)
                else:
                    out.append(s[i])
                    i += 1
        elif pair in ("$(", "@("):
            payload, i = _read_substitution(s, i + 2, "(", ")")
            subs.append(payload)
        elif pair == "&{":
            payload, i = _read_substitution(s, i + 2, "{", "}")
            subs.append(payload)
        else:
            out.append(c)
            i += 1

    return "".join(out), subs, i


def _scan(s: str) -> list[_Tok]:
    toks: list[_Tok] = []
    i = 0

    while i < len(s):
        c = s[i]
        pair = s[i : i + 2]

        if c in " \t":
            i += 1
        elif c in ";\n":
            toks.append(_Tok("op", c, i, i + 1))
            i += 1
        elif pair == "&&":
            toks.append(_Tok("op", "&&", i, i + 2))
            i += 2
        elif pair == "||":
            toks.append(_Tok("op", "||", i, i + 2))
            i += 2
        elif pair == "&{":
            payload, end = _read_substitution(s, i + 2, "{", "}")
            toks.append(_Tok("word", "", i, end, (payload,)))
            i = end
        elif c in "&|" or c in "()":
            toks.append(_Tok("op", c, i, i + 1))
            i += 1
        elif pair in ("$(", "@("):
            payload, end = _read_substitution(s, i + 2, "(", ")")
            toks.append(_Tok("word", "", i, end, (payload,)))
            i = end
        elif pair == ">>":
            toks.append(_Tok("redirect", ">>", i, i + 2))
            i += 2
        elif c == ">":
            toks.append(_Tok("redirect", ">", i, i + 1))
            i += 1
        elif c == "<":
            toks.append(_Tok("redirect", "<", i, i + 1))
            i += 1
        else:
            word, subs, end = _read_word(s, i)
            toks.append(_Tok("word", word, i, end, tuple(subs)))
            i = end

    return toks


# ---------------------------------------------------------------- assembly


def _parse(command: str, depth: int) -> tuple[ParsedCommand, ...]:
    if depth > MAX_DEPTH:
        raise ShellParseError("command nesting is too deep to analyse")
    if "\x00" in command:
        raise ShellParseError("null byte in command")
    if len(command) > MAX_LENGTH:
        raise ShellParseError(f"command longer than {MAX_LENGTH} characters")

    toks = _scan(command)
    out: list[ParsedCommand] = []

    for segment in _split_on_operators(toks):
        argv: list[str] = []
        overwrites: list[str] = []
        subs: list[str] = []

        k = 0
        while k < len(segment):
            tok = segment[k]

            if tok.kind == "redirect":
                if tok.text == ">" and k + 1 < len(segment) and segment[k + 1].kind == "word":
                    overwrites.append(segment[k + 1].text)
                k += 2 if k + 1 < len(segment) else 1
                continue

            next_is_redirect = k + 1 < len(segment) and segment[k + 1].kind == "redirect"
            if tok.text and not (tok.text.isdigit() and next_is_redirect):
                argv.append(tok.text)
            subs.extend(tok.subs)
            k += 1

        if argv:
            raw = command[segment[0].start : segment[-1].end].strip()
            overwrites.extend(_cmdlet_write_targets(argv))
            out.append(ParsedCommand(tuple(argv), raw, tuple(overwrites)))

        for payload in subs:
            out.extend(_parse(payload, depth + 1))

    return tuple(out)


def _cmdlet_write_targets(argv: list[str]) -> list[str]:
    """Out-File and friends truncate a file without any redirection operator."""
    if _program_key(argv[0]) not in _WRITE_CMDLETS:
        return []
    targets: list[str] = []
    rest = list(argv[1:])
    while rest:
        token = rest.pop(0)
        if token.lower() in _PATH_FLAGS and rest:
            targets.append(rest.pop(0))
        elif not token.startswith("-") and not targets:
            targets.append(token)  # positional -Path
    return targets


def _split_on_operators(toks: list[_Tok]) -> list[list[_Tok]]:
    segments: list[list[_Tok]] = []
    current: list[_Tok] = []
    for tok in toks:
        if tok.kind == "op":
            if current:
                segments.append(current)
                current = []
        else:
            current.append(tok)
    if current:
        segments.append(current)
    return segments

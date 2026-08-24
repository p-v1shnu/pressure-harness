"""POSIX shell command-line parser.

Splits a command line into every simple command it would actually run, so the
core never has to judge a command by its first word. Everything here is pure
string handling, which is why the whole parser is testable from any platform.

Fails closed by design (PRD 10.4): syntax this parser cannot account for raises
ShellParseError, and the policy engine turns that into a denial rather than
letting the shell interpret something we did not understand.
"""

from __future__ import annotations

from dataclasses import dataclass

from pharness.ports.shell import ParsedCommand, ShellParseError

MAX_LENGTH = 8192
MAX_DEPTH = 5

_WORD_BREAK = " \t\n;|&()<>"

# Interpreters that take code on the command line. Each entry lists the flags
# whose argument is a program, which is what makes them a hole in any allowlist.
_CODE_FLAGS: dict[str, tuple[str, ...]] = {
    "sh": ("-c",),
    "bash": ("-c",),
    "dash": ("-c",),
    "zsh": ("-c",),
    "ksh": ("-c",),
    "python": ("-c",),
    "python3": ("-c",),
    "perl": ("-e",),
    "ruby": ("-e",),
    "php": ("-r",),
    "node": ("-e", "--eval", "-p", "--print"),
    "deno": ("eval",),
}


@dataclass(frozen=True)
class _Tok:
    kind: str  # "word" | "op" | "redirect"
    text: str
    start: int
    end: int
    subs: tuple[str, ...] = ()


class PosixShell:
    name = "posix"

    def parse(self, command: str) -> tuple[ParsedCommand, ...]:
        return _parse(command, depth=0)

    def interpreter_payloads(self, cmd: ParsedCommand) -> tuple[str, ...]:
        if not cmd.argv:
            return ()
        program = cmd.argv[0].rsplit("/", 1)[-1]

        if program == "eval":
            # Every argument to eval is code.
            return tuple(a for a in cmd.argv[1:] if a)

        flags = _CODE_FLAGS.get(program)
        if not flags:
            return ()

        payloads: list[str] = []
        rest = list(cmd.argv[1:])
        while rest:
            token = rest.pop(0)
            if token in flags:
                if rest:
                    payloads.append(rest.pop(0))
                else:
                    raise ShellParseError(f"{program} {token} with no payload to inspect")
            elif "=" in token and token.split("=", 1)[0] in flags:
                payloads.append(token.split("=", 1)[1])
        return tuple(payloads)


# ---------------------------------------------------------------- scanning


def _read_substitution(s: str, i: int, closer: str) -> tuple[str, int]:
    depth = 1
    start = i
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if closer == ")" and c == "(":
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return s[start:i], i + 1
        i += 1
    raise ShellParseError("unterminated command substitution")


def _read_word(s: str, i: int) -> tuple[str, list[str], int]:
    out: list[str] = []
    subs: list[str] = []

    while i < len(s):
        c = s[i]
        if c in _WORD_BREAK:
            break
        if c == "\\":
            if i + 1 >= len(s):
                raise ShellParseError("trailing backslash")
            out.append(s[i + 1])
            i += 2
        elif c == "'":
            end = s.find("'", i + 1)
            if end < 0:
                raise ShellParseError("unterminated single quote")
            out.append(s[i + 1 : end])
            i = end + 1
        elif c == '"':
            i += 1
            while True:
                if i >= len(s):
                    raise ShellParseError("unterminated double quote")
                if s[i] == "\\" and i + 1 < len(s):
                    out.append(s[i + 1])
                    i += 2
                elif s[i] == '"':
                    i += 1
                    break
                elif s[i : i + 2] == "$(":
                    payload, i = _read_substitution(s, i + 2, ")")
                    subs.append(payload)
                elif s[i] == "`":
                    payload, i = _read_substitution(s, i + 1, "`")
                    subs.append(payload)
                else:
                    out.append(s[i])
                    i += 1
        elif s[i : i + 2] == "$(":
            payload, i = _read_substitution(s, i + 2, ")")
            subs.append(payload)
        elif c == "`":
            payload, i = _read_substitution(s, i + 1, "`")
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
        elif pair == "\\\n":
            i += 2  # line continuation
        elif c in ";\n":
            toks.append(_Tok("op", c, i, i + 1))
            i += 1
        elif pair == "&>":
            # bash shorthand: redirect both streams. `&>>` appends, `&>` truncates.
            appends = s[i : i + 3] == "&>>"
            width = 3 if appends else 2
            toks.append(_Tok("redirect", ">>" if appends else ">", i, i + width))
            i += width
        elif pair == "&&":
            toks.append(_Tok("op", "&&", i, i + 2))
            i += 2
        elif c == "&":
            toks.append(_Tok("op", "&", i, i + 1))
            i += 1
        elif pair == "||":
            toks.append(_Tok("op", "||", i, i + 2))
            i += 2
        elif c == "|":
            toks.append(_Tok("op", "|", i, i + 1))
            i += 1
        elif c in "()":
            toks.append(_Tok("op", c, i, i + 1))
            i += 1
        elif pair == "<<":
            raise ShellParseError("here-documents are not parsed")
        elif pair in ("<(", ">("):
            raise ShellParseError("process substitution is not parsed")
        elif c == "<":
            toks.append(_Tok("redirect", "<", i, i + 1))
            i += 1
        elif pair == ">&":
            toks.append(_Tok("redirect", ">&", i, i + 2))
            i += 2
        elif pair == ">>":
            toks.append(_Tok("redirect", ">>", i, i + 2))
            i += 2
        elif pair == ">|":
            toks.append(_Tok("redirect", ">", i, i + 2))
            i += 2
        elif c == ">":
            toks.append(_Tok("redirect", ">", i, i + 1))
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
                takes_file = tok.text in (">", ">>", "<", ">&")
                if tok.text == ">" and k + 1 < len(segment) and segment[k + 1].kind == "word":
                    overwrites.append(segment[k + 1].text)
                k += 2 if (takes_file and k + 1 < len(segment)) else 1
                continue

            # A bare file descriptor number belongs to the redirect that follows
            # it (`2>&1`), not to the program's arguments.
            next_is_redirect = k + 1 < len(segment) and segment[k + 1].kind == "redirect"
            if not (tok.text.isdigit() and next_is_redirect):
                argv.append(tok.text)
            subs.extend(tok.subs)
            k += 1

        if argv:
            raw = command[segment[0].start : segment[-1].end].strip()
            out.append(ParsedCommand(tuple(argv), raw, tuple(overwrites)))

        # Substituted commands run for real, so they are commands too.
        for payload in subs:
            out.extend(_parse(payload, depth + 1))

    return tuple(out)


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

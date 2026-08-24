"""One suite, run against every ShellPort implementation.

The operators and `$( )` substitution tested here are common to cmd, PowerShell
and POSIX shells, so these are genuine cross-platform obligations rather than
one dialect's habits. Dialect specifics live in their own tests below.
"""

from __future__ import annotations

import pytest

from pharness.adapters.macos.shell import MacOSShell
from pharness.adapters.posix.shell import PosixShell
from pharness.adapters.windows.shell import WindowsShell
from pharness.core.policy.commands import program_key
from pharness.ports import ParsedCommand, ShellParseError, ShellPort

IMPLEMENTED = [
    pytest.param(PosixShell(), id="posix"),
    pytest.param(WindowsShell(), id="windows"),
]


@pytest.fixture(params=IMPLEMENTED)
def shell(request: pytest.FixtureRequest) -> ShellPort:
    return request.param


def programs(commands: tuple[ParsedCommand, ...]) -> list[str]:
    return [program_key(c.argv[0]) for c in commands if c.argv]


def test_satisfies_the_protocol(shell: ShellPort):
    assert isinstance(shell, ShellPort)


def test_simple_command(shell: ShellPort):
    parsed = shell.parse("npm test")
    assert len(parsed) == 1
    assert parsed[0].argv == ("npm", "test")


@pytest.mark.parametrize("separator", ["&&", "||", ";", "|"])
def test_chained_commands_are_all_visible(shell: ShellPort, separator: str):
    """The whole point: a command is never judged by its first word."""
    parsed = shell.parse(f"npm test {separator} git status")
    assert programs(parsed) == ["npm", "git"]


def test_substituted_command_is_visible(shell: ShellPort):
    assert "git" in programs(shell.parse("echo $(git status)"))


def test_nested_substitution_is_visible(shell: ShellPort):
    assert "git" in programs(shell.parse("echo $(echo $(git status))"))


def test_quoted_separator_is_not_a_separator(shell: ShellPort):
    """`echo "a && b"` runs one command, and treating it as two would be noise."""
    parsed = shell.parse('echo "a && b"')
    assert programs(parsed) == ["echo"]


def test_truncating_redirect_is_reported(shell: ShellPort):
    parsed = shell.parse("git status > out.txt")
    assert parsed[0].overwrite_targets == ("out.txt",)


def test_appending_redirect_is_not_a_truncation(shell: ShellPort):
    parsed = shell.parse("git status >> log.txt")
    assert parsed[0].overwrite_targets == ()


def test_every_returned_command_has_a_program(shell: ShellPort):
    for command in shell.parse("npm test && git status | grep x"):
        assert command.argv and command.argv[0]


def test_interpreter_payload_is_extracted(shell: ShellPort):
    """`python -c` reads the same on every platform."""
    parsed = shell.parse('python -c "import os"')
    assert shell.interpreter_payloads(parsed[0]) == ("import os",)


def test_ordinary_command_has_no_payload(shell: ShellPort):
    parsed = shell.parse("npm test")
    assert shell.interpreter_payloads(parsed[0]) == ()


@pytest.mark.parametrize("bad", ["echo 'unterminated", 'echo "unterminated', "echo $(unterminated"])
def test_unparseable_input_raises_rather_than_guessing(shell: ShellPort, bad: str):
    with pytest.raises(ShellParseError):
        shell.parse(bad)


def test_null_byte_is_refused(shell: ShellPort):
    with pytest.raises(ShellParseError):
        shell.parse("npm test\x00 && rm -rf /")


def test_absurdly_long_input_is_refused(shell: ShellPort):
    with pytest.raises(ShellParseError):
        shell.parse("echo " + "a" * 20000)


# -- POSIX specifics -----------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("echo `git status`", ["echo", "git"]),
        # One simple command: seeing through the assignment to npm is the
        # classifier's job, not the parser's (see real_program).
        ("FOO=bar npm test", ["foo=bar"]),
        ("npm test &> out.txt", ["npm"]),
        ("ls 2>&1", ["ls"]),
    ],
)
def test_posix_syntax(line: str, expected: list[str]):
    assert programs(PosixShell().parse(line)) == expected


@pytest.mark.parametrize("bad", ["cat <<EOF", "diff <(a) <(b)", "echo trailing\\"])
def test_posix_exotic_syntax_fails_closed(bad: str):
    with pytest.raises(ShellParseError):
        PosixShell().parse(bad)


def test_posix_eval_treats_every_argument_as_code():
    parsed = PosixShell().parse('eval "rm -rf ."')
    assert PosixShell().interpreter_payloads(parsed[0]) == ("rm -rf .",)


# -- Windows specifics ---------------------------------------------------------


def test_windows_command_flag_takes_the_rest_of_the_line():
    """PowerShell's -Command swallows everything after it; reading one token misses the rest."""
    shell = WindowsShell()
    parsed = shell.parse("powershell -Command npm run lint")
    assert shell.interpreter_payloads(parsed[0]) == ("npm run lint",)


def test_windows_accepts_abbreviated_flags():
    shell = WindowsShell()
    for spelling in ("-Command", "-Comm", "-C"):
        parsed = shell.parse(f'powershell {spelling} "Remove-Item x"')
        assert shell.interpreter_payloads(parsed[0]) == ("Remove-Item x",)


def test_windows_decodes_encoded_commands():
    """The encoding exists to survive quoting; it also hides the command."""
    import base64

    shell = WindowsShell()
    encoded = base64.b64encode("Remove-Item -Recurse C:\\x".encode("utf-16-le")).decode()
    parsed = shell.parse(f"powershell -EncodedCommand {encoded}")
    assert shell.interpreter_payloads(parsed[0]) == ("Remove-Item -Recurse C:\\x",)


def test_windows_undecodable_payload_fails_closed():
    shell = WindowsShell()
    parsed = shell.parse("powershell -EncodedCommand not-valid-base64!")
    with pytest.raises(ShellParseError):
        shell.interpreter_payloads(parsed[0])


def test_windows_caret_and_backtick_escapes():
    assert programs(WindowsShell().parse("echo a^&b")) == ["echo"]
    assert programs(WindowsShell().parse("echo a`&b")) == ["echo"]


def test_windows_literal_string_escape():
    parsed = WindowsShell().parse("echo 'it''s fine'")
    assert parsed[0].argv == ("echo", "it's fine")


def test_windows_out_file_is_a_truncation():
    """Out-File overwrites with no redirection operator to notice."""
    parsed = WindowsShell().parse("Get-Content a | Out-File -Path b.txt")
    assert parsed[-1].overwrite_targets == ("b.txt",)


def test_macos_adapter_is_declared_but_not_implemented():
    shell = MacOSShell()
    with pytest.raises(NotImplementedError, match="M9"):
        shell.parse("npm test")
    with pytest.raises(NotImplementedError, match="M9"):
        shell.interpreter_payloads(ParsedCommand(("npm",), "npm"))

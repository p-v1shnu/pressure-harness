"""Classifies what a command line would actually do.

Parsing belongs to the platform adapter; judging belongs here. The rule this
file exists to enforce is that a command is never judged by its first word
(PRD 10.4): every simple command in the line is examined, including the ones
hidden inside `$( )`, and every interpreter payload is treated as full risk
whether or not we can read it.

Nothing here touches the filesystem, so it can be fuzzed freely. Where a
verdict genuinely depends on the disk -- does this redirect target already
exist -- the caller supplies a probe.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pharness.core.policy.tiers import Tier
from pharness.ports import ParsedCommand, ShellParseError, ShellPort

MAX_PAYLOAD_DEPTH = 3

# Programs whose job is to destroy data. No approval path (PRD 10.3).
DESTRUCTIVE = frozenset(
    {
        "rm",
        "rmdir",
        "unlink",
        "shred",
        "srm",
        "wipe",
        "del",
        "erase",
        "rd",
        "remove-item",
        "ri",
        "clear-content",
        "dd",
        "truncate",
        "mkfs",
        "format",
        "diskpart",
        "fsutil",
        "cipher",
    }
)

# Raising privilege sidesteps every other guard, including "run as the user".
PRIVILEGE = frozenset({"sudo", "doas", "su", "runas", "gsudo", "pkexec", "start-process"})

# Fetches from the network. Harmless alone, forbidden next to an interpreter.
DOWNLOADERS = frozenset(
    {
        "curl",
        "wget",
        "aria2c",
        "httpie",
        "invoke-webrequest",
        "iwr",
        "invoke-restmethod",
        "irm",
        "bitsadmin",
        "certutil",
        "start-bitstransfer",
    }
)

# Fetch code and then run it as part of installing. Egress plus execution.
INSTALLERS: dict[str, frozenset[str]] = {
    "npm": frozenset({"install", "i", "ci", "add", "exec", "create"}),
    "pnpm": frozenset({"install", "i", "add", "dlx", "create"}),
    "yarn": frozenset({"install", "add", "dlx", "create"}),
    "bun": frozenset({"install", "add", "create", "x"}),
    "pip": frozenset({"install"}),
    "pip3": frozenset({"install"}),
    "uv": frozenset({"pip", "add", "sync", "tool"}),
    "poetry": frozenset({"add", "install"}),
    "cargo": frozenset({"install"}),
    "gem": frozenset({"install"}),
    "composer": frozenset({"install", "require"}),
    "go": frozenset({"install", "get"}),
    "apt": frozenset({"install"}),
    "apt-get": frozenset({"install"}),
    "brew": frozenset({"install"}),
    "choco": frozenset({"install"}),
    "winget": frozenset({"install"}),
    "scoop": frozenset({"install"}),
}

# `npx`/`pnpm dlx` download and execute in one step, with no subcommand to check.
FETCH_AND_RUN = frozenset({"npx", "bunx", "pnpx", "uvx"})

# Programs that execute code handed to them. Recognised by name as well as by
# payload flag: `curl x | sh` passes code on stdin, so there is no -c to spot.
INTERPRETERS = frozenset(
    {
        "sh",
        "bash",
        "dash",
        "zsh",
        "ksh",
        "fish",
        "python",
        "python3",
        "py",
        "node",
        "deno",
        "bun",
        "perl",
        "ruby",
        "php",
        "powershell",
        "pwsh",
        "cmd",
        "iex",
        "invoke-expression",
        "eval",
        "source",
    }
)

# Wrappers that run something else. The real program is further along the line.
WRAPPERS = frozenset(
    {"env", "nohup", "time", "timeout", "nice", "stdbuf", "command", "builtin", "exec", "xargs"}
)

_GUARD_MARKERS = ("pressureharness", "pressure-harness", ".pharness")


@dataclass(frozen=True)
class Finding:
    """One reason a command line landed at a tier.

    `detail` names a program or a target, never a whole payload: findings end up
    in the audit log and in approval prompts, and a payload copied into either
    is a payload copied somewhere new.
    """

    tier: Tier
    reason: str
    detail: str = ""


@dataclass(frozen=True)
class CommandAnalysis:
    tier: Tier
    findings: tuple[Finding, ...]
    commands: tuple[ParsedCommand, ...]
    matched_allowlist: str | None = None

    @property
    def top_reason(self) -> str:
        if not self.findings:
            return "nothing to run"
        worst = max(self.findings, key=lambda f: f.tier)
        return f"{worst.reason} ({worst.detail})" if worst.detail else worst.reason


def program_key(argv0: str) -> str:
    """Bare program name, lowercased, without path or Windows extension."""
    tail = argv0.replace("\\", "/").rsplit("/", 1)[-1].lower()
    for suffix in (".exe", ".cmd", ".bat", ".ps1", ".com"):
        if tail.endswith(suffix):
            return tail[: -len(suffix)]
    return tail


def real_program(argv: Sequence[str]) -> tuple[str, tuple[str, ...], bool]:
    """Skip variable assignments and wrappers to find what actually runs.

    `FOO=bar nohup npm test` runs npm, and a check that stops at `FOO=bar`
    learns nothing. The third return value says whether anything was skipped:
    an allowlist entry only matches a command nobody dressed up, because a
    leading assignment can change how the program behaves (LD_PRELOAD and
    friends) without changing a single token the allowlist looks at.
    """
    rest = list(argv)
    wrapped = False
    while rest:
        candidate = rest[0]
        if "=" in candidate and not candidate.startswith("-") and "/" not in candidate:
            rest.pop(0)
            wrapped = True
            continue
        key = program_key(candidate)
        if key in WRAPPERS and len(rest) > 1:
            rest.pop(0)
            wrapped = True
            # Skip the wrapper's own flags and assignments.
            while rest and (rest[0].startswith("-") or "=" in rest[0]):
                rest.pop(0)
            continue
        return key, tuple(rest[1:]), wrapped
    return "", (), wrapped


def _subcommand(args: Sequence[str]) -> str:
    for arg in args:
        if not arg.startswith("-"):
            return arg.lower()
    return ""


def _git_finding(args: Sequence[str]) -> Finding | None:
    flags = {a.lower() for a in args}
    sub = _subcommand(args)

    if sub == "push":
        if "--force" in flags or "-f" in flags:
            return Finding(Tier.FORBIDDEN, "force push rewrites history on the remote", "git push")
        if "--mirror" in flags or "--delete" in flags or "-d" in flags:
            return Finding(Tier.FORBIDDEN, "this push would delete remote refs", "git push")
        return Finding(Tier.EGRESS, "pushing sends code off this machine", "git push")

    if sub == "reset" and "--hard" in flags:
        return Finding(
            Tier.FORBIDDEN,
            "a hard reset discards uncommitted work with nothing to undo it from",
            "git reset",
        )
    if sub == "clean" and flags & {"-f", "-fd", "-fdx", "-xdf", "-x", "-d"}:
        return Finding(Tier.FORBIDDEN, "git clean deletes untracked files", "git clean")
    if sub == "branch" and flags & {"-d", "-D", "--delete"}:
        return Finding(Tier.FORBIDDEN, "deleting a branch can orphan commits", "git branch")
    if sub in ("filter-branch", "filter-repo"):
        return Finding(Tier.FORBIDDEN, "history rewriting is never automatic here", f"git {sub}")
    if sub == "tag" and flags & {"-d", "--delete"}:
        return Finding(Tier.FORBIDDEN, "deleting a tag removes a release marker", "git tag")
    return None


def _guard_tamper(argv: Sequence[str]) -> Finding | None:
    for arg in argv:
        lowered = arg.lower()
        if any(marker in lowered for marker in _GUARD_MARKERS):
            return Finding(
                Tier.FORBIDDEN,
                "that touches Pressure Harness's own files, which no tool may change",
            )
    return None


def _installer_finding(program: str, args: Sequence[str]) -> Finding | None:
    if program in FETCH_AND_RUN:
        return Finding(Tier.EGRESS, "downloads a package and runs it immediately", program)
    subs = INSTALLERS.get(program)
    if subs and _subcommand(args) in subs:
        return Finding(
            Tier.EGRESS,
            "installing fetches code and runs its install scripts",
            f"{program} {_subcommand(args)}",
        )
    return None


def _matches_allowlist(argv: Sequence[str], allow_commands: Sequence[str]) -> str | None:
    """Allowlist entries match on an argv prefix, so `npm test` covers `npm test -- -w`.

    The program name is normalised first: on Windows the same command arrives as
    `npm`, `npm.cmd` or a full path, and an allowlist that only recognises one
    spelling sends the user a stream of prompts for commands they already
    approved -- which is how approval fatigue starts (PRD 10.7).

    Prefix matching is only safe because it is applied to a single simple
    command with no redirection and no interpreter: by the time we get here,
    `npm test && rm -rf .` has already been split into two commands and the
    second one has its own verdict.
    """
    program, args, wrapped = real_program(argv)
    if wrapped:
        return None
    actual = [program, *(a.lower() for a in args)]
    for entry in allow_commands:
        tokens = entry.split()
        if not tokens:
            continue
        normalised = [program_key(tokens[0]), *(t.lower() for t in tokens[1:])]
        if actual[: len(normalised)] == normalised:
            return entry
    return None


def classify(
    command_line: str,
    *,
    shell: ShellPort,
    allow_commands: Sequence[str] = (),
    file_exists: Callable[[str], bool] | None = None,
) -> CommandAnalysis:
    """Judge a whole command line.

    `file_exists` decides whether a `>` redirect would truncate something that
    is already there; without it the redirect is treated as an ordinary write
    rather than assumed harmless.
    """
    try:
        commands = shell.parse(command_line)
    except ShellParseError as exc:
        return CommandAnalysis(
            tier=Tier.FORBIDDEN,
            findings=(
                Finding(
                    Tier.FORBIDDEN,
                    f"this command line cannot be analysed with confidence ({exc})",
                ),
            ),
            commands=(),
        )

    if not commands:
        return CommandAnalysis(
            tier=Tier.FORBIDDEN,
            findings=(Finding(Tier.FORBIDDEN, "no command to run"),),
            commands=(),
        )

    findings: list[Finding] = []
    expanded, payload_findings = _expand_payloads(commands, shell)
    findings.extend(payload_findings)

    saw_downloader = False
    saw_interpreter = bool(payload_findings)

    for cmd in expanded:
        program, args, _ = real_program(cmd.argv)
        if not program:
            continue

        if program in INTERPRETERS:
            saw_interpreter = True

        tamper = _guard_tamper(cmd.argv)
        if tamper:
            findings.append(tamper)

        if program in PRIVILEGE:
            findings.append(
                Finding(Tier.FORBIDDEN, "raising privilege bypasses every other guard", program)
            )
        if program in DESTRUCTIVE:
            findings.append(Finding(Tier.FORBIDDEN, "this deletes or destroys data", program))
        if program in DOWNLOADERS:
            saw_downloader = True
            findings.append(Finding(Tier.EGRESS, "fetches from the network", program))

        if program == "git":
            git_finding = _git_finding(args)
            if git_finding:
                findings.append(git_finding)

        installer = _installer_finding(program, args)
        if installer:
            findings.append(installer)

        for target in cmd.overwrite_targets:
            already_there = file_exists(target) if file_exists else False
            if already_there:
                findings.append(
                    Finding(
                        Tier.FORBIDDEN,
                        "this redirect would overwrite an existing file",
                        target,
                    )
                )
            else:
                findings.append(Finding(Tier.WRITE, "writes a file through redirection", target))

    if saw_downloader and saw_interpreter:
        findings.append(
            Finding(
                Tier.FORBIDDEN,
                "downloading something and piping it straight into an interpreter",
            )
        )

    # Every command line that runs a program gets a baseline of either
    # EXEC_ALLOWED or EXEC_OTHER, and it is added unconditionally.
    #
    # Found by fuzzing: when this was only added for lines with no other
    # findings, `some-unknown-program > out.txt` produced a lone WRITE finding
    # and auto-allowed, because the redirect was the only thing anyone noticed.
    # Running an unrecognised program is the risk; a redirect alongside it is a
    # detail, and details must not be able to lower a tier.
    matched: str | None = None
    can_match_allowlist = (
        len(expanded) == 1
        and not any(f.tier >= Tier.EXEC_OTHER for f in findings)
        # A redirect writes to a path this classifier never checked, so an
        # allowlisted command plus a redirect is not an allowlisted command.
        and not any(cmd.overwrite_targets for cmd in expanded)
    )
    if can_match_allowlist:
        matched = _matches_allowlist(expanded[0].argv, allow_commands)

    if matched:
        findings.append(Finding(Tier.EXEC_ALLOWED, "allowlisted for this workspace", matched))
    else:
        program, _, _ = real_program(expanded[0].argv)
        findings.append(
            Finding(Tier.EXEC_OTHER, "not allowlisted for this workspace", program or "unknown")
        )

    return CommandAnalysis(
        tier=max(f.tier for f in findings),
        findings=tuple(findings),
        commands=tuple(expanded),
        matched_allowlist=matched,
    )


def _expand_payloads(
    commands: Sequence[ParsedCommand], shell: ShellPort, depth: int = 0
) -> tuple[list[ParsedCommand], list[Finding]]:
    """Add commands hidden inside interpreter payloads to the list to judge.

    Every interpreter call is EXEC_OTHER on its own, before anything in the
    payload is read. That is deliberate: a Python or Node payload cannot be
    analysed by a shell parser at all, so the honest position is that we do not
    know what it does. Reading the payload can only make the verdict worse.
    """
    out = list(commands)
    findings: list[Finding] = []

    if depth >= MAX_PAYLOAD_DEPTH:
        findings.append(Finding(Tier.FORBIDDEN, "interpreters nested too deeply to analyse"))
        return out, findings

    for cmd in commands:
        try:
            payloads = shell.interpreter_payloads(cmd)
        except ShellParseError as exc:
            findings.append(
                Finding(Tier.FORBIDDEN, f"an interpreter payload could not be read ({exc})")
            )
            continue

        for payload in payloads:
            program, _, _ = real_program(cmd.argv)
            findings.append(
                Finding(
                    Tier.EXEC_OTHER,
                    "runs code through an interpreter, which no allowlist can cover",
                    program,
                )
            )
            try:
                nested = shell.parse(payload)
            except ShellParseError:
                # Not shell syntax -- a Python or JavaScript payload, most
                # likely. It stays at EXEC_OTHER: unreadable is not the same as
                # safe, and pretending otherwise is how allowlists get bypassed.
                continue
            deeper, deeper_findings = _expand_payloads(nested, shell, depth + 1)
            out.extend(deeper)
            findings.extend(deeper_findings)

    return out, findings

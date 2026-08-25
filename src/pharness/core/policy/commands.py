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

# Container runtimes. They deserve their own rules because a container is a way
# to run a command with different rules than the host's -- which is exactly the
# thing this policy engine exists to decide. Judging `docker` as one opaque
# program means `docker exec api rm -rf /` reads as harmless.
CONTAINER_PROGRAMS = frozenset({"docker", "podman", "docker-compose", "nerdctl"})

# Subcommands that only look. Nothing here lowers their tier -- the user's
# allowlist does that, exactly as it does for `git status` -- but naming them
# means the suggested allowlist in the docs is not guesswork.
CONTAINER_READ_SUBS = frozenset(
    {"ps", "images", "logs", "inspect", "top", "stats", "version", "info", "port", "config"}
)

# Nouns that take their own verb: `docker system prune`, `docker volume rm`.
# Reading only the first word sees "system", which says nothing at all.
CONTAINER_NOUNS = frozenset(
    {"system", "volume", "image", "container", "network", "builder", "buildx"}
)

# Verbs that destroy data nothing here can put back. The journal covers files;
# it has never covered a volume.
CONTAINER_DESTRUCTIVE = frozenset({"prune", "rm"})

# Flags that appear before the verb and consume the next word.
CONTAINER_GLOBAL_VALUE_FLAGS = frozenset(
    {
        "-h",
        "--host",
        "-c",
        "--context",
        "--config",
        "-l",
        "--log-level",
        "--tlscacert",
        "--tlscert",
        "--tlskey",
        "-f",
        "--file",
        "-p",
        "--project-name",
        "--project-directory",
        "--profile",
        "--env-file",
    }
)

# Pointing the client at another daemon acts on a different machine entirely.
CONTAINER_REMOTE_FLAGS = frozenset({"-h", "--host", "-c", "--context"})

# Flags that hand the container the host. Any one of them means the container
# boundary -- and therefore every boundary above it -- no longer applies.
CONTAINER_ESCAPE_FLAGS = frozenset(
    {
        "--privileged",
        "--pid=host",
        "--ipc=host",
        "--uts=host",
        "--userns=host",
        "--network=host",
        "--net=host",
        "--cgroupns=host",
        "--security-opt=seccomp=unconfined",
        "--security-opt=apparmor=unconfined",
    }
)
CONTAINER_ESCAPE_VALUES = frozenset(
    {"host", "seccomp=unconfined", "apparmor=unconfined", "seccomp:unconfined"}
)
CONTAINER_ESCAPE_PAIRED = frozenset(
    {"--pid", "--ipc", "--uts", "--userns", "--network", "--net", "--cgroupns", "--security-opt"}
)

# Host paths that must never be mounted into a container.
FORBIDDEN_MOUNT_SOURCES = (
    "/",
    "/etc",
    "/root",
    "/home",
    "/var",
    "/usr",
    "/boot",
    "/proc",
    "/sys",
)

# Credential directories, matched by name anywhere in the source. `$HOME/.ssh`
# is not expanded by this parser, so matching the tail is what catches it -- and
# mounting a directory is a read of everything under it.
SENSITIVE_MOUNT_NAMES = (".ssh", ".aws", ".gnupg", ".kube", ".docker", ".azure", ".env")

# Flags on run/exec that take a separate value, so the value is not the image.
CONTAINER_VALUE_FLAGS = frozenset(
    {
        "-u",
        "--user",
        "-w",
        "--workdir",
        "-e",
        "--env",
        "--env-file",
        "-v",
        "--volume",
        "--mount",
        "-p",
        "--publish",
        "--name",
        "--network",
        "--net",
        "--entrypoint",
        "--label",
        "-l",
        "--add-host",
        "--device",
        "--restart",
        "--platform",
        "--pull",
        "--security-opt",
        "--cap-add",
        "--cap-drop",
        "--tmpfs",
        "--ulimit",
        "--memory",
        "-m",
        "--cpus",
        "--health-cmd",
        "--log-driver",
        "--ipc",
        "--pid",
        "--uts",
        "--userns",
        "--cgroupns",
        "--build-arg",
        "-f",
        "--file",
        "--index",
        "--profile",
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


def _mount_sources(args: Sequence[str]) -> list[str]:
    """Host paths a run/create would mount, from -v, --volume and --mount."""
    sources: list[str] = []
    rest = list(args)
    while rest:
        token = rest.pop(0)
        value = None
        if token in ("-v", "--volume", "--mount") and rest:
            value = rest.pop(0)
        elif token.startswith(("-v=", "--volume=", "--mount=")):
            value = token.split("=", 1)[1]
        if not value:
            continue

        if value.startswith("type="):  # --mount type=bind,source=/x,target=/y
            for part in value.split(","):
                if part.startswith(("source=", "src=")):
                    sources.append(part.split("=", 1)[1])
        else:  # -v /host:/container[:opts]
            head = value.split(":", 1)[0]
            looks_like_path = head.startswith(("/", "~", ".", "$")) or (
                len(head) > 1 and head[1] == ":"
            )
            if looks_like_path:
                sources.append(head)
    return sources


def _escape_flags(args: Sequence[str]) -> list[str]:
    """Flags that give the container the host's namespaces or privileges."""
    found: list[str] = []
    rest = list(args)
    while rest:
        token = rest.pop(0)
        lowered = token.lower()
        if lowered in CONTAINER_ESCAPE_FLAGS:
            found.append(token)
        elif lowered in CONTAINER_ESCAPE_PAIRED and rest:
            value = rest.pop(0)
            if value.lower() in CONTAINER_ESCAPE_VALUES:
                found.append(f"{token} {value}")
    return found


def _inner_command(args: Sequence[str], subcommand: str) -> list[str]:
    """The command a run/exec would execute inside the container.

    Returns [] when it cannot be identified with confidence, which leaves the
    call at its usual tier rather than guessing something reassuring.
    """
    rest = list(args)
    # Drop everything up to and including the subcommand (handles `compose exec`).
    while rest and rest[0] != subcommand:
        rest.pop(0)
    if rest:
        rest.pop(0)

    while rest:
        token = rest[0]
        if not token.startswith("-"):
            rest.pop(0)  # the image or container name
            return rest
        rest.pop(0)
        if token in CONTAINER_VALUE_FLAGS and rest:
            rest.pop(0)
        elif token == "--":
            return rest
    return []


def container_verb(args: Sequence[str]) -> str:
    """The word that says what a container command actually does.

    `docker compose down`, `docker system prune` and `docker volume rm` all hide
    their verb behind a noun, so a check that reads the first word sees
    "compose", "system" and "volume" -- none of which mean anything.
    """
    words: list[str] = []
    rest = list(args)
    while rest:
        token = rest.pop(0)
        if token.startswith("-"):
            # Global flags come before the verb, and several take a value:
            # `docker -H tcp://host image prune` would otherwise read as a
            # command called "tcp://host".
            if token.lower() in CONTAINER_GLOBAL_VALUE_FLAGS and rest:
                rest.pop(0)
            continue
        words.append(token)

    for index, word in enumerate(words):
        lowered = word.lower()
        if lowered == "compose" or lowered in CONTAINER_NOUNS:
            return words[index + 1].lower() if index + 1 < len(words) else lowered
        return lowered
    return ""


def _container_finding(program: str, args: Sequence[str]) -> list[Finding]:
    """Judge a container command by what it would actually do."""
    findings: list[Finding] = []
    sub = container_verb(args)
    words = [a.lower() for a in args]

    for index, token in enumerate(args):
        if token.lower() in CONTAINER_REMOTE_FLAGS and index + 1 < len(args):
            findings.append(
                Finding(
                    Tier.EGRESS,
                    "this targets a different Docker host, so it acts on another machine",
                    args[index + 1],
                )
            )

    if any("docker.sock" in a for a in words):
        findings.append(
            Finding(
                Tier.FORBIDDEN,
                "handing over the Docker socket is handing over the machine",
                program,
            )
        )

    escapes = _escape_flags(args)
    if escapes:
        findings.append(
            Finding(
                Tier.FORBIDDEN,
                "this gives the container the host, so no boundary above it applies",
                escapes[0],
            )
        )

    for source in _mount_sources(args):
        normalised = source.rstrip("/") or "/"
        if normalised in FORBIDDEN_MOUNT_SOURCES or normalised.endswith(":\\"):
            findings.append(
                Finding(
                    Tier.FORBIDDEN,
                    "mounting this into a container reaches around the workspace entirely",
                    source,
                )
            )
        elif any(name in source for name in SENSITIVE_MOUNT_NAMES):
            findings.append(
                Finding(
                    Tier.FORBIDDEN,
                    "mounting a credential directory hands its contents to the container",
                    source,
                )
            )
        else:
            findings.append(
                Finding(Tier.EXEC_OTHER, "mounts a host directory into the container", source)
            )

    # Deleting volumes destroys data the journal has never covered.
    volumes_flagged = any(flag in words for flag in ("-v", "--volumes", "--volume"))
    touches_volumes = "volume" in words

    if sub in CONTAINER_DESTRUCTIVE and (touches_volumes or volumes_flagged):
        findings.append(
            Finding(
                Tier.FORBIDDEN,
                "this removes volumes, and the data in them is not something anything "
                "here can restore",
                f"{program} {sub}",
            )
        )
    elif sub == "down" and volumes_flagged:
        findings.append(
            Finding(
                Tier.FORBIDDEN,
                "`down -v` deletes the project's volumes, database included",
            )
        )
    elif sub == "prune":
        findings.append(
            Finding(Tier.EXEC_OTHER, "pruning removes containers and images", f"{program} prune")
        )

    if sub in ("pull", "push", "build"):
        findings.append(
            Finding(
                Tier.EGRESS,
                "fetches or publishes images, and a build runs whatever the Dockerfile says",
                f"{program} {sub}",
            )
        )

    return findings


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

        if program in CONTAINER_PROGRAMS:
            findings.extend(_container_finding(program, args))

            # A command run inside a container is still a command. `docker exec
            # api rm -rf /` reads as harmless until you look past the first word.
            sub = container_verb(args)
            if sub in ("run", "exec", "create"):
                inner = _inner_command(args, sub)
                if inner:
                    nested = classify(" ".join(inner), shell=shell, file_exists=None)
                    for finding in nested.findings:
                        # "not allowlisted" is about the host's allowlist and
                        # does not describe the inner command.
                        interesting = finding.tier >= Tier.EXEC_OTHER
                        if interesting and "not allowlisted" not in finding.reason:
                            findings.append(
                                Finding(
                                    finding.tier,
                                    f"inside the container: {finding.reason}",
                                    finding.detail,
                                )
                            )

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

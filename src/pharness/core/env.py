"""Building the environment a child process gets.

Passing the parent environment through is the default everywhere and it is
wrong here: it hands every API key in the shell to anything a model decides to
run (PRD 10.5). So the environment is constructed from an allowlist instead.

The allowlist has to be right or nothing starts. On Windows, `SystemRoot` and
`PATHEXT` are not optional -- programs fail in confusing ways without them,
which is worse than failing loudly.
"""

from __future__ import annotations

from collections.abc import Mapping

# Needed for a process to work at all.
BASE_KEYS = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TZ",
    "TERM",
)

WINDOWS_KEYS = (
    "SystemRoot",
    "SystemDrive",
    "windir",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMDATA",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
)

POSIX_KEYS = (
    "SHELL",
    "USER",
    "LOGNAME",
    "TMPDIR",
    "XDG_CACHE_HOME",
)

# Toolchains that break without their own variables. Added because a harness
# that cannot run `npm test` is not a harness.
TOOLCHAIN_KEYS = (
    "NODE_ENV",
    "NODE_OPTIONS",
    "NVM_DIR",
    "NVM_BIN",
    "PNPM_HOME",
    "COREPACK_HOME",
    "PYTHONPATH",
    "PYTHONHOME",
    "VIRTUAL_ENV",
    "CONDA_PREFIX",
    "CARGO_HOME",
    "RUSTUP_HOME",
    "GOPATH",
    "GOROOT",
    "JAVA_HOME",
    "DOTNET_ROOT",
)

# Never forwarded even if the user allowlists them by name: these change what a
# program *is*, not how it behaves.
ALWAYS_BLOCKED = frozenset(
    {
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "LD_AUDIT",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
        "PYTHONSTARTUP",
        "BASH_ENV",
        "ENV",
    }
)


def default_allowlist(platform: str) -> tuple[str, ...]:
    keys = [*BASE_KEYS, *TOOLCHAIN_KEYS]
    keys.extend(WINDOWS_KEYS if platform == "windows" else POSIX_KEYS)
    return tuple(dict.fromkeys(keys))


def build_env(
    parent: Mapping[str, str],
    platform: str,
    extra_allow: tuple[str, ...] = (),
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Assemble a child environment from `parent` by allowlist.

    Lookups are case-insensitive because Windows environment variables are, and
    a lookup that misses `SystemRoot` because it was spelled `SYSTEMROOT`
    produces a failure nobody can explain.
    """
    allowed = {key.lower() for key in (*default_allowlist(platform), *extra_allow)}
    blocked = {key.lower() for key in ALWAYS_BLOCKED}

    env: dict[str, str] = {}
    for key, value in parent.items():
        lowered = key.lower()
        if lowered in blocked or lowered not in allowed:
            continue
        env[key] = value

    for key, value in (overrides or {}).items():
        if key.lower() in blocked:
            continue
        env[key] = value

    # Non-interactive by default: a child that opens a pager or an editor and
    # waits for a keystroke hangs a tool call until it times out.
    env.setdefault("CI", "1")
    env.setdefault("GIT_PAGER", "cat")
    env.setdefault("PAGER", "cat")
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("NO_COLOR", "1")
    return env

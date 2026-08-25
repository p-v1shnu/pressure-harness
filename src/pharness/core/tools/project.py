"""Running a project's own commands: test, lint, typecheck, build, dev.

The safety point from PRD 8.3: `npm test` is exactly as safe as the project's
`package.json`, and anyone can edit a script to do anything. So the resolved
command is always shown, never just the script name -- "ran the tests" is not
something the user should have to take on trust.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pharness.core.config import ContextSettings
from pharness.core.text import clamp, wrap_external
from pharness.core.tools.results import ToolResult
from pharness.core.workspace import Workspace
from pharness.ports import ProcessPort, ProcessStartError

TASKS = ("dev", "test", "lint", "typecheck", "build", "install")
DEFAULT_TIMEOUT = 600.0

# Detected by lockfile, because that is what the project actually uses rather
# than what happens to be installed.
# Dev servers announce themselves: "Local: http://localhost:5173/",
# "ready on http://127.0.0.1:3000", and so on.
URL_IN_OUTPUT = re.compile(r"https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?(?:/\S*)?")

LOCKFILES = {
    "pnpm-lock.yaml": "pnpm",
    "yarn.lock": "yarn",
    "bun.lockb": "bun",
    "package-lock.json": "npm",
}


@dataclass
class ProjectTools:
    workspace: Workspace
    process: ProcessPort
    context: ContextSettings
    env: Mapping[str, str]

    # -- detection ---------------------------------------------------------

    def package_manager(self) -> str | None:
        root = self.workspace.root
        for lockfile, manager in LOCKFILES.items():
            if (root / lockfile).is_file():
                return manager
        return "npm" if (root / "package.json").is_file() else None

    def package_scripts(self) -> dict[str, str]:
        manifest = self.workspace.root / "package.json"
        if not manifest.is_file():
            return {}
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        scripts = data.get("scripts")
        return {str(k): str(v) for k, v in scripts.items()} if isinstance(scripts, dict) else {}

    def resolve(self, task: str) -> tuple[list[str], str] | None:
        """Return (argv, explanation) for `task`, or None if it is not defined.

        A command configured for the workspace always wins over anything
        detected: the user's mapping is a decision, detection is a guess.
        """
        configured = self.workspace.config.scripts.get(task)
        if configured:
            return configured.split(), f"configured for this workspace: {configured}"

        manager = self.package_manager()
        scripts = self.package_scripts()
        if manager and task in scripts:
            prefix = [manager] if task in ("test", "install") else [manager, "run"]
            return [*prefix, task], f"package.json script {task!r}: {scripts[task]}"

        if task == "install" and manager:
            return [manager, "install"], f"{manager} install"

        if task == "test" and (self.workspace.root / "pyproject.toml").is_file():
            return ["python", "-m", "pytest"], "pyproject.toml present, running pytest"

        return None

    def script_body(self, task: str) -> str | None:
        """The command a package.json script would really run, if any.

        Judging `npm test` tells you nothing: npm hands the script to a shell,
        and the script is whatever the repository says it is. A cloned project
        could define `"test": "rm -rf ~"` and every check upstream would see two
        harmless words. So the script's own text is what gets classified.
        """
        if self.workspace.config.scripts.get(task):
            return None  # the user configured this one themselves
        return self.package_scripts().get(task)

    def describe(self) -> ToolResult:
        manager = self.package_manager()
        lines = [f"workspace: {self.workspace.alias}", f"package manager: {manager or 'none'}"]
        for task in TASKS:
            resolved = self.resolve(task)
            lines.append(f"  {task:10} {' '.join(resolved[0]) if resolved else '-- not defined'}")
        return ToolResult(text="\n".join(lines), meta={"manager": manager})

    # -- running -----------------------------------------------------------

    def run(self, task: str, timeout_sec: float = DEFAULT_TIMEOUT) -> ToolResult:
        if task not in TASKS:
            return ToolResult.failure(f"unknown task {task!r}; expected one of {', '.join(TASKS)}")
        if task == "dev":
            return ToolResult.failure("use start_dev for a long-running server")

        resolved = self.resolve(task)
        if resolved is None:
            return ToolResult.failure(
                f"no {task} command is defined for {self.workspace.alias}. "
                f"Map one in the workspace config under [workspace.scripts]."
            )

        argv, why = resolved
        argv = self._with_executable(argv)
        result = self.process.run(argv, self.workspace.root, self.env, timeout_sec=timeout_sec)

        header = f"$ {' '.join(argv)}\n({why})\n"
        if result.timed_out:
            return ToolResult.failure(
                header
                + f"timed out after {timeout_sec:.0f}s\n"
                + clamp(result.combined, self.context.max_output_bytes // 2).text
            )

        body = wrap_external(
            clamp(result.combined, self.context.max_output_bytes).text, f"the {task} output"
        )
        text = f"{header}exit {result.exit_code} in {result.duration_sec:.1f}s\n\n{body}"
        return ToolResult(
            text=text,
            ok=result.ok,
            meta={"task": task, "argv": argv, "exit_code": result.exit_code},
        )

    def start_dev(self) -> ToolResult:
        resolved = self.resolve("dev")
        if resolved is None:
            return ToolResult.failure(
                f"no dev command is defined for {self.workspace.alias}. "
                "Map one under [workspace.scripts]."
            )

        argv, why = resolved
        argv = self._with_executable(argv)
        try:
            handle = self.process.spawn(argv, self.workspace.root, self.env, label="dev")
        except ProcessStartError as exc:
            return ToolResult.failure(str(exc))

        url = self._wait_for_url(handle)
        lines = [f"started {handle.id}: {' '.join(argv)}", f"({why})", f"pid {handle.pid}"]
        if url:
            lines.append(f"serving at {url}")
        else:
            lines.append(
                "no address printed yet -- check process logs before opening it in a browser"
            )

        return ToolResult(
            text="\n".join(lines),
            meta={"process_id": handle.id, "pid": handle.pid, "argv": argv, "url": url},
        )

    def _wait_for_url(self, handle, timeout_sec: float = 10.0) -> str | None:
        """Watch the dev server's output for the address it is serving on.

        Returning the moment the process starts is technically true and
        practically useless: the next thing anyone does is open the page, and a
        page opened two seconds too early is a connection error that looks like
        a broken change. Most dev servers announce their URL, so this waits for
        one, and says plainly when none appeared rather than implying the server
        is ready.
        """
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if not handle.is_running():
                return None
            match = URL_IN_OUTPUT.search(handle.tail(60))
            if match:
                return match.group(0).rstrip("/.,")
            time.sleep(0.2)
        return None

    def _with_executable(self, argv: list[str]) -> list[str]:
        """Resolve argv[0] on PATH.

        Needed because nothing here runs through a shell, and on Windows the
        thing called `npm` is really `npm.cmd`.
        """
        found = shutil.which(argv[0], path=self.env.get("PATH"))
        return [found, *argv[1:]] if found else argv


def looks_like_project(root: Path) -> bool:
    return any(
        (root / marker).exists()
        for marker in ("package.json", "pyproject.toml", "Cargo.toml", "go.mod", "Makefile")
    )

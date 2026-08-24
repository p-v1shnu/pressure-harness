"""Running a project's own commands: test, lint, typecheck, build, dev.

The safety point from PRD 8.3: `npm test` is exactly as safe as the project's
`package.json`, and anyone can edit a script to do anything. So the resolved
command is always shown, never just the script name -- "ran the tests" is not
something the user should have to take on trust.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pharness.core.config import ContextSettings
from pharness.core.text import clamp
from pharness.core.tools.results import ToolResult
from pharness.core.workspace import Workspace
from pharness.ports import ProcessPort

TASKS = ("dev", "test", "lint", "typecheck", "build", "install")
DEFAULT_TIMEOUT = 600.0

# Detected by lockfile, because that is what the project actually uses rather
# than what happens to be installed.
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

        body = clamp(result.combined, self.context.max_output_bytes).text
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
        handle = self.process.spawn(argv, self.workspace.root, self.env, label="dev")
        return ToolResult(
            text=(
                f"started {handle.id}: {' '.join(argv)}\n({why})\n"
                f"pid {handle.pid}. Read its output with process logs, stop it with process stop."
            ),
            meta={"process_id": handle.id, "pid": handle.pid, "argv": argv},
        )

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

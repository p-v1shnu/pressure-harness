"""Handing a task to another coding agent on this machine.

This is the tool that most directly serves the point of the project: the heavy
work runs locally in a CLI that charges nothing per token, and the conversation
only has to say what needs doing and read back the result.

It is also the one tool whose own rules stop at the boundary. A delegate is a
full agent with its own permissions: it will edit files and run commands that
never pass through this policy engine. So it is always EXEC_OTHER -- never
allowlistable, never automatic -- and the approval prompt shows the whole task
text and the exact command, because that is the last point at which anyone here
can decide anything about it.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from dataclasses import dataclass

from pharness.core.config import ContextSettings
from pharness.core.text import clamp
from pharness.core.tools.results import ToolResult
from pharness.core.workspace import Workspace
from pharness.ports import ProcessPort, ProcessStartError

TASK_PLACEHOLDER = "{task}"
DEFAULT_TIMEOUT = 900.0
MAX_TASK_CHARS = 8000

# Starting points for the CLIs people are most likely to have. They are a guess
# at the right flags, not a promise: the resolved command appears in the
# approval prompt every time, so a wrong one is visible and correctable, and a
# workspace can override any of them.
DEFAULT_TEMPLATES: dict[str, str] = {
    "codex": "codex exec {task}",
    "claude": "claude -p {task}",
}


@dataclass
class DelegateTools:
    workspace: Workspace
    process: ProcessPort
    context: ContextSettings
    env: Mapping[str, str]
    templates: Mapping[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.templates is None:
            self.templates = {}

    # -- what is available -------------------------------------------------

    def resolved_templates(self) -> dict[str, str]:
        """Configured delegates first, then defaults for CLIs that are installed.

        A default only appears when the binary is actually on PATH: offering a
        delegate that cannot run wastes a call and a prompt to find out.
        """
        available = dict(self.templates)
        for name, template in DEFAULT_TEMPLATES.items():
            if name in available:
                continue
            if shutil.which(name, path=self.env.get("PATH")):
                available[name] = template
        return available

    def argv_for(self, name: str, task: str) -> list[str] | None:
        """Build the command, with the task as one argument.

        Substituting into a string and handing it to a shell would make every
        quote in the task a way to change the command. The task is placed as a
        single argv element instead, so it cannot be anything but data.
        """
        template = self.resolved_templates().get(name)
        if template is None:
            return None

        parts = template.split()
        argv: list[str] = []
        placed = False
        for part in parts:
            if part == TASK_PLACEHOLDER:
                argv.append(task)
                placed = True
            elif TASK_PLACEHOLDER in part:
                # e.g. --prompt={task}; still one argument, still not a shell.
                argv.append(part.replace(TASK_PLACEHOLDER, task))
                placed = True
            else:
                argv.append(part)
        if not placed:
            argv.append(task)

        found = shutil.which(argv[0], path=self.env.get("PATH"))
        if found:
            argv[0] = found
        return argv

    def describe(self) -> ToolResult:
        available = self.resolved_templates()
        if not available:
            return ToolResult(
                text=(
                    "No delegate is configured, and neither codex nor claude is on PATH.\n"
                    "Add one under [workspace.delegates], for example:\n"
                    '    codex = "codex exec {task}"'
                ),
                meta={"delegates": []},
            )
        lines = ["Delegates available in this workspace:"]
        for name, template in sorted(available.items()):
            configured = "configured" if name in self.templates else "detected on PATH"
            lines.append(f"  {name:10} {template}   ({configured})")
        lines.append(
            "\nA delegate runs as its own agent with its own permissions. Nothing it "
            "does passes through this policy engine."
        )
        return ToolResult(text="\n".join(lines), meta={"delegates": sorted(available)})

    # -- running -----------------------------------------------------------

    def run(self, name: str, task: str, timeout_sec: float = DEFAULT_TIMEOUT) -> ToolResult:
        task = task.strip()
        if not task:
            return ToolResult.failure("say what the delegate should do")
        if len(task) > MAX_TASK_CHARS:
            return ToolResult.failure(
                f"the task is longer than {MAX_TASK_CHARS} characters; give it a shorter brief"
            )

        argv = self.argv_for(name, task)
        if argv is None:
            available = ", ".join(sorted(self.resolved_templates())) or "none"
            return ToolResult.failure(f"no delegate called {name!r}. Available: {available}")

        try:
            result = self.process.run(argv, self.workspace.root, self.env, timeout_sec=timeout_sec)
        except ProcessStartError as exc:
            return ToolResult.failure(str(exc))

        header = f"$ {' '.join(argv[:-1])} <task>\nran in {self.workspace.alias}"
        if result.timed_out:
            partial = clamp(result.combined, self.context.max_output_bytes // 2).text
            return ToolResult.failure(
                f"{header}\n{name} did not finish within {timeout_sec:.0f}s\n\n{partial}",
                delegate=name,
                timed_out=True,
            )

        body = clamp(result.combined, self.context.max_output_bytes).text
        return ToolResult(
            text=f"{header}\nexit {result.exit_code} in {result.duration_sec:.0f}s\n\n{body}",
            ok=result.ok,
            meta={"delegate": name, "exit_code": result.exit_code, "argv": argv[:-1]},
        )

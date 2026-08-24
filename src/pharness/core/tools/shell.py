"""Running an arbitrary command.

The tool itself is small, and that is the point: by the time it is called the
command has already been parsed, classified and either allowed or approved
(PRD 10.3-10.7). What is left here is running it without adding a shell of our
own -- the platform's shell is invoked deliberately, with the command as a
single argument, so the parse the policy engine did is the parse that happens.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from dataclasses import dataclass

from pharness.core.config import ContextSettings
from pharness.core.text import clamp
from pharness.core.tools.results import ToolResult
from pharness.core.workspace import Workspace
from pharness.ports import ProcessPort

DEFAULT_TIMEOUT = 120.0


@dataclass
class ShellTools:
    workspace: Workspace
    process: ProcessPort
    context: ContextSettings
    env: Mapping[str, str]
    platform: str = "posix"

    def _argv(self, command: str) -> list[str]:
        if self.platform == "windows":
            executable = shutil.which("powershell", path=self.env.get("PATH")) or "powershell.exe"
            return [executable, "-NoProfile", "-NonInteractive", "-Command", command]
        executable = shutil.which("bash", path=self.env.get("PATH")) or "/bin/sh"
        return [executable, "-c", command]

    def exec(self, command: str, timeout_sec: float = DEFAULT_TIMEOUT) -> ToolResult:
        if not command.strip():
            return ToolResult.failure("no command given")

        argv = self._argv(command)
        result = self.process.run(argv, self.workspace.root, self.env, timeout_sec=timeout_sec)

        if result.timed_out:
            partial = clamp(result.combined, self.context.max_output_bytes // 2).text
            return ToolResult.failure(
                f"$ {command}\ntimed out after {timeout_sec:.0f}s\n\n{partial}",
                timed_out=True,
            )

        body = clamp(result.combined, self.context.max_output_bytes).text
        return ToolResult(
            text=f"$ {command}\nexit {result.exit_code} in {result.duration_sec:.1f}s\n\n{body}",
            ok=result.ok,
            meta={"exit_code": result.exit_code, "duration_sec": result.duration_sec},
        )

"""Watching and stopping the processes we started.

A dev server left running after a conversation ends is a port still bound and a
laptop fan still spinning, so everything spawned stays listed until it is
stopped -- including the ones that exited on their own, since "why did it stop"
is the question that follows.
"""

from __future__ import annotations

from dataclasses import dataclass

from pharness.core.config import ContextSettings
from pharness.core.text import clamp
from pharness.core.tools.results import ToolResult
from pharness.ports import ProcessPort


@dataclass
class ProcessTools:
    process: ProcessPort
    context: ContextSettings

    def list(self) -> ToolResult:
        handles = getattr(self.process, "list_all", self.process.list_running)()
        if not handles:
            return ToolResult(text="nothing is running", meta={"count": 0})

        lines = []
        for handle in handles:
            state = "running" if handle.is_running() else f"exited {handle.exit_code()}"
            uptime = getattr(handle, "uptime_sec", lambda: 0.0)()
            lines.append(
                f"{handle.id}  pid {handle.pid}  {state}  {uptime:.0f}s  {' '.join(handle.argv)}"
            )
        return ToolResult(text="\n".join(lines), meta={"count": len(handles)})

    def logs(self, process_id: str, lines: int = 50) -> ToolResult:
        handle = self.process.get(process_id)
        if handle is None:
            return ToolResult.failure(f"no process {process_id!r}")

        lines = max(1, min(lines, 500))
        body = handle.tail(lines) or "(no output yet)"
        excerpt = clamp(body, self.context.max_output_bytes)
        state = "running" if handle.is_running() else f"exited {handle.exit_code()}"
        return ToolResult(
            text=f"{process_id} ({state}), last {lines} lines:\n{excerpt.text}",
            meta={"process_id": process_id, "running": handle.is_running()},
        )

    def stop(self, process_id: str) -> ToolResult:
        handle = self.process.get(process_id)
        if handle is None:
            return ToolResult.failure(f"no process {process_id!r}")
        if not handle.is_running():
            return ToolResult(text=f"{process_id} had already exited {handle.exit_code()}")

        code = handle.stop()
        return ToolResult(
            text=f"stopped {process_id} (pid {handle.pid}), exit {code}",
            meta={"process_id": process_id, "exit_code": code},
        )

    def stop_all(self) -> ToolResult:
        stopped = self.process.stop_all()
        return ToolResult(text=f"stopped {stopped} process(es)", meta={"stopped": stopped})

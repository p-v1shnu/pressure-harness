"""Registering tools with an MCP server.

Two things shape every handler here.

Each tool is one MCP tool with an `op` argument rather than a family of small
ones, because every tool's schema is sent with every message in the
conversation: sixty tools is a standing tax on the quota this project exists to
protect (PRD 8.1).

And no handler runs anything itself. Each one resolves a workspace, describes
what it wants, and hands a callable to the gateway, which decides, asks, runs
and records. A handler that called a tool directly would be a hole straight
through the policy engine.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations

from pharness.core.errors import PharnessError
from pharness.core.policy.engine import Request
from pharness.core.policy.tiers import Tier
from pharness.core.tools.results import ToolResult
from pharness.core.workspace import Workspace
from pharness.runtime import Runtime

INSTRUCTIONS = """\
Tools for working on code on the user's own machine.

Paths are always relative to a workspace: call workspace(op="list") to see what
is authorised, and workspace(op="use", alias=...) to choose one. Only the owner
can authorise a new directory, from the console on that machine.

Some actions are refused outright and some prompt the owner. A refusal is
final -- do not retry it a different way. If a command is refused, say what you
were trying to do and let the owner decide.

Output is deliberately trimmed. Read a range of a file rather than all of it,
and ask for one file's diff rather than the whole change.
"""


def _session_id(ctx: Context) -> str:
    """One id per conversation, so approvals and workspace choice do not leak.

    Falls back to a constant for stdio, where the transport is the conversation
    (PRD 9.3).
    """
    try:
        headers = dict(ctx.headers or {})
    except Exception:
        headers = {}
    for key in ("mcp-session-id", "Mcp-Session-Id"):
        if headers.get(key):
            return str(headers[key])
    return "local"


def reported(fn):
    """Turn our own errors into an answer rather than a tool crash.

    "No workspace is selected, choose one of these" is information the model can
    act on; a stack trace is not. Anything unexpected still raises, because a
    bug should be loud.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except PharnessError as exc:
            return str(exc)

    return wrapper


def build_server(
    runtime: Runtime,
    name: str = "pressure-harness",
    auth_provider: Any = None,
    auth_settings: Any = None,
) -> MCPServer:
    server = MCPServer(
        name=name,
        version="0.1.0",
        instructions=INSTRUCTIONS,
        auth_server_provider=auth_provider,
        auth=auth_settings,
    )
    if auth_provider is not None:
        from pharness.mcp.auth import register_consent_page

        register_consent_page(server, auth_provider)
    capabilities = runtime.adapters.capabilities

    def resolve(ctx: Context, workspace: str | None) -> Workspace:
        return runtime.sessions.resolve(_session_id(ctx), workspace)

    def guarded(
        ctx: Context,
        tool: str,
        op: str | None,
        tier: Tier,
        payload: dict[str, Any],
        workspace: Workspace,
        run: Callable[[], ToolResult],
        command_line: str | None = None,
    ) -> str:
        request = Request(
            session_id=_session_id(ctx),
            tool=tool,
            op=op,
            declared_tier=tier,
            payload=payload,
            command_line=command_line,
        )
        result = runtime.gateway.call(request, workspace, run)
        return result.text

    # -- workspace ---------------------------------------------------------

    @server.tool(
        name="workspace",
        description=(
            "List the directories the owner has authorised, choose one for this "
            "conversation, or describe the current one. You cannot add a workspace."
        ),
        annotations=ToolAnnotations(title="Workspaces", readOnlyHint=True, openWorldHint=False),
    )
    @reported
    def workspace_tool(ctx: Context, op: str = "list", alias: str | None = None) -> str:
        if op == "list":
            if not len(runtime.registry):
                return (
                    "No workspaces are authorised. The owner adds one from the console "
                    "on that machine; you cannot."
                )
            lines = []
            for entry in runtime.registry.all():
                mode = entry.effective_mode(runtime.gateway.clock())
                lines.append(f"{entry.alias:16} {entry.root}  ({mode.value})")
            return "\n".join(lines)

        if op == "use":
            if not alias:
                return "name the workspace to use"
            chosen = runtime.sessions.use(_session_id(ctx), alias)
            return f"now working in {chosen.alias} ({chosen.root})"

        if op == "info":
            chosen = resolve(ctx, alias)
            mode = chosen.effective_mode(runtime.gateway.clock())
            git = runtime.git(chosen)
            branch = git.current_branch() if git.is_repository() else "not a git repository"
            return (
                f"{chosen.alias}\npath: {chosen.root}\nmode: {mode.value}\nbranch: {branch}\n"
                f"push allowed: {chosen.config.git_push}"
            )

        return f"unknown op {op!r}; expected list, use or info"

    # -- reading -----------------------------------------------------------

    @server.tool(
        name="read_file",
        description=(
            "Read a text file from a workspace. Large files return an outline instead; "
            "pass offset and limit to read a range."
        ),
        annotations=ToolAnnotations(title="Read file", readOnlyHint=True, openWorldHint=False),
    )
    @reported
    def read_file_tool(
        ctx: Context,
        path: str,
        offset: int = 0,
        limit: int | None = None,
        workspace: str | None = None,
    ) -> str:
        chosen = resolve(ctx, workspace)
        return guarded(
            ctx,
            "read_file",
            None,
            Tier.READ,
            {"path": path, "offset": offset, "limit": limit},
            chosen,
            lambda: runtime.files(chosen).read(path, offset, limit),
        )

    @server.tool(
        name="search",
        description=(
            "Search a workspace. op='text' matches a regular expression and returns "
            "path:line results; op='files' lists paths matching a glob."
        ),
        annotations=ToolAnnotations(title="Search", readOnlyHint=True, openWorldHint=False),
    )
    @reported
    def search_tool(
        ctx: Context,
        op: str = "text",
        pattern: str = "",
        glob: str | None = None,
        case_sensitive: bool = False,
        max_hits: int | None = None,
        workspace: str | None = None,
    ) -> str:
        chosen = resolve(ctx, workspace)
        tools = runtime.search(chosen)

        if op == "files":
            return guarded(
                ctx,
                "search",
                "files",
                Tier.READ,
                {"glob": glob or "*"},
                chosen,
                lambda: tools.files(glob or "*"),
            )
        if not pattern:
            return "give a pattern to search for"
        return guarded(
            ctx,
            "search",
            "text",
            Tier.READ,
            {"pattern": pattern, "glob": glob},
            chosen,
            lambda: tools.text(pattern, glob, case_sensitive, max_hits),
        )

    # -- writing -----------------------------------------------------------

    @server.tool(
        name="write_file",
        description=(
            "Create a file, or replace one with create_only=false. Prefer apply_patch "
            "for edits to a file that already exists."
        ),
        annotations=ToolAnnotations(
            title="Write file", readOnlyHint=False, destructiveHint=False, openWorldHint=False
        ),
    )
    @reported
    def write_file_tool(
        ctx: Context,
        path: str,
        content: str,
        create_only: bool = True,
        expected_sha: str | None = None,
        workspace: str | None = None,
    ) -> str:
        chosen = resolve(ctx, workspace)
        return guarded(
            ctx,
            "write_file",
            None,
            Tier.WRITE,
            {"path": path, "create_only": create_only, "content": content},
            chosen,
            lambda: runtime.files(chosen).write(path, content, create_only, expected_sha),
        )

    @server.tool(
        name="apply_patch",
        description=(
            "Apply a unified diff across one or more files. All or nothing: if any hunk "
            "does not fit, nothing is written. Use dry_run to check first."
        ),
        annotations=ToolAnnotations(
            title="Apply patch", readOnlyHint=False, destructiveHint=False, openWorldHint=False
        ),
    )
    @reported
    def apply_patch_tool(
        ctx: Context, diff: str, dry_run: bool = False, workspace: str | None = None
    ) -> str:
        chosen = resolve(ctx, workspace)
        tier = Tier.READ if dry_run else Tier.WRITE
        return guarded(
            ctx,
            "apply_patch",
            None,
            tier,
            {"diff": diff, "dry_run": dry_run},
            chosen,
            lambda: runtime.files(chosen).apply_patch(diff, dry_run),
        )

    # -- git ----------------------------------------------------------------

    @server.tool(
        name="git",
        description=(
            "Git operations: status, diff, log, show, branches, add, commit, stash, undo. "
            "diff without a path returns a summary. undo restores the files a checkpoint "
            "changed and is itself undoable."
        ),
        annotations=ToolAnnotations(title="Git", readOnlyHint=False, openWorldHint=False),
    )
    @reported
    def git_tool(
        ctx: Context,
        op: str = "status",
        path: str | None = None,
        paths: list[str] | None = None,
        message: str = "",
        ref: str = "HEAD",
        limit: int = 20,
        staged: bool = False,
        checkpoint: str | None = None,
        workspace: str | None = None,
    ) -> str:
        chosen = resolve(ctx, workspace)
        git = runtime.git(chosen)

        readers: dict[str, tuple[Tier, Callable[[], ToolResult]]] = {
            "status": (Tier.READ, git.status),
            "diff": (Tier.READ, lambda: git.diff(path, staged)),
            "log": (Tier.READ, lambda: git.log(limit)),
            "show": (Tier.READ, lambda: git.show(ref)),
            "branches": (Tier.READ, git.branches),
            "add": (Tier.WRITE, lambda: git.add(paths or ([path] if path else []))),
            "commit": (Tier.WRITE, lambda: git.commit(message)),
            "stash": (Tier.WRITE, lambda: git.stash(message)),
        }

        if op == "undo":
            journal = runtime.journal(chosen)

            def undo() -> ToolResult:
                result = journal.undo(checkpoint)
                return ToolResult(f"{result.summary}\nReverse this with git undo {result.id}")

            return guarded(ctx, "git", "undo", Tier.WRITE, {"checkpoint": checkpoint}, chosen, undo)

        if op == "checkpoints":
            entries = runtime.journal(chosen).list()
            text = "\n".join(c.summary for c in entries[-20:]) or "no checkpoints yet"
            return guarded(
                ctx, "git", "checkpoints", Tier.READ, {}, chosen, lambda: ToolResult(text)
            )

        if op not in readers:
            return f"unknown op {op!r}; expected one of {', '.join(sorted(readers))}, undo"

        tier, run = readers[op]
        return guarded(
            ctx,
            "git",
            op,
            tier,
            {"op": op, "path": path, "paths": paths, "message": message, "ref": ref},
            chosen,
            run,
        )

    # -- running -------------------------------------------------------------

    @server.tool(
        name="project",
        description=(
            "Run the project's own commands: test, lint, typecheck, build, install, or "
            "start the dev server. op='describe' shows what each one resolves to."
        ),
        annotations=ToolAnnotations(title="Project tasks", readOnlyHint=False, openWorldHint=False),
    )
    @reported
    def project_tool(ctx: Context, op: str = "describe", workspace: str | None = None) -> str:
        chosen = resolve(ctx, workspace)
        tools = runtime.project(chosen)

        if op == "describe":
            return guarded(ctx, "project", op, Tier.READ, {}, chosen, tools.describe)
        if op == "dev":
            return guarded(
                ctx, "project", "dev", Tier.EXEC_ALLOWED, {"task": "dev"}, chosen, tools.start_dev
            )

        resolved = tools.resolve(op)
        if resolved is None:
            return f"no {op} command is defined for {chosen.alias}"

        # What gets classified is what will actually run, not the task name.
        # For a package.json script that means the script's own text, because
        # the repository -- not the user -- decides what `npm test` does.
        argv, _ = resolved
        command_line = tools.script_body(op) or " ".join(argv)
        return guarded(
            ctx,
            "project",
            op,
            Tier.EXEC_ALLOWED,
            {"task": op, "command": command_line},
            chosen,
            lambda: tools.run(op),
            command_line=command_line,
        )

    if "shell" in capabilities:

        @server.tool(
            name="shell",
            description=(
                "Run a shell command in a workspace. Commands outside the workspace's "
                "allowlist need the owner's approval, and some are refused outright."
            ),
            annotations=ToolAnnotations(
                title="Shell", readOnlyHint=False, destructiveHint=True, openWorldHint=True
            ),
        )
        @reported
        def shell_tool(
            ctx: Context,
            command: str,
            timeout_sec: float = 120.0,
            workspace: str | None = None,
        ) -> str:
            chosen = resolve(ctx, workspace)
            return guarded(
                ctx,
                "shell",
                None,
                Tier.EXEC_OTHER,
                {"command": command},
                chosen,
                lambda: runtime.shell(chosen).exec(command, timeout_sec),
                command_line=command,
            )

    @server.tool(
        name="process",
        description="List, read the output of, or stop the processes started here.",
        annotations=ToolAnnotations(title="Processes", readOnlyHint=False, openWorldHint=False),
    )
    @reported
    def process_tool(
        ctx: Context,
        op: str = "list",
        process_id: str = "",
        lines: int = 50,
        workspace: str | None = None,
    ) -> str:
        chosen = resolve(ctx, workspace)
        tools = runtime.processes()

        actions: dict[str, tuple[Tier, Callable[[], ToolResult]]] = {
            "list": (Tier.READ, tools.list),
            "logs": (Tier.READ, lambda: tools.logs(process_id, lines)),
            "stop": (Tier.WRITE, lambda: tools.stop(process_id)),
            "stop_all": (Tier.WRITE, tools.stop_all),
        }
        if op not in actions:
            return f"unknown op {op!r}; expected one of {', '.join(actions)}"

        tier, run = actions[op]
        return guarded(ctx, "process", op, tier, {"op": op, "process_id": process_id}, chosen, run)

    if "browser" in capabilities:

        @server.tool(
            name="browser",
            description=(
                "Drive a browser to check your own work. ops: launch, navigate, snapshot, "
                "click, type, eval, console, network, screenshot. The console is usually "
                "where the answer is; the screenshot only confirms it."
            ),
            annotations=ToolAnnotations(
                title="Browser", readOnlyHint=False, destructiveHint=False, openWorldHint=True
            ),
        )
        @reported
        def browser_tool(
            ctx: Context,
            op: str = "snapshot",
            url: str = "",
            selector: str = "",
            text: str = "",
            expression: str = "",
            name: str = "screenshot.png",
            headless: bool = False,
            limit: int = 30,
            workspace: str | None = None,
        ) -> str:
            chosen = resolve(ctx, workspace)
            browser = runtime.browser(chosen)

            # eval runs arbitrary code in the page, so it is never automatic --
            # it is the browser's version of an interpreter (PRD 8.3).
            actions: dict[str, tuple[Tier, Callable[[], ToolResult]]] = {
                "launch": (Tier.EXEC_ALLOWED, lambda: browser.launch(headless)),
                "navigate": (Tier.EXEC_ALLOWED, lambda: browser.navigate(url)),
                "snapshot": (Tier.READ, lambda: browser.snapshot(selector or "body")),
                "click": (Tier.EXEC_ALLOWED, lambda: browser.click(selector)),
                "type": (Tier.EXEC_ALLOWED, lambda: browser.type_text(selector, text)),
                "eval": (Tier.EXEC_OTHER, lambda: browser.evaluate(expression)),
                "console": (Tier.READ, lambda: browser.console(limit)),
                "network": (Tier.READ, lambda: browser.network(limit)),
                "screenshot": (Tier.READ, lambda: browser.screenshot(name)),
            }
            if op not in actions:
                return f"unknown op {op!r}; expected one of {', '.join(actions)}"

            tier, run = actions[op]
            return guarded(
                ctx,
                "browser",
                op,
                tier,
                {"op": op, "url": url, "selector": selector, "expression": expression},
                chosen,
                run,
            )

    if "web_fetch" in capabilities:

        @server.tool(
            name="web_fetch",
            description=(
                "Fetch a URL from this machine. Only hosts the owner allowlisted, and "
                "never addresses inside the local network. Use the browser for localhost."
            ),
            annotations=ToolAnnotations(title="Fetch a URL", readOnlyHint=True, openWorldHint=True),
        )
        @reported
        def web_fetch_tool(ctx: Context, url: str, workspace: str | None = None) -> str:
            chosen = resolve(ctx, workspace)
            return guarded(
                ctx,
                "web_fetch",
                None,
                Tier.EGRESS,
                {"url": url},
                chosen,
                lambda: runtime.web().fetch(url),
            )

    # -- meta ----------------------------------------------------------------

    @server.tool(
        name="notify",
        description="Show the owner a desktop notification. Use it when you need attention.",
        annotations=ToolAnnotations(title="Notify", readOnlyHint=True, openWorldHint=False),
    )
    @reported
    def notify_tool(ctx: Context, title: str, body: str = "") -> str:
        # Labelled as coming from the assistant. An unlabelled notification is a
        # convincing way to ask someone for a pairing code, and the model's text
        # must never be mistakable for the software's own.
        runtime.queue.notifier.notify(f"From the assistant: {title[:100]}", body[:500])
        return "notification sent"

    @server.tool(
        name="system",
        description="Report what this machine and this installation can do.",
        annotations=ToolAnnotations(title="System", readOnlyHint=True, openWorldHint=False),
    )
    @reported
    def system_tool(ctx: Context, op: str = "info") -> str:
        lines = [
            f"platform: {runtime.adapters.platform}"
            + ("" if runtime.adapters.supported else " (not a supported target)"),
            f"capabilities: {', '.join(sorted(capabilities)) or 'none'}",
            f"workspaces: {', '.join(runtime.registry.aliases()) or 'none authorised'}",
            f"approval prompts: {runtime.queue.notifier.name}",
            f"audit log: {runtime.audit.verify().summary}",
        ]
        for warning in runtime.registry.warnings():
            lines.append(f"warning: {warning}")
        return "\n".join(lines)

    return server


def safe_error(exc: Exception) -> str:
    """Turn an internal error into something safe to show the model."""
    if isinstance(exc, PharnessError):
        return str(exc)
    return f"{type(exc).__name__}: the tool failed"

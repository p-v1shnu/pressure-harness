"""The MCP surface, driven the way a client drives it.

These run the server as a real subprocess over stdio rather than calling the
handlers directly. The handlers are the least interesting part; what matters is
that the wiring in between -- schema generation, workspace resolution, the
gateway -- holds when something outside the process is asking.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters, stdio_client

SERVER_SOURCE = """
import pathlib
from pharness.mcp import build_server
from pharness.runtime import build_runtime
runtime = build_runtime(pathlib.Path({config!r}), interactive_prompts=False)
build_server(runtime).run(transport='stdio')
"""

Call = tuple[str, dict]


def drive(config: Path, calls: Sequence[Call]) -> tuple[list, list[str]]:
    """Start the server, make every call in one session, return tools and answers."""

    async def session() -> tuple[list, list[str]]:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-c", SERVER_SOURCE.format(config=str(config))],
            # A real client inherits the environment, and some capabilities are
            # decided by what is on PATH.
            env=dict(os.environ),
        )
        async with (
            stdio_client(params) as (reader, writer),
            ClientSession(reader, writer) as client,
        ):
            await client.initialize()
            tools = (await client.list_tools()).tools

            answers: list[str] = []
            for name, arguments in calls:
                result = await client.call_tool(name, arguments)
                answers.append(
                    "\n".join(
                        block.text
                        for block in result.content
                        if getattr(block, "type", None) == "text"
                    )
                )
            return tools, answers

    return asyncio.run(session())


@pytest.fixture
def config(tmp_path: Path) -> Path:
    project = tmp_path / "proj" / "src"
    project.mkdir(parents=True)
    (project / "app.js").write_text("console.log('hello')\n", encoding="utf-8")
    (tmp_path / "proj" / ".env").write_text("API_SECRET=leak-me-123456\n", encoding="utf-8")

    path = tmp_path / "config.toml"
    path.write_text(
        "[[workspace]]\n"
        'alias = "demo"\n'
        f'path = "{(tmp_path / "proj").as_posix()}"\n'
        'allow_commands = ["echo allowed"]\n',
        encoding="utf-8",
    )
    return path


def test_the_catalogue_is_small_enough_to_afford(config: Path):
    """Every tool's schema rides along with every message (PRD 8.1)."""
    tools, _ = drive(config, [])
    names = {tool.name for tool in tools}

    assert {"workspace", "read_file", "search", "apply_patch", "git", "shell"} <= names
    assert len(tools) <= 16

    weight = sum(len(json.dumps(tool.input_schema)) + len(tool.description or "") for tool in tools)
    assert weight < 12000, f"the catalogue costs {weight} characters per message"


def test_annotations_describe_each_tool_honestly(config: Path):
    """Mislabelling a write as read-only would defeat our own prompts (PRD 4)."""
    tools, _ = drive(config, [])
    by_name = {tool.name: tool for tool in tools}

    assert by_name["read_file"].annotations.read_only_hint is True
    assert by_name["search"].annotations.read_only_hint is True
    assert by_name["write_file"].annotations.read_only_hint is False
    assert by_name["apply_patch"].annotations.read_only_hint is False
    assert by_name["shell"].annotations.destructive_hint is True


def test_reading_and_editing_a_file(config: Path):
    patch = (
        "--- a/src/app.js\n+++ b/src/app.js\n@@ -1 +1 @@\n"
        "-console.log('hello')\n+console.log('hello world')\n"
    )
    _, answers = drive(
        config,
        [
            ("workspace", {"op": "use", "alias": "demo"}),
            ("read_file", {"path": "src/app.js"}),
            ("apply_patch", {"diff": patch}),
            ("read_file", {"path": "src/app.js"}),
        ],
    )
    assert "hello" in answers[1]
    assert "Checkpoint" in answers[2]
    assert "hello world" in answers[3]


def test_an_edit_can_be_undone_through_the_tools(config: Path):
    patch = (
        "--- a/src/app.js\n+++ b/src/app.js\n@@ -1 +1 @@\n"
        "-console.log('hello')\n+console.log('changed')\n"
    )
    _, answers = drive(
        config,
        [
            ("apply_patch", {"diff": patch}),
            ("git", {"op": "undo"}),
            ("read_file", {"path": "src/app.js"}),
        ],
    )
    assert "undo of" in answers[1]
    assert "console.log('hello')" in answers[2]


def test_the_jail_holds_through_the_tool_layer(config: Path):
    _, answers = drive(
        config,
        [
            ("read_file", {"path": "../../etc/passwd"}),
            ("read_file", {"path": ".env"}),
            ("search", {"op": "text", "pattern": "leak-me"}),
        ],
    )
    assert "outside workspace" in answers[0]
    assert "secrets" in answers[1]
    assert "leak-me-123456" not in answers[2]


def test_the_policy_engine_is_in_the_path(config: Path):
    """Allowlisted runs, unlisted needs approval, forbidden is refused outright."""
    _, answers = drive(
        config,
        [
            ("shell", {"command": "echo allowed"}),
            ("shell", {"command": "echo not-allowlisted"}),
            ("shell", {"command": "rm -rf /"}),
        ],
    )
    assert "allowed" in answers[0]
    assert "no interactive prompt" in answers[1]  # nothing can approve it here
    assert "deletes or destroys data" in answers[2]


def test_a_missing_workspace_is_explained_not_crashed(tmp_path: Path):
    empty = tmp_path / "config.toml"
    empty.write_text("", encoding="utf-8")

    _, answers = drive(empty, [("workspace", {"op": "list"}), ("read_file", {"path": "x"})])
    assert "No workspaces are authorised" in answers[0]
    assert "no workspaces are registered" in answers[1].lower()


def test_system_reports_what_is_really_available(config: Path):
    """The capability line is a statement of fact, not a wish list (PRD 14.3)."""
    from pharness.adapters import select

    _, answers = drive(config, [("system", {})])
    report = answers[0]

    assert "capabilities:" in report
    assert "chain intact" in report

    has_browser = select().browser.find_executable() is not None
    assert ("browser" in report) is has_browser


# -- built in-process, so the registration code itself is exercised -------------


def build_in_process(config: Path, capabilities: frozenset[str] | None = None):
    from dataclasses import replace

    from pharness.adapters import select
    from pharness.mcp import build_server
    from pharness.runtime import build_runtime

    adapters = select()
    if capabilities is not None:
        adapters = replace(adapters, capabilities=capabilities)

    runtime = build_runtime(config, interactive_prompts=False, adapters=adapters)
    return runtime, build_server(runtime)


def test_the_tool_list_is_built_from_what_the_platform_can_do(config: Path):
    """A platform never advertises a tool it cannot perform (PRD 14.3).

    Advertising one costs quota and credibility on every attempt that fails.
    """
    _, full = build_in_process(config)
    _, without_shell = build_in_process(config, capabilities=frozenset({"files", "git"}))

    assert "shell" in {tool.name for tool in asyncio.run(full.list_tools())}
    assert "shell" not in {tool.name for tool in asyncio.run(without_shell.list_tools())}


def test_the_runtime_wires_one_gateway_for_everything(config: Path):
    runtime, _ = build_in_process(config)
    assert runtime.gateway.engine is runtime.engine
    assert runtime.gateway.queue is runtime.queue
    assert runtime.gateway.audit is runtime.audit


def test_emergency_stop_records_itself(config: Path):
    runtime, _ = build_in_process(config)
    runtime.emergency_stop()

    last = runtime.audit.read()[-1]["event"]
    assert last["disposition"] == "emergency_stop"
    assert runtime.audit.verify().intact

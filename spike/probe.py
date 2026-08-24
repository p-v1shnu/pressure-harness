"""Local self-test for the M0 spike server.

Run this BEFORE wiring anything into ChatGPT. It speaks MCP over stdio to
m0_spike.py and exercises every tool, so a failure here is our bug and a
failure in ChatGPT afterwards is a platform finding. That separation is the
whole point of M0.

    python probe.py
    python probe.py --extra-tools 40      # check the padding tools register
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import shutil
import sys

from mcp import ClientSession, StdioServerParameters, stdio_client

HERE = pathlib.Path(__file__).resolve().parent
FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{f' -- {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def text_of(result) -> str:
    parts = [c.text for c in result.content if getattr(c, "type", None) == "text"]
    return "\n".join(parts)


async def run(extra_tools: int) -> None:
    # Start from a clean scratch dir so CREATED vs UPDATED is meaningful.
    shutil.rmtree(HERE / "spike-sandbox" / "probe", ignore_errors=True)

    args = [str(HERE / "m0_spike.py"), "stdio"]
    if extra_tools:
        args += ["--extra-tools", str(extra_tools)]

    async with stdio_client(StdioServerParameters(command=sys.executable, args=args)) as (r, w):
        async with ClientSession(r, w) as session:
            init = await session.initialize()
            print(f"\nserver: {init.server_info.name} {init.server_info.version}")
            print(f"protocol: {init.protocol_version}\n")

            listed = await session.list_tools()
            names = [t.name for t in listed.tools]
            print(f"tools ({len(names)}): {', '.join(names[:8])}"
                  f"{' ...' if len(names) > 8 else ''}\n")

            expected = {
                "spike_read_file", "spike_write_file", "spike_overwrite_file",
                "spike_return_image", "spike_echo", "spike_whoami",
            }
            check("all core tools advertised", expected <= set(names),
                  f"missing {sorted(expected - set(names))}" if not expected <= set(names) else "")

            read_tool = next(t for t in listed.tools if t.name == "spike_read_file")
            write_tool = next(t for t in listed.tools if t.name == "spike_write_file")
            over_tool = next(t for t in listed.tools if t.name == "spike_overwrite_file")
            check("read tool annotated readOnlyHint=True",
                  bool(read_tool.annotations and read_tool.annotations.read_only_hint))
            check("write tool annotated readOnlyHint=False",
                  bool(write_tool.annotations) and write_tool.annotations.read_only_hint is False)
            check("overwrite tool annotated destructiveHint=True",
                  bool(over_tool.annotations and over_tool.annotations.destructive_hint))

            got = await session.call_tool("spike_read_file", {"path": "hello.txt"})
            check("read seeded file", "hello from the spike sandbox" in text_of(got))

            got = await session.call_tool(
                "spike_write_file", {"path": "probe/out.txt", "content": "written by probe\n"}
            )
            check("write creates a file", text_of(got).startswith("CREATED"), text_of(got))

            got = await session.call_tool(
                "spike_write_file", {"path": "probe/out.txt", "content": "second write\n"}
            )
            check("write updates a file", text_of(got).startswith("UPDATED"), text_of(got))

            got = await session.call_tool(
                "spike_overwrite_file", {"path": "probe/out.txt", "content": "third\n"}
            )
            check("overwrite existing file", text_of(got).startswith("OVERWROTE"), text_of(got))

            got = await session.call_tool(
                "spike_overwrite_file", {"path": "probe/missing.txt", "content": "x"}
            )
            check("overwrite refuses missing file", "NOT_FOUND" in text_of(got), text_of(got))

            # Path jail. Each of these must be refused.
            for bad in ("../escaped.txt", "probe/../../escaped.txt", "/etc/passwd", "C:\\Windows\\x"):
                got = await session.call_tool("spike_write_file", {"path": bad, "content": "x"})
                refused = bool(got.is_error) or "escape" in text_of(got) or "reject" in text_of(got)
                check(f"path jail refuses {bad!r}", refused, text_of(got)[:80])

            got = await session.call_tool("spike_return_image", {})
            images = [c for c in got.content if getattr(c, "type", None) == "image"]
            check("image tool returns image content", len(images) == 1)
            if images:
                check("image is a PNG", images[0].mime_type == "image/png", images[0].mime_type)

            got = await session.call_tool("spike_echo", {"kilobytes": 4})
            size = len(text_of(got))
            check("echo returns ~4 KB", 3500 < size < 5200, f"{size} bytes")

            got = await session.call_tool("spike_whoami", {})
            check("whoami reports the session", "protocol_version" in text_of(got))

            if extra_tools:
                pads = [n for n in names if n.startswith("spike_pad_")]
                check(f"{extra_tools} padding tools registered", len(pads) == extra_tools,
                      f"got {len(pads)}")
                got = await session.call_tool("spike_pad_000", {"target": "x"})
                check("padding tool is callable", "spike_pad_000" in text_of(got))


def main() -> int:
    parser = argparse.ArgumentParser(description="self-test the M0 spike")
    parser.add_argument("--extra-tools", type=int, default=0)
    args = parser.parse_args()

    asyncio.run(run(args.extra_tools))
    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {', '.join(FAILURES)}")
        return 1
    print("all checks passed -- the spike is ready to point at ChatGPT")
    return 0


if __name__ == "__main__":
    sys.exit(main())

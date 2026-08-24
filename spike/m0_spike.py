"""M0 spike server for Pressure Harness.

Purpose: answer the open questions in docs/PRD.md section 20 (OQ-1..OQ-4)
BEFORE building the real 14-tool catalog. This is throwaway diagnostic code,
not a foundation -- it deliberately skips the policy engine, audit log,
approval queue and OAuth described in the PRD.

Every file tool is confined to a sandbox directory so running this spike
cannot damage anything outside it.

    python m0_spike.py stdio                 # for ChatGPT desktop / Codex CLI
    python m0_spike.py http                  # for ChatGPT web (needs a tunnel)
    python m0_spike.py http --extra-tools 40 # probe the connector tool cap
"""

from __future__ import annotations

import argparse
import os
import pathlib
import secrets
import struct
import sys
import time
import zlib

from mcp.server import MCPServer
from mcp.server.mcpserver import Context, Image
from mcp.types import ToolAnnotations

HERE = pathlib.Path(__file__).resolve().parent
SANDBOX = (HERE / "spike-sandbox").resolve()
TOKEN_FILE = HERE / ".spike-token"

MAX_READ_BYTES = 64 * 1024
MAX_WRITE_BYTES = 256 * 1024

server = MCPServer(
    name="pressure-harness-m0-spike",
    version="0.0.1",
    instructions=(
        "Diagnostic spike for Pressure Harness. All file paths are relative to a "
        "sandbox directory; absolute paths and paths escaping the sandbox are rejected."
    ),
)


# ---------------------------------------------------------------- logging


def log(msg: str) -> None:
    """Log to stderr. stdout is reserved for the stdio transport."""
    print(f"{time.strftime('%H:%M:%S')} [spike] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- sandbox


def sandbox_path(rel: str) -> pathlib.Path:
    """Resolve `rel` inside SANDBOX, or raise.

    A miniature preview of the real path jail (PRD section 10.3). Resolution
    happens before the containment check so symlinks and Windows junctions
    cannot be used to escape.
    """
    if not rel or rel.strip() != rel:
        raise ValueError("path must be a non-empty relative path")
    candidate = pathlib.PurePath(rel)
    if candidate.is_absolute() or (len(rel) > 1 and rel[1] == ":"):
        raise ValueError("absolute paths are rejected; use a path relative to the sandbox")
    if "\x00" in rel:
        raise ValueError("null byte in path")

    resolved = (SANDBOX / rel).resolve()
    if resolved != SANDBOX and SANDBOX not in resolved.parents:
        raise ValueError(f"path escapes the sandbox: {rel}")
    return resolved


# ---------------------------------------------------------------- tools


@server.tool(
    name="spike_read_file",
    description="Read a UTF-8 text file from the spike sandbox.",
    annotations=ToolAnnotations(title="Read file", readOnlyHint=True, openWorldHint=False),
)
def spike_read_file(path: str) -> str:
    """OQ-1 control: a read tool should work on every ChatGPT surface."""
    target = sandbox_path(path)
    log(f"spike_read_file {path}")
    if not target.is_file():
        return f"NOT_FOUND: {path}"
    data = target.read_bytes()[:MAX_READ_BYTES]
    return data.decode("utf-8", errors="replace")


@server.tool(
    name="spike_write_file",
    description="Create or update a UTF-8 text file in the spike sandbox.",
    annotations=ToolAnnotations(
        title="Write file", readOnlyHint=False, destructiveHint=False, openWorldHint=False
    ),
)
def spike_write_file(path: str, content: str) -> str:
    """OQ-1 test: is a non-destructive write blocked on the mobile app?"""
    target = sandbox_path(path)
    payload = content.encode("utf-8")
    if len(payload) > MAX_WRITE_BYTES:
        raise ValueError(f"content exceeds {MAX_WRITE_BYTES} bytes")
    existed = target.is_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    log(f"spike_write_file {path} ({len(payload)} bytes, existed={existed})")
    return f"{'UPDATED' if existed else 'CREATED'} {path} ({len(payload)} bytes)"


@server.tool(
    name="spike_overwrite_file",
    description=(
        "Overwrite an existing file in the spike sandbox, discarding its previous "
        "contents. Fails if the file does not already exist."
    ),
    annotations=ToolAnnotations(
        title="Overwrite file", readOnlyHint=False, destructiveHint=True, openWorldHint=False
    ),
)
def spike_overwrite_file(path: str, content: str) -> str:
    """OQ-1 test, second arm.

    Identical shape to spike_write_file but genuinely destructive and annotated
    as such. Comparing the two isolates one variable: does a client restriction
    key off destructiveHint specifically, or off any write at all?
    """
    target = sandbox_path(path)
    if not target.is_file():
        return f"NOT_FOUND: {path} (this tool only overwrites existing files)"
    payload = content.encode("utf-8")
    if len(payload) > MAX_WRITE_BYTES:
        raise ValueError(f"content exceeds {MAX_WRITE_BYTES} bytes")
    previous = target.stat().st_size
    target.write_bytes(payload)
    log(f"spike_overwrite_file {path} ({previous} -> {len(payload)} bytes)")
    return f"OVERWROTE {path} ({previous} -> {len(payload)} bytes)"


def _test_png(width: int = 240, height: int = 120) -> bytes:
    """Build a recognisable PNG with no image library.

    Colour bars over a checkerboard strip, so a blank or broken render is
    obvious rather than ambiguous.
    """
    bars = [
        (220, 60, 60), (220, 160, 50), (225, 215, 70),
        (70, 180, 90), (60, 130, 220), (140, 80, 200),
    ]
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # PNG filter type 0 for this scanline
        for x in range(width):
            if y > height * 2 // 3:
                on = ((x // 15) + (y // 15)) % 2 == 0
                rows.extend((240, 240, 240) if on else (25, 25, 25))
            else:
                rows.extend(bars[min(x * len(bars) // width, len(bars) - 1)])

    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">2I5B", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


@server.tool(
    name="spike_return_image",
    description="Return a small generated PNG (colour bars over a checkerboard).",
    annotations=ToolAnnotations(title="Return image", readOnlyHint=True, openWorldHint=False),
)
def spike_return_image() -> Image:
    """OQ-2: does ChatGPT render image content returned by an MCP tool?"""
    log("spike_return_image")
    return Image(data=_test_png(), format="png")


@server.tool(
    name="spike_echo",
    description="Return roughly N kilobytes of filler text. Use to observe truncation.",
    annotations=ToolAnnotations(title="Echo bulk text", readOnlyHint=True, openWorldHint=False),
)
def spike_echo(kilobytes: int = 1) -> str:
    """Supports PRD section 11: how much tool output actually survives the round trip?"""
    kilobytes = max(1, min(int(kilobytes), 256))
    log(f"spike_echo {kilobytes} KB")
    line = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" * 2  # 72 chars
    lines = [f"{i:06d} {line}" for i in range((kilobytes * 1024) // 80 + 1)]
    return "\n".join(lines)


@server.tool(
    name="spike_whoami",
    description="Report what the server sees about the current MCP session.",
    annotations=ToolAnnotations(title="Session info", readOnlyHint=True, openWorldHint=False),
)
def spike_whoami(ctx: Context) -> str:
    """OQ-4 and general recon: protocol version, client identity, request headers."""
    lines: list[str] = [f"protocol_version: {ctx.protocol_version}"]

    client = getattr(getattr(ctx.session, "client_params", None), "client_info", None)
    if client is not None:
        lines.append(f"client: {getattr(client, 'name', '?')} {getattr(client, 'version', '')}")

    try:
        headers = dict(ctx.headers or {})
    except Exception:  # stdio has no HTTP headers
        headers = {}
    if headers:
        sensitive = {"authorization", "cookie", "proxy-authorization", "x-api-key"}
        lines.append("headers:")
        for key in sorted(headers):
            value = "<redacted>" if key.lower() in sensitive else headers[key]
            lines.append(f"  {key}: {value}")
    else:
        lines.append("headers: none (stdio transport)")

    log("spike_whoami")
    return "\n".join(lines)


def register_padding_tools(count: int) -> None:
    """OQ-3: register N extra tools to find the connector's tool/schema ceiling.

    Each carries a realistically sized schema and description so the probe
    measures something comparable to the real catalogue.
    """

    def make(index: int) -> None:
        name = f"spike_pad_{index:03d}"

        @server.tool(
            name=name,
            description=(
                f"Padding tool {index} used to probe the connector tool limit. "
                "It accepts a few typical parameters and returns its own name. "
                "It performs no work and touches nothing on the machine."
            ),
            annotations=ToolAnnotations(title=f"Padding {index}", readOnlyHint=True),
        )
        def pad(target: str = "", mode: str = "default", limit: int = 10, verbose: bool = False) -> str:
            return f"{name}(target={target!r}, mode={mode!r}, limit={limit}, verbose={verbose})"

    for index in range(count):
        make(index)


# ---------------------------------------------------------------- entrypoints


def ensure_sandbox() -> None:
    SANDBOX.mkdir(parents=True, exist_ok=True)
    readme = SANDBOX / "README.txt"
    if not readme.exists():
        readme.write_text(
            "Sandbox for the Pressure Harness M0 spike.\n"
            "Files here are safe to delete. Nothing outside this directory is reachable.\n",
            encoding="utf-8",
        )
    sample = SANDBOX / "hello.txt"
    if not sample.exists():
        sample.write_text("hello from the spike sandbox\nline two\n", encoding="utf-8")


def load_or_create_token() -> str:
    """A secret URL path segment.

    ChatGPT custom connectors offer only OAuth or "no authentication", so the
    spike puts a secret in the path to avoid publishing an open endpoint through
    the tunnel. This is spike-only: PRD section 10.6 requires real OAuth for v1,
    and a URL secret is a stopgap, not an auth system.
    """
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(24)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass
    return token


def build_http_app(token: str, json_response: bool):
    from starlette.middleware.base import BaseHTTPMiddleware

    app = server.streamable_http_app(
        streamable_http_path=f"/{token}/mcp",
        json_response=json_response,
    )

    class RequestLog(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            client = request.client.host if request.client else "?"
            agent = request.headers.get("user-agent", "-")[:80]
            path = request.url.path.replace(token, "<token>")
            log(f"HTTP {request.method} {path} from {client} ua={agent}")
            response = await call_next(request)
            log(f"  -> {response.status_code}")
            return response

    app.add_middleware(RequestLog)
    return app


def main() -> int:
    parser = argparse.ArgumentParser(description="Pressure Harness M0 spike")
    parser.add_argument("transport", choices=["stdio", "http"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument(
        "--extra-tools", type=int, default=int(os.environ.get("SPIKE_EXTRA_TOOLS", "0")),
        help="register N padding tools to probe the connector tool limit (OQ-3)",
    )
    parser.add_argument(
        "--json-response", action="store_true",
        help="reply with application/json instead of an SSE stream",
    )
    args = parser.parse_args()

    ensure_sandbox()
    if args.extra_tools > 0:
        register_padding_tools(args.extra_tools)
        log(f"registered {args.extra_tools} padding tools (OQ-3 probe)")

    log(f"sandbox: {SANDBOX}")

    if args.transport == "stdio":
        log("transport: stdio -- point ChatGPT desktop / Codex CLI at this command")
        server.run(transport="stdio")
        return 0

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        log(f"REFUSING to bind {args.host}: bind loopback only and expose it through a tunnel")
        return 2

    token = load_or_create_token()
    url = f"http://{args.host}:{args.port}/{token}/mcp"
    log("transport: streamable http")
    log(f"local MCP URL: {url}")
    log("expose it with:  cloudflared tunnel --url http://127.0.0.1:%d" % args.port)
    log("then register  https://<tunnel-host>/%s/mcp  in ChatGPT" % token)

    import uvicorn

    uvicorn.run(
        build_http_app(token, args.json_response),
        host=args.host,
        port=args.port,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

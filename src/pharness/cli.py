"""The `ph` command line.

Small on purpose. Its jobs are the ones that must never be reachable from a
tool: authorising a workspace, inspecting the audit chain, and asking the policy
engine what it would do. Everything here runs as the user, in a terminal, with
no model involved.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from pharness.adapters import select
from pharness.core.audit import AuditLog
from pharness.core.config import Config, Mode, WorkspaceConfig, load_config, save_config
from pharness.core.errors import PharnessError
from pharness.core.journal import Journal
from pharness.core.policy.commands import classify
from pharness.core.policy.engine import PolicyEngine, Request
from pharness.core.policy.tiers import Tier
from pharness.core.workspace import WorkspaceRegistry


def _config_path(adapters) -> Path:
    return adapters.paths.config_dir() / "config.toml"


def _audit_path(adapters) -> Path:
    return adapters.paths.data_dir() / "audit.jsonl"


def cmd_config(args: argparse.Namespace) -> int:
    adapters = select()
    print(_config_path(adapters))
    return 0


def cmd_workspace_list(args: argparse.Namespace) -> int:
    adapters = select()
    config = load_config(_config_path(adapters))
    registry = WorkspaceRegistry.from_config(config, adapters.paths)

    if not len(registry):
        print("No workspaces authorised yet. Add one with: ph workspace add <path>")
        return 0

    now = datetime.now(UTC)
    for workspace in registry.all():
        flags = [workspace.effective_mode(now).value]
        if workspace.config.git_push:
            flags.append("push")
        exists = "" if workspace.root.is_dir() else "  [MISSING]"
        print(f"{workspace.alias:16} {workspace.root}  ({', '.join(flags)}){exists}")
        if workspace.scope_warning:
            print(f"{'':16} warning: this is {workspace.scope_warning}")
    return 0


def cmd_workspace_add(args: argparse.Namespace) -> int:
    adapters = select()
    path = _config_path(adapters)
    config = load_config(path)

    root = Path(args.path).expanduser()
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return 1

    resolved = adapters.paths.resolve(root)
    alias = args.alias or resolved.name.lower().replace(" ", "-")

    reason = adapters.paths.broad_scope_reason(resolved)
    if reason and not args.yes:
        # The reference tool had a whole drive as its project root (PRD 18).
        print(f"Refusing without --yes: {resolved} is {reason}.", file=sys.stderr)
        print("Point this at a single project directory instead.", file=sys.stderr)
        return 2

    entry = WorkspaceConfig(
        alias=alias,
        path=str(resolved),
        mode=Mode.READ_ONLY if args.read_only else Mode.AUTO_EDIT,
        git_push=False,
        allow_commands=list(args.allow or []),
    )
    updated = Config.model_validate(
        {
            **config.model_dump(mode="json", by_alias=True),
            "workspace": [
                *(w.model_dump(mode="json") for w in config.workspaces if w.alias != alias),
                entry.model_dump(mode="json"),
            ],
        }
    )
    save_config(updated, path)
    print(f"Authorised {alias} -> {resolved} ({entry.mode.value})")
    if reason:
        print(f"warning: this is {reason}")
    return 0


def cmd_audit_verify(args: argparse.Namespace) -> int:
    status = AuditLog(_audit_path(select())).verify()
    print(status.summary)
    return 0 if status.intact else 1


def cmd_audit_tail(args: argparse.Namespace) -> int:
    for record in AuditLog(_audit_path(select())).tail(args.count):
        event = record["event"]
        decision = event.get("decision", "-")
        print(f"{record['ts']}  {decision:5}  {event.get('tool', '-')}  {event.get('reason', '')}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Ask the policy engine what it would do, without running anything.

    The point is that the answer is inspectable: a permission system nobody can
    interrogate is a permission system nobody trusts.
    """
    adapters = select()
    config = load_config(_config_path(adapters))
    registry = WorkspaceRegistry.from_config(config, adapters.paths)

    command = " ".join(a for a in args.command if a != "--")
    if not command.strip():
        print("nothing to check", file=sys.stderr)
        return 2
    workspace = registry.get(args.workspace) if args.workspace else registry.sole()

    if workspace is None:
        analysis = classify(command, shell=adapters.shell)
        print(f"tier {analysis.tier.label}: {analysis.top_reason}")
        print("(no workspace given, so allowlists and mode were not applied)")
        return 0

    engine = PolicyEngine(adapters.shell, file_exists=lambda t: (workspace.root / t).exists())
    verdict = engine.decide(
        Request(
            session_id="cli",
            tool="shell",
            declared_tier=Tier.EXEC_OTHER,
            payload={"command": command},
            command_line=command,
        ),
        workspace,
        datetime.now(UTC),
    )
    print(f"{verdict.decision.value.upper()}  tier {verdict.tier.label}  [{verdict.rule}]")
    print(f"  {verdict.reason}")
    for finding in verdict.findings:
        detail = f" ({finding.detail})" if finding.detail else ""
        print(f"  - {finding.tier.label} {finding.reason}{detail}")
    return 0


def _resolve_workspace(alias: str | None):
    adapters = select()
    config = load_config(_config_path(adapters))
    registry = WorkspaceRegistry.from_config(config, adapters.paths)
    workspace = registry.get(alias) if alias else registry.sole()
    if workspace is None:
        raise PharnessError(
            "several workspaces are registered; name one with --workspace "
            f"({', '.join(registry.aliases()) or 'none'})"
        )
    return workspace


def cmd_checkpoints(args: argparse.Namespace) -> int:
    workspace = _resolve_workspace(args.workspace)
    checkpoints = Journal(workspace.root).list()
    if not checkpoints:
        print("no checkpoints recorded yet")
        return 0
    for checkpoint in checkpoints[-args.count :]:
        print(checkpoint.summary)
        for change in checkpoint.changes:
            print(f"      {change.action:7} {change.path}")
    return 0


def cmd_undo(args: argparse.Namespace) -> int:
    """Undo is journaled too, so this is reversible in turn (PRD 10.8)."""
    workspace = _resolve_workspace(args.workspace)
    journal = Journal(workspace.root)
    result = journal.undo(args.checkpoint)
    print(f"Undone. {result.summary}")
    print(f"Reverse this with: ph undo {result.id}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the MCP server.

    stdio for a client on this machine, streamable HTTP behind a tunnel for
    ChatGPT on the web (PRD 7). Same tools either way -- only the entry point
    differs.
    """
    from pharness.mcp import build_server
    from pharness.runtime import build_runtime

    runtime = build_runtime(interactive_prompts=not args.no_prompt)

    tunnel = None
    tunnel_url = None
    if args.http and args.tunnel:
        from pharness.core.tunnel import TunnelError, TunnelManager

        tunnel = TunnelManager(
            runtime.process,
            runtime.adapters.paths.data_dir(),
            runtime.env,
            provider=args.tunnel_provider,
        )
        try:
            status = tunnel.start(args.port)
        except TunnelError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        tunnel_url = status.url
        print(f"tunnel: {status.summary}", file=sys.stderr)

    auth_provider = auth_settings = None
    pairing_code = None
    if args.http:
        # HTTP always requires OAuth. There is no flag to turn it off: an
        # endpoint reachable through a tunnel with no authentication is a
        # machine anyone who learns the URL can use (PRD 10.6). For an
        # unauthenticated local connection, use stdio.
        from mcp.server.auth.settings import (
            AuthSettings,
            ClientRegistrationOptions,
            RevocationOptions,
        )

        from pharness.core.auth import AuthStore
        from pharness.mcp.auth import PairingOAuthProvider

        # Whatever clients actually reach, which is the tunnel when there is
        # one: OAuth metadata that advertises an unreachable issuer fails in a
        # way that is very hard to read from the client side.
        public_url = (args.public_url or tunnel_url or f"http://{args.host}:{args.port}").rstrip(
            "/"
        )
        store = AuthStore(runtime.adapters.paths.data_dir())
        store.load()
        pairing_code = store.pairing_code

        auth_provider = PairingOAuthProvider(store, public_url)
        auth_settings = AuthSettings(
            issuer_url=public_url,
            resource_server_url=public_url,
            client_registration_options=ClientRegistrationOptions(enabled=True),
            revocation_options=RevocationOptions(enabled=True),
        )

    server = build_server(runtime, auth_provider=auth_provider, auth_settings=auth_settings)

    if not args.no_console:
        _start_console(runtime, args.console_port, auth_provider, tunnel)

    if not len(runtime.registry):
        print(
            "warning: no workspaces are authorised, so the tools have nothing to work on.\n"
            "         add one with: ph workspace add <path>",
            file=sys.stderr,
        )
    print(
        f"serving {runtime.adapters.platform} · prompts via {runtime.queue.notifier.name}",
        file=sys.stderr,
    )

    if args.http:
        print(f"listening on http://{args.host}:{args.port}/mcp", file=sys.stderr)
        if pairing_code:
            print(
                "\n"
                "  ┌──────────────────────────────────────────────┐\n"
                f"  │  pairing code:   {pairing_code}                  │\n"
                "  └──────────────────────────────────────────────┘\n"
                "  Type this on the approval page when a client connects.\n"
                "  Anyone who reaches the tunnel sees that page; only someone\n"
                "  looking at this console has the code.\n",
                file=sys.stderr,
            )
        server.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
        )
    else:
        server.run(transport="stdio")
    return 0


def _start_console(runtime, port: int, auth_provider=None, tunnel=None):
    """Run the console beside the MCP server, in the same process.

    Same process because the console answers approval prompts and shows the
    queue, and neither exists anywhere else -- a console in its own process
    could only ever show what is on disk.
    """
    import threading

    import uvicorn

    from pharness.console import ConsoleApi, build_console_app, new_token

    api = ConsoleApi(
        runtime,
        auth_store=getattr(auth_provider, "store", None),
        tunnel=tunnel,
    )
    token = new_token()
    server = uvicorn.Server(
        uvicorn.Config(
            build_console_app(api, token), host="127.0.0.1", port=port, log_level="error"
        )
    )
    thread = threading.Thread(target=server.run, daemon=True, name="console")
    thread.start()

    print(f"\n  console: http://127.0.0.1:{port}/?token={token}\n", file=sys.stderr)
    return thread


def cmd_auth(args: argparse.Namespace) -> int:
    """Inspect and manage what may connect.

    Separate from the server process on purpose: revoking a client should not
    need the thing you are revoking access to.
    """
    from pharness.core.auth import AuthStore

    store = AuthStore(select().paths.data_dir())
    store.load()

    if args.auth_command == "code":
        print(store.pairing_code)
        return 0

    if args.auth_command == "rotate":
        print(f"new pairing code: {store.rotate_pairing_code()}")
        print("clients already authorised keep working; new ones need this code")
        return 0

    if args.auth_command == "clients":
        clients = store.clients()
        if not clients:
            print("nothing has been authorised yet")
            return 0
        for client_id, name in clients:
            print(f"{client_id}  {name}")
        return 0

    if args.auth_command == "revoke":
        if store.forget_client(args.client_id):
            print(f"revoked {args.client_id}; its tokens stop working immediately")
            return 0
        print(f"no client {args.client_id!r}", file=sys.stderr)
        return 1

    return 2


def cmd_stop(args: argparse.Namespace) -> int:
    from pharness.runtime import build_runtime

    result = build_runtime(interactive_prompts=False).emergency_stop()
    print(
        f"refused {result['refused']} pending request(s), stopped {result['stopped']} process(es)"
    )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    adapters = select()
    problems = 0

    def report(ok: bool, message: str, fatal: bool = True) -> None:
        nonlocal problems
        print(f"{'ok  ' if ok else 'FAIL' if fatal else 'warn'}  {message}")
        if not ok and fatal:
            problems += 1

    report(adapters.supported, f"platform {adapters.platform} is a supported target", fatal=False)

    path = _config_path(adapters)
    try:
        config = load_config(path)
        report(True, f"config readable ({path})")
    except PharnessError as exc:
        report(False, f"config: {exc}")
        return 1

    registry = WorkspaceRegistry.from_config(config, adapters.paths)
    report(len(registry) > 0, f"{len(registry)} workspace(s) authorised", fatal=False)
    for workspace in registry.all():
        report(workspace.root.is_dir(), f"{workspace.alias}: {workspace.root} exists")
    for warning in registry.warnings():
        report(False, f"scope too broad: {warning}", fatal=False)

    status = AuditLog(_audit_path(adapters)).verify()
    report(status.intact, f"audit log: {status.summary}")

    print()
    print("no problems found" if not problems else f"{problems} problem(s) found")
    return 0 if not problems else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ph", description="Pressure Harness control")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check the installation and configuration").set_defaults(
        func=cmd_doctor
    )
    sub.add_parser("config", help="print the config file path").set_defaults(func=cmd_config)

    workspace = sub.add_parser("workspace", help="manage authorised project directories")
    workspace_sub = workspace.add_subparsers(dest="workspace_command", required=True)
    workspace_sub.add_parser("list", help="list authorised workspaces").set_defaults(
        func=cmd_workspace_list
    )
    add = workspace_sub.add_parser("add", help="authorise a project directory")
    add.add_argument("path")
    add.add_argument("--alias")
    add.add_argument("--read-only", action="store_true")
    add.add_argument("--allow", action="append", metavar="COMMAND")
    add.add_argument("--yes", action="store_true", help="accept an over-broad directory")
    add.set_defaults(func=cmd_workspace_add)

    audit = sub.add_parser("audit", help="inspect the audit log")
    audit_sub = audit.add_subparsers(dest="audit_command", required=True)
    audit_sub.add_parser("verify", help="recompute the hash chain").set_defaults(
        func=cmd_audit_verify
    )
    tail = audit_sub.add_parser("tail", help="show recent entries")
    tail.add_argument("count", nargs="?", type=int, default=20)
    tail.set_defaults(func=cmd_audit_tail)

    serve = sub.add_parser("serve", help="run the MCP server")
    serve.add_argument("--http", action="store_true", help="streamable HTTP instead of stdio")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=18765)
    serve.add_argument("--console-port", type=int, default=18766)
    serve.add_argument("--no-console", action="store_true", help="do not run the console")
    serve.add_argument("--tunnel", action="store_true", help="publish through a tunnel")
    serve.add_argument("--tunnel-provider", default="cloudflared", choices=["cloudflared", "ngrok"])
    serve.add_argument(
        "--public-url",
        help="the URL clients reach this server on, e.g. your tunnel address",
    )
    serve.add_argument(
        "--no-prompt",
        action="store_true",
        help="never open an approval window; anything needing approval is refused",
    )
    serve.set_defaults(func=cmd_serve)

    auth = sub.add_parser("auth", help="manage which clients may connect")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    auth_sub.add_parser("code", help="print the pairing code").set_defaults(func=cmd_auth)
    auth_sub.add_parser("rotate", help="issue a new pairing code").set_defaults(func=cmd_auth)
    auth_sub.add_parser("clients", help="list authorised clients").set_defaults(func=cmd_auth)
    revoke = auth_sub.add_parser("revoke", help="revoke a client and its tokens")
    revoke.add_argument("client_id")
    revoke.set_defaults(func=cmd_auth)

    sub.add_parser(
        "stop", help="emergency stop: refuse pending requests, kill processes"
    ).set_defaults(func=cmd_stop)

    checkpoints = sub.add_parser("checkpoints", help="list undoable checkpoints")
    checkpoints.add_argument("--workspace")
    checkpoints.add_argument("count", nargs="?", type=int, default=20)
    checkpoints.set_defaults(func=cmd_checkpoints)

    undo = sub.add_parser("undo", help="restore the files a checkpoint changed")
    undo.add_argument("checkpoint", nargs="?", help="defaults to the most recent")
    undo.add_argument("--workspace")
    undo.set_defaults(func=cmd_undo)

    check = sub.add_parser(
        "check",
        help="show what the policy engine would decide",
        epilog="Put --workspace before the command: ph check --workspace shop -- rm -rf build",
    )
    check.add_argument("--workspace")
    # REMAINDER so a command's own flags (-rf, --force) are not read as ours.
    check.add_argument("command", nargs=argparse.REMAINDER)
    check.set_defaults(func=cmd_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except PharnessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

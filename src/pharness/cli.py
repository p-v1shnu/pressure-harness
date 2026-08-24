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

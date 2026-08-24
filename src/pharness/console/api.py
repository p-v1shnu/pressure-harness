"""What the console can ask the runtime, and what it may change.

The console is the half of the product that is not a tool: it is where the
owner sees what happened, answers approval prompts, and takes permission back
(PRD 12). So the split here is deliberate -- these endpoints are reachable only
from this machine, and several of them do things no tool is ever allowed to do.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pharness.core.approvals import Outcome
from pharness.core.journal import Journal, JournalError
from pharness.runtime import Runtime


def now() -> datetime:
    return datetime.now(UTC)


class ConsoleApi:
    """Plain methods returning plain data. The HTTP layer only serialises."""

    def __init__(self, runtime: Runtime, auth_store: Any = None, tunnel: Any = None) -> None:
        self.runtime = runtime
        self.auth_store = auth_store
        self.tunnel = tunnel

    # -- overview ----------------------------------------------------------

    def status(self) -> dict:
        moment = now()
        workspaces = self.runtime.registry.all()
        elevated = [
            {
                "alias": workspace.alias,
                "expires_in_sec": max(
                    0, int((workspace.grant.expires_at - moment).total_seconds())
                ),
            }
            for workspace in workspaces
            if workspace.grant and workspace.grant.active_at(moment)
        ]

        today = [
            entry
            for entry in self.runtime.audit.tail(500)
            if str(entry.get("ts", "")).startswith(moment.date().isoformat())
        ]

        return {
            "platform": self.runtime.adapters.platform,
            "supported": self.runtime.adapters.supported,
            "capabilities": sorted(self.runtime.adapters.capabilities),
            "notifier": self.runtime.queue.notifier.name,
            "can_prompt": bool(getattr(self.runtime.queue.notifier, "interactive", False)),
            "workspaces": len(workspaces),
            "elevated": elevated,
            "pending": len(self.runtime.queue.pending()),
            "processes": len(self.runtime.process.list_running()),
            "today": {
                "calls": len(today),
                "denied": sum(1 for e in today if e["event"].get("decision") == "deny"),
                "asked": sum(1 for e in today if e["event"].get("decision") == "ask"),
            },
            "audit": self.runtime.audit.verify().summary,
            "audit_intact": self.runtime.audit.verify().intact,
            "warnings": list(self.runtime.registry.warnings()),
        }

    # -- projects ----------------------------------------------------------

    def workspaces(self) -> list[dict]:
        moment = now()
        out = []
        for workspace in self.runtime.registry.all():
            journal = Journal(workspace.root)
            git = self.runtime.git(workspace)
            is_repo = git.is_repository()
            out.append(
                {
                    "alias": workspace.alias,
                    "path": str(workspace.root),
                    "exists": workspace.root.is_dir(),
                    "mode": workspace.effective_mode(moment).value,
                    "configured_mode": workspace.config.mode.value,
                    "git_push": workspace.config.git_push,
                    "allow_commands": list(workspace.config.allow_commands),
                    "scope_warning": workspace.scope_warning,
                    "branch": git.current_branch() if is_repo else None,
                    "checkpoints": len(journal.list()),
                }
            )
        return out

    def elevate(self, alias: str, minutes: int) -> dict:
        """Grant full access for a bounded window, and record it.

        Elevation is a decision worth being able to find later, so it goes in
        the audit log like anything else (PRD 10.2).
        """
        workspace = self.runtime.registry.get(alias)
        grant = workspace.grant_full_access(minutes, now())
        self.runtime.audit.append(
            {
                "tool": "console",
                "decision": "allow",
                "disposition": "elevated",
                "workspace": alias,
                "reason": f"full access granted for {minutes} minutes",
                "expires_at": grant.expires_at.isoformat(),
            }
        )
        return {"alias": alias, "expires_at": grant.expires_at.isoformat()}

    def revoke_elevation(self, alias: str) -> dict:
        workspace = self.runtime.registry.get(alias)
        workspace.revoke_grant()
        self.runtime.audit.append(
            {
                "tool": "console",
                "decision": "deny",
                "disposition": "elevation_revoked",
                "workspace": alias,
                "reason": "the owner ended full access",
            }
        )
        return {"alias": alias, "mode": workspace.effective_mode(now()).value}

    # -- approvals ---------------------------------------------------------

    def pending(self) -> list[dict]:
        moment = now()
        return [
            {
                "id": request.id,
                "workspace": request.workspace,
                "tool": request.tool,
                "op": request.op,
                "tier": request.tier.label,
                "reason": request.reason,
                "payload": request.render(),
                "seconds_left": int(request.seconds_left(moment)),
            }
            for request in self.runtime.queue.pending()
        ]

    def answer(self, request_id: str, outcome: str) -> dict:
        try:
            choice = Outcome(outcome)
        except ValueError:
            return {"ok": False, "error": f"unknown outcome {outcome!r}"}
        if choice in (Outcome.TIMED_OUT, Outcome.RATE_LIMITED):
            return {"ok": False, "error": "that outcome is not something to choose"}

        answered = self.runtime.queue.respond(request_id, choice, "answered in the console")
        return {"ok": answered, "error": None if answered else "it is no longer waiting"}

    def history(self, limit: int = 40) -> list[dict]:
        return [
            {
                "tool": request.tool,
                "workspace": request.workspace,
                "tier": request.tier.label,
                "outcome": str(decision.outcome),
                "note": decision.note,
                "at": decision.decided_at.isoformat() if decision.decided_at else None,
            }
            for request, decision in self.runtime.queue.history()[-limit:]
        ][::-1]

    def rules(self) -> list[dict]:
        """Remembered decisions. A permission nobody can find is one nobody can take back."""
        return [
            {
                "index": index,
                "action": rule.action,
                "tool": rule.tool,
                "workspace": rule.workspace,
                "command_prefix": rule.command_prefix,
                "exact_payload": (rule.exact_payload or "")[:12],
                "session_only": rule.session_id is not None,
                "expires_at": rule.expires_at.isoformat() if rule.expires_at else None,
                "reason": rule.reason,
            }
            for index, rule in enumerate(self.runtime.engine.rules)
        ]

    def forget_rule(self, index: int) -> dict:
        rules = self.runtime.engine.rules
        if not 0 <= index < len(rules):
            return {"ok": False, "error": "no such rule"}
        self.runtime.engine.forget(rules[index])
        self.runtime.audit.append(
            {
                "tool": "console",
                "decision": "deny",
                "disposition": "rule_removed",
                "reason": "the owner removed a remembered permission",
            }
        )
        return {"ok": True}

    # -- activity ----------------------------------------------------------

    def activity(self, limit: int = 100, decision: str | None = None) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        entries = self.runtime.audit.tail(limit * 3)
        rows = []
        for entry in reversed(entries):
            event = entry["event"]
            if decision and event.get("decision") != decision:
                continue
            rows.append(
                {
                    "seq": entry["seq"],
                    "ts": entry["ts"],
                    "tool": event.get("tool"),
                    "op": event.get("op"),
                    "workspace": event.get("workspace"),
                    "tier": event.get("tier"),
                    "decision": event.get("decision"),
                    "disposition": event.get("disposition"),
                    "rule": event.get("rule"),
                    "reason": event.get("reason"),
                    "detail": event.get("detail"),
                    "redacted": event.get("_redacted"),
                }
            )
            if len(rows) >= limit:
                break
        return rows

    # -- changes -----------------------------------------------------------

    def checkpoints(self, alias: str, limit: int = 30) -> list[dict]:
        workspace = self.runtime.registry.get(alias)
        entries = Journal(workspace.root).list()[-limit:]
        return [
            {
                "id": checkpoint.id,
                "ts": checkpoint.ts,
                "label": checkpoint.label,
                "undoes": checkpoint.undoes,
                "changes": [
                    {"path": change.path, "action": change.action} for change in checkpoint.changes
                ],
            }
            for checkpoint in reversed(entries)
        ]

    def undo(self, alias: str, checkpoint: str | None = None) -> dict:
        workspace = self.runtime.registry.get(alias)
        try:
            result = Journal(workspace.root).undo(checkpoint)
        except JournalError as exc:
            return {"ok": False, "error": str(exc)}
        self.runtime.audit.append(
            {
                "tool": "console",
                "decision": "allow",
                "disposition": "undo",
                "workspace": alias,
                "reason": f"the owner undid {checkpoint or 'the last change'}",
            }
        )
        return {"ok": True, "summary": result.summary, "id": result.id}

    # -- processes ---------------------------------------------------------

    def processes(self) -> list[dict]:
        handles = getattr(self.runtime.process, "list_all", self.runtime.process.list_running)()
        return [
            {
                "id": handle.id,
                "pid": handle.pid,
                "label": getattr(handle, "label", ""),
                "argv": list(handle.argv),
                "running": handle.is_running(),
                "exit_code": handle.exit_code(),
                "uptime_sec": int(getattr(handle, "uptime_sec", lambda: 0)()),
            }
            for handle in handles
        ]

    def process_logs(self, process_id: str, lines: int = 200) -> dict:
        handle = self.runtime.process.get(process_id)
        if handle is None:
            return {"ok": False, "error": "no such process"}
        return {"ok": True, "text": handle.tail(lines)}

    def stop_process(self, process_id: str) -> dict:
        handle = self.runtime.process.get(process_id)
        if handle is None:
            return {"ok": False, "error": "no such process"}
        return {"ok": True, "exit_code": handle.stop()}

    # -- connection --------------------------------------------------------

    def connection(self) -> dict:
        data: dict[str, Any] = {
            "stdio_command": "ph serve",
            "tunnel": None,
            "pairing_code": None,
            "clients": [],
        }
        if self.tunnel is not None:
            status = self.tunnel.status()
            data["tunnel"] = {
                "running": status.running,
                "provider": status.provider,
                "url": status.url,
                "summary": status.summary,
            }
        if self.auth_store is not None:
            data["pairing_code"] = self.auth_store.pairing_code
            data["clients"] = [
                {"id": client_id, "name": name} for client_id, name in self.auth_store.clients()
            ]
            data["auth_stats"] = self.auth_store.stats()
        return data

    def rotate_pairing_code(self) -> dict:
        if self.auth_store is None:
            return {"ok": False, "error": "this server is not using OAuth"}
        return {"ok": True, "pairing_code": self.auth_store.rotate_pairing_code()}

    def revoke_client(self, client_id: str) -> dict:
        if self.auth_store is None:
            return {"ok": False, "error": "this server is not using OAuth"}
        removed = self.auth_store.forget_client(client_id)
        if removed:
            self.runtime.audit.append(
                {
                    "tool": "console",
                    "decision": "deny",
                    "disposition": "client_revoked",
                    "reason": f"the owner revoked client {client_id}",
                }
            )
        return {"ok": removed}

    # -- doctor and the stop button ----------------------------------------

    def doctor(self) -> list[dict]:
        checks: list[dict] = []

        def add(ok: bool, label: str, detail: str = "", fatal: bool = True) -> None:
            checks.append(
                {"ok": ok, "label": label, "detail": detail, "level": "error" if fatal else "warn"}
            )

        adapters = self.runtime.adapters
        add(adapters.supported, f"platform {adapters.platform} is a supported target", fatal=False)
        add(
            bool(len(self.runtime.registry)),
            f"{len(self.runtime.registry)} workspace(s) authorised",
            fatal=False,
        )
        for workspace in self.runtime.registry.all():
            add(workspace.root.is_dir(), f"{workspace.alias} exists", str(workspace.root))
            if workspace.scope_warning:
                add(False, f"{workspace.alias} is {workspace.scope_warning}", fatal=False)

        status = self.runtime.audit.verify()
        add(status.intact, "audit log is intact", status.summary)
        add(
            bool(getattr(self.runtime.queue.notifier, "interactive", False)),
            "approval prompts can be shown",
            f"using {self.runtime.queue.notifier.name}",
            fatal=False,
        )
        add(
            adapters.browser.find_executable() is not None,
            "a browser is available",
            fatal=False,
        )
        return checks

    def emergency_stop(self) -> dict:
        return self.runtime.emergency_stop()

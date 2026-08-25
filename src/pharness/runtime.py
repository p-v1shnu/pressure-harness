"""Assembling one running instance.

Everything is wired here so that no other module has to know how the pieces fit
together, and -- more to the point -- so there is exactly one place where the
gateway is put between the transport and the tools. If a tool could be reached
without passing through this wiring, the policy engine would be optional
(PRD 6.1).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from pharness.adapters import Adapters, select, select_notifier
from pharness.core.approvals import ApprovalQueue
from pharness.core.audit import AuditLog, Redactor
from pharness.core.config import Config, load_config
from pharness.core.env import build_env
from pharness.core.gateway import Gateway
from pharness.core.journal import Journal
from pharness.core.policy.engine import PolicyEngine
from pharness.core.policy.path_jail import PathJail
from pharness.core.tools import FileTools, GitTools, ProcessTools, ProjectTools, SearchTools
from pharness.core.tools.browser import BrowserTools
from pharness.core.tools.delegate import DelegateTools
from pharness.core.tools.shell import ShellTools
from pharness.core.tools.web import WebTools
from pharness.core.workspace import Sessions, Workspace, WorkspaceRegistry


@dataclass
class Runtime:
    config: Config
    adapters: Adapters
    registry: WorkspaceRegistry
    sessions: Sessions
    jail: PathJail
    engine: PolicyEngine
    queue: ApprovalQueue
    audit: AuditLog
    gateway: Gateway
    process: object
    env: dict[str, str]
    _journals: dict[str, Journal] = field(default_factory=dict)
    _browser: BrowserTools | None = field(default=None, repr=False)

    # -- per-workspace tools -----------------------------------------------

    def journal(self, workspace: Workspace) -> Journal:
        if workspace.alias not in self._journals:
            self._journals[workspace.alias] = Journal(workspace.root)
        return self._journals[workspace.alias]

    def files(self, workspace: Workspace) -> FileTools:
        return FileTools(workspace, self.jail, self.journal(workspace), self.config.context)

    def search(self, workspace: Workspace) -> SearchTools:
        return SearchTools(workspace, self.jail, self.config.context)

    def git(self, workspace: Workspace) -> GitTools:
        return GitTools(workspace, self.process, self.config.context, self.env)

    def project(self, workspace: Workspace) -> ProjectTools:
        return ProjectTools(workspace, self.process, self.config.context, self.env)

    def shell(self, workspace: Workspace) -> ShellTools:
        return ShellTools(
            workspace, self.process, self.config.context, self.env, self.adapters.platform
        )

    def browser(self, workspace: Workspace) -> BrowserTools:
        """One browser session for the whole runtime.

        Reused rather than rebuilt per call, because the console and network
        logs only mean anything if the connection that collected them is still
        the one being read.
        """
        if self._browser is None:
            self._browser = BrowserTools(
                workspace=workspace,
                context=self.config.context,
                locator=self.adapters.browser,
                process=self.process,
                env=self.env,
                data_dir=self.adapters.paths.data_dir(),
                allowlist=tuple(self.config.network.fetch_allowlist),
            )
        else:
            self._browser.workspace = workspace
        return self._browser

    def web(self) -> WebTools:
        return WebTools(self.config.context, tuple(self.config.network.fetch_allowlist))

    def delegate(self, workspace: Workspace) -> DelegateTools:
        """Workspace templates win over global ones: a project may need a
        different agent, or different flags, than the machine's default."""
        return DelegateTools(
            workspace,
            self.process,
            self.config.context,
            self.env,
            templates={**self.config.delegates, **workspace.config.delegates},
        )

    def processes(self) -> ProcessTools:
        return ProcessTools(self.process, self.config.context)

    # -- lifecycle ----------------------------------------------------------

    def emergency_stop(self) -> dict[str, int]:
        """Everything off, at once (PRD 10.10).

        Order matters: refuse what is waiting before stopping processes, so
        nothing slips through while the stop is in progress.
        """
        refused = self.queue.deny_all("emergency stop")
        stopped = self.process.stop_all()
        if self._browser is not None:
            self._browser.close()
        for workspace in self.registry.all():
            workspace.revoke_grant()
        self.audit.append(
            {
                "tool": "control",
                "decision": "deny",
                "disposition": "emergency_stop",
                "reason": "the operator pressed stop",
                "refused": refused,
                "stopped": stopped,
            }
        )
        return {"refused": refused, "stopped": stopped}


def build_runtime(
    config_path: Path | None = None,
    *,
    interactive_prompts: bool = True,
    adapters: Adapters | None = None,
) -> Runtime:
    adapters = adapters or select()
    config_path = config_path or (adapters.paths.config_dir() / "config.toml")
    config = load_config(config_path)

    data_dir = adapters.paths.data_dir()
    registry = WorkspaceRegistry.from_config(config, adapters.paths)

    redactor = Redactor() if config.security.redact_secrets else None
    audit = AuditLog(data_dir / "audit.jsonl", redactor=redactor)

    notifier = select_notifier(prefer_window=interactive_prompts)
    queue = ApprovalQueue(
        notifier,
        timeout_sec=config.security.approval_timeout_sec,
        rate_limit_per_minute=config.security.approval_rate_limit,
    )

    process = adapters.process_factory(data_dir / "logs")
    engine = PolicyEngine(adapters.shell)

    return Runtime(
        config=config,
        adapters=adapters,
        registry=registry,
        sessions=Sessions(registry),
        jail=PathJail.with_app_dirs(adapters.paths),
        engine=engine,
        queue=queue,
        audit=audit,
        gateway=Gateway(engine, queue, audit),
        process=process,
        env=build_env(os.environ, adapters.platform),
    )

"""Configuration model and loader.

Two rules shape this file, both from the decision to hand the tool to other
people (PRD 17):

* defaults are safe rather than convenient -- there is no way to express
  "unrestricted by default", because the reference tool shipped exactly that
  and it is the failure mode we exist to avoid (PRD 18);
* unsafe combinations are rejected at load time, not warned about at use time.

No tool can reach this file. It is edited from the console UI or the CLI only
(PRD 10.3), so validation here is the last word.
"""

from __future__ import annotations

import re
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any

import tomli_w
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from pharness.core.errors import ConfigError

ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


class Mode(StrEnum):
    """Permission mode for one workspace (PRD 10.2)."""

    READ_ONLY = "read-only"
    AUTO_EDIT = "auto-edit"
    FULL_ACCESS = "full-access"


class ServerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bind: str = "127.0.0.1"
    port: int = Field(default=18765, ge=1024, le=65535)

    @field_validator("bind")
    @classmethod
    def _loopback_only(cls, value: str) -> str:
        if value not in LOOPBACK:
            raise ValueError(
                f"bind must be loopback ({', '.join(sorted(LOOPBACK))}); "
                "reach the server through a tunnel instead of opening a port"
            )
        return value


class SecuritySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_mode: Mode = Mode.AUTO_EDIT
    full_access_ttl_min: int = Field(default=120, ge=1, le=1440)
    approval_timeout_sec: int = Field(default=120, ge=10, le=900)
    approval_rate_limit: int = Field(default=10, ge=1, le=120)
    redact_secrets: bool = True

    @field_validator("default_mode")
    @classmethod
    def _no_default_full_access(cls, value: Mode) -> Mode:
        if value is Mode.FULL_ACCESS:
            raise ValueError(
                "default_mode cannot be full-access; grant it per workspace, "
                "where it expires on its own"
            )
        return value


class ContextSettings(BaseModel):
    """Caps on what travels back into the conversation (PRD 11)."""

    model_config = ConfigDict(extra="forbid")

    max_output_bytes: int = Field(default=8192, ge=512, le=1_048_576)
    search_max_hits: int = Field(default=50, ge=1, le=1000)


class NetworkSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fetch_allowlist: list[str] = Field(default_factory=list)


class TunnelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = "cloudflared"
    auth: str = "oauth"
    autostart: bool = False

    @field_validator("auth")
    @classmethod
    def _reject_open_endpoint(cls, value: str) -> str:
        if value == "none":
            raise ValueError(
                "tunnel auth cannot be none: anyone who learns the tunnel URL "
                "would reach this machine (PRD 10.6)"
            )
        if value != "oauth":
            raise ValueError("tunnel auth must be 'oauth'")
        return value


class WorkspaceConfig(BaseModel):
    """One directory the user has authorised, with its own permissions."""

    model_config = ConfigDict(extra="forbid")

    alias: str
    path: str
    mode: Mode = Mode.AUTO_EDIT
    git_push: bool = False
    allow_commands: list[str] = Field(default_factory=list)
    scripts: dict[str, str] = Field(default_factory=dict)

    @field_validator("alias")
    @classmethod
    def _valid_alias(cls, value: str) -> str:
        if not ALIAS_RE.match(value):
            raise ValueError(
                "alias must be lowercase letters, digits, dash or underscore (max 32 chars)"
            )
        return value

    @field_validator("path")
    @classmethod
    def _non_empty_path(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("path must not be empty")
        return value

    @field_validator("mode")
    @classmethod
    def _no_persistent_full_access(cls, value: Mode) -> Mode:
        if value is Mode.FULL_ACCESS:
            raise ValueError(
                "full-access cannot be stored in config; it is granted at runtime "
                "and expires (PRD 10.2)"
            )
        return value


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    server: ServerSettings = Field(default_factory=ServerSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    context: ContextSettings = Field(default_factory=ContextSettings)
    network: NetworkSettings = Field(default_factory=NetworkSettings)
    tunnel: TunnelSettings = Field(default_factory=TunnelSettings)
    workspaces: list[WorkspaceConfig] = Field(default_factory=list, alias="workspace")

    @model_validator(mode="after")
    def _unique_aliases(self) -> Config:
        seen: set[str] = set()
        for workspace in self.workspaces:
            if workspace.alias in seen:
                raise ValueError(f"duplicate workspace alias {workspace.alias!r}")
            seen.add(workspace.alias)
        return self


def parse_config(raw: dict[str, Any]) -> Config:
    try:
        return Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(_readable(exc)) from exc


def load_config(path: Path) -> Config:
    """Read config from `path`, or return safe defaults if it does not exist yet."""
    if not path.exists():
        return Config()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"could not read {path}: {exc}") from exc
    return parse_config(raw)


def save_config(config: Config, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = config.model_dump(mode="json", by_alias=True, exclude_defaults=False)
    text = tomli_w.dumps(payload)
    # Write then move, so an interrupted save cannot leave a half-written policy
    # file behind.
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def _readable(exc: ValidationError) -> str:
    lines = []
    for error in exc.errors():
        where = ".".join(str(p) for p in error["loc"]) or "config"
        lines.append(f"{where}: {error['msg']}")
    return "; ".join(lines)

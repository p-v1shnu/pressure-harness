"""What a tool hands back.

`text` is what reaches the conversation and is therefore budgeted; `meta` is
for the console and the audit log, which can hold detail without paying for it
every turn (PRD 11).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolResult:
    text: str
    ok: bool = True
    meta: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def failure(cls, message: str, **meta: Any) -> ToolResult:
        return cls(text=message, ok=False, meta=meta)

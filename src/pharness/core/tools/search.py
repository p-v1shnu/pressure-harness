"""Searching a workspace.

Search is where a careless implementation leaks: it walks everything, so it can
read a credential file the read tool would have refused, and it can return more
text than an hour of conversation can afford. Both are handled here rather than
left to the caller -- the same jail rules apply, and results are capped.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from pharness.core.config import ContextSettings
from pharness.core.policy.path_jail import PathJail
from pharness.core.text import clamp, looks_binary, wrap_external
from pharness.core.tools.results import ToolResult
from pharness.core.workspace import Workspace

# Directories that are never worth searching and are expensive to walk.
SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".pharness",
        "node_modules",
        "bower_components",
        "vendor",
        "dist",
        "build",
        "out",
        "target",
        ".next",
        ".nuxt",
        ".svelte-kit",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".gradle",
        ".idea",
        ".vscode",
        "coverage",
        ".cache",
    }
)

MAX_FILE_BYTES = 2 * 1024 * 1024
SNIPPET_CHARS = 160


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    text: str


@dataclass
class SearchTools:
    workspace: Workspace
    jail: PathJail
    context: ContextSettings

    def walk(self, glob: str | None = None) -> Iterator[Path]:
        root = self.workspace.root
        for path in sorted(root.rglob("*")):
            if path.is_dir():
                continue
            relative = path.relative_to(root)
            if any(part in SKIP_DIRS for part in relative.parts):
                continue
            # The same rule the read tool applies: a credential file is not
            # readable through a different door (PRD 10.3).
            if self.jail.secret_reason(relative) is not None:
                continue
            if glob and not (fnmatch(relative.as_posix(), glob) or fnmatch(relative.name, glob)):
                continue
            yield path

    def files(self, glob: str = "*") -> ToolResult:
        root = self.workspace.root
        limit = self.context.search_max_hits
        found = [p.relative_to(root).as_posix() for p in self.walk(glob)]

        shown = found[:limit]
        text = "\n".join(shown) if shown else f"no files match {glob!r}"
        if len(found) > limit:
            text += f"\n\n[{len(found)} files match; showing the first {limit}]"

        excerpt = clamp(text, self.context.max_output_bytes)
        return ToolResult(text=excerpt.text, meta={"matches": len(found), "shown": len(shown)})

    def text(
        self,
        pattern: str,
        glob: str | None = None,
        case_sensitive: bool = False,
        max_hits: int | None = None,
    ) -> ToolResult:
        try:
            regex = re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
        except re.error as exc:
            return ToolResult.failure(f"invalid regular expression: {exc}")

        limit = max_hits or self.context.search_max_hits
        root = self.workspace.root
        hits: list[Hit] = []
        scanned = 0
        capped = False

        for path in self.walk(glob):
            if len(hits) >= limit:
                capped = True
                break
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
                data = path.read_bytes()
            except OSError:
                continue
            if looks_binary(data):
                continue

            scanned += 1
            relative = path.relative_to(root).as_posix()
            for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
                if regex.search(line):
                    hits.append(Hit(relative, number, line.strip()[:SNIPPET_CHARS]))
                    if len(hits) >= limit:
                        capped = True
                        break

        if not hits:
            return ToolResult(
                text=f"no matches for {pattern!r} in {scanned} files",
                meta={"hits": 0, "files_scanned": scanned},
            )

        # `path:line` is the shape every editor and every follow-up read
        # understands, and it costs far less than returning surrounding context.
        body = "\n".join(f"{hit.path}:{hit.line}  {hit.text}" for hit in hits)
        if capped:
            body += f"\n\n[stopped at {limit} matches; narrow the pattern or pass a glob]"

        excerpt = clamp(body, self.context.max_output_bytes)
        return ToolResult(
            text=wrap_external(excerpt.text, "matching lines in this project"),
            meta={"hits": len(hits), "files_scanned": scanned, "capped": capped},
        )

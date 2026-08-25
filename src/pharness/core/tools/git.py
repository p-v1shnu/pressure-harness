"""Git, run as argv rather than through a shell.

No shell means no quoting bugs and no way for a branch name to become a second
command. Every call is a list of arguments handed straight to git.

Output is shaped for a conversation, not a terminal: `diff` answers with a
summary first and full text only when a file is named, because a 4000-line diff
pasted into a chat costs the same budget every turn afterwards (PRD 11).
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pharness.core.config import ContextSettings
from pharness.core.text import clamp, wrap_external
from pharness.core.tools.results import ToolResult
from pharness.core.workspace import Workspace
from pharness.ports import CompletedProcess, ProcessPort

GIT_TIMEOUT = 60.0


@dataclass
class GitTools:
    workspace: Workspace
    process: ProcessPort
    context: ContextSettings
    env: Mapping[str, str]

    # -- plumbing ----------------------------------------------------------

    def _run(self, *args: str, timeout: float = GIT_TIMEOUT) -> CompletedProcess:
        executable = shutil.which("git", path=self.env.get("PATH")) or "git"
        return self.process.run(
            [executable, *args], self.workspace.root, self.env, timeout_sec=timeout
        )

    def _fail(self, result: CompletedProcess) -> ToolResult:
        message = result.combined.strip() or f"git exited {result.exit_code}"
        if result.timed_out:
            message = "git did not finish in time"
        return ToolResult.failure(clamp(message, self.context.max_output_bytes).text)

    def _ok(self, text: str, external: str = "", **meta: object) -> ToolResult:
        excerpt = clamp(text.strip() or "(no output)", self.context.max_output_bytes)
        body = wrap_external(excerpt.text, external) if external else excerpt.text
        return ToolResult(text=body, meta={"truncated": excerpt.truncated, **meta})

    def current_branch(self) -> str:
        """`--show-current` rather than `rev-parse HEAD`, which has no answer
        before the first commit -- exactly when a new project is being set up."""
        result = self._run("branch", "--show-current", timeout=10)
        name = result.stdout.strip() if result.ok else ""
        return name or "(detached)"

    def is_repository(self) -> bool:
        return self._run("rev-parse", "--git-dir", timeout=10).ok

    def _require_repository(self) -> ToolResult | None:
        if self.is_repository():
            return None
        return ToolResult.failure(
            f"{self.workspace.alias} is not a git repository, so git tools are unavailable here"
        )

    # -- reading -----------------------------------------------------------

    def status(self) -> ToolResult:
        if (problem := self._require_repository()) is not None:
            return problem

        porcelain = self._run("status", "--porcelain=v1", "--branch")
        if not porcelain.ok:
            return self._fail(porcelain)

        lines = [line for line in porcelain.stdout.splitlines() if not line.startswith("##")]
        head = self.current_branch()

        if not lines:
            return self._ok(f"On {head}. Working tree clean.", branch=head, dirty=0)

        shown = lines[: self.context.search_max_hits]
        body = "\n".join(shown)
        if len(lines) > len(shown):
            body += f"\n[{len(lines)} changed files; showing {len(shown)}]"
        return self._ok(f"On {head}, {len(lines)} changed:\n{body}", branch=head, dirty=len(lines))

    def diff(self, path: str | None = None, staged: bool = False) -> ToolResult:
        """Summary by default; the full text only for a named file.

        Asking for "the diff" of a large change and getting all of it is how a
        conversation runs out of room three messages in.
        """
        if (problem := self._require_repository()) is not None:
            return problem

        args = ["diff"]
        if staged:
            args.append("--cached")

        if path is None:
            result = self._run(*args, "--stat")
            if not result.ok:
                return self._fail(result)
            body = result.stdout.strip()
            if not body:
                return self._ok("no changes" + (" staged" if staged else ""))
            return self._ok(f"{body}\n\nAsk for one file's diff by naming it.", summary=True)

        result = self._run(*args, "--", path)
        if not result.ok:
            return self._fail(result)
        return self._ok(
            result.stdout or f"no changes in {path}", external=f"the diff of {path}", path=path
        )

    def log(self, limit: int = 20) -> ToolResult:
        if (problem := self._require_repository()) is not None:
            return problem
        limit = max(1, min(limit, 200))
        # Commit messages are written by whoever wrote the repository, which in
        # a cloned project is not the user (threat model A3).
        result = self._run("log", f"-{limit}", "--pretty=format:%h %ad %an: %s", "--date=short")
        return (
            self._ok(result.stdout, external="commit messages") if result.ok else self._fail(result)
        )

    def show(self, ref: str = "HEAD") -> ToolResult:
        if (problem := self._require_repository()) is not None:
            return problem
        result = self._run("show", "--stat", ref)
        return (
            self._ok(result.stdout, external=f"commit {ref}") if result.ok else self._fail(result)
        )

    def branches(self) -> ToolResult:
        if (problem := self._require_repository()) is not None:
            return problem
        result = self._run("branch", "--list", "--format=%(refname:short)")
        return self._ok(result.stdout) if result.ok else self._fail(result)

    # -- writing -----------------------------------------------------------

    def add(self, paths: Sequence[str]) -> ToolResult:
        if (problem := self._require_repository()) is not None:
            return problem
        if not paths:
            return ToolResult.failure("name the files to stage")
        if any(path.startswith("-") for path in paths):
            # `--` would end option parsing anyway, but refusing is clearer than
            # silently reinterpreting something that looks like a flag.
            return ToolResult.failure("file names cannot start with '-'")

        result = self._run("add", "--", *paths)
        if not result.ok:
            return self._fail(result)
        return self._ok(f"staged {len(paths)} path(s)")

    def commit(self, message: str) -> ToolResult:
        """Commit what is staged. No amend, ever.

        Amending rewrites a commit that may already have been pushed or that
        someone else is working from; if a commit is wrong, the fix is another
        commit (PRD 10.3).
        """
        if (problem := self._require_repository()) is not None:
            return problem

        text = message.strip()
        if not text:
            return ToolResult.failure("a commit needs a message")

        staged = self._run("diff", "--cached", "--name-only")
        if staged.ok and not staged.stdout.strip():
            return ToolResult.failure("nothing is staged; stage the files you mean to commit")

        result = self._run("commit", "-m", text)
        if not result.ok:
            return self._fail(result)

        head = self._run("rev-parse", "--short", "HEAD").stdout.strip()
        return self._ok(f"committed {head}\n{result.stdout}", commit=head)

    def stash(self, message: str = "") -> ToolResult:
        """Set work aside. Recoverable, which is why this exists and reset --hard does not."""
        if (problem := self._require_repository()) is not None:
            return problem
        args = ["stash", "push"]
        if message.strip():
            args += ["-m", message.strip()]
        result = self._run(*args)
        return self._ok(result.stdout) if result.ok else self._fail(result)

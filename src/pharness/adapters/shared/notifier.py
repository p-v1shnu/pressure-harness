"""Notifiers that are not tied to one platform.

`ConsoleNotifier` is for a terminal, and is what the CLI uses. `NullNotifier`
cannot ask anything, which makes every request that reaches it refuse -- the
right behaviour for a headless run, and the safe default when no console is
attached.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable

from pharness.core.approvals import ApprovalRequest, Outcome

Respond = Callable[..., None]

PROMPT = """
┌─ Pressure Harness needs permission ─────────────────────────
{body}
├─────────────────────────────────────────────────────────────
│  [a] allow once   [s] allow for this session
│  [r] remember this exact request   [d] deny   (timeout: deny)
└─────────────────────────────────────────────────────────────
"""

_KEYS = {
    "a": Outcome.ONCE,
    "s": Outcome.SESSION,
    "r": Outcome.REMEMBER,
    "d": Outcome.DENY,
}


class NullNotifier:
    """Cannot ask. Everything that reaches it is refused."""

    name = "null"
    interactive = False

    def present(self, request: ApprovalRequest, respond: Respond) -> None:
        return None

    def withdraw(self, request_id: str) -> None:
        return None

    def notify(self, title: str, body: str) -> None:
        return None


class ConsoleNotifier:
    """Asks on the terminal this process was started from.

    Only interactive when stdin really is a terminal: printing a prompt nobody
    can answer and then waiting out the timeout is worse than refusing at once.
    """

    name = "console"

    def __init__(self, stream=None, stdin=None) -> None:
        self._out = stream or sys.stderr
        self._in = stdin or sys.stdin

    @property
    def interactive(self) -> bool:
        try:
            return bool(self._in) and self._in.isatty()
        except (AttributeError, ValueError):
            return False

    def present(self, request: ApprovalRequest, respond: Respond) -> None:
        body = "\n".join(f"│ {line}" for line in request.render().splitlines())
        self._out.write(PROMPT.format(body=body))
        self._out.flush()

        def read() -> None:
            try:
                answer = (self._in.readline() or "").strip().lower()[:1]
            except (OSError, ValueError):
                return
            respond(_KEYS.get(answer, Outcome.DENY), "answered at the console")

        threading.Thread(target=read, daemon=True, name=f"approval-{request.id}").start()

    def withdraw(self, request_id: str) -> None:
        self._out.write(f"(request {request_id} expired and was refused)\n")
        self._out.flush()

    def notify(self, title: str, body: str) -> None:
        self._out.write(f"\n[{title}] {body}\n")
        self._out.flush()

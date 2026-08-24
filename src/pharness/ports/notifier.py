"""Asking the user, outside the conversation.

The reason this is a port at all: the approval prompt must not live in the
chat (PRD 10.1). What the model asks for and what the user sees have to arrive
through different channels, or a compromised conversation can write both halves.

So the core hands a request to a notifier and waits. Whether that becomes a
window, a tray balloon or a line on a terminal is the platform's business.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class NotifierPort(Protocol):
    name: str
    interactive: bool
    """False for a notifier that cannot collect an answer, so requests to it
    time out and are refused rather than waiting forever."""

    def present(self, request, respond) -> None:
        """Show `request` and call `respond(outcome, note)` when the user answers.

        Returns immediately; the answer arrives through the callback. A notifier
        that cannot ask simply never calls back, and the queue's timeout refuses
        the request on its own.
        """

    def withdraw(self, request_id: str) -> None:
        """Take a prompt down because it timed out or was answered elsewhere."""

    def notify(self, title: str, body: str) -> None:
        """Tell the user something that needs no answer."""

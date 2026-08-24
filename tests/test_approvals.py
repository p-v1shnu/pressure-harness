"""The approval queue. Each test here is a way people get this wrong."""

from __future__ import annotations

import threading
import time

import pytest

from pharness.core.approvals import ApprovalQueue, Outcome
from pharness.core.policy.tiers import Tier

ASK = {
    "session_id": "chat",
    "workspace": "proj",
    "tool": "shell",
    "op": None,
    "tier": Tier.EXEC_OTHER,
    "reason": "not allowlisted",
    "digest": "abc123",
    "payload": {"command": "npx prisma migrate deploy"},
}


class Answering:
    """Stands in for the window: answers with a fixed outcome."""

    name = "test"
    interactive = True

    def __init__(self, outcome: Outcome | None = Outcome.ONCE, delay: float = 0.0) -> None:
        self.outcome = outcome
        self.delay = delay
        self.presented: list = []
        self.withdrawn: list[str] = []

    def present(self, request, respond) -> None:
        self.presented.append(request)
        if self.outcome is None:
            return  # never answers

        def later() -> None:
            time.sleep(self.delay)
            respond(self.outcome, "answered in a test")

        threading.Thread(target=later, daemon=True).start()

    def withdraw(self, request_id: str) -> None:
        self.withdrawn.append(request_id)

    def notify(self, title: str, body: str) -> None:
        return None


class Deaf(Answering):
    name = "deaf"
    interactive = False


@pytest.mark.parametrize("outcome", [Outcome.ONCE, Outcome.SESSION, Outcome.REMEMBER])
def test_approvals_come_back_as_approved(outcome: Outcome):
    queue = ApprovalQueue(Answering(outcome), timeout_sec=5)
    assert queue.ask(**ASK).outcome.approved


def test_denial_is_not_an_approval():
    decision = ApprovalQueue(Answering(Outcome.DENY), timeout_sec=5).ask(**ASK)
    assert not decision.outcome.approved


def test_the_prompt_shows_the_literal_payload():
    """The user approves what was requested, not a description of it (PRD 10.1)."""
    notifier = Answering()
    ApprovalQueue(notifier, timeout_sec=5).ask(**ASK)

    [request] = notifier.presented
    assert "npx prisma migrate deploy" in request.render()
    assert request.digest == "abc123"


def test_an_unanswered_prompt_is_refused():
    """An unattended machine must fail closed, not wait."""
    notifier = Answering(outcome=None)
    decision = ApprovalQueue(notifier, timeout_sec=0.3).ask(**ASK)

    assert decision.outcome is Outcome.TIMED_OUT
    assert notifier.withdrawn == ["a1"]


def test_a_notifier_that_cannot_ask_refuses_immediately():
    """Waiting out a full timeout for a prompt nobody can see is just a slow no."""
    started = time.monotonic()
    decision = ApprovalQueue(Deaf(), timeout_sec=30).ask(**ASK)

    assert decision.outcome is Outcome.DENY
    assert time.monotonic() - started < 1.0


def test_a_flood_of_prompts_is_refused_rather_than_shown():
    """Twenty dialogs a minute and people start clicking allow without reading."""
    notifier = Answering()
    queue = ApprovalQueue(notifier, timeout_sec=5, rate_limit_per_minute=3)

    outcomes = [queue.ask(**ASK).outcome for _ in range(5)]
    assert outcomes[:3] == [Outcome.ONCE] * 3
    assert outcomes[3:] == [Outcome.RATE_LIMITED] * 2
    assert len(notifier.presented) == 3


def test_answering_from_elsewhere_resolves_the_prompt():
    """The console and the CLI can answer a request the window is also showing."""
    notifier = Answering(outcome=None)
    queue = ApprovalQueue(notifier, timeout_sec=5)

    result: list = []
    thread = threading.Thread(target=lambda: result.append(queue.ask(**ASK)), daemon=True)
    thread.start()

    deadline = time.monotonic() + 3
    while not queue.pending() and time.monotonic() < deadline:
        time.sleep(0.01)

    [pending] = queue.pending()
    assert queue.respond(pending.id, Outcome.ONCE, "from the console")
    thread.join(timeout=3)

    assert result[0].outcome is Outcome.ONCE
    assert not queue.pending()


def test_answering_an_unknown_request_reports_failure():
    assert not ApprovalQueue(Answering(), timeout_sec=1).respond("a999", Outcome.ONCE)


def test_deny_all_clears_everything_waiting():
    """What the emergency button relies on: nothing is left hanging."""
    notifier = Answering(outcome=None)
    queue = ApprovalQueue(notifier, timeout_sec=10)

    threads = [threading.Thread(target=lambda: queue.ask(**ASK), daemon=True) for _ in range(3)]
    for thread in threads:
        thread.start()

    deadline = time.monotonic() + 3
    while len(queue.pending()) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)

    assert queue.deny_all("emergency stop") == 3
    for thread in threads:
        thread.join(timeout=3)
    assert not queue.pending()


def test_history_records_refusals_too():
    queue = ApprovalQueue(Answering(Outcome.DENY), timeout_sec=5)
    queue.ask(**ASK)
    [(request, decision)] = queue.history()
    assert request.tool == "shell" and decision.outcome is Outcome.DENY


def test_request_renders_multi_line_payloads_readably():
    notifier = Answering()
    queue = ApprovalQueue(notifier, timeout_sec=5)
    queue.ask(**{**ASK, "payload": {"diff": "line one\nline two"}})

    rendered = notifier.presented[0].render()
    assert "line one" in rendered and "line two" in rendered

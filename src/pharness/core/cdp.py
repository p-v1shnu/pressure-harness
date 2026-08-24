"""A small Chrome DevTools Protocol client.

CDP rather than screen-scraping because it is what the browser's own devtools
use: the agent sees the real DOM, the real console errors and the real network
failures, instead of guessing from a picture. That is the difference between an
agent that checks its work and one that reports what it hopes happened.

Written against the blocking websockets client on purpose. Everything else in
this codebase is synchronous, and an event loop smuggled in behind a sync
facade is a source of deadlocks nobody enjoys finding.
"""

from __future__ import annotations

import contextlib
import json
import threading
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

DEFAULT_PORT = 9222
EVENT_BUFFER = 500


class CdpError(Exception):
    pass


@dataclass(frozen=True)
class Target:
    id: str
    title: str
    url: str
    ws_url: str
    type: str = "page"


def _get_json(url: str, timeout: float, method: str = "GET") -> Any:
    """The DevTools HTTP endpoints, via the standard library.

    Two small requests do not justify a dependency, and every dependency is
    something a user has to install successfully before anything works.
    """
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise CdpError(f"the browser did not answer at {url}: {exc}") from exc


def list_targets(port: int = DEFAULT_PORT, host: str = "127.0.0.1", timeout: float = 5.0):
    """Ask the browser what pages it has open."""
    try:
        items = _get_json(f"http://{host}:{port}/json/list", timeout)
    except CdpError as exc:
        raise CdpError(
            f"no browser is listening on {host}:{port}. Launch one first. ({exc})"
        ) from exc

    return [
        Target(
            id=item.get("id", ""),
            title=item.get("title", ""),
            url=item.get("url", ""),
            ws_url=item.get("webSocketDebuggerUrl", ""),
            type=item.get("type", ""),
        )
        for item in items
        if item.get("webSocketDebuggerUrl")
    ]


def new_page(port: int = DEFAULT_PORT, host: str = "127.0.0.1", timeout: float = 5.0) -> Target:
    url = f"http://{host}:{port}/json/new"
    try:
        item = _get_json(url, timeout, method="PUT")
    except CdpError:
        # Older builds answer /json/new on GET instead of PUT.
        item = _get_json(url, timeout)
    return Target(
        id=item["id"],
        title=item.get("title", ""),
        url=item.get("url", ""),
        ws_url=item["webSocketDebuggerUrl"],
        type=item.get("type", "page"),
    )


class CdpSession:
    """One connection to one page.

    A reader thread drains the socket so replies and events never block each
    other, and events are kept in a bounded buffer -- a page that logs in a loop
    must not be able to exhaust memory just by being left open.
    """

    def __init__(self, ws_url: str, timeout: float = 15.0) -> None:
        from websockets.sync.client import connect

        self._timeout = timeout
        self._next_id = 0
        self._lock = threading.Lock()
        self._replies: dict[int, dict[str, Any]] = {}
        self._arrived = threading.Condition(self._lock)
        self._events: deque[dict[str, Any]] = deque(maxlen=EVENT_BUFFER)
        self._closed = threading.Event()

        try:
            self._ws = connect(ws_url, open_timeout=timeout, max_size=32 * 1024 * 1024)
        except Exception as exc:
            raise CdpError(f"could not connect to the page: {exc}") from exc

        self._reader = threading.Thread(target=self._read_loop, daemon=True, name="cdp-reader")
        self._reader.start()

    def _read_loop(self) -> None:
        while not self._closed.is_set():
            try:
                raw = self._ws.recv()
            except Exception:
                break
            try:
                message = json.loads(raw)
            except (TypeError, ValueError):
                continue

            with self._arrived:
                if "id" in message:
                    self._replies[message["id"]] = message
                    self._arrived.notify_all()
                elif "method" in message:
                    self._events.append(message)

    def send(self, method: str, params: dict[str, Any] | None = None, timeout: float | None = None):
        if self._closed.is_set():
            raise CdpError("the browser session is closed")

        with self._lock:
            self._next_id += 1
            message_id = self._next_id

        payload = {"id": message_id, "method": method, "params": params or {}}
        try:
            self._ws.send(json.dumps(payload))
        except Exception as exc:
            raise CdpError(f"could not send {method}: {exc}") from exc

        deadline = timeout if timeout is not None else self._timeout
        with self._arrived:
            if not self._arrived.wait_for(lambda: message_id in self._replies, timeout=deadline):
                raise CdpError(f"{method} did not answer within {deadline:.0f}s")
            reply = self._replies.pop(message_id)

        if "error" in reply:
            raise CdpError(f"{method}: {reply['error'].get('message', reply['error'])}")
        return reply.get("result", {})

    def events(self, prefix: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            collected = [
                event
                for event in self._events
                if prefix is None or str(event.get("method", "")).startswith(prefix)
            ]
        return collected[-limit:]

    def clear_events(self) -> None:
        with self._lock:
            self._events.clear()

    def close(self) -> None:
        self._closed.set()
        with contextlib.suppress(Exception):  # closing twice is fine
            self._ws.close()

    def __enter__(self) -> CdpSession:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@contextmanager
def page_session(
    port: int = DEFAULT_PORT, host: str = "127.0.0.1", target_id: str | None = None
) -> Iterator[CdpSession]:
    targets = [t for t in list_targets(port, host) if t.type == "page"]
    if target_id:
        targets = [t for t in targets if t.id == target_id]
    if not targets:
        raise CdpError("the browser has no page open")

    session = CdpSession(targets[0].ws_url)
    try:
        yield session
    finally:
        session.close()

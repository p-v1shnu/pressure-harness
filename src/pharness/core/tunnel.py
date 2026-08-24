"""Publishing the local server through an outbound tunnel.

Outbound-only, and that is the whole point: nothing is opened on the router and
no port is exposed. The tunnel is a connection this machine makes and holds,
which is the difference between phoning someone and leaving the front door open
(PRD 7).

The tunnel is managed here rather than by a script the user runs alongside,
so the app knows its own address -- which it must, because the OAuth issuer has
to be the URL clients actually reach.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from pharness.ports import ProcessPort, ProcessStartError

# Each provider announces its address on stdout in its own format.
PROVIDERS: dict[str, tuple[list[str], re.Pattern[str]]] = {
    "cloudflared": (
        ["tunnel", "--url", "http://127.0.0.1:{port}"],
        re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com"),
    ),
    "ngrok": (
        ["http", "{port}", "--log", "stdout"],
        re.compile(r"https://[a-z0-9-]+\.ngrok(?:-free)?\.(?:app|io)"),
    ),
}

START_TIMEOUT_SEC = 45.0


class TunnelError(Exception):
    pass


@dataclass
class TunnelStatus:
    running: bool
    provider: str
    url: str | None = None
    process_id: str | None = None
    detail: str = ""

    @property
    def summary(self) -> str:
        if not self.running:
            return f"tunnel is not running{f' ({self.detail})' if self.detail else ''}"
        return f"{self.provider} tunnel is up at {self.url}"


@dataclass
class TunnelManager:
    process: ProcessPort
    cwd: Path
    env: dict[str, str]
    provider: str = "cloudflared"
    _handle: object | None = field(default=None, repr=False)
    _url: str | None = field(default=None, repr=False)

    def status(self) -> TunnelStatus:
        running = self._handle is not None and self._handle.is_running()
        if not running and self._handle is not None:
            return TunnelStatus(
                False, self.provider, detail=f"it exited {self._handle.exit_code()}"
            )
        return TunnelStatus(
            running,
            self.provider,
            self._url,
            getattr(self._handle, "id", None) if running else None,
        )

    def start(self, port: int, timeout_sec: float = START_TIMEOUT_SEC) -> TunnelStatus:
        if self.status().running:
            return self.status()

        if self.provider not in PROVIDERS:
            raise TunnelError(
                f"unknown tunnel provider {self.provider!r}; expected one of {', '.join(PROVIDERS)}"
            )

        template, pattern = PROVIDERS[self.provider]
        argv = [self.provider, *[part.format(port=port) for part in template]]
        try:
            handle = self.process.spawn(argv, self.cwd, self.env, label="tunnel")
        except ProcessStartError as exc:
            raise TunnelError(
                f"{exc}. Install it first, for example: winget install --id Cloudflare.cloudflared"
            ) from exc
        self._handle = handle

        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if not handle.is_running():
                # Almost always "command not found" or a login problem, and the
                # provider's own message says which.
                raise TunnelError(
                    f"{self.provider} stopped before publishing an address:\n{handle.tail(15)}"
                )
            match = pattern.search(handle.tail(80))
            if match:
                self._url = match.group(0)
                return self.status()
            time.sleep(0.3)

        handle.stop()
        raise TunnelError(
            f"{self.provider} did not publish an address within {timeout_sec:.0f}s:\n"
            f"{handle.tail(15)}"
        )

    def stop(self) -> TunnelStatus:
        if self._handle is not None and self._handle.is_running():
            self._handle.stop()
        self._handle = None
        self._url = None
        return TunnelStatus(False, self.provider, detail="stopped")

"""Fetching a URL from this machine.

Two separate risks, both handled here rather than left to the caller.

Reaching inside the network: a request made from the user's machine can touch
things the internet cannot -- a cloud metadata endpoint, a router admin page, an
internal service. So every address is resolved and checked before the request is
made, and again after each redirect, since a redirect is just a second address.

Bringing content back: whatever a page says arrives inside the conversation, so
it is wrapped as data and capped. A page the model was told to read can contain
anything, including instructions addressed to it (PRD 10.5).
"""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

from pharness.core.config import ContextSettings
from pharness.core.text import clamp, wrap_external
from pharness.core.tools.results import ToolResult

MAX_BYTES = 512 * 1024
MAX_REDIRECTS = 3
TIMEOUT = 20.0


_TAGS = re.compile(r"<(script|style)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
_MARKUP = re.compile(r"<[^>]+>")
_BLANKS = re.compile(r"\n{3,}")


class BlockedAddress(Exception):
    pass


def _check_address(host: str) -> None:
    """Refuse anything that is not a public address.

    Loopback included: local services are reached with the browser tool, which
    is visible and deliberate, rather than by a fetch that looks like it went to
    the internet.
    """
    if not host:
        raise BlockedAddress("the URL has no host")

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise BlockedAddress(f"{host} does not resolve ({exc})") from exc

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise BlockedAddress(
                f"{host} resolves to {address}, which is inside the network rather than "
                "on the internet"
            )


def html_to_text(body: str) -> str:
    body = _TAGS.sub(" ", body)
    body = _MARKUP.sub(" ", body)
    body = body.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
    body = body.replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
    lines = [line.strip() for line in body.splitlines()]
    return _BLANKS.sub("\n\n", "\n".join(line for line in lines if line))


@dataclass
class WebTools:
    context: ContextSettings
    allowlist: tuple[str, ...] = ()

    def _allowed(self, host: str) -> bool:
        host = host.lower()
        return any(host == entry or host.endswith(f".{entry}") for entry in self.allowlist)

    def fetch(self, url: str, max_bytes: int = MAX_BYTES) -> ToolResult:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return ToolResult.failure("only http and https URLs can be fetched")

        host = (parsed.hostname or "").lower()
        if not self._allowed(host):
            listed = ", ".join(self.allowlist) or "nothing yet"
            return ToolResult.failure(
                f"{host} is not on the fetch allowlist (currently: {listed}). "
                "The owner adds hosts from the console."
            )

        current = url
        for _ in range(MAX_REDIRECTS + 1):
            try:
                _check_address(urlparse(current).hostname or "")
            except BlockedAddress as exc:
                return ToolResult.failure(str(exc))

            request = urllib.request.Request(
                current, headers={"User-Agent": "PressureHarness/0.1", "Accept": "*/*"}
            )
            try:
                opener = urllib.request.build_opener(_NoRedirect)
                with opener.open(request, timeout=TIMEOUT) as response:
                    status = response.status
                    location = response.headers.get("Location")
                    content_type = response.headers.get("Content-Type", "")
                    raw = response.read(max_bytes + 1)
            except urllib.error.HTTPError as exc:
                status, location = exc.code, exc.headers.get("Location")
                content_type = exc.headers.get("Content-Type", "")
                raw = exc.read(max_bytes + 1)
            except (urllib.error.URLError, OSError, ValueError) as exc:
                return ToolResult.failure(f"could not fetch {current}: {exc}")

            if status in (301, 302, 303, 307, 308) and location:
                # A redirect is a new address, so it is checked like a new
                # request rather than trusted because the first one passed.
                current = urllib.parse.urljoin(current, location)
                parsed = urlparse(current)
                if not self._allowed((parsed.hostname or "").lower()):
                    return ToolResult.failure(
                        f"the redirect to {parsed.hostname} is not on the allowlist"
                    )
                continue
            break
        else:
            return ToolResult.failure("too many redirects")

        truncated = len(raw) > max_bytes
        text = raw[:max_bytes].decode("utf-8", errors="replace")
        if "html" in content_type.lower():
            text = html_to_text(text)

        body = clamp(text, self.context.max_output_bytes).text
        if truncated:
            body += f"\n[stopped after {max_bytes} bytes]"

        return ToolResult(
            text=wrap_external(body, current),
            ok=status < 400,
            meta={"status": status, "url": current, "content_type": content_type},
        )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirects are followed by us, one at a time, with a check between."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

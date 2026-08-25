"""Driving a browser so the agent can check its own work.

This is the difference the whole scope decision turned on: with it, a change is
made, loaded, clicked and read back; without it, the agent reports what it hopes
happened. The console and the network log matter as much as the screenshot --
"TypeError: onSubmit is not a function" is the answer, the picture is just
corroboration.

Everything talks to a browser we launched with a profile directory of our own.
Attaching to the user's everyday Chrome would put their logged-in sessions
inside the blast radius of whatever the model does next.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from pharness.core.cdp import CdpError, CdpSession, list_targets, new_page
from pharness.core.config import ContextSettings
from pharness.core.errors import PathJailError
from pharness.core.policy.path_jail import PathJail
from pharness.core.text import clamp, wrap_external
from pharness.core.tools.results import ToolResult
from pharness.core.workspace import Workspace
from pharness.ports import ProcessStartError

LOAD_SETTLE_SEC = 0.4
MAX_TEXT_CHARS = 4000


# Schemes the browser may be pointed at. Everything else -- view-source:,
# chrome:, filesystem: -- either reads local state or exposes the browser's own
# internals, and none of it is what "open the page you just changed" means.
ALLOWED_SCHEMES = frozenset({"http", "https", "file", "about", "data"})


def _is_local(url: str) -> bool:
    """True for an address on this machine, which never needs the allowlist.

    `file://` is deliberately excluded: a local file is not a local *server*,
    and treating it as one is how the path jail gets bypassed.
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() == "file":
        return False
    host = (parsed.hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "")


@dataclass
class BrowserTools:
    workspace: Workspace
    context: ContextSettings
    locator: object
    process: object
    env: dict[str, str]
    data_dir: Path
    port: int = 9222
    allowlist: tuple[str, ...] = ()
    jail: PathJail | None = None
    """Without one, `file://` URLs cannot be opened at all."""
    _session: CdpSession | None = field(default=None, repr=False)

    # -- connection --------------------------------------------------------

    def launch(self, headless: bool = False) -> ToolResult:
        try:
            if list_targets(self.port):
                return ToolResult(
                    text=f"a browser is already listening on port {self.port}",
                    meta={"port": self.port, "started": False},
                )
        except CdpError:
            pass  # nothing there yet, which is the normal case

        executable = self.locator.find_executable()
        if executable is None:
            return ToolResult.failure(
                "no Chrome or Chromium was found. Install one, or set PHARNESS_BROWSER to its path."
            )

        profile = self.locator.default_profile_dir(self.data_dir)
        profile.mkdir(parents=True, exist_ok=True)
        argv = [
            str(executable),
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "about:blank",
        ]
        if headless:
            argv.insert(1, "--headless=new")

        # Extra flags come from the environment rather than being baked in.
        # Containers usually need --no-sandbox, and the sandbox is a real
        # boundary: weakening it for everyone to make one setup work is the
        # wrong trade. Whoever needs it asks for it.
        extra = self.env.get("PHARNESS_BROWSER_ARGS", "").split()
        argv[1:1] = extra

        try:
            handle = self.process.spawn(argv, self.workspace.root, self.env, label="browser")
        except ProcessStartError as exc:
            return ToolResult.failure(str(exc))

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                if list_targets(self.port):
                    return ToolResult(
                        text=f"browser started on port {self.port} with its own profile",
                        meta={"port": self.port, "process_id": handle.id, "started": True},
                    )
            except CdpError:
                time.sleep(0.25)

        # Say why. The browser prints a precise reason ("Running as root without
        # --no-sandbox is not supported") and hiding it leaves the user with
        # nothing to act on.
        reason = handle.tail(12).strip()
        message = "the browser started but never opened a debugging port"
        if reason:
            message += f"\nit said:\n{reason}"
        return ToolResult.failure(message)

    def _connect(self) -> CdpSession:
        if self._session is not None and not self._session._closed.is_set():
            return self._session

        pages = [target for target in list_targets(self.port) if target.type == "page"]
        target = pages[0] if pages else new_page(self.port)

        session = CdpSession(target.ws_url)
        for domain in ("Page", "Runtime", "Log", "Network"):
            try:
                session.send(f"{domain}.enable")
            except CdpError:
                continue  # an old build without one domain should not stop the rest
        self._session = session
        return session

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    # -- acting ------------------------------------------------------------

    def check_url(self, url: str) -> str | None:
        """Why this URL may not be opened, or None.

        Found by reviewing the finished code: `file://` counted as a local
        address, so the browser could open any file on the machine and report
        its contents -- everything the path jail exists to prevent, one tool
        over. Files now face the same jail as read_file does.
        """
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()

        if not scheme:
            return "give a full URL, including http:// or file://"
        if scheme not in ALLOWED_SCHEMES:
            return f"{scheme}: URLs cannot be opened"

        if scheme == "file":
            if self.jail is None:
                return "this browser cannot open local files"
            try:
                self.jail.check_absolute(self.workspace, Path(url2pathname(parsed.path)))
            except (PathJailError, ValueError, OSError) as exc:
                return str(exc)
            return None

        if scheme in ("about", "data") or _is_local(url):
            return None

        host = (parsed.hostname or "").lower()
        if not any(host == entry or host.endswith(f".{entry}") for entry in self.allowlist):
            return (
                f"{host or url} is not in this workspace's allowed hosts. "
                "Addresses on this machine are always allowed."
            )
        return None

    def navigate(self, url: str, wait_sec: float = 5.0) -> ToolResult:
        refusal = self.check_url(url)
        if refusal is not None:
            return ToolResult.failure(refusal)

        try:
            session = self._connect()
            session.clear_events()
            session.send("Page.navigate", {"url": url}, timeout=wait_sec + 5)
        except CdpError as exc:
            return ToolResult.failure(str(exc))

        deadline = time.monotonic() + wait_sec
        while time.monotonic() < deadline:
            if session.events("Page.loadEventFired"):
                break
            time.sleep(0.1)
        time.sleep(LOAD_SETTLE_SEC)

        failures = [
            event.get("params", {}).get("errorText", "")
            for event in session.events("Network.loadingFailed", limit=20)
        ]
        if failures:
            # Saying "loaded" when nothing loaded sends the model looking for a
            # bug in the page instead of at the server that never answered.
            return ToolResult.failure(
                f"{url} did not load: {failures[-1]}. Is the dev server running?",
                url=url,
            )

        title = self._eval_value(session, "document.title") or "(no title)"
        errors = self._console_errors(session)
        summary = f"loaded {url}\ntitle: {title}"
        if errors:
            summary += f"\n{len(errors)} console error(s) — read them with browser console"
        return ToolResult(text=summary, meta={"url": url, "console_errors": len(errors)})

    def snapshot(self, selector: str = "body") -> ToolResult:
        """Text and interactive elements, not raw HTML.

        Raw HTML is mostly attributes and closing tags: it costs a great deal of
        the conversation's budget to say very little (PRD 11).
        """
        script = f"""
        (() => {{
          const root = document.querySelector({selector!r});
          if (!root) return JSON.stringify({{missing: true}});
          const selector = 'a,button,input,select,textarea,[role=button]';
          const controls = [...root.querySelectorAll(selector)]
            .slice(0, 60)
            .map(el => ({{
              tag: el.tagName.toLowerCase(),
              text: (el.innerText || el.value || el.placeholder || '').trim().slice(0, 60),
              id: el.id || undefined,
              name: el.getAttribute('name') || undefined,
              testid: el.getAttribute('data-testid') || undefined,
            }}));
          return JSON.stringify({{
            title: document.title,
            url: location.href,
            text: (root.innerText || '').slice(0, {MAX_TEXT_CHARS}),
            controls,
          }});
        }})()
        """
        try:
            raw = self._eval_value(self._connect(), script)
        except CdpError as exc:
            return ToolResult.failure(str(exc))

        import json

        try:
            data = json.loads(raw or "{}")
        except ValueError:
            return ToolResult.failure("the page could not be read")
        if data.get("missing"):
            return ToolResult.failure(f"no element matches {selector!r}")

        lines = [f"url: {data.get('url')}", f"title: {data.get('title')}", "", "interactive:"]
        for control in data.get("controls", []):
            handle = control.get("id") or control.get("testid") or control.get("name") or ""
            lines.append(f"  <{control['tag']}> {control.get('text', '')!r} {handle}".rstrip())
        lines += ["", wrap_external(data.get("text", ""), "the page")]

        excerpt = clamp("\n".join(lines), self.context.max_output_bytes)
        return ToolResult(text=excerpt.text, meta={"url": data.get("url")})

    def click(self, selector: str) -> ToolResult:
        script = f"""
        (() => {{
          const el = document.querySelector({selector!r});
          if (!el) return 'missing';
          el.scrollIntoView({{block: 'center'}});
          el.click();
          return 'clicked';
        }})()
        """
        return self._act(script, selector, "clicked", "click")

    def type_text(self, selector: str, text: str) -> ToolResult:
        script = f"""
        (() => {{
          const el = document.querySelector({selector!r});
          if (!el) return 'missing';
          el.focus();
          el.value = {text!r};
          el.dispatchEvent(new Event('input', {{bubbles: true}}));
          el.dispatchEvent(new Event('change', {{bubbles: true}}));
          return 'typed';
        }})()
        """
        return self._act(script, selector, "typed", "type into")

    def _act(self, script: str, selector: str, expected: str, verb: str) -> ToolResult:
        try:
            session = self._connect()
            outcome = self._eval_value(session, script)
        except CdpError as exc:
            return ToolResult.failure(str(exc))

        if outcome == "missing":
            return ToolResult.failure(f"no element matches {selector!r}")

        time.sleep(LOAD_SETTLE_SEC)
        errors = self._console_errors(session)
        text = f"{expected} {selector}"
        if errors:
            text += f"\n{len(errors)} console error(s) since:\n" + "\n".join(errors[:5])
        return ToolResult(text=text, meta={"selector": selector, "console_errors": len(errors)})

    def evaluate(self, expression: str) -> ToolResult:
        try:
            session = self._connect()
            result = session.send(
                "Runtime.evaluate",
                {"expression": expression, "returnByValue": True, "awaitPromise": True},
            )
        except CdpError as exc:
            return ToolResult.failure(str(exc))

        if "exceptionDetails" in result:
            return ToolResult.failure(_exception_text(result["exceptionDetails"]))

        value = result.get("result", {}).get("value")
        rendered = value if isinstance(value, str) else repr(value)
        return ToolResult(text=wrap_external(clamp(rendered, 4096).text, "the page"))

    # -- observing ---------------------------------------------------------

    def console(self, limit: int = 30) -> ToolResult:
        try:
            session = self._connect()
        except CdpError as exc:
            return ToolResult.failure(str(exc))

        lines: list[str] = []
        for event in session.events("Runtime.consoleAPICalled", limit=limit):
            params = event.get("params", {})
            args = " ".join(_render_arg(arg) for arg in params.get("args", []))
            lines.append(f"[{params.get('type', 'log')}] {args}")
        for event in session.events("Log.entryAdded", limit=limit):
            entry = event.get("params", {}).get("entry", {})
            lines.append(f"[{entry.get('level', 'info')}] {entry.get('text', '')}")
        # Uncaught exceptions arrive as their own event, not as console calls,
        # and they are usually the thing worth reading.
        for event in session.events("Runtime.exceptionThrown", limit=limit):
            details = event.get("params", {}).get("exceptionDetails", {})
            lines.append(f"[uncaught] {_exception_text(details)}")

        if not lines:
            return ToolResult(text="the console is empty", meta={"messages": 0})
        excerpt = clamp(
            wrap_external("\n".join(lines[-limit:]), "the browser console"),
            self.context.max_output_bytes,
        )
        return ToolResult(text=excerpt.text, meta={"messages": len(lines)})

    def network(self, limit: int = 30) -> ToolResult:
        try:
            session = self._connect()
        except CdpError as exc:
            return ToolResult.failure(str(exc))

        lines: list[str] = []
        for event in session.events("Network.responseReceived", limit=200):
            response = event.get("params", {}).get("response", {})
            status = response.get("status", 0)
            if status >= 400:
                lines.append(f"{status} {response.get('url', '')[:120]}")
        for event in session.events("Network.loadingFailed", limit=200):
            params = event.get("params", {})
            lines.append(f"failed {params.get('errorText', '')} {params.get('type', '')}")

        if not lines:
            return ToolResult(text="no failed requests", meta={"failures": 0})
        return ToolResult(text="\n".join(lines[-limit:]), meta={"failures": len(lines)})

    def screenshot(self, name: str = "screenshot.png", full_page: bool = False) -> ToolResult:
        """Save a PNG and return where it went.

        A path rather than an image because whether a client renders image
        content from a tool is still an open question (PRD 20, OQ-2). Saving it
        works everywhere; returning it may not.
        """
        try:
            session = self._connect()
            result = session.send(
                "Page.captureScreenshot",
                {"format": "png", "captureBeyondViewport": full_page},
                timeout=30,
            )
        except CdpError as exc:
            return ToolResult.failure(str(exc))

        target = self.data_dir / "screenshots" / Path(name).name
        target.parent.mkdir(parents=True, exist_ok=True)
        data = base64.b64decode(result["data"])
        target.write_bytes(data)

        return ToolResult(
            text=f"saved {target} ({len(data)} bytes)",
            meta={"path": str(target), "bytes": len(data)},
        )

    # -- helpers -----------------------------------------------------------

    def _eval_value(self, session: CdpSession, expression: str) -> str | None:
        result = session.send("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        value = result.get("result", {}).get("value")
        return value if isinstance(value, str) else (None if value is None else str(value))

    def _console_errors(self, session: CdpSession) -> list[str]:
        errors: list[str] = []
        for event in session.events("Runtime.consoleAPICalled", limit=100):
            params = event.get("params", {})
            if params.get("type") in ("error", "assert"):
                errors.append(" ".join(_render_arg(arg) for arg in params.get("args", [])))
        for event in session.events("Runtime.exceptionThrown", limit=100):
            errors.append(_exception_text(event.get("params", {}).get("exceptionDetails", {})))
        return errors


def _exception_text(details: dict) -> str:
    """The useful half of a CDP exception.

    `text` is usually just "Uncaught"; the message and stack live under
    `exception.description`, and the message is the whole point of asking.
    """
    description = details.get("exception", {}).get("description")
    if description:
        return str(description).splitlines()[0]
    return details.get("text") or "the expression threw"


def _render_arg(arg: dict) -> str:
    if "value" in arg:
        return str(arg["value"])
    return str(arg.get("description", arg.get("type", "")))

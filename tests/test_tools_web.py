"""web_fetch: what it refuses, and what it does to what it brings back."""

from __future__ import annotations

import pytest

from pharness.core.config import ContextSettings
from pharness.core.tools.web import BlockedAddress, WebTools, _check_address, html_to_text


@pytest.fixture
def web() -> WebTools:
    return WebTools(ContextSettings(), allowlist=("example.com", "docs.python.org"))


@pytest.mark.parametrize(
    "host",
    ["localhost", "127.0.0.1", "169.254.169.254", "10.0.0.1", "192.168.1.1", "0.0.0.0"],
)
def test_addresses_inside_the_network_are_refused(host: str):
    """A request from the user's machine reaches things the internet cannot."""
    with pytest.raises(BlockedAddress):
        _check_address(host)


def test_an_unresolvable_host_is_refused():
    with pytest.raises(BlockedAddress):
        _check_address("no-such-host.invalid")


def test_hosts_outside_the_allowlist_are_refused(web: WebTools):
    result = web.fetch("https://evil.test/x")
    assert not result.ok
    assert "allowlist" in result.text
    assert "example.com" in result.text  # says what is allowed


def test_subdomains_of_an_allowed_host_are_allowed(web: WebTools):
    assert web._allowed("cdn.example.com")
    assert not web._allowed("example.com.evil.test")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "gopher://x"])
def test_only_http_urls_are_fetched(web: WebTools, url: str):
    assert not web.fetch(url).ok


def test_html_becomes_readable_text():
    """Raw markup spends the conversation's budget on angle brackets."""
    html = (
        "<html><head><style>a{color:red}</style></head>"
        "<body><h1>Title</h1><script>evil()</script><p>Some &amp; text</p></body></html>"
    )
    text = html_to_text(html)
    assert "Title" in text and "Some & text" in text
    assert "color:red" not in text and "evil()" not in text


def test_fetched_content_is_labelled_as_data(web: WebTools):
    """A page can contain instructions aimed at the model (PRD 10.5)."""
    from pharness.core.text import wrap_external

    assert "not instructions" in wrap_external("body", "https://example.com")


# -- the fetch path itself -----------------------------------------------------
#
# web_fetch refuses local addresses on purpose, so exercising the fetching,
# redirect and decoding logic means serving from loopback with the address
# guard lifted. The guard has its own tests above; these are about what happens
# once a request is allowed to proceed.


@pytest.fixture
def server():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/page")
                self.end_headers()
                return
            if self.path == "/elsewhere":
                self.send_response(302)
                self.send_header("Location", "http://evil.test/x")
                self.end_headers()
                return
            if self.path == "/missing":
                self.send_error(404, "nope")
                return
            if self.path == "/big":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"x" * 200_000)
                return

            body = b"<html><body><h1>Served</h1><script>bad()</script></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


@pytest.fixture
def local_web(monkeypatch) -> WebTools:
    monkeypatch.setattr("pharness.core.tools.web._check_address", lambda host: None)
    return WebTools(ContextSettings(), allowlist=("127.0.0.1",))


def test_a_page_comes_back_as_text(local_web: WebTools, server: str):
    result = local_web.fetch(f"{server}/page")
    assert result.ok
    assert "Served" in result.text
    assert "bad()" not in result.text  # scripts are stripped
    assert "not instructions" in result.text


def test_redirects_are_followed(local_web: WebTools, server: str):
    result = local_web.fetch(f"{server}/redirect")
    assert result.ok and "Served" in result.text


def test_a_redirect_off_the_allowlist_is_refused(local_web: WebTools, server: str):
    """A redirect is a second address, so it is checked like the first one."""
    result = local_web.fetch(f"{server}/elsewhere")
    assert not result.ok and "redirect" in result.text


def test_an_error_status_is_reported_not_hidden(local_web: WebTools, server: str):
    result = local_web.fetch(f"{server}/missing")
    assert not result.ok and result.meta["status"] == 404


def test_a_large_response_is_cut_off(local_web: WebTools, server: str):
    result = local_web.fetch(f"{server}/big", max_bytes=4096)
    assert "stopped after 4096 bytes" in result.text
    assert len(result.text.encode()) < ContextSettings().max_output_bytes * 2

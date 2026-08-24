"""Browser tools.

The ones needing a browser skip when there is not one; the rest -- discovery,
the allowlist, how a page's content is labelled -- run everywhere.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from pharness.adapters import select
from pharness.adapters.shared.browser import BrowserLocator
from pharness.core.config import ContextSettings, parse_config
from pharness.core.env import build_env
from pharness.core.tools.browser import EXTERNAL, BrowserTools, _is_local
from pharness.core.workspace import WorkspaceRegistry

PAGE = (
    "<!doctype html><title>Checkout</title>"
    "<h1>Checkout page</h1>"
    "<input id='email' placeholder='email'>"
    "<button id='pay' onclick='onSubmit()'>Pay now</button>"
    "<script>console.log('page ready')</script>"
)

has_browser = pytest.mark.skipif(
    BrowserLocator(select().platform).find_executable() is None,
    reason="no Chromium-family browser on this machine",
)


@pytest.fixture
def browser(tmp_path: Path) -> BrowserTools:
    adapters = select()
    root = tmp_path / "proj"
    root.mkdir()
    (root / "index.html").write_text(PAGE, encoding="utf-8")

    registry = WorkspaceRegistry.from_config(
        parse_config({"workspace": [{"alias": "p", "path": str(root)}]}), adapters.paths
    )
    tools = BrowserTools(
        workspace=registry.get("p"),
        context=ContextSettings(),
        locator=adapters.browser,
        process=adapters.process_factory(tmp_path / "logs"),
        env=build_env(os.environ, adapters.platform),
        data_dir=tmp_path / "data",
        port=int(os.environ.get("PHARNESS_TEST_CDP_PORT", "9222")),
        allowlist=("example.com",),
    )
    yield tools
    tools.close()


# -- no browser needed ---------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "local"),
    [
        ("http://localhost:3000/x", True),
        ("http://127.0.0.1:5173", True),
        ("file:///tmp/x.html", True),
        ("https://example.com/x", False),
    ],
)
def test_local_addresses_are_recognised(url: str, local: bool):
    assert _is_local(url) is local


def test_page_content_is_labelled_as_data():
    """A page the model was told to open can contain instructions (PRD 10.5)."""
    assert "not instructions" in EXTERNAL


def test_a_missing_browser_is_reported_not_raised(tmp_path: Path, browser: BrowserTools):
    class Nothing:
        def find_executable(self):
            return None

        def default_profile_dir(self, data_dir):
            return data_dir / "profile"

    browser.locator = Nothing()
    browser.port = 65500  # nothing is listening here
    result = browser.launch()
    assert not result.ok and "PHARNESS_BROWSER" in result.text


def test_navigating_off_the_allowlist_is_refused(browser: BrowserTools):
    result = browser.navigate("https://not-allowed.test/page")
    assert not result.ok and "allowed hosts" in result.text


# -- a real browser ------------------------------------------------------------


@has_browser
def test_the_whole_loop(browser: BrowserTools):
    """The reason browser control is in scope at all (PRD 13).

    Load the page, press the button, and read the error the page really threw
    rather than guessing whether the change worked.
    """
    assert browser.launch(headless=True).ok

    page = (browser.workspace.root / "index.html").as_uri()
    loaded = browser.navigate(page)
    assert loaded.ok and "Checkout" in loaded.text

    snapshot = browser.snapshot()
    assert "pay" in snapshot.text and "Checkout page" in snapshot.text
    assert "not instructions" in snapshot.text

    assert browser.type_text("#email", "someone@example.com").ok

    clicked = browser.click("#pay")
    assert clicked.ok
    assert clicked.meta["console_errors"] >= 1
    assert "onSubmit is not defined" in clicked.text

    console = browser.console()
    assert "onSubmit is not defined" in console.text

    shot = browser.screenshot("test-shot.png")
    assert shot.ok
    saved = Path(shot.meta["path"])
    assert saved.is_file() and saved.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


@has_browser
def test_a_missing_selector_is_reported(browser: BrowserTools):
    browser.launch(headless=True)
    browser.navigate((browser.workspace.root / "index.html").as_uri())
    assert not browser.click("#not-there").ok
    assert not browser.type_text("#not-there", "x").ok


@has_browser
def test_eval_returns_values_and_reports_exceptions(browser: BrowserTools):
    browser.launch(headless=True)
    browser.navigate((browser.workspace.root / "index.html").as_uri())

    assert "Checkout" in browser.evaluate("document.title").text

    failed = browser.evaluate("noSuchFunction()")
    assert not failed.ok
    assert "not defined" in failed.text


@has_browser
def test_launching_twice_reuses_the_running_browser(browser: BrowserTools):
    browser.launch(headless=True)
    again = browser.launch(headless=True)
    assert again.ok and again.meta["started"] is False


@has_browser
def test_network_failures_are_visible(browser: BrowserTools):
    browser.launch(headless=True)
    browser.navigate((browser.workspace.root / "index.html").as_uri())
    browser.evaluate("fetch('http://127.0.0.1:9/missing').catch(() => {})")
    time.sleep(0.6)
    assert browser.network().ok


@has_browser
def test_a_page_that_did_not_load_is_reported_as_a_failure(browser: BrowserTools):
    """Saying "loaded" when nothing loaded sends the model hunting the wrong bug."""
    browser.launch(headless=True)
    result = browser.navigate("http://127.0.0.1:9/never-listening")
    assert not result.ok
    assert "did not load" in result.text
    assert "dev server" in result.text

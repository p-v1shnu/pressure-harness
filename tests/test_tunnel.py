"""The tunnel manager, exercised with a stand-in binary.

cloudflared is not installed on a test runner, and the interesting behaviour is
ours anyway: waiting for the address, noticing a failure, and reporting what the
provider actually said.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from pharness.adapters import select
from pharness.core.env import build_env
from pharness.core.tunnel import TunnelError, TunnelManager

ANNOUNCES = """import sys, time
print("starting", " ".join(sys.argv[1:]), flush=True)
print("+-----------------------------------------+", flush=True)
print("|  https://brave-lion-42.trycloudflare.com |", flush=True)
while True:
    time.sleep(0.2)
"""

SILENT = "import time\nwhile True: time.sleep(0.2)\n"

FAILS = "import sys\nsys.stderr.write('ERROR: authtoken required\\n')\nsys.exit(1)\n"


@pytest.fixture
def fake_bin(tmp_path: Path):
    """Install a script under the name of a tunnel provider, on a private PATH."""
    bindir = tmp_path / "bin"
    bindir.mkdir()

    def install(name: str, body: str) -> None:
        script = bindir / name
        script.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

    install.dir = bindir  # type: ignore[attr-defined]
    return install


@pytest.fixture
def manager(tmp_path: Path, fake_bin):
    adapters = select()
    env = build_env(
        os.environ,
        adapters.platform,
        overrides={"PATH": f"{fake_bin.dir}{os.pathsep}{os.environ.get('PATH', '')}"},
    )
    made = TunnelManager(
        adapters.process_factory(tmp_path / "logs"), tmp_path, env, provider="cloudflared"
    )
    yield made
    made.stop()


@pytest.mark.skipif(os.name == "nt", reason="the stand-in relies on a shebang")
def test_it_waits_for_the_address(manager, fake_bin):
    fake_bin("cloudflared", ANNOUNCES)

    status = manager.start(18765, timeout_sec=15)
    assert status.running
    assert status.url == "https://brave-lion-42.trycloudflare.com"
    assert "is up at" in status.summary


@pytest.mark.skipif(os.name == "nt", reason="the stand-in relies on a shebang")
def test_starting_twice_is_harmless(manager, fake_bin):
    fake_bin("cloudflared", ANNOUNCES)
    first = manager.start(18765, timeout_sec=15)
    assert manager.start(18765).url == first.url


@pytest.mark.skipif(os.name == "nt", reason="the stand-in relies on a shebang")
def test_a_provider_that_exits_reports_what_it_said(manager, fake_bin):
    """ "It failed" is useless; "authtoken required" is the answer."""
    fake_bin("cloudflared", FAILS)

    with pytest.raises(TunnelError, match="authtoken required"):
        manager.start(18765, timeout_sec=10)


@pytest.mark.skipif(os.name == "nt", reason="the stand-in relies on a shebang")
def test_a_provider_that_never_announces_times_out(manager, fake_bin):
    fake_bin("cloudflared", SILENT)

    with pytest.raises(TunnelError, match="did not publish an address"):
        manager.start(18765, timeout_sec=1)


def test_an_unknown_provider_is_refused(manager):
    manager.provider = "not-a-tunnel"
    with pytest.raises(TunnelError, match="unknown tunnel provider"):
        manager.start(18765)


def test_a_missing_binary_is_reported(manager, tmp_path: Path):
    with pytest.raises(TunnelError):
        manager.start(18765, timeout_sec=5)


@pytest.mark.skipif(os.name == "nt", reason="the stand-in relies on a shebang")
def test_stopping_clears_the_address(manager, fake_bin):
    fake_bin("cloudflared", ANNOUNCES)
    manager.start(18765, timeout_sec=15)

    stopped = manager.stop()
    assert not stopped.running and manager.status().url is None

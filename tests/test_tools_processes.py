"""Process tools: what is running, what it printed, and stopping it."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from pharness.adapters import select
from pharness.core.config import ContextSettings
from pharness.core.env import build_env
from pharness.core.tools import ProcessTools


@pytest.fixture
def tools(tmp_path: Path) -> ProcessTools:
    adapters = select()
    return ProcessTools(adapters.process_factory(tmp_path / "logs"), ContextSettings())


@pytest.fixture
def env() -> dict[str, str]:
    return build_env(os.environ, select().platform)


def test_nothing_running_says_so(tools: ProcessTools):
    assert "nothing is running" in tools.list().text


def test_unknown_process_ids_are_reported(tools: ProcessTools):
    assert not tools.logs("p999").ok
    assert not tools.stop("p999").ok


def test_finished_processes_stay_listed(tools: ProcessTools, env, tmp_path: Path):
    """ "Why did it stop" is the next question, so exited processes are not forgotten."""
    handle = tools.process.spawn([sys.executable, "-c", "print('done')"], tmp_path, env)
    handle._popen.wait(timeout=10)

    listing = tools.list()
    assert handle.id in listing.text
    assert "exited" in listing.text

    assert tools.stop(handle.id).ok is True
    assert "already exited" in tools.stop(handle.id).text


def test_logs_are_capped_to_the_budget(tools: ProcessTools, env, tmp_path: Path):
    tools.context = ContextSettings(max_output_bytes=512)
    handle = tools.process.spawn(
        [sys.executable, "-c", "[print('x' * 100) for _ in range(2000)]"], tmp_path, env
    )
    handle._popen.wait(timeout=20)

    result = tools.logs(handle.id, lines=500)
    assert len(result.text.encode()) < 1200


def test_stop_all_clears_everything(tools: ProcessTools, env, tmp_path: Path):
    for _ in range(2):
        tools.process.spawn([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, env)
    assert tools.stop_all().meta["stopped"] == 2

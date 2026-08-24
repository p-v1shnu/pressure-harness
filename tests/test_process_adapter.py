"""The process adapter for whichever platform the tests are running on.

Uses `sys.executable` for every child so the same suite is meaningful on Linux,
macOS and Windows -- the point is the adapter, not the availability of a shell.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from pharness.adapters import select
from pharness.core.env import build_env


@pytest.fixture
def process(tmp_path: Path):
    adapters = select()
    if not adapters.capabilities:
        pytest.skip(f"no process adapter for {adapters.platform}")
    return adapters.process_factory(tmp_path / "logs")


@pytest.fixture
def env() -> dict[str, str]:
    return build_env(os.environ, select().platform)


def python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_run_captures_output_and_exit_code(process, env, tmp_path: Path):
    result = process.run(python("print('hello')"), tmp_path, env)
    assert result.ok and result.stdout.strip() == "hello"


def test_run_reports_a_failure(process, env, tmp_path: Path):
    result = process.run(python("import sys; sys.stderr.write('bad'); sys.exit(3)"), tmp_path, env)
    assert not result.ok and result.exit_code == 3
    assert "bad" in result.combined


def test_run_times_out_rather_than_hanging(process, env, tmp_path: Path):
    result = process.run(python("import time; time.sleep(30)"), tmp_path, env, timeout_sec=0.5)
    assert result.timed_out and not result.ok


def test_missing_executable_is_reported_not_raised(process, env, tmp_path: Path):
    result = process.run(["definitely-not-a-real-binary-xyz"], tmp_path, env)
    assert not result.ok and "not found" in result.stderr


def test_child_gets_only_the_environment_we_built(process, env, tmp_path: Path):
    """The whole point of core.env, checked against a real process."""
    parent_key = "PHARNESS_TEST_SECRET"
    os.environ[parent_key] = "must-not-leak"
    try:
        built = build_env(os.environ, select().platform)
        result = process.run(
            python(f"import os; print(os.environ.get({parent_key!r}, 'absent'))"),
            tmp_path,
            built,
        )
        assert result.stdout.strip() == "absent"
    finally:
        os.environ.pop(parent_key, None)


def test_spawn_tail_and_stop(process, env, tmp_path: Path):
    handle = process.spawn(
        python(
            "import sys, time\n"
            "for i in range(1000):\n"
            "    print('tick', i, flush=True)\n"
            "    time.sleep(0.02)\n"
        ),
        tmp_path,
        env,
        label="ticker",
    )

    deadline = time.monotonic() + 5
    while "tick" not in handle.tail(5) and time.monotonic() < deadline:
        time.sleep(0.05)

    assert handle.is_running()
    assert "tick" in handle.tail(5)

    handle.stop(timeout_sec=3)
    assert not handle.is_running()
    assert process.get(handle.id) is handle


def test_stopping_kills_the_whole_tree(process, env, tmp_path: Path):
    """Killing only the named process leaves the dev server running and the port bound."""
    marker = tmp_path / "grandchild-alive.txt"
    parent_code = (
        "import subprocess, sys, time\n"
        f"child = subprocess.Popen([sys.executable, '-c', "
        f"\"import time\\nwhile True:\\n    open({str(marker)!r}, 'a').write('x')\\n"
        f'    time.sleep(0.05)"])\n'
        "while True: time.sleep(0.05)\n"
    )
    handle = process.spawn([sys.executable, "-c", parent_code], tmp_path, env)

    deadline = time.monotonic() + 5
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert marker.exists(), "grandchild never started"

    handle.stop(timeout_sec=3)
    time.sleep(0.3)
    size_after_stop = marker.stat().st_size
    time.sleep(0.4)
    assert marker.stat().st_size == size_after_stop, "grandchild survived the stop"


def test_tail_reads_the_end_of_a_large_log(process, env, tmp_path: Path):
    handle = process.spawn(
        python("[print('line %d' % i, flush=True) for i in range(20000)]"), tmp_path, env
    )
    deadline = time.monotonic() + 10
    while handle.is_running() and time.monotonic() < deadline:
        time.sleep(0.05)

    tail = handle.tail(3)
    assert "line 19999" in tail
    assert "line 0\n" not in tail


def test_stop_all_reports_how_many_it_stopped(process, env, tmp_path: Path):
    for _ in range(3):
        process.spawn(python("import time; time.sleep(30)"), tmp_path, env)
    assert process.stop_all() == 3
    assert process.list_running() == ()

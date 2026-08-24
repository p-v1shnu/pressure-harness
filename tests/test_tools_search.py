"""Search must obey the same rules as reading, and the same budget."""

from __future__ import annotations

from pathlib import Path

import pytest

from pharness.adapters.posix.paths import PosixPaths
from pharness.core.config import ContextSettings, parse_config
from pharness.core.policy.path_jail import PathJail
from pharness.core.tools import SearchTools
from pharness.core.workspace import WorkspaceRegistry


@pytest.fixture
def search(tmp_path: Path) -> SearchTools:
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.ts").write_text("export function login() {}\n", encoding="utf-8")
    (root / "src" / "util.ts").write_text("const helper = 1\n", encoding="utf-8")
    (root / ".env").write_text("API_SECRET=login-token-value\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "dep.ts").write_text("login\n", encoding="utf-8")
    (root / "blob.bin").write_bytes(b"login\x00\x01\x02" * 100)

    registry = WorkspaceRegistry.from_config(
        parse_config({"workspace": [{"alias": "p", "path": str(root)}]}), PosixPaths()
    )
    return SearchTools(
        workspace=registry.get("p"),
        jail=PathJail.with_app_dirs(PosixPaths()),
        context=ContextSettings(),
    )


def test_finds_matches_with_line_numbers(search: SearchTools):
    result = search.text("login")
    assert "src/app.ts:1" in result.text


def test_dependency_directories_are_skipped(search: SearchTools):
    assert "node_modules" not in search.text("login").text


def test_credential_files_are_never_searched(search: SearchTools):
    """Otherwise search is a way to read what the read tool refuses."""
    result = search.text("API_SECRET")
    assert result.meta["hits"] == 0
    assert "login-token-value" not in result.text


def test_binary_files_are_skipped(search: SearchTools):
    assert "blob.bin" not in search.text("login").text


def test_no_matches_reports_how_much_was_looked_at(search: SearchTools):
    result = search.text("definitely-not-present")
    assert result.meta["hits"] == 0
    assert "files" in result.text


def test_invalid_regex_is_reported(search: SearchTools):
    result = search.text("unclosed (group")
    assert not result.ok and "invalid regular expression" in result.text


def test_results_are_capped(search: SearchTools):
    root = search.workspace.root
    for index in range(40):
        (root / f"f{index}.ts").write_text("needle\n" * 5, encoding="utf-8")

    result = search.text("needle", max_hits=10)
    assert result.meta["hits"] == 10
    assert result.meta["capped"] is True
    assert "stopped at 10 matches" in result.text


def test_glob_filters_the_file_list(search: SearchTools):
    listed = search.files("*.ts")
    assert "src/app.ts" in listed.text
    assert ".env" not in listed.text


def test_case_insensitive_by_default(search: SearchTools):
    assert search.text("LOGIN").meta["hits"] >= 1
    assert search.text("LOGIN", case_sensitive=True).meta["hits"] == 0

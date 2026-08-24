"""Config rejects unsafe settings at load time rather than warning later."""

from __future__ import annotations

from pathlib import Path

import pytest

from pharness.core.config import Config, Mode, load_config, parse_config, save_config
from pharness.core.errors import ConfigError


def test_defaults_are_the_safe_ones():
    config = Config()
    assert config.security.default_mode is Mode.AUTO_EDIT
    assert config.server.bind == "127.0.0.1"
    assert config.tunnel.auth == "oauth"
    assert config.security.full_access_ttl_min > 0
    assert config.workspaces == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"server": {"bind": "0.0.0.0"}}, "loopback"),
        ({"server": {"bind": "192.168.1.5"}}, "loopback"),
        ({"security": {"default_mode": "full-access"}}, "full-access"),
        ({"tunnel": {"auth": "none"}}, "none"),
        ({"tunnel": {"auth": "basic"}}, "oauth"),
        ({"workspace": [{"alias": "Has Space", "path": "/x"}]}, "alias"),
        ({"workspace": [{"alias": "ok", "path": "   "}]}, "empty"),
        ({"workspace": [{"alias": "ok", "path": "/x", "mode": "full-access"}]}, "runtime"),
        ({"unknown_section": {}}, "Extra inputs"),
    ],
)
def test_unsafe_config_is_refused(raw: dict, expected: str):
    with pytest.raises(ConfigError) as excinfo:
        parse_config(raw)
    assert expected in str(excinfo.value)


def test_duplicate_aliases_are_refused():
    with pytest.raises(ConfigError, match="duplicate"):
        parse_config({"workspace": [{"alias": "a", "path": "/x"}, {"alias": "a", "path": "/y"}]})


def test_round_trip_through_disk(tmp_path: Path):
    original = parse_config(
        {
            "server": {"port": 20000},
            "workspace": [
                {
                    "alias": "shop",
                    "path": "/w/shop",
                    "allow_commands": ["npm test"],
                    "scripts": {"dev": "npm run dev"},
                },
            ],
        }
    )
    target = tmp_path / "config.toml"
    save_config(original, target)
    assert load_config(target) == original


def test_missing_file_yields_defaults(tmp_path: Path):
    assert load_config(tmp_path / "absent.toml") == Config()


def test_malformed_toml_is_reported(tmp_path: Path):
    target = tmp_path / "config.toml"
    target.write_text("this is not = = toml", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(target)

"""The pairing code and the token store.

All of it is state and arithmetic, so none of these tests need a socket.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from pharness.core.auth import (
    ACCESS_TOKEN_TTL_SEC,
    AUTH_CODE_TTL_SEC,
    MAX_ATTEMPTS,
    AuthError,
    AuthStore,
    new_pairing_code,
)


@dataclass
class FakeParams:
    state: str = "xyz"
    scopes: list | None = None
    code_challenge: str = "challenge"
    redirect_uri: str = "http://localhost:9999/cb"
    redirect_uri_provided_explicitly: bool = True
    resource: str | None = None


@pytest.fixture
def clock():
    state = {"now": 1_000_000.0}

    def read() -> float:
        return state["now"]

    read.advance = lambda seconds: state.__setitem__("now", state["now"] + seconds)  # type: ignore[attr-defined]
    return read


@pytest.fixture
def store(tmp_path: Path, clock) -> AuthStore:
    made = AuthStore(tmp_path, clock=clock)
    made.load()
    return made


def test_pairing_codes_avoid_ambiguous_characters():
    """These get read off a screen and typed on a phone."""
    for _ in range(50):
        assert not set(new_pairing_code()) & set("O0I1l")


def test_the_code_survives_a_restart(tmp_path: Path, clock):
    """A code that changes every restart is one nobody can look up."""
    first = AuthStore(tmp_path, clock=clock)
    first.load()

    second = AuthStore(tmp_path, clock=clock)
    second.load()
    assert second.pairing_code == first.pairing_code


def test_rotating_changes_it(store: AuthStore, tmp_path: Path, clock):
    old = store.pairing_code
    new = store.rotate_pairing_code()
    assert new != old

    reopened = AuthStore(tmp_path, clock=clock)
    reopened.load()
    assert reopened.pairing_code == new


def test_a_wrong_code_is_refused(store: AuthStore):
    with pytest.raises(AuthError, match="does not match"):
        store.check_pairing_code("WRONGCOD")


def test_the_right_code_passes_whatever_the_casing(store: AuthStore):
    store.check_pairing_code(f"  {store.pairing_code.lower()}  ")


def test_guessing_gets_locked_out(store: AuthStore, clock):
    """Guessing eight characters takes many tries; this makes them expensive."""
    for _ in range(MAX_ATTEMPTS):
        with pytest.raises(AuthError):
            store.check_pairing_code("NOPENOPE")

    with pytest.raises(AuthError, match="too many wrong codes"):
        store.check_pairing_code(store.pairing_code)  # even the right one waits

    clock.advance(400)
    store.check_pairing_code(store.pairing_code)


def test_rotating_clears_a_lockout(store: AuthStore):
    for _ in range(MAX_ATTEMPTS):
        with pytest.raises(AuthError):
            store.check_pairing_code("NOPENOPE")
    new = store.rotate_pairing_code()
    store.check_pairing_code(new)


# -- consent -------------------------------------------------------------------


def test_consent_needs_the_code(store: AuthStore):
    pending = store.start_consent("client-1", "ChatGPT", FakeParams())
    with pytest.raises(AuthError):
        store.approve_consent(pending.id, "WRONGCOD")

    code = store.approve_consent(pending.id, store.pairing_code)
    assert code.client_id == "client-1"
    assert code.code_challenge == "challenge"


def test_a_consent_page_expires(store: AuthStore, clock):
    pending = store.start_consent("client-1", "ChatGPT", FakeParams())
    clock.advance(AUTH_CODE_TTL_SEC + 1)

    assert store.get_pending(pending.id) is None
    with pytest.raises(AuthError, match="expired"):
        store.approve_consent(pending.id, store.pairing_code)


def test_denying_removes_the_request(store: AuthStore):
    pending = store.start_consent("client-1", "ChatGPT", FakeParams())
    store.deny_consent(pending.id)
    assert store.get_pending(pending.id) is None


# -- codes and tokens ----------------------------------------------------------


def approved(store: AuthStore, client_id: str = "client-1"):
    pending = store.start_consent(client_id, "ChatGPT", FakeParams())
    return store.approve_consent(pending.id, store.pairing_code)


def test_an_authorization_code_works_once(store: AuthStore):
    code = approved(store)
    assert store.load_code("client-1", code.code) is not None

    store.consume_code(code.code)
    assert store.load_code("client-1", code.code) is None


def test_a_code_belongs_to_one_client(store: AuthStore):
    code = approved(store)
    assert store.load_code("someone-else", code.code) is None


def test_an_authorization_code_expires(store: AuthStore, clock):
    code = approved(store)
    clock.advance(AUTH_CODE_TTL_SEC + 1)
    assert store.load_code("client-1", code.code) is None


def test_tokens_are_issued_and_expire(store: AuthStore, clock):
    store.register_client("client-1", {"client_id": "client-1"})
    access, refresh = store.issue_tokens("client-1", ["read"])

    assert store.load_access_token(access.token) is not None
    clock.advance(ACCESS_TOKEN_TTL_SEC + 1)
    assert store.load_access_token(access.token) is None
    assert store.load_refresh_token("client-1", refresh.token) is not None


def test_a_refresh_token_is_single_use(store: AuthStore):
    store.register_client("client-1", {"client_id": "client-1"})
    _, refresh = store.issue_tokens("client-1", [])

    rotated = store.rotate_refresh_token(refresh.token)
    assert rotated is not None
    assert store.rotate_refresh_token(refresh.token) is None


def test_revoking_a_client_kills_its_tokens(store: AuthStore):
    """Revoking should not need the server that is being revoked from."""
    store.register_client("client-1", {"client_id": "client-1", "client_name": "ChatGPT"})
    access, refresh = store.issue_tokens("client-1", [])
    assert store.load_access_token(access.token) is not None

    assert store.forget_client("client-1")
    assert store.load_access_token(access.token) is None
    assert store.load_refresh_token("client-1", refresh.token) is None
    assert not store.forget_client("client-1")


def test_clients_and_refresh_tokens_survive_a_restart(tmp_path: Path, clock):
    first = AuthStore(tmp_path, clock=clock)
    first.load()
    first.register_client("client-1", {"client_id": "client-1", "client_name": "ChatGPT"})
    _, refresh = first.issue_tokens("client-1", ["read"])

    second = AuthStore(tmp_path, clock=clock)
    second.load()
    assert second.get_client("client-1") is not None
    assert second.load_refresh_token("client-1", refresh.token) is not None


def test_a_corrupt_state_file_does_not_stop_startup(tmp_path: Path, clock):
    (tmp_path / "oauth-clients.json").write_text("{not json", encoding="utf-8")
    store = AuthStore(tmp_path, clock=clock)
    store.load()
    assert store.pairing_code

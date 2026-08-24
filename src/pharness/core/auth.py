"""Tokens, clients, and the pairing code that gates them.

The problem this solves: a tunnel URL is not a secret worth relying on, and
ChatGPT's connectors offer only OAuth or no authentication at all (PRD 10.6).
So the server runs a small authorization server -- and the question becomes
what proves that whoever reaches the consent page is the machine's owner.

The answer here is a pairing code printed on the machine's own console. Anyone
can reach the consent page through the tunnel; only someone with access to the
machine can read the code. That binds "may approve" to "is at the keyboard",
which is the same principle as approving tool calls outside the chat.

Everything in this module is pure state and clock arithmetic, so all of it can
be tested without a socket.
"""

from __future__ import annotations

import contextlib
import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/1/O/0: these get read aloud
CODE_LENGTH = 8
MAX_ATTEMPTS = 5
LOCKOUT_SEC = 300
AUTH_CODE_TTL_SEC = 300
ACCESS_TOKEN_TTL_SEC = 3600
REFRESH_TOKEN_TTL_SEC = 30 * 24 * 3600

Clock = Callable[[], float]


class AuthError(Exception):
    """Something about an authorization attempt was wrong. The message is shown
    to whoever is at the consent page, so it says what to do, not what we know."""


def _now() -> float:
    return time.time()


def new_pairing_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


@dataclass
class PendingConsent:
    id: str
    client_id: str
    client_name: str
    params: Any
    created_at: float
    approved_code: str | None = None


@dataclass
class StoredCode:
    code: str
    client_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    code_challenge: str
    scopes: list[str]
    expires_at: float
    resource: str | None = None


@dataclass
class StoredToken:
    token: str
    client_id: str
    scopes: list[str]
    expires_at: float
    resource: str | None = None


@dataclass
class AuthStore:
    """Clients, codes and tokens, plus the pairing code that guards consent."""

    data_dir: Path
    clock: Clock = _now
    pairing_code: str = field(default_factory=new_pairing_code)

    _clients: dict[str, dict] = field(default_factory=dict)
    _pending: dict[str, PendingConsent] = field(default_factory=dict)
    _codes: dict[str, StoredCode] = field(default_factory=dict)
    _access: dict[str, StoredToken] = field(default_factory=dict)
    _refresh: dict[str, StoredToken] = field(default_factory=dict)
    _failures: list[float] = field(default_factory=list)

    # -- persistence -------------------------------------------------------

    @property
    def state_path(self) -> Path:
        return self.data_dir / "oauth-clients.json"

    def load(self) -> None:
        """Restore registered clients and refresh tokens.

        Without this, restarting the server means re-pairing from scratch, and a
        security control people have to redo constantly is one they turn off.
        Access tokens are deliberately not persisted: they are short-lived and
        cheap to reissue.
        """
        raw: dict = {}
        if self.state_path.exists():
            try:
                raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = {}

        if not raw.get("pairing_code"):
            # First run, or a file from before codes were stored. Persist the
            # one we just generated, otherwise every `ph auth code` would print
            # a different answer and none of them would be the real one.
            self.save()

        # The code is kept rather than regenerated: it only gates authorising a
        # new client, which is rare, and a code that changes every restart is one
        # nobody can look up when they need it.
        if raw.get("pairing_code"):
            self.pairing_code = str(raw["pairing_code"])
        self._clients = dict(raw.get("clients", {}))
        now = self.clock()
        for item in raw.get("refresh_tokens", []):
            if item.get("expires_at", 0) > now:
                self._refresh[item["token"]] = StoredToken(**item)

    def save(self) -> None:
        payload = {
            "pairing_code": self.pairing_code,
            "clients": self._clients,
            "refresh_tokens": [
                {
                    "token": token.token,
                    "client_id": token.client_id,
                    "scopes": token.scopes,
                    "expires_at": token.expires_at,
                    "resource": token.resource,
                }
                for token in self._refresh.values()
            ],
        }
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp.replace(self.state_path)
        # Owner-only where the filesystem supports it; Windows ignores it.
        with contextlib.suppress(OSError):
            self.state_path.chmod(0o600)

    # -- clients -----------------------------------------------------------

    def register_client(self, client_id: str, info: dict) -> None:
        self._clients[client_id] = info
        self.save()

    def get_client(self, client_id: str) -> dict | None:
        return self._clients.get(client_id)

    def clients(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (client_id, info.get("client_name") or "(unnamed)")
            for client_id, info in self._clients.items()
        )

    def forget_client(self, client_id: str) -> bool:
        """Revoke a client outright: its tokens stop working immediately."""
        if client_id not in self._clients:
            return False
        del self._clients[client_id]
        self._access = {k: v for k, v in self._access.items() if v.client_id != client_id}
        self._refresh = {k: v for k, v in self._refresh.items() if v.client_id != client_id}
        self.save()
        return True

    # -- pairing -----------------------------------------------------------

    def rotate_pairing_code(self) -> str:
        self.pairing_code = new_pairing_code()
        self._failures.clear()
        self.save()
        return self.pairing_code

    def locked_out(self) -> float:
        """Seconds remaining in a lockout, or 0.

        Guessing eight characters takes a great many tries; a lockout makes
        those tries expensive rather than free.
        """
        now = self.clock()
        self._failures = [stamp for stamp in self._failures if now - stamp < LOCKOUT_SEC]
        if len(self._failures) < MAX_ATTEMPTS:
            return 0.0
        return LOCKOUT_SEC - (now - self._failures[0])

    def check_pairing_code(self, attempt: str) -> None:
        remaining = self.locked_out()
        if remaining > 0:
            raise AuthError(
                f"too many wrong codes; try again in {remaining / 60:.0f} minutes "
                "or restart the server for a new code"
            )
        if not secrets.compare_digest(attempt.strip().upper(), self.pairing_code):
            self._failures.append(self.clock())
            left = MAX_ATTEMPTS - len(self._failures)
            raise AuthError(
                "that code does not match the one on the machine's console"
                + (f" ({left} attempts left)" if left > 0 else "")
            )
        self._failures.clear()

    # -- consent -----------------------------------------------------------

    def start_consent(self, client_id: str, client_name: str, params: Any) -> PendingConsent:
        pending = PendingConsent(
            id=secrets.token_urlsafe(16),
            client_id=client_id,
            client_name=client_name,
            params=params,
            created_at=self.clock(),
        )
        self._pending[pending.id] = pending
        return pending

    def get_pending(self, pending_id: str) -> PendingConsent | None:
        pending = self._pending.get(pending_id)
        if pending and self.clock() - pending.created_at > AUTH_CODE_TTL_SEC:
            del self._pending[pending_id]
            return None
        return pending

    def approve_consent(self, pending_id: str, attempt: str) -> StoredCode:
        pending = self.get_pending(pending_id)
        if pending is None:
            raise AuthError("this approval page has expired; start again from the client")

        self.check_pairing_code(attempt)
        del self._pending[pending_id]

        params = pending.params
        stored = StoredCode(
            code=secrets.token_urlsafe(32),
            client_id=pending.client_id,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            code_challenge=params.code_challenge,
            scopes=list(params.scopes or []),
            expires_at=self.clock() + AUTH_CODE_TTL_SEC,
            resource=getattr(params, "resource", None),
        )
        self._codes[stored.code] = stored
        return stored

    def deny_consent(self, pending_id: str) -> None:
        self._pending.pop(pending_id, None)

    # -- codes and tokens --------------------------------------------------

    def load_code(self, client_id: str, code: str) -> StoredCode | None:
        stored = self._codes.get(code)
        if stored is None or stored.client_id != client_id:
            return None
        if stored.expires_at < self.clock():
            del self._codes[code]
            return None
        return stored

    def consume_code(self, code: str) -> None:
        """An authorization code is good exactly once."""
        self._codes.pop(code, None)

    def issue_tokens(
        self, client_id: str, scopes: list[str], resource: str | None = None
    ) -> tuple[StoredToken, StoredToken]:
        now = self.clock()
        access = StoredToken(
            token=secrets.token_urlsafe(32),
            client_id=client_id,
            scopes=list(scopes),
            expires_at=now + ACCESS_TOKEN_TTL_SEC,
            resource=resource,
        )
        refresh = StoredToken(
            token=secrets.token_urlsafe(32),
            client_id=client_id,
            scopes=list(scopes),
            expires_at=now + REFRESH_TOKEN_TTL_SEC,
            resource=resource,
        )
        self._access[access.token] = access
        self._refresh[refresh.token] = refresh
        self.save()
        return access, refresh

    def load_access_token(self, token: str) -> StoredToken | None:
        stored = self._access.get(token)
        if stored is None:
            return None
        if stored.expires_at < self.clock():
            del self._access[token]
            return None
        if stored.client_id not in self._clients:
            return None  # the client was revoked
        return stored

    def load_refresh_token(self, client_id: str, token: str) -> StoredToken | None:
        stored = self._refresh.get(token)
        if stored is None or stored.client_id != client_id:
            return None
        if stored.expires_at < self.clock():
            del self._refresh[token]
            return None
        return stored

    def rotate_refresh_token(self, old: str) -> tuple[StoredToken, StoredToken] | None:
        """Refresh tokens are single-use: a stolen one is only good until the
        real client refreshes, which is when the theft becomes visible."""
        stored = self._refresh.pop(old, None)
        if stored is None:
            return None
        return self.issue_tokens(stored.client_id, stored.scopes, stored.resource)

    def revoke(self, token: str) -> None:
        self._access.pop(token, None)
        self._refresh.pop(token, None)
        self.save()

    def stats(self) -> dict[str, int]:
        return {
            "clients": len(self._clients),
            "access_tokens": len(self._access),
            "refresh_tokens": len(self._refresh),
            "pending": len(self._pending),
        }


def iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat()

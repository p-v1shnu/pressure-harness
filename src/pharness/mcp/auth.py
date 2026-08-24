"""The OAuth authorization server, and the consent page it serves.

The protocol plumbing comes from the MCP SDK; what is ours is the decision of
who may approve. A tunnel makes the consent page reachable by anyone who learns
the URL, so approving requires the pairing code printed on the machine's own
console -- the same idea as approving tool calls outside the chat, applied to
the connection itself (PRD 10.6).
"""

from __future__ import annotations

import html
from typing import Any

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from pharness.core.auth import ACCESS_TOKEN_TTL_SEC, AuthError, AuthStore

CONSENT_PATH = "/pharness/consent"

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pressure Harness — approve a connection</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 15px/1.55 system-ui, sans-serif; max-width: 34rem;
          margin: 8vh auto; padding: 0 1.2rem; }}
  h1 {{ font-size: 1.25rem; margin-bottom: .3rem; }}
  .who {{ padding: .8rem 1rem; border-radius: .5rem;
          background: rgba(127,127,127,.12); margin: 1rem 0; }}
  label {{ display: block; margin: 1.4rem 0 .4rem; font-weight: 600; }}
  input {{ font: 1.4rem/1 ui-monospace, monospace; letter-spacing: .18em; padding: .6rem .7rem;
           width: 100%; box-sizing: border-box; text-transform: uppercase; }}
  button {{ font: inherit; padding: .6rem 1.1rem; margin-top: 1.1rem; margin-right: .5rem; }}
  .error {{ color: #b00020; margin-top: 1rem; }}
  .note {{ opacity: .75; font-size: .9rem; margin-top: 1.6rem; }}
</style></head><body>
<h1>Approve a connection to this machine</h1>
<p>Something is asking to use the tools on this computer.</p>
<div class="who"><strong>{client}</strong><br><small>{redirect}</small></div>
<form method="post" action="{action}">
  <input type="hidden" name="pending" value="{pending}">
  <label for="code">Pairing code</label>
  <input id="code" name="code" autocomplete="off" autocapitalize="characters"
         spellcheck="false" autofocus placeholder="XXXXXXXX" maxlength="8">
  <p class="note">The code is printed in the Pressure Harness console on the
  computer being connected to. If you cannot see it there, do not approve this.</p>
  {error}
  <button type="submit" name="decision" value="approve">Approve</button>
  <button type="submit" name="decision" value="deny">Deny</button>
</form>
</body></html>
"""

DONE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{title}</title><style>body{{font:15px/1.55 system-ui,sans-serif;max-width:32rem;
margin:10vh auto;padding:0 1.2rem}}</style></head>
<body><h1>{title}</h1><p>{body}</p></body></html>
"""


class PairingOAuthProvider(OAuthAuthorizationServerProvider):
    """An authorization server whose consent step needs the machine's console."""

    def __init__(self, store: AuthStore, base_url: str) -> None:
        self.store = store
        self.base_url = base_url.rstrip("/")

    # -- clients -----------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        raw = self.store.get_client(client_id)
        return OAuthClientInformationFull.model_validate(raw) if raw else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self.store.register_client(
            client_info.client_id, client_info.model_dump(mode="json", exclude_none=True)
        )

    # -- authorization -----------------------------------------------------

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Send the browser to our own consent page rather than approving here.

        Nothing is granted by asking; the grant happens when someone types the
        code shown on the machine.
        """
        pending = self.store.start_consent(
            client.client_id, client.client_name or client.client_id, params
        )
        return f"{self.base_url}{CONSENT_PATH}?pending={pending.id}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        stored = self.store.load_code(client.client_id, authorization_code)
        if stored is None:
            return None
        return AuthorizationCode(
            code=stored.code,
            scopes=stored.scopes,
            expires_at=stored.expires_at,
            client_id=stored.client_id,
            code_challenge=stored.code_challenge,
            redirect_uri=stored.redirect_uri,  # type: ignore[arg-type]
            redirect_uri_provided_explicitly=stored.redirect_uri_provided_explicitly,
            resource=stored.resource,
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        if self.store.load_code(client.client_id, authorization_code.code) is None:
            raise TokenError("invalid_grant", "that authorization code is no longer valid")
        self.store.consume_code(authorization_code.code)

        access, refresh = self.store.issue_tokens(
            client.client_id, list(authorization_code.scopes), authorization_code.resource
        )
        return _token_response(access, refresh)

    # -- refresh and revocation --------------------------------------------

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        stored = self.store.load_refresh_token(client.client_id, refresh_token)
        if stored is None:
            return None
        return RefreshToken(
            token=stored.token,
            client_id=stored.client_id,
            scopes=stored.scopes,
            expires_at=int(stored.expires_at),
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        rotated = self.store.rotate_refresh_token(refresh_token.token)
        if rotated is None:
            raise TokenError("invalid_grant", "that refresh token is no longer valid")
        access, refresh = rotated
        return _token_response(access, refresh)

    async def load_access_token(self, token: str) -> AccessToken | None:
        stored = self.store.load_access_token(token)
        if stored is None:
            return None
        return AccessToken(
            token=stored.token,
            client_id=stored.client_id,
            scopes=stored.scopes,
            expires_at=int(stored.expires_at),
            resource=stored.resource,
        )

    async def revoke_token(self, token: Any) -> None:
        self.store.revoke(getattr(token, "token", str(token)))


def _token_response(access, refresh) -> OAuthToken:
    return OAuthToken(
        access_token=access.token,
        token_type="Bearer",
        expires_in=ACCESS_TOKEN_TTL_SEC,
        scope=" ".join(access.scopes),
        refresh_token=refresh.token,
    )


def register_consent_page(server, provider: PairingOAuthProvider) -> None:
    """Attach the consent page to the MCP app.

    It lives on the same server the client is trying to reach, so there is no
    second thing to run and no second port to expose.
    """
    show, submit = consent_handlers(provider)
    server.custom_route(CONSENT_PATH, methods=["GET"])(show)
    server.custom_route(CONSENT_PATH, methods=["POST"])(submit)


def consent_handlers(provider: PairingOAuthProvider):
    store = provider.store

    def render(pending_id: str, client: str, redirect: str, error: str = "") -> HTMLResponse:
        return HTMLResponse(
            PAGE.format(
                client=html.escape(client),
                redirect=html.escape(redirect),
                pending=html.escape(pending_id),
                action=CONSENT_PATH,
                error=f'<p class="error">{html.escape(error)}</p>' if error else "",
            )
        )

    async def show(request: Request) -> HTMLResponse:
        pending = store.get_pending(request.query_params.get("pending", ""))
        if pending is None:
            return HTMLResponse(
                DONE.format(
                    title="This request expired",
                    body="Start again from the application that sent you here.",
                ),
                status_code=400,
            )
        return render(pending.id, pending.client_name, str(pending.params.redirect_uri))

    async def submit(request: Request) -> HTMLResponse | RedirectResponse:
        form = await request.form()
        pending_id = str(form.get("pending", ""))
        pending = store.get_pending(pending_id)

        if pending is None:
            return HTMLResponse(
                DONE.format(
                    title="This request expired",
                    body="Start again from the application that sent you here.",
                ),
                status_code=400,
            )

        if form.get("decision") == "deny":
            store.deny_consent(pending_id)
            return HTMLResponse(
                DONE.format(title="Not approved", body="Nothing was granted. You can close this."),
            )

        try:
            code = store.approve_consent(pending_id, str(form.get("code", "")))
        except AuthError as exc:
            return render(
                pending.id, pending.client_name, str(pending.params.redirect_uri), str(exc)
            )

        from mcp.server.auth.provider import construct_redirect_uri

        target = construct_redirect_uri(
            code.redirect_uri, code=code.code, state=pending.params.state
        )
        return RedirectResponse(target, status_code=302)

    return show, submit

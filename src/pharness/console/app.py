"""The console's HTTP layer.

Served on loopback with a token in the URL. Loopback because the console can
take permissions away and answer approval prompts, so it must never be
reachable through the tunnel that publishes the tools; a token as well, because
loopback also means every other program on the machine.

A local web app rather than a native window, with the window as an optional
wrapper over the same page. It means the console can be opened from a phone on
the same network by forwarding a port deliberately, it degrades to "open this
URL" where no GUI toolkit is installed, and -- not least -- it can be tested.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from pharness.console.api import ConsoleApi
from pharness.console.ui import PAGE

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def new_token() -> str:
    return secrets.token_urlsafe(24)


def build_console_app(api: ConsoleApi, token: str) -> Starlette:
    def guard(request: Request) -> Response | None:
        client = request.client.host if request.client else ""
        if client and client not in LOOPBACK_HOSTS:
            # Reaching the console from elsewhere is never expected: it is the
            # place permissions are handed out and taken back.
            return JSONResponse({"error": "the console is local only"}, status_code=403)

        supplied = request.headers.get("x-pharness-token") or request.query_params.get("token")
        if not supplied or not secrets.compare_digest(supplied, token):
            return JSONResponse({"error": "wrong or missing console token"}, status_code=401)
        return None

    def endpoint(handler: Callable[..., Any], *, method: str = "GET") -> Callable:
        async def route(request: Request) -> Response:
            denied = guard(request)
            if denied is not None:
                return denied

            payload: dict[str, Any] = {}
            if method == "POST":
                try:
                    body = await request.body()
                    payload = json.loads(body) if body else {}
                except ValueError:
                    return JSONResponse({"error": "expected a JSON body"}, status_code=400)
            else:
                payload = dict(request.query_params)
                payload.pop("token", None)

            try:
                result = handler(**_coerce(handler, payload))
            except TypeError as exc:
                return JSONResponse({"error": f"bad arguments: {exc}"}, status_code=400)
            except Exception as exc:
                return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)

            return JSONResponse(result)

        return route

    async def index(request: Request) -> Response:
        denied = guard(request)
        if denied is not None:
            return HTMLResponse(
                "<h1>Not this way</h1><p>Open the console using the link printed "
                "on this machine.</p>",
                status_code=denied.status_code,
            )
        return HTMLResponse(PAGE.replace("__TOKEN__", token))

    routes = [
        Route("/", index),
        Route("/api/status", endpoint(api.status)),
        Route("/api/workspaces", endpoint(api.workspaces)),
        Route("/api/pending", endpoint(api.pending)),
        Route("/api/approvals/history", endpoint(api.history)),
        Route("/api/rules", endpoint(api.rules)),
        Route("/api/activity", endpoint(api.activity)),
        Route("/api/checkpoints", endpoint(api.checkpoints)),
        Route("/api/processes", endpoint(api.processes)),
        Route("/api/process-logs", endpoint(api.process_logs)),
        Route("/api/connection", endpoint(api.connection)),
        Route("/api/doctor", endpoint(api.doctor)),
        Route("/api/answer", endpoint(api.answer, method="POST"), methods=["POST"]),
        Route("/api/elevate", endpoint(api.elevate, method="POST"), methods=["POST"]),
        Route(
            "/api/revoke-elevation",
            endpoint(api.revoke_elevation, method="POST"),
            methods=["POST"],
        ),
        Route("/api/forget-rule", endpoint(api.forget_rule, method="POST"), methods=["POST"]),
        Route("/api/undo", endpoint(api.undo, method="POST"), methods=["POST"]),
        Route("/api/stop-process", endpoint(api.stop_process, method="POST"), methods=["POST"]),
        Route(
            "/api/rotate-pairing-code",
            endpoint(api.rotate_pairing_code, method="POST"),
            methods=["POST"],
        ),
        Route("/api/revoke-client", endpoint(api.revoke_client, method="POST"), methods=["POST"]),
        Route("/api/emergency-stop", endpoint(api.emergency_stop, method="POST"), methods=["POST"]),
    ]
    return Starlette(routes=routes)


def _coerce(handler: Callable[..., Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Turn query strings into the types the handler declared.

    Query parameters arrive as text, so `limit=50` would be the string "50" and
    a handler that slices with it would fail in a confusing place.
    """
    import inspect

    signature = inspect.signature(handler)
    out: dict[str, Any] = {}
    for name, parameter in signature.parameters.items():
        if name not in payload:
            continue
        value = payload[name]
        annotation = parameter.annotation
        if isinstance(value, str) and annotation in (int, "int", "int | None"):
            try:
                value = int(value)
            except ValueError:
                continue
        out[name] = value
    return out

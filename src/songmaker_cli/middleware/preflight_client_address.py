"""Hands the request line the client address for a request CORS answers itself."""

from __future__ import annotations

from logline import set_client_ip
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send
from webauth.proxies import resolve_client_ip


def _is_cors_preflight(request: Request) -> bool:
    return (
        request.method == "OPTIONS"
        and "origin" in request.headers
        and "access-control-request-method" in request.headers
    )


class PreflightClientAddressMiddleware:
    """Runs just inside the request line, which reports the address.

    Starlette's CORSMiddleware answers a preflight itself, outside webauth's ClientAddressMiddleware
    (webauth installs that just inside the host's CORS), so webauth never writes the address for
    it; every other request gets its address from webauth.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            request = Request(scope)
            if _is_cors_preflight(request):
                set_client_ip(scope, resolve_client_ip(request))
        await self.app(scope, receive, send)

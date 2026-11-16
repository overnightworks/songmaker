"""Hands the request line the client address the trusted-proxy decider resolved."""

from __future__ import annotations

from logline import set_client_ip
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send
from webauth.proxies import resolve_client_ip


class ClientAddressMiddleware:
    """Runs just inside the request line, which reports the address."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            set_client_ip(scope, resolve_client_ip(Request(scope)))
        await self.app(scope, receive, send)

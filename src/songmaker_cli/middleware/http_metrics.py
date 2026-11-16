"""HTTP request metrics: method, status and duration of each request that gets this far."""

from __future__ import annotations

import logging
from time import perf_counter

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger(__name__)


class HttpMetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        start = perf_counter()
        status_code = 500

        async def observed_send(message: Message) -> None:
            nonlocal status_code
            await send(message)
            if message["type"] == "http.response.start":
                status_code = message["status"]

        try:
            await self.app(scope, receive, observed_send)
        finally:
            try:
                request.app.state.http_metrics.record(
                    request.method, status_code, (perf_counter() - start) * 1000,
                )
            except Exception:
                # Metrics must not mask an exchange failure or invalidate a sent response.
                log.exception("HTTP metrics recording failed")

"""Access logging middleware -- structured request/response logging."""

from __future__ import annotations

import logging
from time import perf_counter

import structlog
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from webauth.proxies import resolve_client_ip

log = logging.getLogger(__name__)


class AccessLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        ip = resolve_client_ip(request)
        previous_context = structlog.contextvars.get_contextvars()
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            ip=ip, method=request.method, path=request.url.path,
        )
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
                duration_ms = (perf_counter() - start) * 1000
                log.info(
                    "ACCESS %s %s %s %d (%.0fms)",
                    ip, request.method, request.url.path, status_code, duration_ms,
                )
                http_metrics = getattr(request.app.state, "http_metrics", None)
                if http_metrics:
                    try:
                        http_metrics.record(request.method, status_code, duration_ms)
                    except Exception:
                        # Metrics must not mask an exchange failure or invalidate a sent response.
                        log.exception("HTTP metrics recording failed")
            finally:
                # Auth may bind user_id downstream; none of that request may leak.
                structlog.contextvars.clear_contextvars()
                structlog.contextvars.bind_contextvars(**previous_context)

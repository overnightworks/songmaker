"""Access logging middleware -- structured request/response logging."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

log = logging.getLogger(__name__)


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        import structlog

        structlog.contextvars.clear_contextvars()

        from songmaker_cli.auth import resolve_client_ip
        ip = resolve_client_ip(request)

        structlog.contextvars.bind_contextvars(
            ip=ip, method=request.method, path=request.url.path,
        )

        start = datetime.now(timezone.utc)
        response = await call_next(request)
        duration_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        log.info(
            "ACCESS %s %s %s %d (%.0fms)",
            ip, request.method, request.url.path,
            response.status_code, duration_ms,
        )

        http_metrics = getattr(request.app.state, "http_metrics", None)
        if http_metrics:
            http_metrics.record(request.method, response.status_code, duration_ms)

        return response

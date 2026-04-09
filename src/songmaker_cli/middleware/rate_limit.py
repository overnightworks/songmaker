"""Global per-IP rate limiter -- defense against multi-account abuse."""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from songmaker_cli.app_context import AppContext
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)

IP_RATE_WINDOW = 60
STATIC_ASSET_PREFIX = "/_app/"


class IpRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(app, **kwargs)
        self._limiter = None

    def _get_limiter(self, ctx: AppContext):  # type: ignore[no-untyped-def]
        if self._limiter is None:
            from songmaker_cli.constants import REDIS_RL_IP_PREFIX
            from songmaker_cli.redis_client import RedisRateLimiter
            self._limiter = RedisRateLimiter(
                ctx.redis, REDIS_RL_IP_PREFIX,
                get_settings().ip_rate_limit, IP_RATE_WINDOW,
            )
        return self._limiter

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.url.path.startswith(STATIC_ASSET_PREFIX):
            return await call_next(request)
        from songmaker_cli.auth import get_client_ip
        ctx: AppContext = request.app.state.ctx
        direct_ip = request.client.host if request.client else "unknown"
        ip = get_client_ip(direct_ip, request.headers.get("x-forwarded-for"), ctx.trusted_proxies)
        try:
            allowed = self._get_limiter(ctx).is_allowed(ip)
        except Exception:
            log.warning("IP rate limiter unavailable -- rejecting request")
            return JSONResponse(
                {"detail": "Rate limiter unavailable"}, status_code=503,
                headers={"Retry-After": "5"},
            )
        if not allowed:
            return JSONResponse(
                {"detail": "Too many requests"}, status_code=429,
                headers={"Retry-After": str(IP_RATE_WINDOW)},
            )
        return await call_next(request)

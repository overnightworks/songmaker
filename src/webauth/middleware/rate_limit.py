"""Per-IP rate limiting: one budget class per request, one counter per class."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from webauth.config import web_auth_config
from webauth.policies import RateLimitClass
from webauth.proxies import resolve_client_ip
from webauth.rate_limit import RedisRateLimiter

if TYPE_CHECKING:
    from starlette.requests import Request

    from webauth.config import RateLimitKeyPrefixes, WebAuthConfig
    from webauth.policies import RateLimitPolicy

log = logging.getLogger(__name__)

LIMITER_UNAVAILABLE_RETRY_AFTER_SECONDS: Final = 5


def _key_prefix(
    prefixes: RateLimitKeyPrefixes, rate_limit_class: RateLimitClass,
) -> str:
    return {
        RateLimitClass.API: prefixes.api,
        RateLimitClass.MEDIA: prefixes.media,
        RateLimitClass.STREAM: prefixes.stream,
    }[rate_limit_class]


class IpRateLimitMiddleware(BaseHTTPMiddleware):
    """Spend one request of the address's budget for the class it falls into."""

    def __init__(self, app, policy: RateLimitPolicy, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(app, **kwargs)
        self._policy = policy
        self._limiters: dict[RateLimitClass, RedisRateLimiter] = {}

    def _limiter(
        self, config: WebAuthConfig, rate_limit_class: RateLimitClass,
    ) -> RedisRateLimiter:
        limiter = self._limiters.get(rate_limit_class)
        if limiter is None:
            budget = self._policy.budget(rate_limit_class)
            limiter = RedisRateLimiter(
                config.redis,
                _key_prefix(config.rate_limit_key_prefixes, rate_limit_class),
                budget.max_requests,
                budget.window_seconds,
            )
            self._limiters[rate_limit_class] = limiter
        return limiter

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path
        if self._policy.is_exempt(path):
            return await call_next(request)
        ip = resolve_client_ip(request)
        rate_limit_class = self._policy.classify(path)
        try:
            allowed = self._limiter(
                web_auth_config(request), rate_limit_class,
            ).is_allowed(ip)
        except Exception:
            log.warning("IP rate limiter unavailable -- rejecting request")
            return JSONResponse(
                {"detail": "Rate limiter unavailable"}, status_code=503,
                headers={"Retry-After": str(LIMITER_UNAVAILABLE_RETRY_AFTER_SECONDS)},
            )
        if not allowed:
            window = self._policy.budget(rate_limit_class).window_seconds
            return JSONResponse(
                {"detail": "Too many requests"}, status_code=429,
                headers={"Retry-After": str(window)},
            )
        return await call_next(request)

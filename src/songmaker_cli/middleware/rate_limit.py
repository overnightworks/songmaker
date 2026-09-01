"""Global per-IP rate limiter -- defense against multi-account abuse.

Requests are split into budget classes so that one traffic pattern cannot
starve another sharing the same IP (issue #257): a player streaming an MP3
in range chunks, or an SSE connection reconnecting after a network hiccup,
used to compete for the same 120-requests/minute budget as everything else
and could lock a working user out of their own session. `_classify_path` is
the single place that maps a path to a class; every request gets exactly one
class, and an unrecognized path falls into the API class (fail closed, not
fail open).
"""

from __future__ import annotations

import logging
import re
from enum import Enum, auto
from typing import TYPE_CHECKING, Final

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import PWA_ICON_PATHS, RESOURCE_EVENT_STREAM_PATH
from songmaker_cli.settings import get_settings

if TYPE_CHECKING:
    from songmaker_cli.redis_client import RedisRateLimiter

log = logging.getLogger(__name__)

IP_RATE_WINDOW = 60
STATIC_ASSET_PREFIX = "/_app/"
MEDIA_PATH_PREFIX = "/audio/"
JOB_STREAM_PATH_PREFIX = "/api/jobs/"
JOB_STREAM_PATH_SUFFIX = "/stream"

# Every Range-served audio endpoint outside `/audio/*`, one regex per
# literal route in sharing_api.py / queue_stream_api.py -- each requires
# the `audio` segment at the exact position that route defines, so a slug
# that literally reads "audio" cannot slide a real metadata route
# (`/shared/{slug}`, `/shared/{slug}/cover`, the `/stream` manifest POSTs)
# into the Media class by shape alone (issue #257 review finding:
# `/shared/song/audio`, `/shared/audio/cover`, etc. must stay API).
# `[^/]+` pins the slug/id to exactly one segment; the trailing `/.+` on
# the filename routes requires an actual filename segment, so a bare
# `.../audio` with nothing after it (what a same-shaped metadata slug
# produces) does not match. The bare-slug pattern additionally excludes
# the `song/`, `gen/`, `playlist/`, and `queue-streams/` prefixes via a
# negative lookahead -- without it, `/shared/playlist/audio/stream`
# ([^/]+="playlist", filename="stream") would misclassify the
# `/shared/playlist/{slug}/stream` manifest POST (slug="audio") as Media;
# the router resolves that path to the metadata handler, not the bare-slug
# audio route, and the four sibling routes already have their own patterns
# below, so excluding their prefixes here costs the bare-slug pattern
# nothing. All are `FileResponse`, which serves Range requests -- the same
# seek/scrub pattern as `/audio/*`, just for a stranger listening to a
# public share (or, for the queue-streams routes, an authenticated preview)
# instead of the owner's own player. A public share is the operator's
# public face: a listener range-requesting a shared album must not be
# locked out by the same API budget that locked out the operator's own
# player.
AUDIO_ROUTE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^/shared/(?!song/|gen/|playlist/|queue-streams/)[^/]+/audio/.+$"),
    re.compile(r"^/shared/song/[^/]+/audio/.+$"),        # /shared/song/{slug}/audio/{filename}
    re.compile(r"^/shared/gen/[^/]+/audio/.+$"),         # /shared/gen/{slug}/audio/{filename}
    re.compile(r"^/shared/playlist/[^/]+/audio/.+$"),    # /shared/playlist/{slug}/audio/{filename}
    re.compile(r"^/shared/queue-streams/[^/]+/audio$"),  # /shared/queue-streams/{id}/audio
    re.compile(r"^/api/queue-streams/[^/]+/audio$"),     # /api/queue-streams/{id}/audio
)

# Static PWA root assets are fetched by the browser and the service worker
# outside of user-driven navigation, so they must not compete with `/api/*`
# calls for any class's budget. No API path belongs in this allowlist.
#
# `/health` is deliberately NOT here: it is the most expensive anonymous
# endpoint (a DB query plus ~6 Redis round trips for worker/queue state),
# the browser only polls it every 15s (~4/min, see health.ts), and nothing
# in the deploy hits it as a healthcheck (docker-compose.yml has none) --
# exempting it would let an anonymous caller hammer the priciest endpoint
# for free. It stays in the API class.
RATE_LIMIT_EXEMPT_PATHS = frozenset({
    "/manifest.webmanifest",
    "/robots.txt",
    "/favicon.svg",
    "/service-worker.js",
}) | PWA_ICON_PATHS


class RateLimitClass(Enum):
    """A request's budget class, decided once by `_classify_path`."""

    API = auto()
    MEDIA = auto()
    STREAM = auto()


def _is_job_stream_path(path: str) -> bool:
    return path.startswith(JOB_STREAM_PATH_PREFIX) and path.endswith(JOB_STREAM_PATH_SUFFIX)


def _is_audio_route(path: str) -> bool:
    return any(pattern.match(path) for pattern in AUDIO_ROUTE_PATTERNS)


def _classify_path(path: str) -> RateLimitClass:
    """Map a request path to its rate-limit budget class.

    Every path gets a class. An unrecognized path is API, not exempt --
    fail closed rather than let an unclassified route slip through unlimited.
    """
    if path.startswith(MEDIA_PATH_PREFIX) or _is_audio_route(path):
        return RateLimitClass.MEDIA
    if path == RESOURCE_EVENT_STREAM_PATH or _is_job_stream_path(path):
        return RateLimitClass.STREAM
    return RateLimitClass.API


class IpRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(app, **kwargs)
        self._limiters: dict[RateLimitClass, RedisRateLimiter] = {}

    def _get_limiter(
        self, ctx: AppContext, rate_limit_class: RateLimitClass,
    ) -> RedisRateLimiter:
        limiter = self._limiters.get(rate_limit_class)
        if limiter is None:
            from songmaker_cli.constants import (
                REDIS_RL_IP_MEDIA_PREFIX,
                REDIS_RL_IP_PREFIX,
                REDIS_RL_IP_STREAM_PREFIX,
            )
            from songmaker_cli.redis_client import RedisRateLimiter
            settings = get_settings()
            prefix, budget = {
                RateLimitClass.API: (REDIS_RL_IP_PREFIX, settings.ip_rate_limit),
                RateLimitClass.MEDIA: (REDIS_RL_IP_MEDIA_PREFIX, settings.media_rate_limit),
                RateLimitClass.STREAM: (REDIS_RL_IP_STREAM_PREFIX, settings.stream_rate_limit),
            }[rate_limit_class]
            limiter = RedisRateLimiter(ctx.redis, prefix, budget, IP_RATE_WINDOW)
            self._limiters[rate_limit_class] = limiter
        return limiter

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path
        if path.startswith(STATIC_ASSET_PREFIX) or path in RATE_LIMIT_EXEMPT_PATHS:
            return await call_next(request)
        from songmaker_cli.auth import resolve_client_ip
        ctx: AppContext = request.app.state.ctx
        ip = resolve_client_ip(request)
        rate_limit_class = _classify_path(path)
        try:
            allowed = self._get_limiter(ctx, rate_limit_class).is_allowed(ip)
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

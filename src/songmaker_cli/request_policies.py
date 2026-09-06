"""Songmaker's answers to the request policies `webauth` asks for.

The library owns what a rate limit, a CSRF check, a body cap, and a response
header are. Which of songmaker's own paths each of them applies to is a
product decision and lives here, built once at startup and handed to the
middleware in `server.create_app`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from songmaker_cli.constants import PWA_ICON_PATHS, RESOURCE_EVENT_STREAM_PATH
from webauth.policies import (
    BodySizePolicy,
    BodySizeRule,
    CacheControlRule,
    CsrfPolicy,
    PathRules,
    PathShape,
    RateLimitBudget,
    RateLimitClass,
    RateLimitPolicy,
    SecurityHeadersPolicy,
    default_content_security_policy,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from songmaker_cli.settings import Settings

IP_RATE_LIMIT_WINDOW_SECONDS: Final = 60

API_PATH_PREFIX: Final = "/api/"
STATIC_ASSET_PREFIX: Final = "/_app/"
MEDIA_PATH_PREFIX: Final = "/audio/"
JOB_STREAM_PATH: Final = PathShape(starts_with="/api/jobs/", ends_with="/stream")

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
RATE_LIMIT_EXEMPT_PATHS: Final[frozenset[str]] = frozenset({
    "/manifest.webmanifest",
    "/robots.txt",
    "/favicon.svg",
    "/service-worker.js",
}) | PWA_ICON_PATHS

# A login and a first-time setup carry no session yet, so they cannot submit
# a session-bound CSRF token; workers on `/api/internal/*` have no session
# at all and authenticate with the internal token instead. Both still owe
# the same-origin check.
CSRF_TOKEN_EXEMPT_PATHS: Final[frozenset[str]] = frozenset({
    "/api/auth/login", "/api/auth/setup",
})
CSRF_TOKEN_EXEMPT_PREFIXES: Final[tuple[str, ...]] = ("/api/internal/",)

# Large multipart uploads are a path-exact allowlist, never a suffix match:
# an unrelated route ending in `/reimport` must not inherit an upload budget.
AUDIO_UPLOAD_PATH: Final = "/api/audio/upload"
LORA_SAMPLE_ROUTE: Final = re.compile(r"^/api/loras/[^/]+/samples\Z")
SONG_REIMPORT_ROUTE: Final = re.compile(r"^/api/songs/[^/]+/reimport\Z")
SONG_COVER_ROUTE: Final = re.compile(r"^/api/songs/[^/]+/cover\Z")
ALBUM_COVER_ROUTE: Final = re.compile(r"^/api/albums/[^/]+/cover\Z")
PLAYLIST_COVER_ROUTE: Final = re.compile(r"^/api/playlists/[^/]+/cover\Z")
COVER_UPLOAD_METHODS: Final[frozenset[str]] = frozenset({"POST"})

RESOURCE_EVENT_STREAM_CACHE_CONTROL: Final = "no-cache, no-store"
API_CACHE_CONTROL: Final = "no-store"


def build_rate_limit_policy(settings: Settings) -> RateLimitPolicy:
    """The three per-IP budgets and the paths that spend from each."""
    return RateLimitPolicy(
        budgets={
            RateLimitClass.API: RateLimitBudget(
                settings.ip_rate_limit, IP_RATE_LIMIT_WINDOW_SECONDS,
            ),
            RateLimitClass.MEDIA: RateLimitBudget(
                settings.media_rate_limit, IP_RATE_LIMIT_WINDOW_SECONDS,
            ),
            RateLimitClass.STREAM: RateLimitBudget(
                settings.stream_rate_limit, IP_RATE_LIMIT_WINDOW_SECONDS,
            ),
        },
        exempt=PathRules(
            exact=RATE_LIMIT_EXEMPT_PATHS, prefixes=(STATIC_ASSET_PREFIX,),
        ),
        media=PathRules(
            prefixes=(MEDIA_PATH_PREFIX,), patterns=AUDIO_ROUTE_PATTERNS,
        ),
        stream=PathRules(
            exact=frozenset({RESOURCE_EVENT_STREAM_PATH}), shapes=(JOB_STREAM_PATH,),
        ),
    )


def build_csrf_policy() -> CsrfPolicy:
    """Every mutating API call is same-origin; most also carry a token."""
    return CsrfPolicy(
        protected=PathRules(prefixes=(API_PATH_PREFIX,)),
        token_exempt=PathRules(
            exact=CSRF_TOKEN_EXEMPT_PATHS, prefixes=CSRF_TOKEN_EXEMPT_PREFIXES,
        ),
    )


def build_body_size_policy(settings: Settings) -> BodySizePolicy:
    """A small JSON cap for every route, raised on the upload routes only."""
    return BodySizePolicy(
        default_max_bytes=settings.max_request_body_bytes,
        rules=(
            BodySizeRule(
                paths=PathRules(exact=frozenset({AUDIO_UPLOAD_PATH})),
                max_bytes=settings.max_upload_body_bytes,
            ),
            BodySizeRule(
                paths=PathRules(patterns=(LORA_SAMPLE_ROUTE,)),
                max_bytes=settings.max_upload_body_bytes,
            ),
            BodySizeRule(
                paths=PathRules(patterns=(SONG_REIMPORT_ROUTE,)),
                max_bytes=settings.max_reimport_body_bytes,
            ),
            BodySizeRule(
                paths=PathRules(patterns=(SONG_COVER_ROUTE,)),
                max_bytes=settings.max_cover_upload_body_bytes,
            ),
            BodySizeRule(
                paths=PathRules(patterns=(ALBUM_COVER_ROUTE, PLAYLIST_COVER_ROUTE)),
                max_bytes=settings.max_cover_upload_body_bytes,
                methods=COVER_UPLOAD_METHODS,
            ),
        ),
    )


def build_security_headers_policy(script_hashes: Sequence[str]) -> SecurityHeadersPolicy:
    """The library's default policy, plus what may be cached: nothing under `/api/`.

    The resource-event stream additionally forbids caching its reconnect
    stream in an intermediary, which `no-store` alone does not.
    """
    return SecurityHeadersPolicy(
        content_security_policy=default_content_security_policy(script_hashes),
        cache_control_rules=(
            CacheControlRule(
                paths=PathRules(exact=frozenset({RESOURCE_EVENT_STREAM_PATH})),
                value=RESOURCE_EVENT_STREAM_CACHE_CONTROL,
            ),
            CacheControlRule(
                paths=PathRules(prefixes=(API_PATH_PREFIX,)),
                value=API_CACHE_CONTROL,
            ),
        ),
    )

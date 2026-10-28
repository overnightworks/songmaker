"""Songmaker's answers to the request policies `webauth` asks for.

The library owns what a rate limit, a CSRF check, a body cap, and a response
header are. Which of songmaker's own paths each of them applies to is a
product decision and lives here, built once at startup and handed to the
middleware in `server.create_app`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from webauth.policies import (
    BodySizePolicy,
    BodySizeRule,
    CacheControlRule,
    CspDirective,
    CsrfPolicy,
    PathRules,
    PathShape,
    RateLimitBudget,
    RateLimitPolicy,
    RateLimitRule,
    SecurityHeadersPolicy,
    default_content_security_policy,
)
from webauth.sign_in_routes import SignInPaths

from songmaker_cli.constants import (
    LOGOUT_PATH,
    OIDC_CALLBACK_PATH,
    OIDC_START_PATH,
    PWA_ICON_PATHS,
    RESOURCE_EVENT_STREAM_PATH,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from songmaker_cli.settings import Settings

IP_RATE_LIMIT_WINDOW_SECONDS: Final = 60
API_BUDGET_NAME: Final = "api"
MEDIA_BUDGET_NAME: Final = "media"
STREAM_BUDGET_NAME: Final = "stream"

API_PATH_PREFIX: Final = "/api/"
INTERNAL_API_PREFIX: Final = "/api/internal/"
STATIC_ASSET_PREFIX: Final = "/_app/"
MEDIA_PATH_PREFIX: Final = "/audio/"
JOB_STREAM_PATH: Final = PathShape(starts_with="/api/jobs/", ends_with="/stream")

# Every Range-served audio endpoint outside `/audio/*`, one regex per
# literal route in sharing_api.py -- each requires
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
# public share instead of the owner's own player. A public share is the operator's
# public face: a listener range-requesting a shared album must not be
# locked out by the same API budget that locked out the operator's own
# player.
AUDIO_ROUTE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^/shared/(?!song/|gen/|playlist/|queue-streams/)[^/]+/audio/.+$"),
    re.compile(r"^/shared/song/[^/]+/audio/.+$"),        # /shared/song/{slug}/audio/{filename}
    re.compile(r"^/shared/gen/[^/]+/audio/.+$"),         # /shared/gen/{slug}/audio/{filename}
    re.compile(r"^/shared/playlist/[^/]+/audio/.+$"),    # /shared/playlist/{slug}/audio/{filename}
    re.compile(r"^/shared/queue-streams/[^/]+/audio$"),  # /shared/queue-streams/{id}/audio
)

# The realm calls this over the private network `hal_backchannel_songmaker`, where
# songmaker-web carries the alias of the public host, on the container's fixed port. The
# Logout Token's signature is the boundary and the edge denies the path publicly; the Host
# "<public host>:<port>" only filters routing: any other admitted Host gets an empty 404, an
# unlisted one TrustedHost's 400.
BACKCHANNEL_LOGOUT_PATH: Final = "/auth/backchannel-logout"

# Static PWA root assets are fetched by the browser and the service worker
# outside of user-driven navigation, so they must not compete with `/api/*`
# calls for any class's budget. No API path belongs in this allowlist, except the
# realm's back-channel call, which a throttled caller must not be able to starve.
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

# The four sign-in routes; webauth derives their CSRF, rate-limit, body-size and cache rules.
SIGN_IN_PATHS: Final = SignInPaths(
    start=OIDC_START_PATH,
    callback=OIDC_CALLBACK_PATH,
    logout=LOGOUT_PATH,
    backchannel_logout=BACKCHANNEL_LOGOUT_PATH,
)

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
# The shell names the current build's hashed files, which a deploy deletes.
SPA_SHELL_HEADERS: Final = {"Cache-Control": "no-cache"}
STYLE_SOURCES_ADDED: Final = {CspDirective.STYLE_SRC: ("'unsafe-inline'",)}


def build_rate_limit_policy(settings: Settings) -> RateLimitPolicy:
    """The three per-IP budgets and the paths that spend from each."""
    return RateLimitPolicy(
        default=RateLimitBudget(
            API_BUDGET_NAME, settings.ip_rate_limit, IP_RATE_LIMIT_WINDOW_SECONDS,
        ),
        rules=(
            RateLimitRule(
                paths=PathRules(prefixes=(MEDIA_PATH_PREFIX,), patterns=AUDIO_ROUTE_PATTERNS),
                budget=RateLimitBudget(
                    MEDIA_BUDGET_NAME, settings.media_rate_limit, IP_RATE_LIMIT_WINDOW_SECONDS,
                ),
            ),
            RateLimitRule(
                paths=PathRules(
                    exact=frozenset({RESOURCE_EVENT_STREAM_PATH}), shapes=(JOB_STREAM_PATH,),
                ),
                budget=RateLimitBudget(
                    STREAM_BUDGET_NAME, settings.stream_rate_limit, IP_RATE_LIMIT_WINDOW_SECONDS,
                ),
            ),
        ),
        exempt=PathRules(
            exact=RATE_LIMIT_EXEMPT_PATHS | SIGN_IN_PATHS.backchannel.exact,
            prefixes=(STATIC_ASSET_PREFIX,),
        ),
    )


def build_csrf_origin_policy() -> CsrfPolicy:
    """Every state-changing request is checked for the same origin; it is the only CSRF guard.

    The realm's back-channel call and the workers on `/api/internal/*` have no
    session and no browser: the Logout Token and the internal token are their proof.
    """
    return CsrfPolicy(
        exempt=PathRules(
            exact=SIGN_IN_PATHS.backchannel.exact, prefixes=(INTERNAL_API_PREFIX,),
        ),
    )


def build_body_size_policy(settings: Settings) -> BodySizePolicy:
    """A small JSON cap for every route, raised on the upload routes only."""
    return BodySizePolicy(
        default_max_bytes=settings.max_request_body_bytes,
        rules=(
            SIGN_IN_PATHS.backchannel_body_size_rule,
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

    The SvelteKit build applies inline styles, which the default `style-src 'self'`
    blocks, so this is the one source the app adds.

    The resource-event stream additionally forbids caching its reconnect
    stream in an intermediary, which `no-store` alone does not.
    """
    return SecurityHeadersPolicy(
        content_security_policy=default_content_security_policy(
            script_hashes, added_sources=STYLE_SOURCES_ADDED,
        ),
        cache_control_rules=(
            CacheControlRule(
                paths=PathRules(exact=frozenset({RESOURCE_EVENT_STREAM_PATH})),
                value=RESOURCE_EVENT_STREAM_CACHE_CONTROL,
            ),
            CacheControlRule(
                paths=PathRules(prefixes=(API_PATH_PREFIX,)),
                value=API_CACHE_CONTROL,
            ),
            SIGN_IN_PATHS.cache_control_rule,
        ),
    )

"""What the public share routes of both halves use: the rate limit and the audio name."""

from __future__ import annotations

from typing import Final

from fastapi import HTTPException, Request
from webauth.proxies import resolve_client_ip
from webauth.rate_limit import RedisRateLimitBackend

import songmaker_cli.constants as _consts
from songmaker_cli.api_helpers import RateLimitRejected, enforce_rate_limit, get_cached_limiter
from songmaker_cli.app_context import AppContext
from songmaker_cli.audio_paths import AudioPathRejectedError, require_canonical_audio_filename
from songmaker_cli.constants import (
    REDIS_RL_SHARED_PREFIX,
    REDIS_RL_SHARED_STREAM_PREFIX,
    LimiterFailurePolicy,
)
from songmaker_cli.db.models import Generation

NOT_FOUND_DETAIL: Final = "Not found"
# A public audio address names the take, never its stored path: that path
# starts with the creator's account id.
SHARED_AUDIO_SUFFIX: Final = ".mp3"


# Public, unauthenticated share endpoints fail open: blocking real listeners
# on a transient Redis outage is worse than a brief, unenforced rate limit.
_SHARED_LIMITER_FAILURE_POLICY = LimiterFailurePolicy.FAIL_OPEN


def get_shared_limiter(request: Request, *, stream: bool = False) -> RedisRateLimitBackend:
    state_attr, prefix = (
        ("_shared_stream_limiter", REDIS_RL_SHARED_STREAM_PREFIX)
        if stream else ("_shared_limiter", REDIS_RL_SHARED_PREFIX)
    )

    def build() -> RedisRateLimitBackend:
        ctx: AppContext = request.app.state.ctx
        return RedisRateLimitBackend(ctx.redis, prefix)

    return get_cached_limiter(request, state_attr, build)


def check_shared_rate_limit(request: Request) -> None:
    check_rate_limit(
        request,
        get_shared_limiter(request),
        limit=_consts.SHARING_RATE_LIMIT,
        window_seconds=_consts.SHARING_RATE_WINDOW_SECONDS,
    )


def check_rate_limit(
    request: Request,
    limiter: RedisRateLimitBackend,
    *,
    limit: int,
    window_seconds: int,
) -> None:
    try:
        enforce_rate_limit(
            limiter, resolve_client_ip(request),
            policy=_SHARED_LIMITER_FAILURE_POLICY,
            limit=limit,
            window_seconds=window_seconds,
            unavailable_log_message="Shared rate limiter unavailable -- allowing request",
        )
    except RateLimitRejected as rejected:
        raise HTTPException(  # unread: share
            429, "Too many requests",
            headers={"Retry-After": str(rejected.retry_after_seconds)},
        ) from rejected


def shared_audio_url_for_take(route: str, generation: Generation) -> str | None:
    if not generation.mp3_path:
        return None
    try:
        require_canonical_audio_filename(generation.mp3_path)
    except AudioPathRejectedError:
        return None
    return f"{route}/{generation.id}{SHARED_AUDIO_SUFFIX}"


def generation_id_of_shared_audio_name(filename: str) -> str | None:
    generation_id = filename.removesuffix(SHARED_AUDIO_SUFFIX)
    if generation_id == filename or not generation_id or "/" in generation_id:
        return None
    return generation_id


def entry_album(entry):
    generation = entry.generation
    return generation.song.album if generation is not None and generation.song else None

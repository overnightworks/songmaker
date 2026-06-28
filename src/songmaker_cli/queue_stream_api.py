"""Authenticated queue stream endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

import songmaker_cli.constants as _consts
from songmaker_cli.api_helpers import check_generation_access
from songmaker_cli.api_models.queue_streams import (
    QueueStreamManifestResponse,
    QueueStreamSnapshotRequest,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.constants import AUDIO_MEDIA_TYPES, REDIS_RL_QUEUE_STREAM_PREFIX
from songmaker_cli.middleware import AuthenticatedUser, get_current_user
from songmaker_cli.queue_streams import (
    build_queue_stream_snapshot,
    load_queue_stream_manifest,
    queue_stream_audio_path,
    track_source_from_generation,
)
from songmaker_cli.redis_client import RedisRateLimiter

router = APIRouter()
log = logging.getLogger(__name__)


def _get_queue_stream_limiter(request: Request) -> RedisRateLimiter:
    limiter = getattr(request.app.state, "_queue_stream_limiter", None)
    if limiter is None:
        ctx: AppContext = request.app.state.ctx
        limiter = RedisRateLimiter(
            ctx.redis,
            REDIS_RL_QUEUE_STREAM_PREFIX,
            _consts.QUEUE_STREAM_AUTH_RATE_LIMIT,
            _consts.QUEUE_STREAM_AUTH_RATE_WINDOW_SECONDS,
        )
        request.app.state._queue_stream_limiter = limiter
    return limiter


def _check_queue_stream_rate_limit(request: Request, user: AuthenticatedUser) -> None:
    try:
        allowed = _get_queue_stream_limiter(request).is_allowed(user.id)
    except Exception:
        log.warning("Queue stream rate limiter unavailable -- allowing request")
        return
    if not allowed:
        raise HTTPException(
            429,
            "Too many queue stream requests",
            headers={"Retry-After": str(_consts.QUEUE_STREAM_AUTH_RATE_WINDOW_SECONDS)},
        )


@router.post("/queue-streams")
def api_create_queue_stream(
    req: QueueStreamSnapshotRequest,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> QueueStreamManifestResponse:
    _check_queue_stream_rate_limit(request, user)
    sources = []
    for index, item in enumerate(req.tracks):
        gen = check_generation_access(session, item.generation_id, user)
        key = item.entry_id or f"{item.generation_id}:{index}"
        sources.append(
            track_source_from_generation(
                gen,
                key=key,
                index=index,
                entry_id=item.entry_id,
                audio_url=f"/audio/{gen.mp3_path}",
            )
        )

    snapshot = build_queue_stream_snapshot(
        ctx,
        sources,
        scope="auth",
        scope_id=user.id,
        stream_url="",
    )
    snapshot.stream_url = f"/api/queue-streams/{snapshot.snapshot_id}/audio"
    return snapshot


@router.get("/queue-streams/{snapshot_id}/audio")
def api_get_queue_stream_audio(
    snapshot_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    manifest = load_queue_stream_manifest(ctx, snapshot_id)
    if manifest.get("scope") != "auth" or manifest.get("scope_id") != user.id:
        raise HTTPException(404, "Queue stream not found")
    audio_path = queue_stream_audio_path(ctx, snapshot_id)
    media_type = AUDIO_MEDIA_TYPES.get(audio_path.suffix, "application/octet-stream")
    return FileResponse(audio_path, media_type=media_type)

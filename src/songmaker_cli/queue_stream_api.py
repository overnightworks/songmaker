"""Authenticated queue stream endpoints."""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

import songmaker_cli.constants as _consts
from songmaker_cli.api_helpers import check_generation_access
from songmaker_cli.api_models.queue_streams import (
    QueueStreamLibraryRequest,
    QueueStreamManifestResponse,
    QueueStreamPinResponse,
    QueueStreamSnapshotRequest,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.constants import AUDIO_MEDIA_TYPES, REDIS_RL_QUEUE_STREAM_PREFIX
from songmaker_cli.db.models import Generation, Song
from songmaker_cli.db.queries import list_songs
from songmaker_cli.middleware import AuthenticatedUser, get_current_user
from songmaker_cli.queue_streams import (
    PinnedBytesExceededError,
    QueueStreamSource,
    build_queue_stream_snapshot,
    load_queue_stream_manifest,
    pin_snapshot,
    queue_stream_audio_path,
    track_source_from_generation,
    unpin_snapshot,
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


def _pick_library_generation(song: Song) -> Generation | None:
    """Return the generation to stream for this song in a library snapshot.

    Prefers the picked (non-archived) generation; falls back to the first
    (newest) non-archived generation that has an mp3_path.  Returns None when
    the song has no eligible generation — callers skip such songs.
    """
    picked = next(
        (g for g in song.generations if g.is_picked and not g.is_archived and g.mp3_path),
        None,
    )
    if picked is not None:
        return picked
    return next(
        (g for g in song.generations if not g.is_archived and g.mp3_path),
        None,
    )


def shuffle_library_sources(
    sources: list[QueueStreamSource],
    start_generation_id: str | None,
    shuffle_seq: Callable[[list[QueueStreamSource]], None] | None = None,
) -> list[QueueStreamSource]:
    if len(sources) <= 1:
        return list(sources)
    seen: set[str] = set()
    unique: list[QueueStreamSource] = []
    for source in sources:
        generation_id = source.generation.id
        if generation_id in seen:
            continue
        seen.add(generation_id)
        unique.append(source)
    mix = shuffle_seq if shuffle_seq is not None else random.shuffle
    if start_generation_id is None:
        mix(unique)
        return unique
    start: QueueStreamSource | None = None
    rest: list[QueueStreamSource] = []
    for item in unique:
        if start is None and item.generation.id == start_generation_id:
            start = item
        else:
            rest.append(item)
    mix(rest)
    if start is None:
        return rest
    return [start, *rest]


@router.post("/queue-streams/library")
def api_create_library_queue_stream(
    req: QueueStreamLibraryRequest,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> QueueStreamManifestResponse:
    _check_queue_stream_rate_limit(request, user)

    songs = list_songs(session, user_id=user.id, light=True)
    songs = sorted(
        songs,
        key=lambda song: (
            song.album.title if song.album is not None else "",
            song.track_number,
            song.id,
        ),
    )

    start_gen: Generation | None = None
    if req.start_generation_id is not None:
        try:
            start_gen = check_generation_access(session, req.start_generation_id, user)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            start_gen = None

    def _library_generation_for_song(song: Song) -> Generation | None:
        if (
            start_gen is not None
            and start_gen.song_id == song.id
            and not start_gen.is_archived
            and start_gen.mp3_path
        ):
            return start_gen
        return _pick_library_generation(song)

    sources: list[QueueStreamSource] = [
        track_source_from_generation(
            gen,
            key=gen.id,
            index=0,  # placeholder; reindexed below
            entry_id=None,
            audio_url=f"/audio/{gen.mp3_path}",
        )
        for song in songs
        for gen in [_library_generation_for_song(song)]
        if gen is not None
    ]

    if req.shuffle:
        sources = shuffle_library_sources(
            sources, start_gen.id if start_gen is not None else None
        )
    elif start_gen is not None:
        rotation_pos = next(
            (i for i, s in enumerate(sources) if s.generation.id == start_gen.id),
            None,
        )
        if rotation_pos is not None:
            sources = sources[rotation_pos:] + sources[:rotation_pos]

    sources = [replace(s, index=new_idx) for new_idx, s in enumerate(sources)]

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


@router.post("/queue-streams/{snapshot_id}/pin")
def api_pin_queue_stream(
    snapshot_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    ctx: AppContext = Depends(get_app_context),
) -> QueueStreamPinResponse:
    _check_queue_stream_rate_limit(request, user)
    manifest = load_queue_stream_manifest(ctx, snapshot_id)
    if manifest.get("scope") != "auth" or manifest.get("scope_id") != user.id:
        raise HTTPException(404, "Queue stream not found")
    try:
        updated = pin_snapshot(ctx, snapshot_id)
    except PinnedBytesExceededError:
        raise HTTPException(409, "Pinned storage cap reached")
    return QueueStreamPinResponse(
        snapshot_id=snapshot_id,
        pinned=bool(updated.get("pinned", False)),
        pinned_at=updated.get("pinned_at"),
    )


@router.delete("/queue-streams/{snapshot_id}/pin")
def api_unpin_queue_stream(
    snapshot_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    ctx: AppContext = Depends(get_app_context),
) -> QueueStreamPinResponse:
    _check_queue_stream_rate_limit(request, user)
    manifest = load_queue_stream_manifest(ctx, snapshot_id)
    if manifest.get("scope") != "auth" or manifest.get("scope_id") != user.id:
        raise HTTPException(404, "Queue stream not found")
    updated = unpin_snapshot(ctx, snapshot_id)
    return QueueStreamPinResponse(
        snapshot_id=snapshot_id,
        pinned=bool(updated.get("pinned", False)),
        pinned_at=updated.get("pinned_at"),
    )

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
    LibraryTakePool,
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
    resolve_audio_path,
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
    except Exception as exc:
        log.warning("Queue stream rate limiter unavailable -- rejecting request")
        raise HTTPException(503, "Queue stream rate limiter unavailable") from exc
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


def generation_matches_pool(generation: Generation, pool: LibraryTakePool) -> bool:
    if generation.is_archived or not generation.mp3_path:
        return False
    if pool == "mix":
        return bool(generation.is_picked or generation.is_kept)
    if pool == "picks":
        return bool(generation.is_picked)
    if pool == "keeps":
        return bool(generation.is_kept)
    if pool == "all":
        return True
    raise ValueError(f"Unknown library take pool: {pool}")


def _take_sort_key(generation: Generation) -> tuple[float, str]:
    created = generation.created_at
    timestamp = -created.timestamp() if created is not None else 0.0
    return (timestamp, generation.id)


def collect_library_pool_generations(
    songs: list[Song],
    pool: LibraryTakePool,
    start_gen: Generation | None,
    is_readable: Callable[[Generation], bool],
) -> list[Generation]:
    selected: list[Generation] = []
    seen: set[str] = set()
    for song in songs:
        takes = [gen for gen in song.generations if generation_matches_pool(gen, pool)]
        takes.sort(key=_take_sort_key)
        for gen in takes:
            if gen.id in seen or not is_readable(gen):
                continue
            seen.add(gen.id)
            selected.append(gen)
    if (
        start_gen is not None
        and start_gen.id not in seen
        and not start_gen.is_archived
        and start_gen.mp3_path
        and is_readable(start_gen)
    ):
        selected.insert(0, start_gen)
    return selected


def _library_audio_readable(ctx: AppContext, generation: Generation) -> bool:
    if not generation.mp3_path:
        return False
    try:
        resolve_audio_path(ctx.audio_dir, generation.mp3_path)
    except HTTPException:
        return False
    return True


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
        start_gen = check_generation_access(session, req.start_generation_id, user)

    pool_generations = collect_library_pool_generations(
        songs,
        req.pool,
        start_gen,
        lambda gen: _library_audio_readable(ctx, gen),
    )
    if not pool_generations:
        raise HTTPException(422, f"No playable takes in pool '{req.pool}'")

    sources: list[QueueStreamSource] = [
        track_source_from_generation(
            gen,
            key=gen.id,
            index=0,
            entry_id=None,
            audio_url=f"/audio/{gen.mp3_path}",
        )
        for gen in pool_generations
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

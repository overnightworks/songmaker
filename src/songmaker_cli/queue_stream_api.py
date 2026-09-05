"""Authenticated queue stream endpoints."""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Final

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

import songmaker_cli.constants as _consts
from songmaker_cli import queue_streams
from songmaker_cli.api_helpers import (
    check_generation_access,
    enforce_rate_limit,
    get_cached_limiter,
    raise_audio_file_http_error,
)
from songmaker_cli.api_models.queue_streams import (
    LibraryTakePool,
    QueueStreamLibraryRequest,
    QueueStreamManifestResponse,
    QueueStreamPinResponse,
    QueueStreamSkipResponse,
    QueueStreamSnapshotRequest,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.audio_paths import AudioFileNotFoundError
from songmaker_cli.constants import (
    AUDIO_MEDIA_TYPES,
    REDIS_RL_QUEUE_STREAM_PREFIX,
    LimiterFailurePolicy,
)
from songmaker_cli.db.models import Generation, Song
from songmaker_cli.db.queries import list_songs
from songmaker_cli.middleware import AuthenticatedUser, get_current_user
from songmaker_cli.queue_streams import (
    PinnedBytesExceededError,
    QueueStreamSource,
    build_queue_stream_snapshot,
    ensure_sources_detachable,
    load_queue_stream_manifest,
    pin_snapshot,
    prepare_queue_stream_admission,
    queue_stream_audio_path,
    track_source_from_generation,
    unpin_snapshot,
)
from songmaker_cli.redis_client import RedisRateLimiter

router = APIRouter()

QUEUE_STREAM_NOT_FOUND_DETAIL: Final = "Queue stream not found"
LIBRARY_QUEUE_STREAM_SCAN_LIMIT = 1_000


# Authenticated queue-stream creation fails closed: an unenforced limit here
# could let one user exhaust storage or worker capacity unbounded.
_QUEUE_STREAM_LIMITER_FAILURE_POLICY = LimiterFailurePolicy.FAIL_CLOSED


def _get_queue_stream_limiter(request: Request) -> RedisRateLimiter:
    def _build() -> RedisRateLimiter:
        ctx: AppContext = request.app.state.ctx
        return RedisRateLimiter(
            ctx.redis,
            REDIS_RL_QUEUE_STREAM_PREFIX,
            _consts.QUEUE_STREAM_AUTH_RATE_LIMIT,
            _consts.QUEUE_STREAM_AUTH_RATE_WINDOW_SECONDS,
        )

    return get_cached_limiter(request, "_queue_stream_limiter", _build)


def check_queue_stream_rate_limit(request: Request, user: AuthenticatedUser) -> None:
    enforce_rate_limit(
        _get_queue_stream_limiter(request),
        user.id,
        policy=_QUEUE_STREAM_LIMITER_FAILURE_POLICY,
        reject_detail="Too many queue stream requests",
        retry_after_seconds=_consts.QUEUE_STREAM_AUTH_RATE_WINDOW_SECONDS,
        unavailable_log_message="Queue stream rate limiter unavailable -- rejecting request",
        unavailable_detail="Queue stream rate limiter unavailable",
    )


@router.post("/queue-streams")
def api_create_queue_stream(
    req: QueueStreamSnapshotRequest,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> QueueStreamManifestResponse:
    check_queue_stream_rate_limit(request, user)
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

    ensure_sources_detachable(sources)
    session.close()
    try:
        admission = prepare_queue_stream_admission(ctx, sources)
    except AudioFileNotFoundError as exc:
        raise_audio_file_http_error(exc, public=False)

    snapshot = build_queue_stream_snapshot(
        ctx,
        sources,
        scope="auth",
        scope_id=user.id,
        stream_url="",
        admission=admission,
    )
    snapshot.stream_url = f"/api/queue-streams/{snapshot.snapshot_id}/audio"
    return snapshot


def generation_matches_pool(generation: Generation, pool: LibraryTakePool) -> bool:
    if generation.is_archived:
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
) -> list[Generation]:
    selected: list[Generation] = []
    seen: set[str] = set()
    for song in songs:
        takes = [gen for gen in song.generations if generation_matches_pool(gen, pool)]
        takes.sort(key=_take_sort_key)
        for gen in takes:
            if gen.id in seen:
                continue
            seen.add(gen.id)
            selected.append(gen)
    if start_gen is not None and start_gen.id not in seen and not start_gen.is_archived:
        selected.insert(0, start_gen)
    return selected


def _library_skip(ctx: AppContext, generation: Generation) -> QueueStreamSkipResponse | None:
    if not generation.mp3_path:
        return QueueStreamSkipResponse(
            song_id=generation.song_id,
            generation_id=generation.id,
            reason="missing_path",
        )
    try:
        audio_path = queue_streams.resolve_audio_path(ctx.audio_dir, generation.mp3_path)
        if not audio_path.exists():
            return QueueStreamSkipResponse(
                song_id=generation.song_id,
                generation_id=generation.id,
                reason="missing_file",
            )
    except (HTTPException, OSError):
        return QueueStreamSkipResponse(
            song_id=generation.song_id,
            generation_id=generation.id,
            reason="missing_file",
        )
    try:
        if not audio_path.is_file():
            return QueueStreamSkipResponse(
                song_id=generation.song_id,
                generation_id=generation.id,
                reason="unreadable_file",
            )
        with audio_path.open("rb") as audio_file:
            audio_file.read(1)
        queue_streams.probe_audio_duration(audio_path)
    except (HTTPException, OSError):
        return QueueStreamSkipResponse(
            song_id=generation.song_id,
            generation_id=generation.id,
            reason="unreadable_file",
        )
    return None


@dataclass
class LibraryPoolMembership:
    pool: LibraryTakePool
    sources: list[QueueStreamSource]
    skipped: list[QueueStreamSkipResponse]
    skipped_complete: bool


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


def resolve_library_pool_membership(
    session: Session,
    user: AuthenticatedUser,
    ctx: AppContext,
    *,
    pool: LibraryTakePool,
    start_generation_id: str | None,
    shuffle: bool,
) -> LibraryPoolMembership:
    songs = list_songs(
        session,
        user_id=user.id,
        light=True,
        with_generations=True,
        exclude_archived_albums=True,
    )
    songs = sorted(
        songs,
        key=lambda song: (
            song.album.title if song.album is not None else "",
            song.track_number,
            song.id,
        ),
    )

    start_gen: Generation | None = None
    if start_generation_id is not None:
        start_gen = check_generation_access(session, start_generation_id, user)
        if start_gen.is_archived:
            raise HTTPException(422, _consts.QUEUE_STREAM_UNPLAYABLE_START_DETAIL)

    pool_generations = collect_library_pool_generations(
        songs,
        pool,
        start_gen,
    )
    candidate_sources = _library_candidate_sources(pool_generations)
    canonical_rank = {source.generation.id: rank for rank, source in enumerate(candidate_sources)}
    candidate_sources = _order_library_candidates(
        candidate_sources,
        start_gen,
        shuffle,
    )

    skipped, playable_sources, unscanned_tail = _scan_library_candidates(
        ctx,
        candidate_sources,
        start_gen,
    )
    if not playable_sources:
        _raise_empty_library_pool(pool, unscanned_tail)

    skipped.sort(key=lambda item: canonical_rank[item.generation_id])
    sources = [replace(source, index=index) for index, source in enumerate(playable_sources)]
    return LibraryPoolMembership(
        pool=pool,
        sources=sources,
        skipped=skipped,
        skipped_complete=not unscanned_tail,
    )


def _library_candidate_sources(pool_generations: list[Generation]) -> list[QueueStreamSource]:
    return [
        track_source_from_generation(
            gen,
            key=gen.id,
            index=index,
            entry_id=None,
            audio_url=f"/audio/{gen.mp3_path}",
        )
        for index, gen in enumerate(pool_generations)
    ]


def _order_library_candidates(
    sources: list[QueueStreamSource],
    start_gen: Generation | None,
    shuffle: bool,
) -> list[QueueStreamSource]:
    if shuffle:
        return shuffle_library_sources(sources, start_gen.id if start_gen is not None else None)
    if start_gen is None:
        return sources
    return _rotate_sources_to_start(sources, start_gen.id)


def _rotate_sources_to_start(
    sources: list[QueueStreamSource],
    start_generation_id: str,
) -> list[QueueStreamSource]:
    rotation_pos = next(
        (
            index
            for index, source in enumerate(sources)
            if source.generation.id == start_generation_id
        ),
        None,
    )
    if rotation_pos is None:
        return sources
    return sources[rotation_pos:] + sources[:rotation_pos]


def _scan_library_candidates(
    ctx: AppContext,
    candidate_sources: list[QueueStreamSource],
    start_gen: Generation | None,
) -> tuple[list[QueueStreamSkipResponse], list[QueueStreamSource], bool]:
    skipped: list[QueueStreamSkipResponse] = []
    playable_sources: list[QueueStreamSource] = []
    scanned = 0
    playable_scan_limit = queue_streams.QUEUE_STREAM_MAX_TRACKS + 1
    for source in candidate_sources:
        if (
            scanned >= LIBRARY_QUEUE_STREAM_SCAN_LIMIT
            or len(playable_sources) >= playable_scan_limit
        ):
            break
        scanned += 1
        skip = _library_skip(ctx, source.generation)
        if skip is not None:
            if start_gen is not None and source.generation.id == start_gen.id:
                raise HTTPException(422, _consts.QUEUE_STREAM_UNPLAYABLE_START_DETAIL)
            skipped.append(skip)
        else:
            playable_sources.append(source)
    return skipped, playable_sources, scanned < len(candidate_sources)


def _raise_empty_library_pool(pool: LibraryTakePool, unscanned_tail: bool) -> None:
    if unscanned_tail:
        raise HTTPException(422, "No playable takes in scanned library window")
    raise HTTPException(422, f"{_consts.QUEUE_STREAM_EMPTY_POOL_DETAIL} '{pool}'")


@router.post(
    "/queue-streams/library",
    responses={422: {"description": "Library has no playable starting take"}},
)
def api_create_library_queue_stream(
    req: QueueStreamLibraryRequest,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> QueueStreamManifestResponse:
    check_queue_stream_rate_limit(request, user)
    membership = resolve_library_pool_membership(
        session,
        user,
        ctx,
        pool=req.pool,
        start_generation_id=req.start_generation_id,
        shuffle=req.shuffle,
    )
    ensure_sources_detachable(membership.sources)
    session.close()
    try:
        admission = prepare_queue_stream_admission(ctx, membership.sources)
    except AudioFileNotFoundError as exc:
        raise_audio_file_http_error(exc, public=False)

    snapshot = build_queue_stream_snapshot(
        ctx,
        membership.sources,
        scope="auth",
        scope_id=user.id,
        stream_url="",
        force_windowed=not membership.skipped_complete,
        admission=admission,
    )
    snapshot.stream_url = f"/api/queue-streams/{snapshot.snapshot_id}/audio"
    snapshot.skipped = membership.skipped
    snapshot.skipped_complete = membership.skipped_complete
    return snapshot


@router.get(
    "/queue-streams/{snapshot_id}/audio",
    responses={404: {"description": "Queue stream does not exist"}},
)
def api_get_queue_stream_audio(
    snapshot_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    manifest = load_queue_stream_manifest(ctx, snapshot_id)
    if manifest.scope != "auth" or manifest.scope_id != user.id:
        raise HTTPException(404, QUEUE_STREAM_NOT_FOUND_DETAIL)
    audio_path = queue_stream_audio_path(ctx, snapshot_id)
    media_type = AUDIO_MEDIA_TYPES.get(audio_path.suffix, "application/octet-stream")
    return FileResponse(audio_path, media_type=media_type)


@router.post(
    "/queue-streams/{snapshot_id}/pin",
    responses={
        404: {"description": "Queue stream does not exist"},
        409: {"description": "Pinned storage cap is reached"},
    },
)
def api_pin_queue_stream(
    snapshot_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    ctx: AppContext = Depends(get_app_context),
) -> QueueStreamPinResponse:
    check_queue_stream_rate_limit(request, user)
    manifest = load_queue_stream_manifest(ctx, snapshot_id)
    if manifest.scope != "auth" or manifest.scope_id != user.id:
        raise HTTPException(404, QUEUE_STREAM_NOT_FOUND_DETAIL)
    try:
        updated = pin_snapshot(ctx, snapshot_id)
    except PinnedBytesExceededError:
        raise HTTPException(409, "Pinned storage cap reached")
    return QueueStreamPinResponse(
        snapshot_id=snapshot_id,
        pinned=updated.pinned,
        pinned_at=updated.pinned_at.isoformat() if updated.pinned_at else None,
    )


@router.delete(
    "/queue-streams/{snapshot_id}/pin",
    responses={404: {"description": "Queue stream does not exist"}},
)
def api_unpin_queue_stream(
    snapshot_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    ctx: AppContext = Depends(get_app_context),
) -> QueueStreamPinResponse:
    check_queue_stream_rate_limit(request, user)
    manifest = load_queue_stream_manifest(ctx, snapshot_id)
    if manifest.scope != "auth" or manifest.scope_id != user.id:
        raise HTTPException(404, QUEUE_STREAM_NOT_FOUND_DETAIL)
    updated = unpin_snapshot(ctx, snapshot_id)
    return QueueStreamPinResponse(
        snapshot_id=snapshot_id,
        pinned=updated.pinned,
        pinned_at=updated.pinned_at.isoformat() if updated.pinned_at else None,
    )

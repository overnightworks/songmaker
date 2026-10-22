"""Authenticated queue stream endpoints."""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from webauth.ports import AuthenticatedUser

from songmaker_cli.api_helpers import (
    check_generation_access,
    raise_audio_file_http_error,
)
from songmaker_cli.api_models.queue_streams import (
    QueueStreamLibraryRequest,
    QueueStreamManifestResponse,
    QueueStreamPinResponse,
    QueueStreamSnapshotRequest,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.audio_paths import AudioFileNotFoundError
from songmaker_cli.auth_dependencies import get_current_user
from songmaker_cli.constants import (
    AUDIO_MEDIA_TYPES,
)
from songmaker_cli.queue_streams import (
    PinnedBytesExceededError,
    build_queue_stream_snapshot,
    check_queue_stream_rate_limit,
    ensure_sources_detachable,
    load_queue_stream_manifest,
    pin_snapshot,
    prepare_queue_stream_admission,
    queue_stream_audio_path,
    resolve_library_pool_membership,
    track_source_from_generation,
    unpin_snapshot,
)

router = APIRouter()

QUEUE_STREAM_NOT_FOUND_DETAIL: Final = "Queue stream not found"


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

"""Song and Version API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import (
    Pagination,
    check_album_access,
    check_song_access,
    check_song_access_including_deleted,
    cleanup_generation_files,
    gen_params_to_dict,
    owner_filter,
)
from songmaker_cli.api_models import (
    CleanupResponse,
    PaginatedResponse,
    ShareResponse,
    SongCreateRequest,
    SongMoveRequest,
    SongResponse,
    SongSummaryResponse,
    SongUpdateRequest,
    StatusResponse,
    VersionResponse,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.constants import AuditAction, ResourceType
from songmaker_cli.db.queries import (
    RestoreWindowExpiredError,
    cleanup_song,
    count_songs,
    create_song,
    delete_version,
    disable_song_sharing,
    enable_song_sharing,
    get_album,
    list_songs,
    move_song,
    record_audit,
    restore_song,
    soft_delete_song,
    update_song,
)
from songmaker_cli.middleware import AuthenticatedUser, get_current_user

router = APIRouter()


@router.get("/songs")
def api_list_songs(
    page: Pagination,
    album_id: str | None = Query(None),
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> PaginatedResponse[SongSummaryResponse]:
    uid = owner_filter(user)
    total = count_songs(session, album_id=album_id, user_id=uid)
    songs = list_songs(
        session, album_id=album_id, user_id=uid, light=True,
        offset=page.offset, limit=page.limit,
    )
    return PaginatedResponse(
        items=[SongSummaryResponse.from_orm(s) for s in songs],
        total=total, offset=page.offset, limit=page.limit,
    )


@router.get("/songs/{song_id}")
def api_get_song(
    song_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> SongResponse:
    song = check_song_access(session, song_id, user)
    return SongResponse.from_orm(song)


@router.post("/songs")
def api_create_song(
    req: SongCreateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> SongResponse:
    album = get_album(session, req.album_id)
    check_album_access(album, user)
    song = create_song(
        session, title=req.title, album_id=req.album_id,
        lyrics=req.lyrics, prompt=req.prompt, bpm=req.bpm,
        audio_duration=req.audio_duration, key_scale=req.key_scale,
        vocal_language=req.vocal_language,
        generation_params=gen_params_to_dict(req.generation_params),
    )
    record_audit(session, user.id, AuditAction.CREATE, ResourceType.SONG, song.id)
    session.commit()
    return SongResponse.from_orm(song)


@router.put("/songs/{song_id}")
def api_update_song(
    song_id: str, req: SongUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> SongResponse:
    check_song_access(session, song_id, user)
    kwargs: dict = dict(
        lyrics=req.lyrics, prompt=req.prompt,
        bpm=req.bpm, audio_duration=req.audio_duration, key_scale=req.key_scale,
    )
    if "generation_params" in req.model_fields_set:
        kwargs["generation_params"] = gen_params_to_dict(req.generation_params)
    try:
        version = update_song(session, song_id, **kwargs)
    except ValueError:
        raise HTTPException(404, "Song not found")
    record_audit(session, user.id, AuditAction.UPDATE, ResourceType.SONG, song_id)
    session.commit()
    return SongResponse.from_orm(version.song)


@router.put("/songs/{song_id}/album")
def api_move_song(
    song_id: str, req: SongMoveRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> SongResponse:
    check_song_access(session, song_id, user)
    target_album = get_album(session, req.album_id)
    check_album_access(target_album, user)
    try:
        song = move_song(session, song_id, req.album_id)
    except ValueError:
        raise HTTPException(404, "Song or album not found")
    record_audit(
        session, user.id, AuditAction.MOVE, ResourceType.SONG,
        song_id, f"album={req.album_id}",
    )
    session.commit()
    return SongResponse.from_orm(song)


@router.delete("/songs/{song_id}")
def api_delete_song(
    song_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    check_song_access(session, song_id, user)
    try:
        soft_delete_song(session, song_id)
    except ValueError:
        raise HTTPException(404, "Song not found")
    record_audit(session, user.id, AuditAction.DELETE, ResourceType.SONG, song_id)
    session.commit()
    return StatusResponse()


@router.post("/songs/{song_id}/restore")
def api_restore_song(
    song_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> SongResponse:
    check_song_access_including_deleted(session, song_id, user)
    try:
        restored = restore_song(session, song_id)
    except RestoreWindowExpiredError as e:
        raise HTTPException(410, str(e))
    except ValueError as e:
        raise HTTPException(404, str(e))
    record_audit(session, user.id, AuditAction.RESTORE, ResourceType.SONG, song_id)
    session.commit()
    return SongResponse.from_orm(restored)


@router.post("/songs/{song_id}/cleanup")
def api_cleanup_song(
    song_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> CleanupResponse:
    check_song_access(session, song_id, user)
    count, paths = cleanup_song(session, song_id)
    record_audit(
        session, user.id, AuditAction.CLEANUP, ResourceType.SONG,
        song_id, f"deleted={count}",
    )
    session.commit()
    cleanup_generation_files(ctx.audio_dir, paths)
    return CleanupResponse(deleted=count)


@router.post("/songs/{song_id}/share")
def api_share_song(
    song_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ShareResponse:
    check_song_access(session, song_id, user)
    try:
        song = enable_song_sharing(session, song_id)
    except ValueError:
        raise HTTPException(404, "Song not found")
    record_audit(session, user.id, AuditAction.SHARE, ResourceType.SONG, song_id)
    session.commit()
    base_url = str(request.base_url).rstrip("/")
    return ShareResponse(
        share_url=f"{base_url}/share/song/{song.share_slug}",
        share_slug=song.share_slug,
    )


@router.delete("/songs/{song_id}/share")
def api_unshare_song(
    song_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    check_song_access(session, song_id, user)
    try:
        disable_song_sharing(session, song_id)
    except ValueError:
        raise HTTPException(404, "Song not found")
    record_audit(session, user.id, AuditAction.UNSHARE, ResourceType.SONG, song_id)
    session.commit()
    return StatusResponse()


@router.get("/songs/{song_id}/versions")
def api_song_versions(
    song_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[VersionResponse]:
    song = check_song_access(session, song_id, user)
    return [VersionResponse.from_orm(v) for v in reversed(song.versions)]


@router.delete("/versions/{version_id}")
def api_delete_version(
    version_id: str,
    delete_generations: bool = Query(False),
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> StatusResponse:
    from songmaker_cli.db.models import Version as VersionModel

    ver = session.query(VersionModel).filter_by(id=version_id).first()
    if not ver:
        raise HTTPException(404, "Version not found")
    check_song_access(session, ver.song_id, user)
    try:
        paths = delete_version(
            session, version_id,
            delete_generations=delete_generations,
        )
    except ValueError:
        raise HTTPException(404, "Version not found")
    record_audit(session, user.id, AuditAction.DELETE, ResourceType.VERSION, version_id)
    session.commit()
    cleanup_generation_files(ctx.audio_dir, paths)
    return StatusResponse()

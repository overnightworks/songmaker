"""Song and Version API endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import (
    Pagination,
    check_album_access,
    check_song_access,
    check_song_access_including_deleted,
    cleanup_generation_files,
    gen_params_to_json,
    owner_filter,
    page_has_more,
    parse_optional_search_query,
    resolve_public_base_url,
    unique_song_slug,
)
from songmaker_cli.api_models import (
    CleanupResponse,
    LibrarySort,
    PaginatedResponse,
    ShareResponse,
    SongCreateRequest,
    SongMoveRequest,
    SongResponse,
    SongSummaryResponse,
    SongUpdateRequest,
    StatusResponse,
    TitleUpdateRequest,
    VersionResponse,
)
from songmaker_cli.api_models.generation_params import BaseGenerationParams
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.constants import (
    COVER_MAX_BYTES,
    COVER_NOT_FOUND,
    COVER_VARIANT_DETAIL,
    COVER_VERSION_QUERY,
    AuditAction,
    ResourceType,
)
from songmaker_cli.covers import (
    COVER_RESPONSE_HEADERS,
    CoverRejectedError,
    cover_media_type,
    remove_song_cover_files,
    resolve_song_cover_file,
    write_song_cover,
)
from songmaker_cli.db.queries import (
    RestoreWindowExpiredError,
    cleanup_song,
    count_generations_by_song,
    count_songs,
    create_song,
    delete_version,
    disable_song_sharing,
    enable_song_sharing,
    get_album,
    list_songs,
    move_song,
    record_audit,
    record_song_listen,
    rename_song,
    restore_song,
    set_song_cover_key,
    soft_delete_song,
    update_song,
)
from songmaker_cli.db.queries.playlists import best_playable_generation
from songmaker_cli.middleware import AuthenticatedUser, get_current_user
from songmaker_cli.reference_audio import (
    ReferenceAudioRejected,
    resolve_owned_reference_audio,
)


def _require_owned_reference_audio(
    audio_dir: Path, user_id: str, generation_params: BaseGenerationParams | None,
) -> None:
    if generation_params is None:
        return
    path = generation_params.reference_audio_path
    if not path:
        return
    try:
        resolve_owned_reference_audio(audio_dir, user_id, path)
    except ReferenceAudioRejected as exc:
        raise HTTPException(404, "Reference audio not found") from exc

router = APIRouter()

SONG_NOT_FOUND_DETAIL: Final = "Song not found"


@router.get("/songs")
def api_list_songs(
    page: Pagination,
    album_id: str | None = Query(None),
    q: str | None = Query(None),
    sort: LibrarySort | None = Query(None),
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> PaginatedResponse[SongSummaryResponse]:
    query = parse_optional_search_query(q)
    uid = owner_filter(user)
    # Direct-by-ID (album_id set) must still surface an archived album's
    # songs — AlbumDetailView relies on this. Only the unscoped browse
    # case hides songs of archived albums, matching the library/mix/pool.
    exclude_archived_albums = album_id is None
    total = count_songs(
        session, album_id=album_id, user_id=uid, q=query,
        exclude_archived_albums=exclude_archived_albums,
    )
    songs = list_songs(
        session, album_id=album_id, user_id=uid, light=True,
        offset=page.offset, limit=page.limit, q=query, sort=sort,
        exclude_archived_albums=exclude_archived_albums,
    )
    generation_counts = count_generations_by_song(session, [s.id for s in songs])
    items = [
        SongSummaryResponse.from_orm(s, generation_count=generation_counts.get(s.id, 0))
        for s in songs
    ]
    return PaginatedResponse(
        items=items,
        total=total, offset=page.offset, limit=page.limit,
        has_more=page_has_more(offset=page.offset, fetched=len(items), total=total),
    )


@router.get("/songs/{song_id}")
def api_get_song(
    song_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> SongResponse:
    song = check_song_access(session, song_id, user)
    return SongResponse.from_orm(song)


@router.post(
    "/songs",
    responses={404: {"description": "Album or reference audio not found"}},
)
def api_create_song(
    req: SongCreateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> SongResponse:
    album = get_album(session, req.album_id)
    check_album_access(album, user)
    _require_owned_reference_audio(ctx.audio_dir, user.id, req.generation_params)
    slug = unique_song_slug(session, req.album_id, req.title)
    song = create_song(
        session, title=req.title, album_id=req.album_id,
        lyrics=req.lyrics, prompt=req.prompt, bpm=req.bpm,
        audio_duration=req.audio_duration, key_scale=req.key_scale,
        vocal_language=req.vocal_language,
        generation_params=gen_params_to_json(req.generation_params),
        slug=slug,
    )
    record_audit(session, user.id, AuditAction.CREATE, ResourceType.SONG, song.id)
    session.commit()
    return SongResponse.from_orm(song)


@router.put(
    "/songs/{song_id}",
    responses={404: {"description": "Song or reference audio not found"}},
)
def api_update_song(
    song_id: str, req: SongUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> SongResponse:
    check_song_access(session, song_id, user)
    if "generation_params" in req.model_fields_set:
        _require_owned_reference_audio(ctx.audio_dir, user.id, req.generation_params)
    kwargs: dict = {
        "lyrics": req.lyrics,
        "prompt": req.prompt,
        "bpm": req.bpm,
        "audio_duration": req.audio_duration,
        "key_scale": req.key_scale,
    }
    if "generation_params" in req.model_fields_set:
        kwargs["generation_params"] = gen_params_to_json(req.generation_params)
    try:
        version = update_song(session, song_id, **kwargs)
    except ValueError:
        raise HTTPException(404, SONG_NOT_FOUND_DETAIL)
    record_audit(session, user.id, AuditAction.UPDATE, ResourceType.SONG, song_id)
    session.commit()
    return SongResponse.from_orm(version.song)


@router.put(
    "/songs/{song_id}/title",
    responses={
        404: {"description": SONG_NOT_FOUND_DETAIL},
        422: {"description": "Song title is required"},
    },
)
def api_rename_song(
    song_id: str, req: TitleUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> SongResponse:
    song = check_song_access(session, song_id, user)
    title = req.title.strip()
    if not title:
        raise HTTPException(422, "Title is required")
    slug = unique_song_slug(
        session, song.album_id, title, exclude_song_id=song_id,
    )
    try:
        song = rename_song(
            session, song_id, title, slug=slug, force_new_version=True,
        )
    except ValueError:
        raise HTTPException(404, SONG_NOT_FOUND_DETAIL)
    record_audit(session, user.id, AuditAction.UPDATE, ResourceType.SONG, song_id)
    session.commit()
    return SongResponse.from_orm(song)


@router.put(
    "/songs/{song_id}/album",
    responses={404: {"description": "Song or album not found"}},
)
def api_move_song(
    song_id: str, req: SongMoveRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> SongResponse:
    song = check_song_access(session, song_id, user)
    target_album = get_album(session, req.album_id)
    check_album_access(target_album, user)
    slug = unique_song_slug(
        session, req.album_id, song.title, exclude_song_id=song_id,
    )
    try:
        song = move_song(session, song_id, req.album_id, slug=slug)
    except ValueError:
        raise HTTPException(404, "Song or album not found")
    record_audit(
        session, user.id, AuditAction.MOVE, ResourceType.SONG,
        song_id, f"album={req.album_id}",
    )
    session.commit()
    return SongResponse.from_orm(song)


@router.delete(
    "/songs/{song_id}",
    responses={404: {"description": SONG_NOT_FOUND_DETAIL}},
)
def api_delete_song(
    song_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    check_song_access(session, song_id, user)
    try:
        soft_delete_song(session, song_id)
    except ValueError:
        raise HTTPException(404, SONG_NOT_FOUND_DETAIL)
    record_audit(session, user.id, AuditAction.DELETE, ResourceType.SONG, song_id)
    session.commit()
    return StatusResponse()


@router.post(
    "/songs/{song_id}/restore",
    responses={
        404: {"description": SONG_NOT_FOUND_DETAIL},
        410: {"description": "Song restore window has expired"},
    },
)
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


@router.post(
    "/songs/{song_id}/listen",
    responses={422: {"description": "Song has no playable take"}},
)
def api_record_song_listen(
    song_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    song = check_song_access(session, song_id, user)
    if best_playable_generation(song) is None:
        raise HTTPException(422, "Song is not playable")
    record_song_listen(session, song)
    session.commit()
    return StatusResponse()


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


@router.post(
    "/songs/{song_id}/share",
    responses={404: {"description": SONG_NOT_FOUND_DETAIL}},
)
def api_share_song(
    song_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ShareResponse:
    check_song_access(session, song_id, user)
    base_url = resolve_public_base_url()
    try:
        song = enable_song_sharing(session, song_id)
    except ValueError:
        raise HTTPException(404, SONG_NOT_FOUND_DETAIL)
    record_audit(session, user.id, AuditAction.SHARE, ResourceType.SONG, song_id)
    session.commit()
    return ShareResponse(
        share_url=f"{base_url}/share/song/{song.share_slug}",
        share_slug=song.share_slug,
    )


@router.get(
    "/songs/{song_id}/cover",
    responses={404: {"description": "Song or cover not found"}},
)
async def api_get_song_cover(
    song_id: str,
    variant: str = Query(COVER_VARIANT_DETAIL),
    v: str | None = Query(None, alias=COVER_VERSION_QUERY),
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    song = check_song_access(session, song_id, user)
    if v is not None and v != song.cover_key:
        raise HTTPException(404, COVER_NOT_FOUND)
    try:
        path = resolve_song_cover_file(ctx.audio_dir, song.id, song.cover_key, variant)
    except CoverRejectedError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except FileNotFoundError:
        raise HTTPException(404, COVER_NOT_FOUND)
    return FileResponse(
        path,
        media_type=cover_media_type(variant, song.cover_key or ""),
        headers=COVER_RESPONSE_HEADERS,
    )


@router.post("/songs/{song_id}/cover")
async def api_upload_song_cover(
    song_id: str,
    file: UploadFile,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> SongResponse:
    song = check_song_access(session, song_id, user)
    payload = await file.read(COVER_MAX_BYTES + 1)
    try:
        cover_key = write_song_cover(ctx.audio_dir, song.id, payload)
    except CoverRejectedError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    song = set_song_cover_key(session, song.id, cover_key)
    record_audit(session, user.id, AuditAction.UPDATE, ResourceType.SONG, song.id)
    session.commit()
    return SongResponse.from_orm(song)


@router.delete("/songs/{song_id}/cover")
def api_delete_song_cover(
    song_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> SongResponse:
    song = check_song_access(session, song_id, user)
    song = set_song_cover_key(session, song.id, None)
    record_audit(session, user.id, AuditAction.UPDATE, ResourceType.SONG, song.id)
    session.commit()
    remove_song_cover_files(ctx.audio_dir, song.id)
    return SongResponse.from_orm(song)


@router.delete(
    "/songs/{song_id}/share",
    responses={404: {"description": SONG_NOT_FOUND_DETAIL}},
)
def api_unshare_song(
    song_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    check_song_access(session, song_id, user)
    try:
        disable_song_sharing(session, song_id)
    except ValueError:
        raise HTTPException(404, SONG_NOT_FOUND_DETAIL)
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


@router.delete(
    "/versions/{version_id}",
    responses={404: {"description": "Version not found"}},
)
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

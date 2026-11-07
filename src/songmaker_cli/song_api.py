"""Song and Version API endpoints."""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from webauth.ports import AuthenticatedUser

from songmaker_cli.api_helpers import (
    Pagination,
    check_album_access,
    check_own_playlist_access,
    check_song_access,
    check_song_access_including_deleted,
    cleanup_generation_files,
    gen_params_to_json,
    owner_filter,
    page_has_more,
    parse_optional_search_query,
    unique_song_slug,
)
from songmaker_cli.api_models import (
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
from songmaker_cli.api_models.songs import ShareKind, SongListenRequest, public_share_url
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.auth_dependencies import get_current_user
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
from songmaker_cli.db.models import Song
from songmaker_cli.db.queries.activity import record_song_played
from songmaker_cli.db.queries.albums import RestoreWindowExpiredError, get_album
from songmaker_cli.db.queries.auth import record_audit
from songmaker_cli.db.queries.playlists import best_playable_generation, playlist_holds_song
from songmaker_cli.db.queries.reference_recordings import (
    linked_reference_ids,
    lock_and_mark_reference_used,
)
from songmaker_cli.db.queries.sharing import has_playable_pick
from songmaker_cli.db.queries.songs import (
    EmptySongTitleError,
    UnstorableSongTitleError,
    count_generations_by_song,
    count_songs,
    create_song,
    disable_song_sharing,
    enable_song_sharing,
    list_songs,
    move_song,
    record_playlist_listen,
    rename_song,
    restore_song,
    set_song_cover_key,
    soft_delete_song,
    song_ids_with_pick,
    stored_song_title,
    update_song,
)
from songmaker_cli.db.queries.versions import VersionInUseError, delete_version
from songmaker_cli.reference_audio import commit_unused_stamps


def _attach_reference(session: Session, user_id: str, reference_id: str | None) -> None:
    """Lock the owner's row for the link being saved and mark it used; the caller's commit
    releases the lock.

    A missing or foreign id answers like any other missing resource.
    """
    if reference_id is None:
        return
    if lock_and_mark_reference_used(session, user_id, reference_id) is None:
        raise HTTPException(404)


router = APIRouter()


def _song_response(song: Song) -> SongResponse:
    # Every detail path loads song.generations, so the pick needs no query.
    return SongResponse.from_orm(song, has_pick=has_playable_pick(song.generations))

SONG_NOT_FOUND_DETAIL: Final = "Song not found"
VERSION_IN_USE_DETAIL: Final = (
    "This version has a take rendering; wait for it to finish or cancel it."
)


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
    picked_song_ids = song_ids_with_pick(session, [s.id for s in songs])
    items = [
        SongSummaryResponse.from_orm(
            s,
            generation_count=generation_counts.get(s.id, 0),
            has_pick=s.id in picked_song_ids,
        )
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
    return _song_response(song)


def _title_refusal_detail(error: UnstorableSongTitleError) -> str:
    return "Title is required" if isinstance(error, EmptySongTitleError) else "Title is too long"


@router.post(
    "/songs",
    responses={
        404: {"description": "Album or reference audio not found"},
        422: {"description": "Song title is required or too long"},
    },
)
def api_create_song(
    req: SongCreateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> SongResponse:
    album = get_album(session, req.album_id)
    check_album_access(album, user)
    try:
        title = stored_song_title(req.title)
    except UnstorableSongTitleError as exc:
        raise HTTPException(422, _title_refusal_detail(exc)) from exc
    slug = unique_song_slug(session, req.album_id, title)
    _attach_reference(session, user.id, req.reference_recording_id)
    song = create_song(
        session, title=title, album_id=req.album_id,
        lyrics=req.lyrics, prompt=req.prompt, bpm=req.bpm,
        audio_duration=req.audio_duration, key_scale=req.key_scale,
        vocal_language=req.vocal_language,
        generation_params=gen_params_to_json(req.generation_params),
        reference_recording_id=req.reference_recording_id,
        slug=slug, created_by=user.id,
    )
    record_audit(session, user.id, AuditAction.CREATE, ResourceType.SONG, song.id)
    session.commit()
    return _song_response(song)


@router.put(
    "/songs/{song_id}",
    responses={404: {"description": "Song or reference audio not found"}},
)
def api_update_song(
    song_id: str, req: SongUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> SongResponse:
    check_song_access(session, song_id, user)
    _attach_reference(session, user.id, req.reference_recording_id)
    kwargs: dict = {
        "lyrics": req.lyrics,
        "prompt": req.prompt,
        "bpm": req.bpm,
        "audio_duration": req.audio_duration,
        "key_scale": req.key_scale,
        "vocal_language": req.vocal_language,
    }
    if "generation_params" in req.model_fields_set:
        kwargs["generation_params"] = gen_params_to_json(req.generation_params)
    candidates: set[str] = set()
    if "reference_recording_id" in req.model_fields_set:
        kwargs["reference_recording_id"] = req.reference_recording_id
        candidates = linked_reference_ids(session, [song_id])
    try:
        version = update_song(
            session, song_id, force_new_version=req.new_version, edited_by=user.id, **kwargs,
        )
    except ValueError:
        raise HTTPException(404, SONG_NOT_FOUND_DETAIL)
    record_audit(session, user.id, AuditAction.UPDATE, ResourceType.SONG, song_id)
    session.commit()
    commit_unused_stamps(session, candidates)
    return _song_response(version.song)


@router.put(
    "/songs/{song_id}/title",
    responses={
        404: {"description": SONG_NOT_FOUND_DETAIL},
        422: {"description": "Song title is required or too long"},
    },
)
def api_rename_song(
    song_id: str, req: TitleUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> SongResponse:
    song = check_song_access(session, song_id, user)
    try:
        title = stored_song_title(req.title)
    except UnstorableSongTitleError as exc:
        raise HTTPException(422, _title_refusal_detail(exc)) from exc
    slug = unique_song_slug(
        session, song.album_id, title, exclude_song_id=song_id,
    )
    try:
        song = rename_song(
            session, song_id, title, slug=slug, force_new_version=True, edited_by=user.id,
        )
    except ValueError:
        raise HTTPException(404, SONG_NOT_FOUND_DETAIL)
    record_audit(session, user.id, AuditAction.UPDATE, ResourceType.SONG, song_id)
    session.commit()
    return _song_response(song)


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
    return _song_response(song)


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
    return _song_response(restored)


@router.post(
    "/songs/{song_id}/listen",
    responses={
        404: {"description": "Song not found, or playlist not found or not the caller's"},
        422: {"description": "Song has no playable take, or the playlist does not hold it"},
    },
)
def api_record_song_listen(
    song_id: str,
    req: SongListenRequest | None = None,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    song = check_song_access(session, song_id, user)
    if best_playable_generation(song) is None:
        raise HTTPException(422, "Song is not playable")
    playlist = None
    if req is not None and req.playlist_id is not None:
        playlist = check_own_playlist_access(session, req.playlist_id, user)
        if not playlist_holds_song(session, playlist, song):
            raise HTTPException(422, "Playlist does not hold this song")
    if playlist is not None:
        record_playlist_listen(session, playlist, song=song)
    record_song_played(
        session, user_id=user.id, song_id=song.id, in_playlist=playlist is not None,
    )
    session.commit()
    return StatusResponse()


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
    try:
        song = enable_song_sharing(session, song_id)
    except ValueError:
        raise HTTPException(404, SONG_NOT_FOUND_DETAIL)
    record_audit(session, user.id, AuditAction.SHARE, ResourceType.SONG, song_id)
    share_url = public_share_url(ShareKind.SONG, song.share_slug)
    session.commit()
    return ShareResponse(
        share_url=share_url,
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
    return _song_response(song)


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
    return _song_response(song)


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
    responses={
        404: {"description": "Version not found"},
        409: {"description": "A queued or running job renders this version"},
    },
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
    candidates = linked_reference_ids(session, [ver.song_id])
    try:
        paths = delete_version(
            session, version_id,
            delete_generations=delete_generations,
        )
    except VersionInUseError:
        raise HTTPException(409, VERSION_IN_USE_DETAIL)
    except ValueError:
        raise HTTPException(404, "Version not found")
    record_audit(session, user.id, AuditAction.DELETE, ResourceType.VERSION, version_id)
    session.commit()
    commit_unused_stamps(session, candidates)
    cleanup_generation_files(ctx.audio_dir, paths)
    return StatusResponse()

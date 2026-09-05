"""Playlist CRUD, entry management, and sharing endpoints."""

from __future__ import annotations

import logging
from typing import Final

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import (
    check_generation_access,
    check_song_access,
    resolve_public_base_url,
    unique_playlist_slug,
)
from songmaker_cli.api_models import (
    AddAlbumToPlaylistRequest,
    AddAlbumToPlaylistResponse,
    AddGenerationToPlaylistRequest,
    AddSongToPlaylistRequest,
    PlaylistAlbumSkipResponse,
    PlaylistCreateRequest,
    PlaylistDetailResponse,
    PlaylistEntryResponse,
    PlaylistResponse,
    PlaylistUpdateRequest,
    ReorderPlaylistEntryRequest,
    ShareResponse,
    StatusResponse,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.auth import ROLE_ADMIN
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
    remove_playlist_cover_files,
    resolve_playlist_cover_file,
    write_playlist_cover,
)
from songmaker_cli.db.models import Generation, Playlist
from songmaker_cli.db.queries import (
    add_album_to_playlist,
    add_generation_to_playlist,
    add_song_to_playlist,
    best_playable_generation,
    create_playlist,
    delete_playlist,
    disable_playlist_sharing,
    enable_playlist_sharing,
    get_album,
    get_playlist,
    list_playlists,
    record_audit,
    remove_from_playlist,
    reorder_playlist_entry,
    set_playlist_cover_key,
    update_playlist,
)
from songmaker_cli.middleware import AuthenticatedUser, get_current_user
from songmaker_cli.queue_streams import resolve_audio_path

log = logging.getLogger(__name__)

router = APIRouter()

PLAYLIST_NOT_FOUND_DETAIL: Final = "Playlist not found"
ALBUM_NOT_FOUND_DETAIL: Final = "Album not found"


def _check_playlist_access(
    session: Session, playlist_id: str, user: AuthenticatedUser,
) -> Playlist:
    playlist = get_playlist(session, playlist_id)
    if not playlist:
        raise HTTPException(404, PLAYLIST_NOT_FOUND_DETAIL)
    if user.role != ROLE_ADMIN and playlist.created_by != user.id:
        raise HTTPException(404, PLAYLIST_NOT_FOUND_DETAIL)
    return playlist


@router.get("/playlists")
def api_list_playlists(
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[PlaylistResponse]:
    playlists = list_playlists(session, user.id)
    return [PlaylistResponse.from_orm(p) for p in playlists]


@router.post("/playlists")
def api_create_playlist(
    req: PlaylistCreateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> PlaylistResponse:
    slug = unique_playlist_slug(session, req.title)
    playlist = create_playlist(session, req.title, user.id, slug=slug)
    record_audit(session, user.id, AuditAction.CREATE, ResourceType.PLAYLIST, playlist.id)
    session.commit()
    return PlaylistResponse.from_orm(playlist)


@router.get(
    "/playlists/{playlist_id}",
    responses={404: {"description": PLAYLIST_NOT_FOUND_DETAIL}},
)
def api_get_playlist(
    playlist_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> PlaylistDetailResponse:
    playlist = _check_playlist_access(session, playlist_id, user)
    return PlaylistDetailResponse.from_orm(playlist)


@router.put(
    "/playlists/{playlist_id}",
    responses={404: {"description": PLAYLIST_NOT_FOUND_DETAIL}},
)
def api_update_playlist(
    playlist_id: str,
    req: PlaylistUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> PlaylistResponse:
    _check_playlist_access(session, playlist_id, user)
    slug = unique_playlist_slug(session, req.title, exclude_playlist_id=playlist_id)
    try:
        playlist = update_playlist(session, playlist_id, req.title, slug=slug)
    except ValueError:
        raise HTTPException(404, PLAYLIST_NOT_FOUND_DETAIL)
    session.commit()
    return PlaylistResponse.from_orm(playlist)


@router.delete(
    "/playlists/{playlist_id}",
    responses={404: {"description": PLAYLIST_NOT_FOUND_DETAIL}},
)
def api_delete_playlist(
    playlist_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> StatusResponse:
    _check_playlist_access(session, playlist_id, user)
    try:
        delete_playlist(session, playlist_id)
    except ValueError:
        raise HTTPException(404, PLAYLIST_NOT_FOUND_DETAIL)
    record_audit(session, user.id, AuditAction.DELETE, ResourceType.PLAYLIST, playlist_id)
    session.commit()
    remove_playlist_cover_files(ctx.audio_dir, playlist_id)
    return StatusResponse()


# ── Cover ──────────────────────────────────────────────────────────────


@router.get(
    "/playlists/{playlist_id}/cover",
    responses={404: {"description": "Playlist or cover not found"}},
)
def api_get_playlist_cover(
    playlist_id: str,
    variant: str = Query(COVER_VARIANT_DETAIL),
    v: str | None = Query(None, alias=COVER_VERSION_QUERY),
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    playlist = _check_playlist_access(session, playlist_id, user)
    if v is not None and v != playlist.cover_key:
        raise HTTPException(404, COVER_NOT_FOUND)
    try:
        path = resolve_playlist_cover_file(
            ctx.audio_dir, playlist.id, playlist.cover_key, variant,
        )
    except CoverRejectedError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except FileNotFoundError:
        raise HTTPException(404, COVER_NOT_FOUND)
    return FileResponse(
        path,
        media_type=cover_media_type(variant, playlist.cover_key or ""),
        headers=COVER_RESPONSE_HEADERS,
    )


@router.put(
    "/playlists/{playlist_id}/cover",
    responses={404: {"description": PLAYLIST_NOT_FOUND_DETAIL}},
)
async def api_upload_playlist_cover(
    playlist_id: str,
    file: UploadFile,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> PlaylistResponse:
    playlist = _check_playlist_access(session, playlist_id, user)
    payload = await file.read(COVER_MAX_BYTES + 1)
    try:
        cover_key = write_playlist_cover(ctx.audio_dir, playlist.id, payload)
    except CoverRejectedError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    playlist = set_playlist_cover_key(session, playlist.id, cover_key)
    record_audit(session, user.id, AuditAction.UPDATE, ResourceType.PLAYLIST, playlist.id)
    session.commit()
    return PlaylistResponse.from_orm(playlist)


@router.delete(
    "/playlists/{playlist_id}/cover",
    responses={404: {"description": PLAYLIST_NOT_FOUND_DETAIL}},
)
def api_delete_playlist_cover(
    playlist_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> PlaylistResponse:
    playlist = _check_playlist_access(session, playlist_id, user)
    playlist = set_playlist_cover_key(session, playlist.id, None)
    record_audit(session, user.id, AuditAction.UPDATE, ResourceType.PLAYLIST, playlist.id)
    session.commit()
    remove_playlist_cover_files(ctx.audio_dir, playlist.id)
    return PlaylistResponse.from_orm(playlist)


# ── Entries ────────────────────────────────────────────────────────────


@router.post(
    "/playlists/{playlist_id}/entries/generation",
    responses={404: {"description": "Playlist or generation not found"}},
)
def api_add_generation_to_playlist(
    playlist_id: str,
    req: AddGenerationToPlaylistRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> PlaylistEntryResponse:
    _check_playlist_access(session, playlist_id, user)
    check_generation_access(session, req.generation_id, user)
    try:
        entry = add_generation_to_playlist(session, playlist_id, req.generation_id)
    except ValueError:
        raise HTTPException(404, "Generation not found")
    session.commit()
    entry = session.merge(entry)
    playlist = get_playlist(session, playlist_id)
    entry_obj = next((e for e in playlist.entries if e.id == entry.id), None)
    return PlaylistEntryResponse.from_orm(entry_obj)


@router.post(
    "/playlists/{playlist_id}/entries/song",
    responses={
        400: {"description": "Song has no playable take"},
        404: {"description": "Playlist or song not found"},
    },
)
def api_add_song_to_playlist(
    playlist_id: str,
    req: AddSongToPlaylistRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> StatusResponse:
    _check_playlist_access(session, playlist_id, user)
    song = check_song_access(session, req.song_id, user)
    playable = best_playable_generation(song)
    if playable is None:
        raise HTTPException(400, "Song has no playable take")
    try:
        resolve_audio_path(ctx.audio_dir, playable.mp3_path)
    except (HTTPException, OSError):
        raise HTTPException(400, "Song has no playable take")
    try:
        add_song_to_playlist(session, playlist_id, req.song_id)
    except ValueError:
        raise HTTPException(404, "Song not found")
    session.commit()
    return StatusResponse()


@router.post(
    "/playlists/{playlist_id}/entries/album",
    responses={404: {"description": "Playlist or album not found"}},
)
def api_add_album_to_playlist(
    playlist_id: str,
    req: AddAlbumToPlaylistRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> AddAlbumToPlaylistResponse:
    _check_playlist_access(session, playlist_id, user)
    album = get_album(session, req.album_id)
    if not album:
        raise HTTPException(404, ALBUM_NOT_FOUND_DETAIL)
    if user.role != ROLE_ADMIN and album.created_by != user.id:
        raise HTTPException(404, ALBUM_NOT_FOUND_DETAIL)

    def _readable(generation: Generation) -> bool:
        try:
            resolve_audio_path(ctx.audio_dir, generation.mp3_path)
        except (HTTPException, OSError):
            return False
        return True

    try:
        result = add_album_to_playlist(
            session, playlist_id, req.album_id, is_readable=_readable
        )
    except ValueError:
        raise HTTPException(404, ALBUM_NOT_FOUND_DETAIL)
    session.commit()
    return AddAlbumToPlaylistResponse(
        added_count=len(result.entries),
        skipped=[
            PlaylistAlbumSkipResponse(
                song_id=item.song_id, title=item.title, reason=item.reason
            )
            for item in result.skipped
        ],
    )


@router.delete(
    "/playlists/{playlist_id}/entries/{entry_id}",
    responses={404: {"description": "Playlist or entry not found"}},
)
def api_remove_from_playlist(
    playlist_id: str,
    entry_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    _check_playlist_access(session, playlist_id, user)
    try:
        remove_from_playlist(session, playlist_id, entry_id)
    except ValueError:
        raise HTTPException(404, "Playlist entry not found")
    session.commit()
    return StatusResponse()


@router.patch(
    "/playlists/{playlist_id}/entries/{entry_id}/position",
    responses={404: {"description": "Playlist or entry not found"}},
)
def api_reorder_playlist_entry(
    playlist_id: str,
    entry_id: str,
    req: ReorderPlaylistEntryRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    _check_playlist_access(session, playlist_id, user)
    try:
        reorder_playlist_entry(session, playlist_id, entry_id, req.new_position)
    except ValueError:
        raise HTTPException(404, "Playlist entry not found")
    session.commit()
    return StatusResponse()


# ── Sharing ────────────────────────────────────────────────────────────


@router.post(
    "/playlists/{playlist_id}/share",
    responses={404: {"description": PLAYLIST_NOT_FOUND_DETAIL}},
)
def api_share_playlist(
    playlist_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ShareResponse:
    _check_playlist_access(session, playlist_id, user)
    base_url = resolve_public_base_url()
    try:
        playlist = enable_playlist_sharing(session, playlist_id)
    except ValueError:
        raise HTTPException(404, PLAYLIST_NOT_FOUND_DETAIL)
    record_audit(session, user.id, AuditAction.SHARE, ResourceType.PLAYLIST, playlist_id)
    session.commit()
    return ShareResponse(
        share_url=f"{base_url}/share/playlist/{playlist.share_slug}",
        share_slug=playlist.share_slug,
    )


@router.delete(
    "/playlists/{playlist_id}/share",
    responses={404: {"description": PLAYLIST_NOT_FOUND_DETAIL}},
)
def api_unshare_playlist(
    playlist_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    _check_playlist_access(session, playlist_id, user)
    try:
        disable_playlist_sharing(session, playlist_id)
    except ValueError:
        raise HTTPException(404, PLAYLIST_NOT_FOUND_DETAIL)
    record_audit(session, user.id, AuditAction.UNSHARE, ResourceType.PLAYLIST, playlist_id)
    session.commit()
    return StatusResponse()

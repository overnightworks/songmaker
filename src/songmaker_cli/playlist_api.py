"""Playlist CRUD, entry management, and sharing endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import (
    check_generation_access,
    check_song_access,
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
from songmaker_cli.constants import AuditAction, ResourceType
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
    update_playlist,
)
from songmaker_cli.middleware import AuthenticatedUser, get_current_user
from songmaker_cli.queue_streams import resolve_audio_path

log = logging.getLogger(__name__)

router = APIRouter()


def _check_playlist_access(
    session: Session, playlist_id: str, user: AuthenticatedUser,
) -> Playlist:
    playlist = get_playlist(session, playlist_id)
    if not playlist:
        raise HTTPException(404, "Playlist not found")
    if user.role != ROLE_ADMIN and playlist.created_by != user.id:
        raise HTTPException(404, "Playlist not found")
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


@router.get("/playlists/{playlist_id}")
def api_get_playlist(
    playlist_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> PlaylistDetailResponse:
    playlist = _check_playlist_access(session, playlist_id, user)
    return PlaylistDetailResponse.from_orm(playlist)


@router.put("/playlists/{playlist_id}")
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
        raise HTTPException(404, "Playlist not found")
    session.commit()
    return PlaylistResponse.from_orm(playlist)


@router.delete("/playlists/{playlist_id}")
def api_delete_playlist(
    playlist_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    _check_playlist_access(session, playlist_id, user)
    try:
        delete_playlist(session, playlist_id)
    except ValueError:
        raise HTTPException(404, "Playlist not found")
    record_audit(session, user.id, AuditAction.DELETE, ResourceType.PLAYLIST, playlist_id)
    session.commit()
    return StatusResponse()


# ── Entries ────────────────────────────────────────────────────────────


@router.post("/playlists/{playlist_id}/entries/generation")
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


@router.post("/playlists/{playlist_id}/entries/song")
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
    except HTTPException:
        raise HTTPException(400, "Song has no playable take")
    try:
        add_song_to_playlist(session, playlist_id, req.song_id)
    except ValueError:
        raise HTTPException(404, "Song not found")
    session.commit()
    return StatusResponse()


@router.post("/playlists/{playlist_id}/entries/album")
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
        raise HTTPException(404, "Album not found")
    if user.role != ROLE_ADMIN and album.created_by != user.id:
        raise HTTPException(404, "Album not found")

    def _readable(generation: Generation) -> bool:
        try:
            resolve_audio_path(ctx.audio_dir, generation.mp3_path)
        except HTTPException:
            return False
        return True

    try:
        result = add_album_to_playlist(
            session, playlist_id, req.album_id, is_readable=_readable
        )
    except ValueError:
        raise HTTPException(404, "Album not found")
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


@router.delete("/playlists/{playlist_id}/entries/{entry_id}")
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


@router.patch("/playlists/{playlist_id}/entries/{entry_id}/position")
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


@router.post("/playlists/{playlist_id}/share")
def api_share_playlist(
    playlist_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ShareResponse:
    _check_playlist_access(session, playlist_id, user)
    try:
        playlist = enable_playlist_sharing(session, playlist_id)
    except ValueError:
        raise HTTPException(404, "Playlist not found")
    record_audit(session, user.id, AuditAction.SHARE, ResourceType.PLAYLIST, playlist_id)
    session.commit()
    base_url = str(request.base_url).rstrip("/")
    return ShareResponse(
        share_url=f"{base_url}/share/playlist/{playlist.share_slug}",
        share_slug=playlist.share_slug,
    )


@router.delete("/playlists/{playlist_id}/share")
def api_unshare_playlist(
    playlist_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    _check_playlist_access(session, playlist_id, user)
    try:
        disable_playlist_sharing(session, playlist_id)
    except ValueError:
        raise HTTPException(404, "Playlist not found")
    record_audit(session, user.id, AuditAction.UNSHARE, ResourceType.PLAYLIST, playlist_id)
    session.commit()
    return StatusResponse()

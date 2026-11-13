"""Playlist CRUD, entry management, and sharing endpoints."""

from __future__ import annotations

import logging
from typing import Final

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from webauth.ports import AuthenticatedUser

from songmaker_cli.agent.mcp import Exclusion, ToolEffect, agent_tool, exclude_route
from songmaker_cli.api_helpers import (
    PLAYLIST_NOT_FOUND_DETAIL,
    can_access_album,
    check_album_access,
    check_generation_access,
    check_playlist_access,
    check_song_access,
    cover_file_response,
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
from songmaker_cli.api_models.playlists import AlbumReach
from songmaker_cli.api_models.songs import ShareKind, public_share_url
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.audio_paths import AudioPathRejectedError, resolve_audio_path
from songmaker_cli.auth_dependencies import get_current_user
from songmaker_cli.constants import (
    COVER_MAX_BYTES,
    COVER_VARIANT_DETAIL,
    COVER_VERSION_QUERY,
    AuditAction,
    ResourceType,
)
from songmaker_cli.covers import (
    CoverRejectedError,
    remove_playlist_cover_files,
    resolve_playlist_cover_file,
    write_playlist_cover,
)
from songmaker_cli.db.models import Generation
from songmaker_cli.db.queries.albums import get_album
from songmaker_cli.db.queries.auth import record_audit
from songmaker_cli.db.queries.generations import ArchivedTakeError
from songmaker_cli.db.queries.playlists import (
    add_album_to_playlist,
    add_generation_to_playlist,
    add_song_to_playlist,
    create_playlist,
    delete_playlist,
    disable_playlist_sharing,
    enable_playlist_sharing,
    get_playlist,
    list_playlists,
    remove_from_playlist,
    reorder_playlist_entry,
    set_playlist_cover_key,
    update_playlist,
)
from songmaker_cli.db.queries.sharing import presented_take
from songmaker_cli.refusals import Refusal
from songmaker_cli.words import SOURCE_LANGUAGE, text

log = logging.getLogger(__name__)

router = APIRouter()

ALBUM_NOT_FOUND_DETAIL: Final = "Album not found"


def _albums_reached_by(user: AuthenticatedUser) -> AlbumReach:
    return lambda album: can_access_album(album, user)


_LIST_PLAYLISTS_DESCRIPTION = "List the person's own playlists."


@router.get(
    "/playlists",
    description=_LIST_PLAYLISTS_DESCRIPTION,
    openapi_extra=agent_tool(name="list_playlists", effect=ToolEffect.READ_ONLY),
)
def api_list_playlists(
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[PlaylistResponse]:
    playlists = list_playlists(session, user.id)
    return [PlaylistResponse.from_orm(p, reaches=_albums_reached_by(user)) for p in playlists]


_CREATE_PLAYLIST_DESCRIPTION = "Create a playlist owned by the person."


@router.post(
    "/playlists",
    description=_CREATE_PLAYLIST_DESCRIPTION,
    openapi_extra=agent_tool(name="create_playlist", effect=ToolEffect.SIDE_EFFECTING),
)
def api_create_playlist(
    req: PlaylistCreateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> PlaylistResponse:
    slug = unique_playlist_slug(session, req.title)
    playlist = create_playlist(session, req.title, user.id, slug=slug)
    record_audit(session, user.id, AuditAction.CREATE, ResourceType.PLAYLIST, playlist.id)
    session.commit()
    return PlaylistResponse.from_orm(playlist, reaches=_albums_reached_by(user))


_GET_PLAYLIST_DESCRIPTION = (
    "Read one of the person's own playlists with its entries and share link if it is shared."
)


@router.get(
    "/playlists/{playlist_id}",
    description=_GET_PLAYLIST_DESCRIPTION,
    openapi_extra=agent_tool(name="get_playlist", effect=ToolEffect.READ_ONLY),
    responses={404: {"description": PLAYLIST_NOT_FOUND_DETAIL}},
)
def api_get_playlist(
    playlist_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> PlaylistDetailResponse:
    playlist = check_playlist_access(session, playlist_id, user)
    return PlaylistDetailResponse.from_orm(playlist, reaches=_albums_reached_by(user))


@router.put(
    "/playlists/{playlist_id}",
    description="Rename one of the person's own playlists.",
    responses={404: {"description": PLAYLIST_NOT_FOUND_DETAIL}},
    openapi_extra=agent_tool(name="update_playlist", effect=ToolEffect.SIDE_EFFECTING),
)
def api_update_playlist(
    playlist_id: str,
    req: PlaylistUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> PlaylistResponse:
    check_playlist_access(session, playlist_id, user)
    slug = unique_playlist_slug(session, req.title, exclude_playlist_id=playlist_id)
    try:
        playlist = update_playlist(session, playlist_id, req.title, slug=slug)
    except ValueError:
        raise HTTPException(404, PLAYLIST_NOT_FOUND_DETAIL)
    session.commit()
    return PlaylistResponse.from_orm(playlist, reaches=_albums_reached_by(user))


@router.delete(
    "/playlists/{playlist_id}",
    responses={404: {"description": PLAYLIST_NOT_FOUND_DETAIL}},
    openapi_extra=exclude_route(Exclusion.FINAL_DELETION),
)
def api_delete_playlist(
    playlist_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> StatusResponse:
    check_playlist_access(session, playlist_id, user)
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
    openapi_extra=exclude_route(Exclusion.BROWSER_ONLY),
)
def api_get_playlist_cover(
    playlist_id: str,
    variant: str = Query(COVER_VARIANT_DETAIL),
    v: str | None = Query(None, alias=COVER_VERSION_QUERY),
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    playlist = check_playlist_access(session, playlist_id, user)
    return cover_file_response(
        resolve_playlist_cover_file, ctx.audio_dir, playlist, variant, v,
    )


@router.put(
    "/playlists/{playlist_id}/cover",
    responses={404: {"description": PLAYLIST_NOT_FOUND_DETAIL}},
    openapi_extra=exclude_route(Exclusion.BROWSER_ONLY),
)
async def api_upload_playlist_cover(
    playlist_id: str,
    file: UploadFile,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> PlaylistResponse:
    playlist = check_playlist_access(session, playlist_id, user)
    payload = await file.read(COVER_MAX_BYTES + 1)
    try:
        cover_key = write_playlist_cover(ctx.audio_dir, playlist.id, payload)
    except CoverRejectedError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    playlist = set_playlist_cover_key(session, playlist.id, cover_key)
    record_audit(session, user.id, AuditAction.UPDATE, ResourceType.PLAYLIST, playlist.id)
    session.commit()
    return PlaylistResponse.from_orm(playlist, reaches=_albums_reached_by(user))


@router.delete(
    "/playlists/{playlist_id}/cover",
    responses={404: {"description": PLAYLIST_NOT_FOUND_DETAIL}},
    openapi_extra=exclude_route(Exclusion.FINAL_DELETION),
)
def api_delete_playlist_cover(
    playlist_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> PlaylistResponse:
    playlist = check_playlist_access(session, playlist_id, user)
    playlist = set_playlist_cover_key(session, playlist.id, None)
    record_audit(session, user.id, AuditAction.UPDATE, ResourceType.PLAYLIST, playlist.id)
    session.commit()
    remove_playlist_cover_files(ctx.audio_dir, playlist.id)
    return PlaylistResponse.from_orm(playlist, reaches=_albums_reached_by(user))


# ── Entries ────────────────────────────────────────────────────────────


_ADD_TAKE_TO_PLAYLIST_DESCRIPTION = (
    "Add one of the person's own takes to one of their playlists. A shared playlist shows "
    "it."
)


@router.post(
    "/playlists/{playlist_id}/entries/generation",
    description=_ADD_TAKE_TO_PLAYLIST_DESCRIPTION,
    openapi_extra=agent_tool(name="add_take_to_playlist", effect=ToolEffect.SIDE_EFFECTING),
    responses={
        404: {"description": "Playlist or generation not found"},
        409: {"description": text(SOURCE_LANGUAGE, "takeRefusal.archived")},
    },
)
def api_add_generation_to_playlist(
    playlist_id: str,
    req: AddGenerationToPlaylistRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> PlaylistEntryResponse:
    check_playlist_access(session, playlist_id, user)
    check_generation_access(session, req.generation_id, user)
    try:
        entry = add_generation_to_playlist(session, playlist_id, req.generation_id)
    except ValueError:
        raise HTTPException(404, "Generation not found")
    except ArchivedTakeError:
        raise Refusal(409, "takeRefusal.archived")
    session.commit()
    entry = session.merge(entry)
    playlist = get_playlist(session, playlist_id)
    entry_obj = next((e for e in playlist.entries if e.id == entry.id), None)
    return PlaylistEntryResponse.from_orm(entry_obj)


_ADD_SONG_TO_PLAYLIST_DESCRIPTION = (
    "Add the playable take of one of the person's own songs to one of their playlists. A "
    "shared playlist shows it."
)


@router.post(
    "/playlists/{playlist_id}/entries/song",
    description=_ADD_SONG_TO_PLAYLIST_DESCRIPTION,
    openapi_extra=agent_tool(name="add_song_to_playlist", effect=ToolEffect.SIDE_EFFECTING),
    responses={
        400: {"description": "Song has no playable take"},
        404: {"description": "Playlist or song not found"},
        409: {"description": text(SOURCE_LANGUAGE, "takeRefusal.archived")},
    },
)
def api_add_song_to_playlist(
    playlist_id: str,
    req: AddSongToPlaylistRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> StatusResponse:
    check_playlist_access(session, playlist_id, user)
    song = check_song_access(session, req.song_id, user)
    playable = presented_take(song.generations)
    if playable is None:
        raise HTTPException(400, "Song has no playable take")
    try:
        resolve_audio_path(ctx.audio_dir, playable.mp3_path)
    except (AudioPathRejectedError, OSError):
        raise HTTPException(400, "Song has no playable take")
    try:
        add_song_to_playlist(session, playlist_id, req.song_id)
    except ValueError:
        raise HTTPException(404, "Song not found")
    except ArchivedTakeError:
        raise Refusal(409, "takeRefusal.archived")
    session.commit()
    return StatusResponse()


_ADD_ALBUM_TO_PLAYLIST_DESCRIPTION = (
    "Add the playable takes of one of the person's own albums to one of their playlists. A "
    "shared playlist shows them."
)


@router.post(
    "/playlists/{playlist_id}/entries/album",
    description=_ADD_ALBUM_TO_PLAYLIST_DESCRIPTION,
    openapi_extra=agent_tool(name="add_album_to_playlist", effect=ToolEffect.SIDE_EFFECTING),
    responses={404: {"description": "Playlist or album not found"}},
)
def api_add_album_to_playlist(
    playlist_id: str,
    req: AddAlbumToPlaylistRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> AddAlbumToPlaylistResponse:
    check_playlist_access(session, playlist_id, user)
    check_album_access(get_album(session, req.album_id), user)

    def _readable(generation: Generation) -> bool:
        try:
            resolve_audio_path(ctx.audio_dir, generation.mp3_path)
        except (AudioPathRejectedError, OSError):
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
    description=(
        "Take one entry out of the person's own playlist; the song stays and can be added again."
    ),
    responses={404: {"description": "Playlist or entry not found"}},
    openapi_extra=agent_tool(name="remove_playlist_entry", effect=ToolEffect.SIDE_EFFECTING),
)
def api_remove_from_playlist(
    playlist_id: str,
    entry_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    check_playlist_access(session, playlist_id, user)
    try:
        remove_from_playlist(session, playlist_id, entry_id)
    except ValueError:
        raise HTTPException(404, "Playlist entry not found")
    session.commit()
    return StatusResponse()


@router.patch(
    "/playlists/{playlist_id}/entries/{entry_id}/position",
    description="Move one entry of the person's own playlist to another position in its order.",
    responses={404: {"description": "Playlist or entry not found"}},
    openapi_extra=agent_tool(name="move_playlist_entry", effect=ToolEffect.SIDE_EFFECTING),
)
def api_reorder_playlist_entry(
    playlist_id: str,
    entry_id: str,
    req: ReorderPlaylistEntryRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    check_playlist_access(session, playlist_id, user)
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
    openapi_extra=exclude_route(Exclusion.SHARING),
)
def api_share_playlist(
    playlist_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ShareResponse:
    check_playlist_access(session, playlist_id, user)
    try:
        playlist = enable_playlist_sharing(session, playlist_id)
    except ValueError:
        raise HTTPException(404, PLAYLIST_NOT_FOUND_DETAIL)
    record_audit(session, user.id, AuditAction.SHARE, ResourceType.PLAYLIST, playlist_id)
    share_url = public_share_url(ShareKind.PLAYLIST, playlist.share_slug)
    session.commit()
    return ShareResponse(
        share_url=share_url,
        share_slug=playlist.share_slug,
    )


_UNSHARE_PLAYLIST_DESCRIPTION = (
    "End the share of one of the person's own playlists. "
    "Its public link stops working for good, and sharing the playlist again makes a new link."
)


@router.delete(
    "/playlists/{playlist_id}/share",
    description=_UNSHARE_PLAYLIST_DESCRIPTION,
    openapi_extra=agent_tool(name="unshare_playlist", effect=ToolEffect.SIDE_EFFECTING),
    responses={404: {"description": PLAYLIST_NOT_FOUND_DETAIL}},
)
def api_unshare_playlist(
    playlist_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    check_playlist_access(session, playlist_id, user)
    try:
        disable_playlist_sharing(session, playlist_id)
    except ValueError:
        raise HTTPException(404, PLAYLIST_NOT_FOUND_DETAIL)
    record_audit(session, user.id, AuditAction.UNSHARE, ResourceType.PLAYLIST, playlist_id)
    session.commit()
    return StatusResponse()

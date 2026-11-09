"""Public share file endpoints: covers, audio and queue-stream audio."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Final

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from songmaker_cli.agent.mcp import Exclusion, exclude_route
from songmaker_cli.api_helpers import (
    audio_file_response,
    audio_response,
    cover_file_response,
    raise_audio_file_http_error,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.audio_paths import (
    AudioFileNotFoundError,
    canonical_audio_path,
    require_existing_audio_path,
)
from songmaker_cli.constants import (
    COVER_NOT_FOUND,
    COVER_VARIANT_DETAIL,
    COVER_VERSION_QUERY,
    HTTP_NOT_FOUND,
)
from songmaker_cli.covers import (
    resolve_cover_file,
    resolve_playlist_cover_file,
    resolve_song_cover_file,
)
from songmaker_cli.db.models import Album, Playlist, Song
from songmaker_cli.db.queries.albums import get_album_by_slug
from songmaker_cli.db.queries.generations import get_presented_generation
from songmaker_cli.db.queries.playlists import get_playlist_by_slug
from songmaker_cli.db.queries.sharing import (
    is_playable_take,
    presented_playlist_entries,
    presented_take,
    shared_album_take_stored_path,
    shared_playlist_take_stored_path,
    shared_song_take_stored_path,
)
from songmaker_cli.db.queries.songs import get_song_by_slug
from songmaker_cli.queue_streams import (
    QUEUE_STREAM_NOT_FOUND_DETAIL,
    QueueStreamManifest,
    load_queue_stream_manifest,
    queue_stream_audio_path,
)
from songmaker_cli.shared_access import (
    NOT_FOUND_DETAIL,
    check_shared_rate_limit,
    entry_album,
    generation_id_of_shared_audio_name,
)

router = APIRouter()

# A queue-stream snapshot expires within hours and its share can be revoked, so
# no cache may keep it past the request.
QUEUE_STREAM_AUDIO_CACHE_CONTROL: Final = "no-store"


def _presented_audio_response(
    request: Request,
    db: Session,
    ctx: AppContext,
    slug: str,
    filename: str,
    stored_path_of_presented_take: Callable[[Session, str, str], str | None],
) -> FileResponse:
    """Serve the take a public share presents under an audio name."""
    check_shared_rate_limit(request)
    generation_id = generation_id_of_shared_audio_name(filename)
    stored_filename = (
        stored_path_of_presented_take(db, slug, generation_id) if generation_id else None
    )
    if stored_filename is None:
        raise HTTPException(404, HTTP_NOT_FOUND)
    return _shared_audio_file_response(ctx, stored_filename)


def _shared_audio_file_response(ctx: AppContext, stored_filename: str) -> FileResponse:
    audio_path = canonical_audio_path(ctx.audio_dir, stored_filename)
    try:
        audio_path = require_existing_audio_path(audio_path)
    except AudioFileNotFoundError as exc:
        raise_audio_file_http_error(exc, public=True)
    return audio_file_response(audio_path)


def _shared_cover_response(
    request: Request,
    resolve_entity: Callable[[], Album | Song | Playlist | None],
    audio_dir: Path,
    variant: str,
    version: str | None,
    resolve_file: Callable[[Path, str, str | None, str], Path] = resolve_cover_file,
) -> FileResponse:
    check_shared_rate_limit(request)
    entity = resolve_entity()
    if entity is None:
        raise HTTPException(404, NOT_FOUND_DETAIL)
    return cover_file_response(resolve_file, audio_dir, entity, variant, version)


def _validate_shared_queue_manifest(manifest: QueueStreamManifest, db: Session) -> None:
    scope = manifest.scope
    slug = manifest.scope_id
    tracks = manifest.tracks
    if scope == "shared-playlist":
        playlist = get_playlist_by_slug(db, slug)
        if not playlist:
            raise HTTPException(404, NOT_FOUND_DETAIL)
        valid_tracks = {
            (entry.id, entry.generation.id)
            for entry in presented_playlist_entries(playlist)
            if is_playable_take(entry.generation)
        }
        if any((track.entry_id, track.generation_id) not in valid_tracks for track in tracks):
            raise HTTPException(404, QUEUE_STREAM_NOT_FOUND_DETAIL)
        return

    if scope == "shared-album":
        album = get_album_by_slug(db, slug)
        if not album:
            raise HTTPException(404, NOT_FOUND_DETAIL)
        valid_tracks = {
            (song.id, gen.id)
            for song in album.songs
            if (gen := presented_take(song.generations)) is not None
        }
        if any((track.song_id, track.generation_id) not in valid_tracks for track in tracks):
            raise HTTPException(404, QUEUE_STREAM_NOT_FOUND_DETAIL)
        return

    raise HTTPException(404, QUEUE_STREAM_NOT_FOUND_DETAIL)


@router.get(
    "/shared/{slug}/cover",
    responses={404: {"description": "Shared album or cover not found"}},
    openapi_extra=exclude_route(Exclusion.PUBLIC_VIEW),
)
async def get_shared_album_cover(
    slug: str,
    request: Request,
    variant: str = Query(COVER_VARIANT_DETAIL),
    v: str | None = Query(None, alias=COVER_VERSION_QUERY),
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    return _shared_cover_response(
        request, lambda: get_album_by_slug(db, slug), ctx.audio_dir, variant, v,
    )


@router.get(
    "/shared/{slug}/audio/{filename:path}",
    responses={404: {"description": "Shared audio file not found"}},
    openapi_extra=exclude_route(Exclusion.PUBLIC_VIEW),
)
def get_shared_audio(
    slug: str,
    filename: str,
    request: Request,
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    return _presented_audio_response(
        request, db, ctx, slug, filename, shared_album_take_stored_path,
    )


@router.get(
    "/shared/song/{slug}/album-cover",
    responses={404: {"description": "Shared song, album, or cover not found"}},
    openapi_extra=exclude_route(Exclusion.PUBLIC_VIEW),
)
async def get_shared_song_album_cover(
    slug: str,
    request: Request,
    variant: str = Query(COVER_VARIANT_DETAIL),
    v: str | None = Query(None, alias=COVER_VERSION_QUERY),
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    def resolve_album() -> Album | None:
        song = get_song_by_slug(db, slug)
        return song.album if song else None

    return _shared_cover_response(request, resolve_album, ctx.audio_dir, variant, v)


@router.get(
    "/shared/song/{slug}/cover",
    responses={404: {"description": "Shared song or cover not found"}},
    openapi_extra=exclude_route(Exclusion.PUBLIC_VIEW),
)
async def get_shared_song_cover(
    slug: str,
    request: Request,
    variant: str = Query(COVER_VARIANT_DETAIL),
    v: str | None = Query(None, alias=COVER_VERSION_QUERY),
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    return _shared_cover_response(
        request, lambda: get_song_by_slug(db, slug), ctx.audio_dir, variant, v,
        resolve_song_cover_file,
    )


@router.get(
    "/shared/song/{slug}/audio/{filename:path}",
    responses={404: {"description": "Shared audio file not found"}},
    openapi_extra=exclude_route(Exclusion.PUBLIC_VIEW),
)
def get_shared_song_audio(
    slug: str,
    filename: str,
    request: Request,
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    return _presented_audio_response(
        request, db, ctx, slug, filename, shared_song_take_stored_path,
    )


@router.get(
    "/shared/gen/{slug}/album-cover",
    responses={404: {"description": "Shared generation, album, or cover not found"}},
    openapi_extra=exclude_route(Exclusion.PUBLIC_VIEW),
)
async def get_shared_generation_album_cover(
    slug: str,
    request: Request,
    variant: str = Query(COVER_VARIANT_DETAIL),
    v: str | None = Query(None, alias=COVER_VERSION_QUERY),
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    def resolve_album() -> Album | None:
        generation = get_presented_generation(db, slug)
        return generation.song.album if generation else None

    return _shared_cover_response(request, resolve_album, ctx.audio_dir, variant, v)


@router.get(
    "/shared/gen/{slug}/audio/{filename:path}",
    responses={404: {"description": "Shared audio file not found"}},
    openapi_extra=exclude_route(Exclusion.PUBLIC_VIEW),
)
def get_shared_gen_audio(
    slug: str,
    filename: str,
    request: Request,
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    check_shared_rate_limit(request)
    gen = get_presented_generation(db, slug)
    if not gen or generation_id_of_shared_audio_name(filename) != gen.id:
        raise HTTPException(404, HTTP_NOT_FOUND)
    return _shared_audio_file_response(ctx, gen.mp3_path)


@router.get(
    "/shared/playlist/{slug}/cover",
    responses={404: {"description": "Shared playlist or cover not found"}},
    openapi_extra=exclude_route(Exclusion.PUBLIC_VIEW),
)
async def get_shared_playlist_cover(
    slug: str,
    request: Request,
    variant: str = Query(COVER_VARIANT_DETAIL),
    v: str | None = Query(None, alias=COVER_VERSION_QUERY),
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    return _shared_cover_response(
        request, lambda: get_playlist_by_slug(db, slug), ctx.audio_dir, variant, v,
        resolve_playlist_cover_file,
    )


@router.get(
    "/shared/playlist/{slug}/album-cover/{album_id}",
    responses={404: {"description": "Shared playlist, album, or cover not found"}},
    openapi_extra=exclude_route(Exclusion.PUBLIC_VIEW),
)
async def get_shared_playlist_album_cover(
    slug: str,
    album_id: str,
    request: Request,
    variant: str = Query(COVER_VARIANT_DETAIL),
    v: str | None = Query(None, alias=COVER_VERSION_QUERY),
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    def resolve_album() -> Album:
        playlist = get_playlist_by_slug(db, slug)
        if not playlist:
            raise HTTPException(404, NOT_FOUND_DETAIL)
        album = next((
            album
            for entry in playlist.entries
            if (album := entry_album(entry)) is not None and album.id == album_id
        ), None)
        if album is None:
            raise HTTPException(404, COVER_NOT_FOUND)
        return album

    return _shared_cover_response(request, resolve_album, ctx.audio_dir, variant, v)


@router.get(
    "/shared/playlist/{slug}/audio/{filename:path}",
    responses={404: {"description": "Shared audio file not found"}},
    openapi_extra=exclude_route(Exclusion.PUBLIC_VIEW),
)
def get_shared_playlist_audio(
    slug: str,
    filename: str,
    request: Request,
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    return _presented_audio_response(
        request, db, ctx, slug, filename, shared_playlist_take_stored_path,
    )


@router.get(
    "/shared/queue-streams/{snapshot_id}/audio",
    responses={404: {"description": QUEUE_STREAM_NOT_FOUND_DETAIL}},
    openapi_extra=exclude_route(Exclusion.PUBLIC_VIEW),
)
def get_shared_queue_stream_audio(
    snapshot_id: str,
    request: Request,
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    check_shared_rate_limit(request)
    manifest = load_queue_stream_manifest(ctx, snapshot_id)
    _validate_shared_queue_manifest(manifest, db)
    return audio_response(
        queue_stream_audio_path(ctx, snapshot_id), QUEUE_STREAM_AUDIO_CACHE_CONTROL,
    )

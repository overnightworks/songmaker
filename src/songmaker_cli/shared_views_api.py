"""Public share views: the album, song, take and playlist pages and their queue streams."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

import songmaker_cli.constants as _consts
from songmaker_cli.agent.mcp import Exclusion, exclude_route
from songmaker_cli.api_helpers import raise_audio_file_http_error
from songmaker_cli.api_models import (
    QueueStreamManifestResponse,
    SharedAlbumResponse,
    SharedGenerationResponse,
    SharedPlaylistEntryResponse,
    SharedPlaylistResponse,
    SharedSongItem,
    SharedSongResponse,
)
from songmaker_cli.api_models.playlists import (
    shared_playlist_album_cover_urls,
    shared_playlist_cover_urls,
)
from songmaker_cli.api_models.songs import (
    public_album_cover_urls,
    public_album_cover_urls_at,
    public_song_cover_urls,
    share_pick_media,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.audio_paths import AudioFileNotFoundError
from songmaker_cli.covers import (
    album_cover_file_exists,
    playlist_cover_file_exists,
    song_cover_file_exists,
)
from songmaker_cli.db.queries.albums import get_album_by_slug
from songmaker_cli.db.queries.generations import get_presented_generation
from songmaker_cli.db.queries.playlists import get_playlist_by_slug
from songmaker_cli.db.queries.sharing import (
    is_playable_take,
    presented_playlist_entries,
    presented_take,
)
from songmaker_cli.db.queries.songs import get_song_by_slug
from songmaker_cli.queue_streams import (
    QueueStreamSource,
    SnapshotScope,
    build_queue_stream_snapshot,
    ensure_sources_detachable,
    public_queue_stream_manifest,
    track_source_from_generation,
)
from songmaker_cli.shared_access import (
    NOT_FOUND_DETAIL,
    check_rate_limit,
    check_shared_rate_limit,
    entry_album,
    get_shared_limiter,
    shared_audio_url_for_take,
)

router = APIRouter()


def _check_shared_stream_rate_limit(request: Request) -> None:
    check_rate_limit(
        request,
        get_shared_limiter(request, stream=True),
        limit=_consts.SHARING_STREAM_RATE_LIMIT,
        window_seconds=_consts.SHARING_STREAM_RATE_WINDOW_SECONDS,
    )


def _shared_audio_url(
    route: str,
    generation,
) -> str | None:
    if (
        generation is None
        or not is_playable_take(generation)
    ):
        return None
    return shared_audio_url_for_take(route, generation)


def _offered_cover[T](file_exists: bool, build_urls: Callable[[], T]) -> T | None:
    return build_urls() if file_exists else None


@router.get(
    "/shared/{slug}",
    responses={404: {"description": "Shared album not found"}},
    openapi_extra=exclude_route(Exclusion.PUBLIC_VIEW),
)
def get_shared_album(
    slug: str,
    request: Request,
    db: Session = Depends(get_db_session),
) -> JSONResponse:
    check_shared_rate_limit(request)

    album = get_album_by_slug(db, slug)
    if not album:
        raise HTTPException(404, NOT_FOUND_DETAIL)
    ctx: AppContext = request.app.state.ctx
    songs = sorted(album.songs, key=lambda s: s.track_number)
    picked_by_song = {s.id: presented_take(s.generations) for s in songs}
    cover = _offered_cover(
        album_cover_file_exists(ctx.audio_dir, album.id, album.cover_key),
        lambda: public_album_cover_urls(slug, album.cover_key),
    )
    song_items = []
    for s in songs:
        gen = picked_by_song[s.id]
        media = share_pick_media(gen)
        song_items.append(SharedSongItem(
            id=s.id,
            title=s.title,
            track_number=s.track_number,
            audio_url=_shared_audio_url(f"/shared/{slug}/audio", gen),
            generation_id=media.generation_id,
            audio_duration=media.audio_duration,
            lyrics=media.lyrics,
            whisper_cues=media.whisper_cues,
        ))
    response = SharedAlbumResponse.from_orm(album, songs=song_items, cover=cover)
    return JSONResponse(response.model_dump())


def _public_queue_stream(
    ctx: AppContext,
    db: Session,
    sources: list[QueueStreamSource],
    scope: SnapshotScope,
    slug: str,
) -> QueueStreamManifestResponse:
    ensure_sources_detachable(sources)
    db.close()

    try:
        snapshot = build_queue_stream_snapshot(
            ctx,
            sources,
            scope=scope,
            scope_id=slug,
            stream_url="",
        )
    except AudioFileNotFoundError as exc:
        raise_audio_file_http_error(exc, public=True)
    snapshot.stream_url = f"/shared/queue-streams/{snapshot.snapshot_id}/audio"
    return public_queue_stream_manifest(snapshot)


@router.post(
    "/shared/{slug}/stream",
    responses={404: {"description": "Shared album not found"}},
    openapi_extra=exclude_route(Exclusion.PUBLIC_VIEW),
)
def get_shared_album_stream(
    slug: str,
    request: Request,
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> QueueStreamManifestResponse:
    check_shared_rate_limit(request)
    _check_shared_stream_rate_limit(request)
    album = get_album_by_slug(db, slug)
    if not album:
        raise HTTPException(404, NOT_FOUND_DETAIL)
    sources = []
    songs = sorted(album.songs, key=lambda s: s.track_number)
    for index, song in enumerate(songs):
        gen = presented_take(song.generations)
        if not gen:
            continue
        audio_url = _shared_audio_url(f"/shared/{slug}/audio", gen)
        if audio_url is None:
            continue
        sources.append(
            track_source_from_generation(
                gen,
                key=f"{song.id}:{gen.id}:{index}",
                index=len(sources),
                entry_id=None,
                audio_url=audio_url,
            )
        )
    return _public_queue_stream(ctx, db, sources, "shared-album", slug)


@router.get(
    "/shared/song/{slug}",
    responses={404: {"description": "Shared song not found"}},
    openapi_extra=exclude_route(Exclusion.PUBLIC_VIEW),
)
def get_shared_song(
    slug: str,
    request: Request,
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> JSONResponse:
    check_shared_rate_limit(request)
    song = get_song_by_slug(db, slug)
    if not song:
        raise HTTPException(404, NOT_FOUND_DETAIL)
    gen = presented_take(song.generations)
    media = share_pick_media(gen)
    cover = _offered_cover(
        song_cover_file_exists(ctx.audio_dir, song.id, song.cover_key),
        lambda: public_song_cover_urls(slug, song.cover_key),
    )
    song_album = song.album
    album_cover = _offered_cover(
        song_album is not None
        and album_cover_file_exists(ctx.audio_dir, song_album.id, song_album.cover_key),
        lambda: public_album_cover_urls_at(
            f"/shared/song/{slug}/album-cover", song_album.cover_key
        ),
    )
    response = SharedSongResponse(
        title=song.title,
        artist=song.album.artist if song.album else "",
        album_title=song.album.title if song.album else "",
        audio_url=_shared_audio_url(f"/shared/song/{slug}/audio", gen),
        cover=cover,
        album_cover=album_cover,
        generation_id=media.generation_id,
        audio_duration=media.audio_duration,
        lyrics=media.lyrics,
        whisper_cues=media.whisper_cues,
    )
    return JSONResponse(response.model_dump())


@router.get(
    "/shared/gen/{slug}",
    responses={404: {"description": "Shared generation not found"}},
    openapi_extra=exclude_route(Exclusion.PUBLIC_VIEW),
)
def get_shared_generation(
    slug: str,
    request: Request,
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> JSONResponse:
    check_shared_rate_limit(request)
    gen = get_presented_generation(db, slug)
    if not gen:
        raise HTTPException(404, NOT_FOUND_DETAIL)
    media = share_pick_media(gen)
    album = gen.song.album
    album_cover = _offered_cover(
        album is not None
        and album_cover_file_exists(ctx.audio_dir, album.id, album.cover_key),
        lambda: public_album_cover_urls_at(
            f"/shared/gen/{slug}/album-cover", album.cover_key
        ),
    )
    response = SharedGenerationResponse(
        title=gen.song.title,
        artist=album.artist if album else "",
        album_title=album.title if album else "",
        generation_number=gen.generation_number,
        audio_url=shared_audio_url_for_take(f"/shared/gen/{slug}/audio", gen),
        generation_id=media.generation_id,
        audio_duration=media.audio_duration,
        lyrics=media.lyrics,
        whisper_cues=media.whisper_cues,
        album_cover=album_cover,
    )
    return JSONResponse(response.model_dump())


@router.get(
    "/shared/playlist/{slug}",
    responses={404: {"description": "Shared playlist not found"}},
    openapi_extra=exclude_route(Exclusion.PUBLIC_VIEW),
)
def get_shared_playlist(
    slug: str,
    request: Request,
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> JSONResponse:
    check_shared_rate_limit(request)
    playlist = get_playlist_by_slug(db, slug)
    if not playlist:
        raise HTTPException(404, NOT_FOUND_DETAIL)
    entries = presented_playlist_entries(playlist)
    entry_items = _shared_playlist_entries(ctx, entries, slug)
    cover = _shared_playlist_cover(ctx, playlist, slug)
    album_covers = _shared_playlist_album_covers(ctx, entries, slug) if cover is None else []
    response = SharedPlaylistResponse.from_orm(
        playlist,
        entries=entry_items,
        cover=cover,
        album_covers=album_covers,
    )
    return JSONResponse(response.model_dump())


def _shared_playlist_entries(
    ctx: AppContext, entries, slug: str,
) -> list[SharedPlaylistEntryResponse]:
    return [
        SharedPlaylistEntryResponse.from_orm(
            entry,
            audio_url=_shared_audio_url(
                f"/shared/playlist/{slug}/audio", entry.generation,
            ),
            album_cover=_shared_entry_album_cover(ctx, entry, slug),
        )
        for entry in entries
    ]


def _shared_entry_album_cover(ctx: AppContext, entry, slug: str):
    album = entry_album(entry)
    return _offered_cover(
        album is not None
        and album_cover_file_exists(ctx.audio_dir, album.id, album.cover_key),
        lambda: shared_playlist_album_cover_urls(slug, album.id, album.cover_key),
    )


def _shared_playlist_cover(ctx: AppContext, playlist, slug: str):
    return _offered_cover(
        playlist_cover_file_exists(ctx.audio_dir, playlist.id, playlist.cover_key),
        lambda: shared_playlist_cover_urls(slug, playlist.cover_key),
    )


def _shared_playlist_album_covers(ctx: AppContext, entries, slug: str) -> list:
    album_covers = []
    covered_album_ids = set()
    for entry in entries:
        album = entry_album(entry)
        if album is None or album.id in covered_album_ids:
            continue
        cover = _shared_entry_album_cover(ctx, entry, slug)
        if cover is None:
            continue
        covered_album_ids.add(album.id)
        album_covers.append(cover)
        if len(album_covers) == 4:
            break
    return album_covers


@router.post(
    "/shared/playlist/{slug}/stream",
    responses={404: {"description": "Shared playlist not found"}},
    openapi_extra=exclude_route(Exclusion.PUBLIC_VIEW),
)
def get_shared_playlist_stream(
    slug: str,
    request: Request,
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> QueueStreamManifestResponse:
    check_shared_rate_limit(request)
    _check_shared_stream_rate_limit(request)
    playlist = get_playlist_by_slug(db, slug)
    if not playlist:
        raise HTTPException(404, NOT_FOUND_DETAIL)
    sources = []
    for entry in presented_playlist_entries(playlist):
        gen = entry.generation
        if not is_playable_take(gen):
            continue
        audio_url = _shared_audio_url(
            f"/shared/playlist/{slug}/audio", gen,
        )
        if audio_url is None:
            continue
        sources.append(
            track_source_from_generation(
                gen,
                key=entry.id,
                index=len(sources),
                entry_id=entry.id,
                audio_url=audio_url,
            )
        )
    return _public_queue_stream(ctx, db, sources, "shared-playlist", slug)

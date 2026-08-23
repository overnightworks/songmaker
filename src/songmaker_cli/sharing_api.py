"""Sharing and audio file serving endpoints."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

import songmaker_cli.constants as _consts
from songmaker_cli.api_models import (
    QueueStreamManifestResponse,
    SharedAlbumResponse,
    SharedGenerationResponse,
    SharedPlaylistEntryResponse,
    SharedPlaylistResponse,
    SharedSongItem,
    SharedSongResponse,
)
from songmaker_cli.api_models.songs import (
    public_album_cover_urls,
    public_song_cover_urls,
    share_pick_media,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.auth import get_client_ip
from songmaker_cli.constants import (
    AUDIO_MEDIA_TYPES,
    COVER_NOT_FOUND,
    COVER_VARIANT_DETAIL,
    COVER_VERSION_QUERY,
    REDIS_RL_SHARED_PREFIX,
    REDIS_RL_SHARED_STREAM_PREFIX,
)
from songmaker_cli.covers import (
    COVER_RESPONSE_HEADERS,
    CoverRejectedError,
    album_cover_file_exists,
    cover_media_type,
    resolve_cover_file,
    resolve_song_cover_file,
    song_cover_file_exists,
)
from songmaker_cli.db.queries import (
    get_album_by_slug,
    get_generation_by_slug,
    get_playlist_by_slug,
    get_song_by_slug,
)
from songmaker_cli.db.queries.sharing import is_playable_take
from songmaker_cli.middleware import AuthenticatedUser, get_current_user
from songmaker_cli.queue_streams import (
    build_queue_stream_snapshot,
    load_queue_stream_manifest,
    public_queue_stream_manifest,
    queue_stream_audio_path,
    track_source_from_generation,
)
from songmaker_cli.redis_client import RedisRateLimiter

log = logging.getLogger(__name__)

router = APIRouter()


def _get_shared_limiter(request: Request) -> RedisRateLimiter:
    limiter = getattr(request.app.state, "_shared_limiter", None)
    if limiter is None:
        ctx: AppContext = request.app.state.ctx
        limiter = RedisRateLimiter(
            ctx.redis, REDIS_RL_SHARED_PREFIX,
            _consts.SHARING_RATE_LIMIT, _consts.SHARING_RATE_WINDOW_SECONDS,
        )
        request.app.state._shared_limiter = limiter
    return limiter


def _get_shared_stream_limiter(request: Request) -> RedisRateLimiter:
    limiter = getattr(request.app.state, "_shared_stream_limiter", None)
    if limiter is None:
        ctx: AppContext = request.app.state.ctx
        limiter = RedisRateLimiter(
            ctx.redis,
            REDIS_RL_SHARED_STREAM_PREFIX,
            _consts.SHARING_STREAM_RATE_LIMIT,
            _consts.SHARING_STREAM_RATE_WINDOW_SECONDS,
        )
        request.app.state._shared_stream_limiter = limiter
    return limiter


def _check_shared_rate_limit(request: Request) -> None:
    _check_rate_limit(
        request,
        _get_shared_limiter(request),
        retry_after=_consts.SHARING_RATE_WINDOW_SECONDS,
    )


def _check_shared_stream_rate_limit(request: Request) -> None:
    _check_rate_limit(
        request,
        _get_shared_stream_limiter(request),
        retry_after=_consts.SHARING_STREAM_RATE_WINDOW_SECONDS,
    )


def _check_rate_limit(
    request: Request,
    limiter: RedisRateLimiter,
    *,
    retry_after: int,
) -> None:
    ctx: AppContext = request.app.state.ctx
    direct_ip = request.client.host if request.client else "unknown"
    ip = get_client_ip(
        direct_ip,
        request.headers.get("x-forwarded-for"),
        ctx.trusted_proxies,
    )
    try:
        allowed = limiter.is_allowed(ip)
    except Exception:
        log.warning("Shared rate limiter unavailable -- allowing request")
        return
    if not allowed:
        raise HTTPException(
            429, "Too many requests",
            headers={"Retry-After": str(retry_after)},
        )


def _picked_generation(song):
    picked = [g for g in song.generations if g.is_picked and is_playable_take(g)]
    if picked:
        return picked[0]
    available = sorted(
        (g for g in song.generations if is_playable_take(g)),
        key=lambda g: g.generation_number,
    )
    if available:
        return available[-1]
    return None


def _picked_filename(song) -> str | None:
    gen = _picked_generation(song)
    return gen.mp3_path if gen else None


def _resolve_audio_path(audio_dir: Path, rel_path: str) -> Path:
    audio_path = (audio_dir / rel_path).resolve()
    if not audio_path.is_relative_to(audio_dir.resolve()):
        raise HTTPException(403, "Path traversal denied")
    if not audio_path.exists():
        raise HTTPException(404, "Audio file not found")
    return audio_path


def _validate_shared_queue_manifest(manifest: dict, db: Session) -> None:
    scope = manifest.get("scope")
    slug = str(manifest.get("scope_id") or "")
    tracks = manifest.get("tracks") or []
    if scope == "shared-playlist":
        playlist = get_playlist_by_slug(db, slug)
        if not playlist:
            raise HTTPException(404, "Not found")
        valid_tracks = {
            (entry.id, entry.generation.id)
            for entry in playlist.entries
            if entry.generation is not None
        }
        if any(
            (track.get("entry_id"), track.get("generation_id")) not in valid_tracks
            for track in tracks
        ):
            raise HTTPException(404, "Queue stream not found")
        return

    if scope == "shared-album":
        album = get_album_by_slug(db, slug)
        if not album:
            raise HTTPException(404, "Not found")
        valid_tracks = {
            (song.id, gen.id)
            for song in album.songs
            if (gen := _picked_generation(song)) is not None
        }
        if any(
            (track.get("song_id"), track.get("generation_id")) not in valid_tracks
            for track in tracks
        ):
            raise HTTPException(404, "Queue stream not found")
        return

    raise HTTPException(404, "Queue stream not found")


@router.get("/audio/{owner_id}/{filename}")
async def get_audio(
    owner_id: str, filename: str,
    user: AuthenticatedUser = Depends(get_current_user),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    if user.role != "admin" and owner_id != user.id:
        raise HTTPException(404, "Audio file not found")

    audio_path = _resolve_audio_path(ctx.audio_dir, f"{owner_id}/{filename}")
    media_type = AUDIO_MEDIA_TYPES.get(audio_path.suffix, "application/octet-stream")
    return FileResponse(audio_path, media_type=media_type)


@router.get("/shared/{slug}")
def get_shared_album(
    slug: str,
    request: Request,
    db: Session = Depends(get_db_session),
) -> JSONResponse:
    _check_shared_rate_limit(request)

    album = get_album_by_slug(db, slug)
    if not album:
        raise HTTPException(404, "Not found")
    ctx: AppContext = request.app.state.ctx
    songs = sorted(album.songs, key=lambda s: s.track_number)
    picked_by_song = {s.id: _picked_generation(s) for s in songs}
    cover = None
    if (
        album.cover_key
        and album_cover_file_exists(ctx.audio_dir, album.id, album.cover_key)
    ):
        cover = public_album_cover_urls(slug, album.cover_key)
    song_items = []
    for s in songs:
        gen = picked_by_song[s.id]
        media = share_pick_media(gen)
        song_items.append(SharedSongItem(
            id=s.id,
            title=s.title,
            track_number=s.track_number,
            audio_url=(
                f"/shared/{slug}/audio/{gen.mp3_path}"
                if gen and gen.mp3_path else None
            ),
            generation_id=media.generation_id,
            audio_duration=media.audio_duration,
            lyrics=media.lyrics,
            whisper_cues=media.whisper_cues,
        ))
    response = SharedAlbumResponse.from_orm(album, songs=song_items, cover=cover)
    return JSONResponse(response.model_dump())


@router.get("/shared/{slug}/cover")
async def get_shared_album_cover(
    slug: str,
    request: Request,
    variant: str = Query(COVER_VARIANT_DETAIL),
    v: str | None = Query(None, alias=COVER_VERSION_QUERY),
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    _check_shared_rate_limit(request)
    album = get_album_by_slug(db, slug)
    if not album:
        raise HTTPException(404, "Not found")
    if v is not None and v != album.cover_key:
        raise HTTPException(404, COVER_NOT_FOUND)
    try:
        path = resolve_cover_file(ctx.audio_dir, album.id, album.cover_key, variant)
    except CoverRejectedError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except FileNotFoundError:
        raise HTTPException(404, COVER_NOT_FOUND)
    return FileResponse(
        path,
        media_type=cover_media_type(variant, album.cover_key or ""),
        headers=COVER_RESPONSE_HEADERS,
    )


@router.post("/shared/{slug}/stream")
def get_shared_album_stream(
    slug: str,
    request: Request,
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> QueueStreamManifestResponse:
    _check_shared_rate_limit(request)
    _check_shared_stream_rate_limit(request)
    album = get_album_by_slug(db, slug)
    if not album:
        raise HTTPException(404, "Not found")
    sources = []
    songs = sorted(album.songs, key=lambda s: s.track_number)
    for index, song in enumerate(songs):
        gen = _picked_generation(song)
        if not gen:
            continue
        sources.append(
            track_source_from_generation(
                gen,
                key=f"{song.id}:{gen.id}:{index}",
                index=len(sources),
                entry_id=None,
                audio_url=f"/shared/{slug}/audio/{gen.mp3_path}",
            )
        )
    snapshot = build_queue_stream_snapshot(
        ctx,
        sources,
        scope="shared-album",
        scope_id=slug,
        stream_url="",
    )
    snapshot.stream_url = f"/shared/queue-streams/{snapshot.snapshot_id}/audio"
    return public_queue_stream_manifest(snapshot)


@router.get("/shared/{slug}/audio/{filename:path}")
async def get_shared_audio(
    slug: str,
    filename: str,
    request: Request,
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    _check_shared_rate_limit(request)
    album = get_album_by_slug(db, slug)
    if not album:
        raise HTTPException(404, "Not found")

    valid_filenames = {
        fn for s in album.songs
        if (fn := _picked_filename(s))
    }
    if filename not in valid_filenames:
        raise HTTPException(404, "Not found")

    audio_path = _resolve_audio_path(ctx.audio_dir, filename)
    media_type = AUDIO_MEDIA_TYPES.get(audio_path.suffix, "application/octet-stream")
    return FileResponse(audio_path, media_type=media_type)


@router.get("/shared/song/{slug}")
def get_shared_song(
    slug: str,
    request: Request,
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> JSONResponse:
    _check_shared_rate_limit(request)
    song = get_song_by_slug(db, slug)
    if not song:
        raise HTTPException(404, "Not found")
    gen = _picked_generation(song)
    media = share_pick_media(gen)
    cover = None
    if (
        song.cover_key
        and song_cover_file_exists(ctx.audio_dir, song.id, song.cover_key)
    ):
        cover = public_song_cover_urls(slug, song.cover_key)
    response = SharedSongResponse(
        title=song.title,
        artist=song.album.artist if song.album else "",
        album_title=song.album.title if song.album else "",
        audio_url=(
            f"/shared/song/{slug}/audio/{gen.mp3_path}"
            if gen and gen.mp3_path else None
        ),
        cover=cover,
        generation_id=media.generation_id,
        audio_duration=media.audio_duration,
        lyrics=media.lyrics,
        whisper_cues=media.whisper_cues,
    )
    return JSONResponse(response.model_dump())


@router.get("/shared/song/{slug}/cover")
async def get_shared_song_cover(
    slug: str,
    request: Request,
    variant: str = Query(COVER_VARIANT_DETAIL),
    v: str | None = Query(None, alias=COVER_VERSION_QUERY),
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    _check_shared_rate_limit(request)
    song = get_song_by_slug(db, slug)
    if not song:
        raise HTTPException(404, "Not found")
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


@router.get("/shared/song/{slug}/audio/{filename:path}")
async def get_shared_song_audio(
    slug: str,
    filename: str,
    request: Request,
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    _check_shared_rate_limit(request)
    song = get_song_by_slug(db, slug)
    if not song:
        raise HTTPException(404, "Not found")

    picked_path = _picked_filename(song)
    if not picked_path or filename != picked_path:
        raise HTTPException(404, "Not found")

    audio_path = _resolve_audio_path(ctx.audio_dir, filename)
    media_type = AUDIO_MEDIA_TYPES.get(audio_path.suffix, "application/octet-stream")
    return FileResponse(audio_path, media_type=media_type)


@router.get("/shared/gen/{slug}")
def get_shared_generation(
    slug: str,
    request: Request,
    db: Session = Depends(get_db_session),
) -> JSONResponse:
    _check_shared_rate_limit(request)
    gen = get_generation_by_slug(db, slug)
    if not gen:
        raise HTTPException(404, "Not found")
    media = share_pick_media(gen)
    response = SharedGenerationResponse(
        title=gen.song.title if gen.song else "",
        artist=gen.song.album.artist if gen.song and gen.song.album else "",
        album_title=gen.song.album.title if gen.song and gen.song.album else "",
        generation_number=gen.generation_number,
        seed=gen.seed,
        audio_url=(
            f"/shared/gen/{slug}/audio/{gen.mp3_path}"
            if gen.mp3_path else None
        ),
        generation_id=media.generation_id,
        audio_duration=media.audio_duration,
        lyrics=media.lyrics,
        whisper_cues=media.whisper_cues,
    )
    return JSONResponse(response.model_dump())


@router.get("/shared/gen/{slug}/audio/{filename:path}")
async def get_shared_gen_audio(
    slug: str,
    filename: str,
    request: Request,
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    _check_shared_rate_limit(request)
    gen = get_generation_by_slug(db, slug)
    if not gen:
        raise HTTPException(404, "Not found")

    if filename != gen.mp3_path:
        raise HTTPException(404, "Not found")

    audio_path = _resolve_audio_path(ctx.audio_dir, filename)
    media_type = AUDIO_MEDIA_TYPES.get(audio_path.suffix, "application/octet-stream")
    return FileResponse(audio_path, media_type=media_type)


@router.get("/shared/playlist/{slug}")
def get_shared_playlist(
    slug: str,
    request: Request,
    db: Session = Depends(get_db_session),
) -> JSONResponse:
    _check_shared_rate_limit(request)
    playlist = get_playlist_by_slug(db, slug)
    if not playlist:
        raise HTTPException(404, "Not found")
    entries = sorted(playlist.entries, key=lambda e: e.position)
    entry_items = []
    for e in entries:
        if e.generation is None:
            continue
        gen = e.generation
        media = share_pick_media(gen)
        entry_items.append(SharedPlaylistEntryResponse(
            entry_id=e.id,
            song_title=gen.song.title if gen.song else "",
            artist=gen.song.album.artist if gen.song and gen.song.album else "",
            generation_number=gen.generation_number,
            audio_url=(
                f"/shared/playlist/{slug}/audio/{gen.mp3_path}"
                if gen.mp3_path else None
            ),
            generation_id=media.generation_id,
            audio_duration=media.audio_duration,
            lyrics=media.lyrics,
            whisper_cues=media.whisper_cues,
        ))
    response = SharedPlaylistResponse(title=playlist.title, entries=entry_items)
    return JSONResponse(response.model_dump())


@router.post("/shared/playlist/{slug}/stream")
def get_shared_playlist_stream(
    slug: str,
    request: Request,
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> QueueStreamManifestResponse:
    _check_shared_rate_limit(request)
    _check_shared_stream_rate_limit(request)
    playlist = get_playlist_by_slug(db, slug)
    if not playlist:
        raise HTTPException(404, "Not found")
    sources = []
    entries = sorted(playlist.entries, key=lambda e: e.position)
    for entry in entries:
        gen = entry.generation
        if gen is None:
            continue
        sources.append(
            track_source_from_generation(
                gen,
                key=entry.id,
                index=len(sources),
                entry_id=entry.id,
                audio_url=f"/shared/playlist/{slug}/audio/{gen.mp3_path}",
            )
        )
    snapshot = build_queue_stream_snapshot(
        ctx,
        sources,
        scope="shared-playlist",
        scope_id=slug,
        stream_url="",
    )
    snapshot.stream_url = f"/shared/queue-streams/{snapshot.snapshot_id}/audio"
    return public_queue_stream_manifest(snapshot)


@router.get("/shared/playlist/{slug}/audio/{filename:path}")
async def get_shared_playlist_audio(
    slug: str,
    filename: str,
    request: Request,
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    _check_shared_rate_limit(request)
    playlist = get_playlist_by_slug(db, slug)
    if not playlist:
        raise HTTPException(404, "Not found")

    valid_filenames = {
        e.generation.mp3_path
        for e in playlist.entries
        if e.generation is not None
    }
    if filename not in valid_filenames:
        raise HTTPException(404, "Not found")

    audio_path = _resolve_audio_path(ctx.audio_dir, filename)
    media_type = AUDIO_MEDIA_TYPES.get(audio_path.suffix, "application/octet-stream")
    return FileResponse(audio_path, media_type=media_type)


@router.get("/shared/queue-streams/{snapshot_id}/audio")
def get_shared_queue_stream_audio(
    snapshot_id: str,
    request: Request,
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    _check_shared_rate_limit(request)
    manifest = load_queue_stream_manifest(ctx, snapshot_id)
    _validate_shared_queue_manifest(manifest, db)
    audio_path = queue_stream_audio_path(ctx, snapshot_id)
    media_type = AUDIO_MEDIA_TYPES.get(audio_path.suffix, "application/octet-stream")
    return FileResponse(audio_path, media_type=media_type)

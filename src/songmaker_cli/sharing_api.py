"""Sharing and audio file serving endpoints."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

import songmaker_cli.constants as _consts
from songmaker_cli.api_models import (
    SharedAlbumResponse,
    SharedGenerationResponse,
    SharedPlaylistEntryResponse,
    SharedPlaylistResponse,
    SharedSongItem,
    SharedSongResponse,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.auth import get_client_ip
from songmaker_cli.constants import (
    AUDIO_MEDIA_TYPES,
    REDIS_RL_SHARED_PREFIX,
)
from songmaker_cli.db.queries import (
    get_album_by_slug,
    get_generation_by_slug,
    get_playlist_by_slug,
    get_song_by_slug,
)
from songmaker_cli.middleware import AuthenticatedUser, get_current_user
from songmaker_cli.redis_client import RedisRateLimiter

log = logging.getLogger(__name__)

router = APIRouter()


def _get_shared_limiter(request: Request) -> RedisRateLimiter:
    limiter = getattr(request.app.state, "_shared_limiter", None)
    if limiter is None:
        ctx: AppContext = request.app.state.ctx
        limiter = RedisRateLimiter(
            ctx.redis, REDIS_RL_SHARED_PREFIX,
            _consts.SHARED_RATE_LIMIT, _consts.SHARED_RATE_WINDOW_SECONDS,
        )
        request.app.state._shared_limiter = limiter
    return limiter


def _check_shared_rate_limit(request: Request) -> None:
    ctx: AppContext = request.app.state.ctx
    direct_ip = request.client.host if request.client else "unknown"
    ip = get_client_ip(
        direct_ip,
        request.headers.get("x-forwarded-for"),
        ctx.trusted_proxies,
    )
    try:
        allowed = _get_shared_limiter(request).is_allowed(ip)
    except Exception:
        log.warning("Shared rate limiter unavailable -- allowing request")
        return
    if not allowed:
        raise HTTPException(
            429, "Too many requests",
            headers={"Retry-After": str(_consts.SHARED_RATE_WINDOW_SECONDS)},
        )


def _picked_filename(song) -> str | None:
    picked = [g for g in song.generations if g.is_picked and not g.is_archived]
    if picked:
        return picked[0].mp3_path
    available = sorted(
        (g for g in song.generations if g.mp3_path and not g.is_archived),
        key=lambda g: g.generation_number,
    )
    if available:
        return available[-1].mp3_path
    return None


def _resolve_audio_path(audio_dir: Path, rel_path: str) -> Path:
    audio_path = (audio_dir / rel_path).resolve()
    if not audio_path.is_relative_to(audio_dir.resolve()):
        raise HTTPException(403, "Path traversal denied")
    if not audio_path.exists():
        raise HTTPException(404, "Audio file not found")
    return audio_path


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
    songs = sorted(album.songs, key=lambda s: s.track_number)
    picked_by_song = {s.id: _picked_filename(s) for s in songs}
    response = SharedAlbumResponse(
        title=album.title,
        artist=album.artist,
        subtitle=album.subtitle,
        year=album.year,
        songs=[
            SharedSongItem(
                title=s.title,
                track_number=s.track_number,
                audio_url=(
                    f"/shared/{slug}/audio/{picked_by_song[s.id]}"
                    if picked_by_song[s.id] else None
                ),
            )
            for s in songs
        ],
    )
    return JSONResponse(response.model_dump())


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
) -> JSONResponse:
    _check_shared_rate_limit(request)
    song = get_song_by_slug(db, slug)
    if not song:
        raise HTTPException(404, "Not found")
    picked_path = _picked_filename(song)
    response = SharedSongResponse(
        title=song.title,
        artist=song.album.artist if song.album else "",
        album_title=song.album.title if song.album else "",
        audio_url=(
            f"/shared/song/{slug}/audio/{picked_path}"
            if picked_path else None
        ),
    )
    return JSONResponse(response.model_dump())


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
    response = SharedPlaylistResponse(
        title=playlist.title,
        entries=[
            SharedPlaylistEntryResponse(
                song_title=e.generation.song.title if e.generation and e.generation.song else "",
                artist=(
                    e.generation.song.album.artist
                    if e.generation and e.generation.song and e.generation.song.album
                    else ""
                ),
                generation_number=e.generation.generation_number if e.generation else 0,
                audio_url=(
                    f"/shared/playlist/{slug}/audio/{e.generation.mp3_path}"
                    if e.generation else None
                ),
            )
            for e in entries
            if e.generation is not None
        ],
    )
    return JSONResponse(response.model_dump())


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

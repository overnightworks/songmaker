"""Sharing and audio file serving endpoints."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

import songmaker_cli.constants as _consts
from songmaker_cli.api_models import SharedAlbumResponse, SharedSongItem
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.auth import get_client_ip
from songmaker_cli.constants import (
    AUDIO_MEDIA_TYPES,
    REDIS_RL_SHARED_PREFIX,
)
from songmaker_cli.db.queries import get_album_by_slug
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
    base_url = str(request.base_url).rstrip("/")
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
                    f"{base_url}/shared/{slug}/audio/{picked_by_song[s.id]}"
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

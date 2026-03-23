"""REST API endpoints backed by the database.

Mounted on the FastAPI app at /api/*. Replaces manifest.json for the frontend.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from songmaker_cli.claude.provider import (
    UnavailableError,
    call_claude,
    is_available,
)
from songmaker_cli.db.engine import get_session_factory
from songmaker_cli.db.queries import (
    album_to_dict,
    create_song,
    get_album,
    get_song,
    get_version,
    get_version_by_path,
    list_albums,
    list_library,
    list_revisions,
    list_versions,
    revision_to_dict,
    save_rating,
    song_to_dict,
    update_song,
    version_to_dict,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _get_session() -> Session:  # type: ignore[misc]
    """FastAPI dependency that provides a DB session with rollback on error."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class RateRequest(BaseModel):
    rating: float = Field(ge=0, le=100)
    notes: str = ""


class SongCreateRequest(BaseModel):
    title: str
    album_id: str
    lyrics: str = ""
    prompt: str = ""
    bpm: int = 0
    duration: int = 180
    key: str = ""
    language: str = ""


class SongUpdateRequest(BaseModel):
    lyrics: str | None = None
    prompt: str | None = None
    bpm: int | None = None
    duration: int | None = None
    key: str | None = None


class PaginatedResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    offset: int
    limit: int


@router.get("/albums")
def api_list_albums(session: Session = Depends(_get_session)) -> list[dict]:
    albums = list_albums(session)
    return [album_to_dict(a) for a in albums]


@router.get("/albums/{album_id}")
def api_get_album(album_id: str, session: Session = Depends(_get_session)) -> dict:
    album = get_album(session, album_id)
    if not album:
        raise HTTPException(404, f"Album not found: {album_id}")
    return album_to_dict(album)


@router.get("/albums/{album_id}/versions")
def api_album_versions(
    album_id: str,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(_get_session),
) -> PaginatedResponse:
    versions, total = list_library(session, album_id=album_id, limit=limit, offset=offset)
    return PaginatedResponse(
        items=[version_to_dict(v) for v in versions],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/library")
def api_library(
    album_id: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(_get_session),
) -> PaginatedResponse:
    versions, total = list_library(session, album_id=album_id, limit=limit, offset=offset)
    return PaginatedResponse(
        items=[version_to_dict(v) for v in versions],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/versions/{version_id}")
def api_get_version(version_id: str, session: Session = Depends(_get_session)) -> dict:
    version = get_version(session, version_id)
    if not version:
        raise HTTPException(404, f"Version not found: {version_id}")
    return version_to_dict(version)


@router.get("/songs/{song_id}/versions")
def api_song_versions(song_id: str, session: Session = Depends(_get_session)) -> list[dict]:
    versions = list_versions(session, song_id)
    return [version_to_dict(v) for v in versions]


@router.post("/versions/{version_id}/rate")
def api_rate_version(
    version_id: str, req: RateRequest, session: Session = Depends(_get_session),
) -> dict:
    version = get_version(session, version_id)
    if not version:
        raise HTTPException(404, f"Version not found: {version_id}")

    save_rating(session, version_id, req.rating, req.notes)
    session.commit()
    return {"status": "ok", "version_id": version_id, "rating": req.rating}


@router.post("/rate/{album}/{version_name}")
def api_rate_by_path(
    album: str, version_name: str, req: RateRequest,
    session: Session = Depends(_get_session),
) -> dict:
    """Legacy-compatible rating endpoint using mp3 path convention."""
    mp3_path = f"{album}/{version_name}.mp3"
    version = get_version_by_path(session, mp3_path)
    if not version:
        raise HTTPException(404, f"Version not found: {mp3_path}")

    save_rating(session, version.id, req.rating, req.notes)
    session.commit()
    return {"status": "ok", "version": version_name, "rating": req.rating}


# ── Song CRUD ────────────────────────────────────────────────────────


@router.post("/songs")
def api_create_song(
    req: SongCreateRequest, session: Session = Depends(_get_session),
) -> dict:
    song = create_song(
        session,
        title=req.title,
        album_id=req.album_id,
        lyrics=req.lyrics,
        prompt=req.prompt,
        bpm=req.bpm,
        duration=req.duration,
        key=req.key,
        language=req.language,
    )
    session.commit()
    return song_to_dict(song)


@router.get("/songs/{song_id}")
def api_get_song(song_id: str, session: Session = Depends(_get_session)) -> dict:
    song = get_song(session, song_id)
    if not song:
        raise HTTPException(404, "Song not found")
    return song_to_dict(song)


@router.put("/songs/{song_id}")
def api_update_song(
    song_id: str, req: SongUpdateRequest, session: Session = Depends(_get_session),
) -> dict:
    try:
        update_song(
            session,
            song_id,
            lyrics=req.lyrics,
            prompt=req.prompt,
            bpm=req.bpm,
            duration=req.duration,
            key=req.key,
        )
    except ValueError:
        raise HTTPException(404, "Song not found")
    session.commit()
    song = get_song(session, song_id)
    return song_to_dict(song)


@router.get("/songs/{song_id}/revisions")
def api_list_revisions(
    song_id: str, session: Session = Depends(_get_session),
) -> list[dict]:
    revisions = list_revisions(session, song_id)
    total = len(revisions)
    return [revision_to_dict(r, total - i, total) for i, r in enumerate(revisions)]


# ── Capabilities ─────────────────────────────────────────────────────


def _resolve_claude_key(header_key: str | None) -> str | None:
    """Get Claude API key: header (BYOK) > env var > None (fall back to CLI)."""
    if header_key:
        return header_key
    return os.environ.get("ANTHROPIC_API_KEY")


@router.get("/capabilities")
def api_capabilities() -> dict:
    """Report which features are available based on server config."""
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    return {
        "claude_api": bool(env_key),
        "claude_cli": is_available(api_key=None),
        "generation": True,
        "scoring": True,
    }


# ── Claude chat ──────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str
    system: str = ""
    context: str = ""


@router.post("/chat")
def api_chat(
    req: ChatRequest,
    x_claude_key: str | None = Header(None),
) -> dict:
    """Chat with Claude for lyrics co-writing.

    Uses BYOK key from header, env var, or falls back to CLI.
    """
    api_key = _resolve_claude_key(x_claude_key)

    prompt = req.message
    if req.context:
        prompt = f"Song context:\n{req.context}\n\n{req.message}"

    try:
        response = call_claude(prompt, api_key=api_key, system=req.system or None)
    except UnavailableError as e:
        raise HTTPException(503, str(e))

    return {"response": response.text}

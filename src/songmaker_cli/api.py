"""REST API endpoints backed by the database."""

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
    generation_to_dict,
    get_album,
    get_generation,
    get_generation_by_path,
    get_song,
    list_albums,
    list_songs,
    save_rating,
    song_to_dict,
    update_song,
    version_to_dict,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _get_session() -> Session:  # type: ignore[misc]
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


# ── Albums ───────────────────────────────────────────────────────────


@router.get("/albums")
def api_list_albums(session: Session = Depends(_get_session)) -> list[dict]:
    return [album_to_dict(a) for a in list_albums(session)]


@router.get("/albums/{album_id}")
def api_get_album(album_id: str, session: Session = Depends(_get_session)) -> dict:
    album = get_album(session, album_id)
    if not album:
        raise HTTPException(404, "Album not found")
    return album_to_dict(album)


# ── Songs ────────────────────────────────────────────────────────────


@router.get("/songs")
def api_list_songs(
    album_id: str | None = Query(None),
    session: Session = Depends(_get_session),
) -> list[dict]:
    return [song_to_dict(s) for s in list_songs(session, album_id=album_id)]


@router.get("/songs/{song_id}")
def api_get_song(song_id: str, session: Session = Depends(_get_session)) -> dict:
    song = get_song(session, song_id)
    if not song:
        raise HTTPException(404, "Song not found")
    return song_to_dict(song)


@router.post("/songs")
def api_create_song(
    req: SongCreateRequest, session: Session = Depends(_get_session),
) -> dict:
    song = create_song(
        session, title=req.title, album_id=req.album_id,
        lyrics=req.lyrics, prompt=req.prompt, bpm=req.bpm,
        duration=req.duration, key=req.key, language=req.language,
    )
    session.commit()
    return song_to_dict(song)


@router.put("/songs/{song_id}")
def api_update_song(
    song_id: str, req: SongUpdateRequest, session: Session = Depends(_get_session),
) -> dict:
    try:
        update_song(
            session, song_id,
            lyrics=req.lyrics, prompt=req.prompt,
            bpm=req.bpm, duration=req.duration, key=req.key,
        )
    except ValueError:
        raise HTTPException(404, "Song not found")
    session.commit()
    song = get_song(session, song_id)
    return song_to_dict(song)


@router.get("/songs/{song_id}/versions")
def api_song_versions(
    song_id: str, session: Session = Depends(_get_session),
) -> list[dict]:
    song = get_song(session, song_id)
    if not song:
        raise HTTPException(404, "Song not found")
    return [version_to_dict(v) for v in reversed(song.versions)]


# ── Generations ──────────────────────────────────────────────────────


@router.get("/generations/{gen_id}")
def api_get_generation(
    gen_id: str, session: Session = Depends(_get_session),
) -> dict:
    gen = get_generation(session, gen_id)
    if not gen:
        raise HTTPException(404, "Generation not found")
    return generation_to_dict(gen)


# ── Ratings ──────────────────────────────────────────────────────────


@router.post("/generations/{gen_id}/rate")
def api_rate_generation(
    gen_id: str, req: RateRequest, session: Session = Depends(_get_session),
) -> dict:
    gen = get_generation(session, gen_id)
    if not gen:
        raise HTTPException(404, "Generation not found")
    save_rating(session, gen_id, req.rating, req.notes)
    session.commit()
    return {"status": "ok", "generation_id": gen_id, "rating": req.rating}


@router.post("/rate/{album}/{gen_name}")
def api_rate_by_path(
    album: str, gen_name: str, req: RateRequest,
    session: Session = Depends(_get_session),
) -> dict:
    mp3_path = f"{album}/{gen_name}.mp3"
    gen = get_generation_by_path(session, mp3_path)
    if not gen:
        raise HTTPException(404, "Generation not found")
    save_rating(session, gen.id, req.rating, req.notes)
    session.commit()
    return {"status": "ok", "generation": gen_name, "rating": req.rating}


# ── Capabilities ─────────────────────────────────────────────────────


def _resolve_claude_key(header_key: str | None) -> str | None:
    if header_key:
        return header_key
    return os.environ.get("ANTHROPIC_API_KEY")


@router.get("/capabilities")
def api_capabilities() -> dict:
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
    api_key = _resolve_claude_key(x_claude_key)
    prompt = req.message
    if req.context:
        prompt = f"Song context:\n{req.context}\n\n{req.message}"

    try:
        response = call_claude(prompt, api_key=api_key, system=req.system or None)
    except UnavailableError as e:
        raise HTTPException(503, str(e))

    return {"response": response.text}

"""REST API endpoints backed by the database."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from songmaker_cli.claude.provider import (
    UnavailableError,
    call_claude,
    is_available,
)
from songmaker_cli.config import (
    find_project_root,
    load_generation_defaults,
    save_generation_defaults,
)
from songmaker_cli.constants import OUTPUT_ROOT
from songmaker_cli.db.engine import get_session_factory
from songmaker_cli.db.queries import (
    album_to_dict,
    cleanup_album,
    create_job,
    create_song,
    delete_generation,
    delete_version,
    generation_to_dict,
    get_album,
    get_generation,
    get_generation_by_path,
    get_job,
    get_song,
    job_to_dict,
    list_albums,
    list_songs,
    pick_generation,
    save_rating,
    song_to_dict,
    unpick_generation,
    update_song,
    version_to_dict,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _resolve_output_dir() -> Path:
    root = find_project_root(Path.cwd())
    return (root / OUTPUT_ROOT) if root else Path(OUTPUT_ROOT)


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
    generation_params: dict | None = None


_VALID_GEN_PARAM_KEYS = frozenset({
    "inference_steps", "guidance_scale", "shift",
    "think_mode", "lm_temperature", "infer_method",
})


def _validate_generation_params(params: dict | None) -> dict | None:
    if params is None:
        return None
    invalid = set(params.keys()) - _VALID_GEN_PARAM_KEYS
    if invalid:
        raise HTTPException(
            422, f"Unknown generation_params keys: {', '.join(sorted(invalid))}",
        )
    return params


class SongUpdateRequest(BaseModel):
    lyrics: str | None = None
    prompt: str | None = None
    bpm: int | None = None
    duration: int | None = None
    key: str | None = None
    generation_params: dict | None = None


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
    _validate_generation_params(req.generation_params)
    song = create_song(
        session, title=req.title, album_id=req.album_id,
        lyrics=req.lyrics, prompt=req.prompt, bpm=req.bpm,
        duration=req.duration, key=req.key, language=req.language,
        generation_params=req.generation_params,
    )
    session.commit()
    return song_to_dict(song)


@router.put("/songs/{song_id}")
def api_update_song(
    song_id: str, req: SongUpdateRequest, session: Session = Depends(_get_session),
) -> dict:
    _validate_generation_params(req.generation_params)
    kwargs: dict = dict(
        lyrics=req.lyrics, prompt=req.prompt,
        bpm=req.bpm, duration=req.duration, key=req.key,
    )
    if "generation_params" in req.model_fields_set:
        kwargs["generation_params"] = req.generation_params
    try:
        update_song(session, song_id, **kwargs)
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


# ── Versions (delete) ────────────────────────────────────────────────


@router.delete("/versions/{version_id}")
def api_delete_version(
    version_id: str,
    delete_generations: bool = Query(False),
    session: Session = Depends(_get_session),
) -> dict:
    try:
        delete_version(
            session, version_id,
            delete_generations=delete_generations,
            output_dir=_resolve_output_dir(),
        )
    except ValueError:
        raise HTTPException(404, "Version not found")
    session.commit()
    return {"status": "ok"}


# ── Generations ──────────────────────────────────────────────────────


@router.get("/generations/{gen_id}")
def api_get_generation(
    gen_id: str, session: Session = Depends(_get_session),
) -> dict:
    gen = get_generation(session, gen_id)
    if not gen:
        raise HTTPException(404, "Generation not found")
    return generation_to_dict(gen)


@router.delete("/generations/{gen_id}")
def api_delete_generation(
    gen_id: str, session: Session = Depends(_get_session),
) -> dict:
    try:
        delete_generation(session, gen_id, output_dir=_resolve_output_dir())
    except ValueError:
        raise HTTPException(404, "Generation not found")
    session.commit()
    return {"status": "ok"}


# ── Generation + Scoring ─────────────────────────────────────────────


class GenerateRequest(BaseModel):
    count: int = Field(1, ge=1, le=10)


class ScoreRequest(BaseModel):
    scorers: list[str] | None = None


@router.post("/songs/{song_id}/generate")
def api_generate_song(
    song_id: str,
    req: GenerateRequest,
    session: Session = Depends(_get_session),
) -> dict:
    song = get_song(session, song_id)
    if not song:
        raise HTTPException(404, "Song not found")
    version = song.latest_version
    if not version or not version.lyrics or not version.prompt:
        raise HTTPException(400, "Song needs lyrics and a style prompt before generating")

    job = create_job(session, "generate")
    session.commit()

    from songmaker_cli.gpu_queue import get_gpu_queue
    from songmaker_cli.jobs import run_generation_job

    get_gpu_queue().submit(
        job.id, "generate", run_generation_job,
        args=(job.id, song_id, version.id, req.count),
    )

    return job_to_dict(job)


@router.post("/generations/{gen_id}/score")
def api_score_generation(
    gen_id: str,
    req: ScoreRequest,
    session: Session = Depends(_get_session),
) -> dict:
    gen = get_generation(session, gen_id)
    if not gen:
        raise HTTPException(404, "Generation not found")

    job = create_job(session, "score")
    session.commit()

    from songmaker_cli.gpu_queue import get_gpu_queue
    from songmaker_cli.jobs import run_scoring_job

    get_gpu_queue().submit(
        job.id, "score", run_scoring_job,
        args=(job.id, gen_id, req.scorers),
    )

    return job_to_dict(job)


# ── Jobs ────────────────────────────────────────────────────────────


@router.get("/jobs/{job_id}")
def api_get_job(job_id: str, session: Session = Depends(_get_session)) -> dict:
    job = get_job(session, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job_to_dict(job)


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


# ── Pick ─────────────────────────────────────────────────────────────


@router.post("/generations/{gen_id}/pick")
def api_pick_generation(
    gen_id: str, session: Session = Depends(_get_session),
) -> dict:
    try:
        pick_generation(session, gen_id)
    except ValueError:
        raise HTTPException(404, "Generation not found")
    session.commit()
    return {"status": "ok"}


@router.post("/generations/{gen_id}/unpick")
def api_unpick_generation(
    gen_id: str, session: Session = Depends(_get_session),
) -> dict:
    try:
        unpick_generation(session, gen_id)
    except ValueError:
        raise HTTPException(404, "Generation not found")
    session.commit()
    return {"status": "ok"}


@router.post("/albums/{album_id}/cleanup")
def api_cleanup_album(
    album_id: str, session: Session = Depends(_get_session),
) -> dict:
    album = get_album(session, album_id)
    if not album:
        raise HTTPException(404, "Album not found")
    count = cleanup_album(session, album_id, output_dir=_resolve_output_dir())
    session.commit()
    return {"status": "ok", "deleted": count}


# ── Generation Defaults ──────────────────────────────────────────────


@router.get("/settings/generation-defaults")
def api_get_generation_defaults() -> dict:
    return load_generation_defaults()


class GenerationDefaultsRequest(BaseModel):
    turbo: dict | None = None
    sft: dict | None = None


@router.put("/settings/generation-defaults")
def api_set_generation_defaults(req: GenerationDefaultsRequest) -> dict:
    data: dict = {}
    if req.turbo is not None:
        data["turbo"] = req.turbo
    if req.sft is not None:
        data["sft"] = req.sft
    save_generation_defaults(data)
    return data


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

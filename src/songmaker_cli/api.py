"""REST API endpoints backed by the database."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from songmaker_cli.admin_api import router as admin_router
from songmaker_cli.api_models import (
    AlbumResponse,
    CapabilitiesResponse,
    ChatRequest,
    ChatResponse,
    CleanupResponse,
    GenerateRequest,
    GenerationDefaultsRequest,
    GenerationResponse,
    JobResponse,
    RateRequest,
    RateResponse,
    ScoreRequest,
    SongCreateRequest,
    SongResponse,
    SongUpdateRequest,
    StatusResponse,
    VersionResponse,
)
from songmaker_cli.auth import (
    GENERATION_RATE_LIMIT_USER,
    MAX_QUEUE_DEPTH,
    MAX_USER_ACTIVE_JOBS,
    RATE_LIMIT_WINDOW_SECONDS,
    ROLE_ADMIN,
    SCORING_RATE_LIMIT_USER,
)
from songmaker_cli.auth_api import router as auth_router
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
    cleanup_album,
    count_total_queued_jobs,
    count_user_active_jobs,
    count_user_jobs_in_window,
    create_job,
    create_song,
    delete_generation,
    delete_version,
    get_album,
    get_generation,
    get_generation_by_path,
    get_job,
    get_song,
    list_albums,
    list_songs,
    pick_generation,
    save_rating,
    unpick_generation,
    update_song,
)
from songmaker_cli.gpu_queue import get_gpu_queue
from songmaker_cli.jobs import run_generation_job, run_scoring_job
from songmaker_cli.middleware import AuthenticatedUser

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")
router.include_router(auth_router)
router.include_router(admin_router)


_cached_output_dir: Path | None = None


def _resolve_output_dir() -> Path:
    global _cached_output_dir
    if _cached_output_dir is None:
        root = find_project_root(Path.cwd())
        _cached_output_dir = (root / OUTPUT_ROOT) if root else Path(OUTPUT_ROOT)
    return _cached_output_dir


def _get_optional_user(request: Request) -> AuthenticatedUser | None:
    return getattr(request.state, "user", None)


def _check_rate_limit(
    session: Session, user: AuthenticatedUser | None, job_type: str,
) -> None:
    if not user or user.role == ROLE_ADMIN:
        return

    if count_total_queued_jobs(session) >= MAX_QUEUE_DEPTH:
        raise HTTPException(429, "Queue is full. Try again later.")

    if count_user_active_jobs(session, user.id) >= MAX_USER_ACTIVE_JOBS:
        raise HTTPException(429, "You already have an active job. Wait for it to finish.")

    limit = GENERATION_RATE_LIMIT_USER if job_type == "generate" else SCORING_RATE_LIMIT_USER
    count = count_user_jobs_in_window(session, user.id, job_type, RATE_LIMIT_WINDOW_SECONDS)
    if count >= limit:
        raise HTTPException(429, f"Rate limit reached ({limit}/{job_type}s per hour).")


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


_VALID_GEN_PARAM_KEYS = frozenset({
    "inference_steps", "guidance_scale", "shift",
    "think_mode", "lm_temperature", "lm_top_k", "lm_top_p",
    "lm_cfg_scale", "lm_negative_prompt", "infer_method", "batch_size",
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


# ── Albums ───────────────────────────────────────────────────────────


@router.get("/albums")
def api_list_albums(session: Session = Depends(_get_session)) -> list[AlbumResponse]:
    return [AlbumResponse.from_orm(a) for a in list_albums(session)]


@router.get("/albums/{album_id}")
def api_get_album(album_id: str, session: Session = Depends(_get_session)) -> AlbumResponse:
    album = get_album(session, album_id)
    if not album:
        raise HTTPException(404, "Album not found")
    return AlbumResponse.from_orm(album)


# ── Songs ────────────────────────────────────────────────────────────


@router.get("/songs")
def api_list_songs(
    album_id: str | None = Query(None),
    session: Session = Depends(_get_session),
) -> list[SongResponse]:
    return [SongResponse.from_orm(s) for s in list_songs(session, album_id=album_id)]


@router.get("/songs/{song_id}")
def api_get_song(song_id: str, session: Session = Depends(_get_session)) -> SongResponse:
    song = get_song(session, song_id)
    if not song:
        raise HTTPException(404, "Song not found")
    return SongResponse.from_orm(song)


@router.post("/songs")
def api_create_song(
    req: SongCreateRequest, session: Session = Depends(_get_session),
) -> SongResponse:
    log.debug("POST /songs: title='%s', album='%s'", req.title, req.album_id)
    _validate_generation_params(req.generation_params)
    song = create_song(
        session, title=req.title, album_id=req.album_id,
        lyrics=req.lyrics, prompt=req.prompt, bpm=req.bpm,
        duration=req.duration, key=req.key, language=req.language,
        generation_params=req.generation_params,
    )
    session.commit()
    return SongResponse.from_orm(song)


@router.put("/songs/{song_id}")
def api_update_song(
    song_id: str, req: SongUpdateRequest, session: Session = Depends(_get_session),
) -> SongResponse:
    log.debug("PUT /songs/%s: fields_set=%s", song_id, req.model_fields_set)
    _validate_generation_params(req.generation_params)
    kwargs: dict = dict(
        lyrics=req.lyrics, prompt=req.prompt,
        bpm=req.bpm, duration=req.duration, key=req.key,
    )
    if "generation_params" in req.model_fields_set:
        kwargs["generation_params"] = req.generation_params
    try:
        version = update_song(session, song_id, **kwargs)
    except ValueError:
        raise HTTPException(404, "Song not found")
    session.commit()
    return SongResponse.from_orm(version.song)


@router.get("/songs/{song_id}/versions")
def api_song_versions(
    song_id: str, session: Session = Depends(_get_session),
) -> list[VersionResponse]:
    song = get_song(session, song_id)
    if not song:
        raise HTTPException(404, "Song not found")
    return [VersionResponse.from_orm(v) for v in reversed(song.versions)]


# ── Versions (delete) ────────────────────────────────────────────────


@router.delete("/versions/{version_id}")
def api_delete_version(
    version_id: str,
    delete_generations: bool = Query(False),
    session: Session = Depends(_get_session),
) -> StatusResponse:
    try:
        delete_version(
            session, version_id,
            delete_generations=delete_generations,
            output_dir=_resolve_output_dir(),
        )
    except ValueError:
        raise HTTPException(404, "Version not found")
    session.commit()
    return StatusResponse()


# ── Generations ──────────────────────────────────────────────────────


@router.get("/generations/{gen_id}")
def api_get_generation(
    gen_id: str, session: Session = Depends(_get_session),
) -> GenerationResponse:
    gen = get_generation(session, gen_id)
    if not gen:
        raise HTTPException(404, "Generation not found")
    return GenerationResponse.from_orm(gen)


@router.delete("/generations/{gen_id}")
def api_delete_generation(
    gen_id: str, session: Session = Depends(_get_session),
) -> StatusResponse:
    try:
        delete_generation(session, gen_id, output_dir=_resolve_output_dir())
    except ValueError:
        raise HTTPException(404, "Generation not found")
    session.commit()
    return StatusResponse()


# ── Generation + Scoring ─────────────────────────────────────────────


@router.post("/songs/{song_id}/generate")
def api_generate_song(
    song_id: str,
    req: GenerateRequest,
    request: Request,
    session: Session = Depends(_get_session),
) -> JobResponse:
    user = _get_optional_user(request)
    _check_rate_limit(session, user, "generate")

    song = get_song(session, song_id)
    if not song:
        raise HTTPException(404, "Song not found")
    version = song.latest_version
    if not version or not version.lyrics or not version.prompt:
        raise HTTPException(400, "Song needs lyrics and a style prompt before generating")

    job = create_job(session, "generate", user_id=user.id if user else None)
    session.commit()
    log.info("Generate: song='%s', count=%d, job=%s", song.title, req.count, job.id)

    get_gpu_queue().submit(
        job.id, "generate", run_generation_job,
        args=(job.id, song_id, version.id, req.count),
    )

    return JobResponse.from_orm(job)


@router.post("/generations/{gen_id}/score")
def api_score_generation(
    gen_id: str,
    req: ScoreRequest,
    request: Request,
    session: Session = Depends(_get_session),
) -> JobResponse:
    user = _get_optional_user(request)
    _check_rate_limit(session, user, "score")

    gen = get_generation(session, gen_id)
    if not gen:
        raise HTTPException(404, "Generation not found")

    job = create_job(session, "score", user_id=user.id if user else None)
    session.commit()

    get_gpu_queue().submit(
        job.id, "score", run_scoring_job,
        args=(job.id, gen_id, req.scorers),
    )

    return JobResponse.from_orm(job)


# ── Jobs ────────────────────────────────────────────────────────────


@router.get("/jobs/{job_id}")
def api_get_job(job_id: str, session: Session = Depends(_get_session)) -> JobResponse:
    job = get_job(session, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return JobResponse.from_orm(job)


# ── Ratings ──────────────────────────────────────────────────────────


@router.post("/generations/{gen_id}/rate")
def api_rate_generation(
    gen_id: str, req: RateRequest, session: Session = Depends(_get_session),
) -> RateResponse:
    gen = get_generation(session, gen_id)
    if not gen:
        raise HTTPException(404, "Generation not found")
    save_rating(session, gen_id, req.rating, req.notes)
    session.commit()
    return RateResponse(generation_id=gen_id, rating=req.rating)


@router.post("/rate/{album}/{gen_name}")
def api_rate_by_path(
    album: str, gen_name: str, req: RateRequest,
    session: Session = Depends(_get_session),
) -> RateResponse:
    mp3_path = f"{album}/{gen_name}.mp3"
    gen = get_generation_by_path(session, mp3_path)
    if not gen:
        raise HTTPException(404, "Generation not found")
    save_rating(session, gen.id, req.rating, req.notes)
    session.commit()
    return RateResponse(generation=gen_name, rating=req.rating)


# ── Pick ─────────────────────────────────────────────────────────────


@router.post("/generations/{gen_id}/pick")
def api_pick_generation(
    gen_id: str, session: Session = Depends(_get_session),
) -> StatusResponse:
    try:
        pick_generation(session, gen_id)
    except ValueError:
        raise HTTPException(404, "Generation not found")
    session.commit()
    return StatusResponse()


@router.post("/generations/{gen_id}/unpick")
def api_unpick_generation(
    gen_id: str, session: Session = Depends(_get_session),
) -> StatusResponse:
    try:
        unpick_generation(session, gen_id)
    except ValueError:
        raise HTTPException(404, "Generation not found")
    session.commit()
    return StatusResponse()


@router.post("/albums/{album_id}/cleanup")
def api_cleanup_album(
    album_id: str, session: Session = Depends(_get_session),
) -> CleanupResponse:
    album = get_album(session, album_id)
    if not album:
        raise HTTPException(404, "Album not found")
    count = cleanup_album(session, album_id, output_dir=_resolve_output_dir())
    session.commit()
    return CleanupResponse(deleted=count)


# ── Generation Defaults ──────────────────────────────────────────────


@router.get("/settings/generation-defaults")
def api_get_generation_defaults() -> dict:
    return load_generation_defaults()


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
def api_capabilities() -> CapabilitiesResponse:
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    return CapabilitiesResponse(
        claude_api=bool(env_key),
        claude_cli=is_available(api_key=None),
        generation=True,
        scoring=True,
    )


# ── Claude chat ──────────────────────────────────────────────────────


@router.post("/chat")
def api_chat(
    req: ChatRequest,
    x_claude_key: str | None = Header(None),
) -> ChatResponse:
    api_key = _resolve_claude_key(x_claude_key)
    prompt = req.message
    if req.context:
        prompt = f"Song context:\n{req.context}\n\n{req.message}"

    try:
        response = call_claude(prompt, api_key=api_key, system=req.system or None)
    except UnavailableError as e:
        raise HTTPException(503, str(e))

    return ChatResponse(response=response.text)

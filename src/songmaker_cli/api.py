"""REST API endpoints backed by the database."""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from songmaker_cli.admin_api import router as admin_router
from songmaker_cli.api_models import (
    AlbumCreateRequest,
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
    SongSummaryResponse,
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
    get_output_dir,
    load_generation_defaults,
    save_generation_defaults,
)
from songmaker_cli.db.engine import get_db_session
from songmaker_cli.db.models import Album, Generation, Song
from songmaker_cli.db.queries import (
    cleanup_album,
    count_total_queued_jobs,
    count_user_active_jobs,
    count_user_jobs_in_window,
    create_album,
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
from songmaker_cli.middleware import AuthenticatedUser, require_admin

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")
router.include_router(auth_router)
router.include_router(admin_router)


def _resolve_output_dir() -> Path:
    return get_output_dir()


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


_get_session = get_db_session


_VALID_GEN_PARAM_KEYS = frozenset({
    "inference_steps", "guidance_scale", "shift",
    "think_mode", "lm_temperature", "lm_top_k", "lm_top_p",
    "lm_cfg_scale", "lm_negative_prompt", "infer_method", "batch_size",
})

_GEN_PARAM_STRING_KEYS = frozenset({"lm_negative_prompt", "infer_method", "think_mode"})
_GEN_PARAM_MAX_STRING_LENGTH = 2000

_GEN_PARAM_LIMITS: dict[str, tuple[float, float]] = {
    "inference_steps": (1, 200),
    "guidance_scale": (0, 50),
    "shift": (0, 100),
    "lm_temperature": (0, 5),
    "lm_top_k": (0, 1000),
    "lm_top_p": (0, 1),
    "lm_cfg_scale": (0, 50),
    "batch_size": (1, 8),
}


def _validate_generation_params(params: dict | None) -> dict | None:
    if params is None:
        return None
    invalid = set(params.keys()) - _VALID_GEN_PARAM_KEYS
    if invalid:
        raise HTTPException(
            422, f"Unknown generation_params keys: {', '.join(sorted(invalid))}",
        )
    for key, val in params.items():
        if key in _GEN_PARAM_STRING_KEYS:
            if not isinstance(val, str):
                raise HTTPException(422, f"{key} must be a string")
            if len(val) > _GEN_PARAM_MAX_STRING_LENGTH:
                raise HTTPException(
                    422, f"{key} exceeds max length ({_GEN_PARAM_MAX_STRING_LENGTH})",
                )
        elif key in _GEN_PARAM_LIMITS:
            if not isinstance(val, (int, float)):
                raise HTTPException(422, f"{key} must be a number")
            lo, hi = _GEN_PARAM_LIMITS[key]
            if val < lo or val > hi:
                raise HTTPException(422, f"{key}={val} out of range [{lo}, {hi}]")
    return params


# ── Albums ───────────────────────────────────────────────────────────


def _slugify(text: str) -> str:
    """Convert text to a filesystem-safe ASCII slug."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "untitled"


def _unique_album_id(session: Session, base_slug: str) -> str:
    """Return a unique album ID, appending -2, -3, etc. if needed."""
    candidate = base_slug
    counter = 1
    while get_album(session, candidate):
        counter += 1
        candidate = f"{base_slug}-{counter}"
    return candidate


def _owner_filter(user: AuthenticatedUser | None) -> str | None:
    if not user or user.role == ROLE_ADMIN:
        return None
    return user.id


def _check_album_access(album: Album | None, user: AuthenticatedUser | None) -> Album:
    if not album:
        raise HTTPException(404, "Album not found")
    if user and user.role != ROLE_ADMIN and album.created_by != user.id:
        raise HTTPException(404, "Album not found")
    return album


def _check_song_access(
    session: Session, song_id: str, user: AuthenticatedUser | None,
) -> Song:
    """Load a song and verify ownership. Returns the song or raises 404."""
    song = get_song(session, song_id)
    if not song:
        raise HTTPException(404, "Song not found")
    if user and user.role != ROLE_ADMIN:
        album = song.album
        if album and album.created_by != user.id:
            raise HTTPException(404, "Song not found")
    return song


def _check_generation_access(
    session: Session, gen_id: str, user: AuthenticatedUser | None,
) -> Generation:
    """Load a generation and verify ownership. Returns the generation or raises 404."""
    gen = get_generation(session, gen_id)
    if not gen:
        raise HTTPException(404, "Generation not found")
    if user and user.role != ROLE_ADMIN:
        album = gen.song.album if gen.song else None
        if album and album.created_by != user.id:
            raise HTTPException(404, "Generation not found")
    return gen


@router.get("/albums")
def api_list_albums(
    request: Request, session: Session = Depends(_get_session),
) -> list[AlbumResponse]:
    user = _get_optional_user(request)
    return [AlbumResponse.from_orm(a) for a in list_albums(session, user_id=_owner_filter(user))]


@router.get("/albums/{album_id}")
def api_get_album(
    album_id: str, request: Request, session: Session = Depends(_get_session),
) -> AlbumResponse:
    user = _get_optional_user(request)
    album = get_album(session, album_id)
    _check_album_access(album, user)
    return AlbumResponse.from_orm(album)


@router.post("/albums")
def api_create_album(
    request: Request,
    data: AlbumCreateRequest,
    session: Session = Depends(_get_session),
) -> AlbumResponse:
    user = _get_optional_user(request)
    title = data.title.strip()
    if not title:
        raise HTTPException(422, "Title is required")
    album_id = _unique_album_id(session, _slugify(title))
    try:
        album = create_album(
            session, album_id, title,
            artist=data.artist,
            created_by=user.id if user else None,
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, f"Album '{title}' already exists")
    return AlbumResponse.from_orm(album)


# ── Songs ────────────────────────────────────────────────────────────


@router.get("/songs")
def api_list_songs(
    request: Request,
    album_id: str | None = Query(None),
    session: Session = Depends(_get_session),
) -> list[SongSummaryResponse]:
    user = _get_optional_user(request)
    return [
        SongSummaryResponse.from_orm(s)
        for s in list_songs(session, album_id=album_id, user_id=_owner_filter(user), light=True)
    ]


@router.get("/songs/{song_id}")
def api_get_song(
    song_id: str, request: Request, session: Session = Depends(_get_session),
) -> SongResponse:
    user = _get_optional_user(request)
    song = get_song(session, song_id)
    if not song:
        raise HTTPException(404, "Song not found")
    if user and user.role != ROLE_ADMIN and song.album and song.album.created_by != user.id:
        raise HTTPException(404, "Song not found")
    return SongResponse.from_orm(song)


@router.post("/songs")
def api_create_song(
    req: SongCreateRequest, request: Request,
    session: Session = Depends(_get_session),
) -> SongResponse:
    user = _get_optional_user(request)
    album = get_album(session, req.album_id)
    _check_album_access(album, user)
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
    song_id: str, req: SongUpdateRequest, request: Request,
    session: Session = Depends(_get_session),
) -> SongResponse:
    user = _get_optional_user(request)
    _check_song_access(session, song_id, user)
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
    song_id: str, request: Request, session: Session = Depends(_get_session),
) -> list[VersionResponse]:
    user = _get_optional_user(request)
    song = _check_song_access(session, song_id, user)
    return [VersionResponse.from_orm(v) for v in reversed(song.versions)]


# ── Versions (delete) ────────────────────────────────────────────────


@router.delete("/versions/{version_id}")
def api_delete_version(
    version_id: str,
    request: Request,
    delete_generations: bool = Query(False),
    session: Session = Depends(_get_session),
) -> StatusResponse:
    from songmaker_cli.db.models import Version as VersionModel

    user = _get_optional_user(request)
    ver = session.query(VersionModel).filter_by(id=version_id).first()
    if not ver:
        raise HTTPException(404, "Version not found")
    _check_song_access(session, ver.song_id, user)
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
    gen_id: str, request: Request, session: Session = Depends(_get_session),
) -> GenerationResponse:
    user = _get_optional_user(request)
    gen = _check_generation_access(session, gen_id, user)
    return GenerationResponse.from_orm(gen)


@router.delete("/generations/{gen_id}")
def api_delete_generation(
    gen_id: str, request: Request, session: Session = Depends(_get_session),
) -> StatusResponse:
    user = _get_optional_user(request)
    _check_generation_access(session, gen_id, user)
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

    song = _check_song_access(session, song_id, user)
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

    _check_generation_access(session, gen_id, user)

    job = create_job(session, "score", user_id=user.id if user else None)
    session.commit()

    get_gpu_queue().submit(
        job.id, "score", run_scoring_job,
        args=(job.id, gen_id, req.scorers),
    )

    return JobResponse.from_orm(job)


# ── Jobs ────────────────────────────────────────────────────────────


@router.get("/jobs/{job_id}")
def api_get_job(
    job_id: str, request: Request, session: Session = Depends(_get_session),
) -> JobResponse:
    user = _get_optional_user(request)
    job = get_job(session, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if user and user.role != ROLE_ADMIN and job.user_id != user.id:
        raise HTTPException(404, "Job not found")
    return JobResponse.from_orm(job)


# ── Ratings ──────────────────────────────────────────────────────────


@router.post("/generations/{gen_id}/rate")
def api_rate_generation(
    gen_id: str, req: RateRequest, request: Request,
    session: Session = Depends(_get_session),
) -> RateResponse:
    user = _get_optional_user(request)
    _check_generation_access(session, gen_id, user)
    save_rating(session, gen_id, req.rating, req.notes)
    session.commit()
    return RateResponse(generation_id=gen_id, rating=req.rating)


@router.post("/rate/{album}/{gen_name}")
def api_rate_by_path(
    album: str, gen_name: str, req: RateRequest,
    request: Request,
    session: Session = Depends(_get_session),
) -> RateResponse:
    user = _get_optional_user(request)
    mp3_path = f"{album}/{gen_name}.mp3"
    gen = get_generation_by_path(session, mp3_path)
    if not gen:
        raise HTTPException(404, "Generation not found")
    _check_generation_access(session, gen.id, user)
    save_rating(session, gen.id, req.rating, req.notes)
    session.commit()
    return RateResponse(generation=gen_name, rating=req.rating)


# ── Pick ─────────────────────────────────────────────────────────────


@router.post("/generations/{gen_id}/pick")
def api_pick_generation(
    gen_id: str, request: Request, session: Session = Depends(_get_session),
) -> StatusResponse:
    user = _get_optional_user(request)
    _check_generation_access(session, gen_id, user)
    try:
        pick_generation(session, gen_id)
    except ValueError:
        raise HTTPException(404, "Generation not found")
    session.commit()
    return StatusResponse()


@router.post("/generations/{gen_id}/unpick")
def api_unpick_generation(
    gen_id: str, request: Request, session: Session = Depends(_get_session),
) -> StatusResponse:
    user = _get_optional_user(request)
    _check_generation_access(session, gen_id, user)
    try:
        unpick_generation(session, gen_id)
    except ValueError:
        raise HTTPException(404, "Generation not found")
    session.commit()
    return StatusResponse()


@router.post("/albums/{album_id}/cleanup")
def api_cleanup_album(
    album_id: str, request: Request, session: Session = Depends(_get_session),
) -> CleanupResponse:
    user = _get_optional_user(request)
    album = get_album(session, album_id)
    _check_album_access(album, user)
    count = cleanup_album(session, album_id, output_dir=_resolve_output_dir())
    session.commit()
    return CleanupResponse(deleted=count)


# ── Generation Defaults ──────────────────────────────────────────────


@router.get("/settings/generation-defaults")
def api_get_generation_defaults(
    _admin: AuthenticatedUser = Depends(require_admin),
) -> dict:
    return load_generation_defaults()


@router.put("/settings/generation-defaults")
def api_set_generation_defaults(
    req: GenerationDefaultsRequest,
    _admin: AuthenticatedUser = Depends(require_admin),
) -> dict:
    data: dict = {}
    if req.turbo is not None:
        data["turbo"] = req.turbo
    if req.sft is not None:
        data["sft"] = req.sft
    save_generation_defaults(data)
    return data


# ── Capabilities ─────────────────────────────────────────────────────


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
def api_chat(req: ChatRequest) -> ChatResponse:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    prompt = req.message
    if req.context:
        prompt = f"Song context:\n{req.context}\n\n{req.message}"

    try:
        response = call_claude(prompt, api_key=api_key, system=req.system or None)
    except UnavailableError as e:
        raise HTTPException(503, str(e))

    return ChatResponse(response=response.text)

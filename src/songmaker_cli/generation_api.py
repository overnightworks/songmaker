"""Generation, scoring, rating, pick, and job API endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import (
    check_generation_access,
    check_song_access,
    create_job_with_rate_limit,
)
from songmaker_cli.api_models import (
    GenerateRequest,
    GenerationResponse,
    JobResponse,
    RateRequest,
    RateResponse,
    ScoreRequest,
    StatusResponse,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.auth import ROLE_ADMIN
from songmaker_cli.db.queries import (
    delete_generation,
    get_generation_by_path,
    get_job,
    pick_generation,
    record_audit,
    save_rating,
    unpick_generation,
)
from songmaker_cli.middleware import AuthenticatedUser, get_current_user

log = logging.getLogger(__name__)

router = APIRouter()


# ── Generations ──────────────────────────────────────────────────────


@router.get("/generations/{gen_id}")
def api_get_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> GenerationResponse:
    gen = check_generation_access(session, gen_id, user)
    return GenerationResponse.from_orm(gen)


@router.delete("/generations/{gen_id}")
def api_delete_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> StatusResponse:
    check_generation_access(session, gen_id, user)
    try:
        delete_generation(session, gen_id, output_dir=ctx.output_dir)
    except ValueError:
        raise HTTPException(404, "Generation not found")
    record_audit(session, user.id, "delete", "generation", gen_id)
    session.commit()
    return StatusResponse()


# ── Generation + Scoring ─────────────────────────────────────────────


@router.post("/songs/{song_id}/generate")
async def api_generate_song(
    song_id: str,
    req: GenerateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> JobResponse:
    song = check_song_access(session, song_id, user)
    version = song.latest_version
    if not version or not version.lyrics or not version.prompt:
        raise HTTPException(400, "Song needs lyrics and a style prompt before generating")

    if req.model:
        from songmaker_cli.arq_pool import get_active_model
        active = await get_active_model()
        if active is None:
            raise HTTPException(503, "ACE-Step server not available")
        if req.model != active:
            raise HTTPException(409, f"Model '{req.model}' not available, active: '{active}'")

    job = create_job_with_rate_limit(session, user, "generate")
    record_audit(session, user.id, "generate", "song", song_id, f"count={req.count}")
    session.commit()
    log.info("Generate: song='%s', count=%d, job=%s", song.title, req.count, job.id)

    try:
        from songmaker_cli.arq_pool import get_arq_pool
        pool = get_arq_pool()
        await pool.enqueue_job("generate", job.id, song_id, version.id, req.count, user.id)
    except ConnectionError:
        raise HTTPException(503, "Job queue unavailable")

    return JobResponse.from_orm(job)


@router.post("/generations/{gen_id}/score")
async def api_score_generation(
    gen_id: str,
    req: ScoreRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> JobResponse:
    check_generation_access(session, gen_id, user)

    job = create_job_with_rate_limit(session, user, "score")
    record_audit(session, user.id, "score", "generation", gen_id)
    session.commit()

    try:
        from songmaker_cli.arq_pool import get_arq_pool
        await get_arq_pool().enqueue_job("score", job.id, gen_id, req.scorers)
    except ConnectionError:
        raise HTTPException(503, "Job queue unavailable")

    return JobResponse.from_orm(job)


# ── Jobs ────────────────────────────────────────────────────────────


@router.get("/jobs/{job_id}")
def api_get_job(
    job_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> JobResponse:
    job = get_job(session, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if user.role != ROLE_ADMIN and job.user_id != user.id:
        raise HTTPException(404, "Job not found")
    return JobResponse.from_orm(job)


# ── Ratings ──────────────────────────────────────────────────────────


@router.post("/generations/{gen_id}/rate")
def api_rate_generation(
    gen_id: str, req: RateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> RateResponse:
    check_generation_access(session, gen_id, user)
    save_rating(session, gen_id, req.rating, req.notes)
    session.commit()
    return RateResponse(generation_id=gen_id, rating=req.rating)


@router.post("/rate/{album}/{gen_name}")
def api_rate_by_path(
    album: str, gen_name: str, req: RateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> RateResponse:
    if ".." in album or ".." in gen_name or "/" in album or "/" in gen_name:
        raise HTTPException(400, "Invalid path")
    mp3_path = f"{album}/{gen_name}.mp3"
    gen = get_generation_by_path(session, mp3_path)
    if not gen:
        raise HTTPException(404, "Generation not found")
    check_generation_access(session, gen.id, user)
    save_rating(session, gen.id, req.rating, req.notes)
    session.commit()
    return RateResponse(generation=gen_name, rating=req.rating)


# ── Pick ─────────────────────────────────────────────────────────────


@router.post("/generations/{gen_id}/pick")
def api_pick_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    check_generation_access(session, gen_id, user)
    try:
        pick_generation(session, gen_id)
    except ValueError:
        raise HTTPException(404, "Generation not found")
    session.commit()
    return StatusResponse()


@router.post("/generations/{gen_id}/unpick")
def api_unpick_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    check_generation_access(session, gen_id, user)
    try:
        unpick_generation(session, gen_id)
    except ValueError:
        raise HTTPException(404, "Generation not found")
    session.commit()
    return StatusResponse()

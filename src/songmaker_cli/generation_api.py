"""Generation, scoring, rating, pick, and job API endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import (
    check_generation_access,
    check_redis_health,
    check_song_access,
    cleanup_generation_files,
    create_job_with_rate_limit,
)
from songmaker_cli.api_models import (
    GenerateRequest,
    GenerationResponse,
    JobResponse,
    RateRequest,
    RateResponse,
    ScoreRequest,
    ShareResponse,
    StatusResponse,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.arq_pool import get_active_model, get_arq_pool, is_worker_healthy
from songmaker_cli.auth import ROLE_ADMIN
from songmaker_cli.db.models import Job
from songmaker_cli.db.queries import (
    delete_generation,
    disable_generation_sharing,
    enable_generation_sharing,
    get_job,
    keep_generation,
    pick_generation,
    record_audit,
    save_rating,
    unkeep_generation,
    unpick_generation,
    update_job_status,
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
        paths = delete_generation(session, gen_id)
    except ValueError:
        raise HTTPException(404, "Generation not found")
    record_audit(session, user.id, "delete", "generation", gen_id)
    session.commit()
    cleanup_generation_files(ctx.audio_dir, paths)
    return StatusResponse()


# ── Generation + Scoring ─────────────────────────────────────────────


@router.post("/songs/{song_id}/generate")
async def api_generate_song(
    song_id: str,
    req: GenerateRequest,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> JobResponse:
    check_redis_health(request)
    song = check_song_access(session, song_id, user)
    if req.version_id:
        version = next((v for v in song.versions if v.id == req.version_id), None)
        if not version:
            raise HTTPException(404, "Version not found")
    else:
        version = song.latest_version
    if not version or not version.lyrics or not version.prompt:
        raise HTTPException(400, "Song needs lyrics and a style prompt before generating")

    if req.model:
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
        pool = get_arq_pool()
        if not await is_worker_healthy():
            _fail_job(ctx, job.id)
            raise HTTPException(503, "Worker not running")
        await pool.enqueue_job("generate", job.id, song_id, version.id, req.count, user.id)
    except ConnectionError:
        _fail_job(ctx, job.id)
        raise HTTPException(503, "Job queue unavailable")

    return JobResponse.from_orm(job)


@router.post("/generations/{gen_id}/score")
async def api_score_generation(
    gen_id: str,
    req: ScoreRequest,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> JobResponse:
    check_redis_health(request)
    check_generation_access(session, gen_id, user)

    job = create_job_with_rate_limit(session, user, "score")
    record_audit(session, user.id, "score", "generation", gen_id)
    session.commit()

    try:
        if not await is_worker_healthy():
            _fail_job(ctx, job.id)
            raise HTTPException(503, "Worker not running")
        await get_arq_pool().enqueue_job("score", job.id, gen_id, req.scorers)
    except ConnectionError:
        _fail_job(ctx, job.id)
        raise HTTPException(503, "Job queue unavailable")

    return JobResponse.from_orm(job)


# ── Jobs ────────────────────────────────────────────────────────────


@router.get("/jobs/{job_id}")
def api_get_job(
    job_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> JobResponse:
    job = _check_job_access(session, job_id, user)
    return JobResponse.from_orm(job)


@router.post("/jobs/{job_id}/cancel")
def api_cancel_job(
    job_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> JobResponse:
    job = _check_job_access(session, job_id, user)
    if job.status not in ("queued", "running"):
        raise HTTPException(409, "Only queued or running jobs can be cancelled")
    update_job_status(session, job_id, "cancelled")
    record_audit(session, user.id, "cancel", "job", job_id)
    session.commit()
    job = get_job(session, job_id)
    return JobResponse.from_orm(job)


def _check_job_access(session: Session, job_id: str, user: AuthenticatedUser) -> Job:
    job = get_job(session, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if user.role != ROLE_ADMIN and job.user_id != user.id:
        raise HTTPException(404, "Job not found")
    return job


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


@router.post("/generations/{gen_id}/keep")
def api_keep_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    check_generation_access(session, gen_id, user)
    try:
        keep_generation(session, gen_id)
    except ValueError:
        raise HTTPException(404, "Generation not found")
    session.commit()
    return StatusResponse()


@router.post("/generations/{gen_id}/unkeep")
def api_unkeep_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    check_generation_access(session, gen_id, user)
    try:
        unkeep_generation(session, gen_id)
    except ValueError:
        raise HTTPException(404, "Generation not found")
    session.commit()
    return StatusResponse()


@router.post("/generations/{gen_id}/share")
def api_share_generation(
    gen_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ShareResponse:
    check_generation_access(session, gen_id, user)
    try:
        gen = enable_generation_sharing(session, gen_id)
    except ValueError:
        raise HTTPException(404, "Generation not found")
    record_audit(session, user.id, "share", "generation", gen_id)
    session.commit()
    base_url = str(request.base_url).rstrip("/")
    return ShareResponse(
        share_url=f"{base_url}/share/gen/{gen.share_slug}",
        share_slug=gen.share_slug,
    )


@router.delete("/generations/{gen_id}/share")
def api_unshare_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    check_generation_access(session, gen_id, user)
    try:
        disable_generation_sharing(session, gen_id)
    except ValueError:
        raise HTTPException(404, "Generation not found")
    record_audit(session, user.id, "unshare", "generation", gen_id)
    session.commit()
    return StatusResponse()


def _fail_job(ctx: AppContext, job_id: str) -> None:
    try:
        with ctx.db() as session:
            update_job_status(session, job_id, "failed", error="Job queue unavailable")
            session.commit()
    except Exception:
        log.warning("Failed to mark job %s as failed after enqueue error", job_id)

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
from songmaker_cli.auth import ROLE_ADMIN
from songmaker_cli.config import get_output_dir
from songmaker_cli.db.engine import get_db_session
from songmaker_cli.db.queries import (
    delete_generation,
    get_generation_by_path,
    get_job,
    pick_generation,
    record_audit,
    save_rating,
    unpick_generation,
)
from songmaker_cli.gpu_queue import get_gpu_queue
from songmaker_cli.jobs import run_generation_job, run_scoring_job
from songmaker_cli.middleware import AuthenticatedUser, get_current_user

log = logging.getLogger(__name__)

router = APIRouter()

_get_session = get_db_session


# ── Generations ──────────────────────────────────────────────────────


@router.get("/generations/{gen_id}")
def api_get_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(_get_session),
) -> GenerationResponse:
    gen = check_generation_access(session, gen_id, user)
    return GenerationResponse.from_orm(gen)


@router.delete("/generations/{gen_id}")
def api_delete_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(_get_session),
) -> StatusResponse:
    check_generation_access(session, gen_id, user)
    try:
        delete_generation(session, gen_id, output_dir=get_output_dir())
    except ValueError:
        raise HTTPException(404, "Generation not found")
    record_audit(session, user.id, "delete", "generation", gen_id)
    session.commit()
    return StatusResponse()


# ── Generation + Scoring ─────────────────────────────────────────────


@router.post("/songs/{song_id}/generate")
def api_generate_song(
    song_id: str,
    req: GenerateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(_get_session),
) -> JobResponse:
    song = check_song_access(session, song_id, user)
    version = song.latest_version
    if not version or not version.lyrics or not version.prompt:
        raise HTTPException(400, "Song needs lyrics and a style prompt before generating")

    job = create_job_with_rate_limit(session, user, "generate")
    record_audit(session, user.id, "generate", "song", song_id, f"count={req.count}")
    session.commit()
    log.info("Generate: song='%s', count=%d, job=%s", song.title, req.count, job.id)

    get_gpu_queue().submit(
        job.id, "generate", run_generation_job,
        args=(job.id, song_id, version.id, req.count, user.id),
    )

    return JobResponse.from_orm(job)


@router.post("/generations/{gen_id}/score")
def api_score_generation(
    gen_id: str,
    req: ScoreRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(_get_session),
) -> JobResponse:
    check_generation_access(session, gen_id, user)

    job = create_job_with_rate_limit(session, user, "score")
    record_audit(session, user.id, "score", "generation", gen_id)
    session.commit()

    get_gpu_queue().submit(
        job.id, "score", run_scoring_job,
        args=(job.id, gen_id, req.scorers),
    )

    return JobResponse.from_orm(job)


# ── Jobs ────────────────────────────────────────────────────────────


@router.get("/jobs/{job_id}")
def api_get_job(
    job_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(_get_session),
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
    session: Session = Depends(_get_session),
) -> RateResponse:
    check_generation_access(session, gen_id, user)
    save_rating(session, gen_id, req.rating, req.notes)
    session.commit()
    return RateResponse(generation_id=gen_id, rating=req.rating)


@router.post("/rate/{album}/{gen_name}")
def api_rate_by_path(
    album: str, gen_name: str, req: RateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(_get_session),
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
    session: Session = Depends(_get_session),
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
    session: Session = Depends(_get_session),
) -> StatusResponse:
    check_generation_access(session, gen_id, user)
    try:
        unpick_generation(session, gen_id)
    except ValueError:
        raise HTTPException(404, "Generation not found")
    session.commit()
    return StatusResponse()

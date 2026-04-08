"""Generation, scoring, rating, pick, and job API endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import uuid
from collections.abc import AsyncGenerator, Callable
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from songmaker_cli.acestep_state import read_worker_state
from songmaker_cli.api_helpers import (
    check_generation_access,
    check_redis_health,
    check_song_access,
    cleanup_generation_files,
    create_job_with_rate_limit,
)
from songmaker_cli.api_models import (
    BulkDeleteRequest,
    BulkDeleteResponse,
    CoverRequest,
    GenerateRequest,
    GenerationResponse,
    JobResponse,
    RateRequest,
    RateResponse,
    RepaintRequest,
    ScoreRequest,
    ShareResponse,
    StatusResponse,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.arq_pool import (
    get_arq_pool,
    is_music_worker_healthy,
    is_scoring_worker_healthy,
)
from songmaker_cli.auth import ROLE_ADMIN
from songmaker_cli.constants import (
    ARQ_MUSIC_QUEUE_NAME,
    ARQ_SCORING_QUEUE_NAME,
    JOB_ACTIVE_STATUSES,
    JOB_TERMINAL_STATUSES,
    SSE_POLL_INTERVAL_SECONDS,
    AuditAction,
    JobStatus,
    JobType,
    ResourceType,
)
from songmaker_cli.db.models import Generation, Job
from songmaker_cli.db.queries import (
    bulk_delete_generations,
    delete_generation,
    disable_generation_sharing,
    enable_generation_sharing,
    get_job,
    get_queue_position,
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


async def _has_online_acestep_worker(session: Session) -> bool:
    from songmaker_cli.db.queries import list_worker_identities

    pool = get_arq_pool()
    for w in list_worker_identities(session):
        if await read_worker_state(pool, w.id) is not None:
            return True
    return False


def _resolve_source_wav(audio_dir: Path, gen: Generation, session: Session) -> Path:
    if gen.wav_path:
        wav = audio_dir / gen.wav_path
        if wav.exists():
            return wav

    mp3 = audio_dir / gen.mp3_path
    if not mp3.exists():
        raise HTTPException(400, "Source generation has no audio file")

    wav = mp3.with_suffix(".wav")
    if not wav.exists():
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(mp3), str(wav)],
                check=True, capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            raise HTTPException(500, "Failed to convert MP3 to WAV") from exc

    wav_rel = str(wav.relative_to(audio_dir))
    gen.wav_path = wav_rel
    session.flush()

    return wav


# ── Reference audio upload ───────────────────────────────────────────


class ReferenceAudioResponse(BaseModel):
    path: str
    filename: str


@router.post("/audio/upload")
async def api_upload_reference_audio(
    file: UploadFile,
    user: AuthenticatedUser = Depends(get_current_user),
    ctx: AppContext = Depends(get_app_context),
) -> ReferenceAudioResponse:
    from songmaker_cli.constants import (
        REFERENCE_AUDIO_DIR,
        REFERENCE_AUDIO_EXTENSIONS,
        REFERENCE_AUDIO_MAX_BYTES,
    )

    if not file.filename:
        raise HTTPException(400, "No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in REFERENCE_AUDIO_EXTENSIONS:
        accepted = ", ".join(sorted(REFERENCE_AUDIO_EXTENSIONS))
        raise HTTPException(400, f"Unsupported format '{ext}'. Accepted: {accepted}")

    content = await file.read()
    if len(content) > REFERENCE_AUDIO_MAX_BYTES:
        max_mb = REFERENCE_AUDIO_MAX_BYTES // 1024 // 1024
        raise HTTPException(400, f"File too large (max {max_mb}MB)")
    if len(content) < 100:
        raise HTTPException(400, "File is empty or too small")

    ref_dir = ctx.audio_dir / user.id / REFERENCE_AUDIO_DIR
    ref_dir.mkdir(parents=True, exist_ok=True)
    file_id = str(uuid.uuid4())
    rel_path = f"{user.id}/{REFERENCE_AUDIO_DIR}/{file_id}{ext}"
    dest = ctx.audio_dir / rel_path
    dest.write_bytes(content)

    log.info("Reference audio uploaded: %s (%d bytes)", rel_path, len(content))
    return ReferenceAudioResponse(path=rel_path, filename=file.filename)


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
    record_audit(session, user.id, AuditAction.DELETE, ResourceType.GENERATION, gen_id)
    session.commit()
    cleanup_generation_files(ctx.audio_dir, paths)
    return StatusResponse()


@router.post("/generations/bulk-delete")
def api_bulk_delete_generations(
    req: BulkDeleteRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> BulkDeleteResponse:
    if not req.generation_ids:
        return BulkDeleteResponse(deleted=0)
    deduplicated_ids = list(set(req.generation_ids))
    try:
        count, paths = bulk_delete_generations(session, deduplicated_ids, user.id)
    except ValueError:
        raise HTTPException(404, "One or more generations not found")
    except PermissionError:
        raise HTTPException(404, "One or more generations not found")
    for gen_id in deduplicated_ids:
        record_audit(session, user.id, AuditAction.DELETE, ResourceType.GENERATION, gen_id)
    session.commit()
    cleanup_generation_files(ctx.audio_dir, paths)
    return BulkDeleteResponse(deleted=count)


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

    job = create_job_with_rate_limit(session, user, JobType.GENERATE)
    record_audit(
        session, user.id, AuditAction.GENERATE, ResourceType.SONG,
        song_id, f"count={req.count}",
    )
    session.commit()
    log.info("Generate: song='%s', count=%d, job=%s, model=%s",
             song.title, req.count, job.id, req.model)

    try:
        pool = get_arq_pool()
        if not await is_music_worker_healthy():
            _fail_job(ctx, job.id)
            raise HTTPException(503, "Worker not running")
        if not await _has_online_acestep_worker(session):
            _fail_job(ctx, job.id)
            raise HTTPException(503, "No online ACE-Step workers")
        await pool.enqueue_job(
            "generate", job.id, song_id, version.id, req.count, user.id, req.seed,
            req.model,
            _queue_name=ARQ_MUSIC_QUEUE_NAME,
        )
    except ConnectionError:
        _fail_job(ctx, job.id)
        raise HTTPException(503, "Job queue unavailable")

    return JobResponse.from_orm(job, queue_position=get_queue_position(session, job))


@router.post("/generations/{gen_id}/repaint")
async def api_repaint_generation(
    gen_id: str,
    req: RepaintRequest,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> JobResponse:
    check_redis_health(request)
    gen = check_generation_access(session, gen_id, user)
    song = gen.song

    if req.version_id:
        version = next((v for v in song.versions if v.id == req.version_id), None)
        if not version:
            raise HTTPException(404, "Version not found")
    else:
        version = gen.version

    if not version:
        raise HTTPException(400, "Generation has no linked version")

    if req.repainting_start >= req.repainting_end:
        raise HTTPException(400, "repainting_start must be less than repainting_end")

    wav_path = _resolve_source_wav(ctx.audio_dir, gen, session)

    lyrics = req.lyrics if req.lyrics is not None else version.lyrics
    prompt = req.prompt if req.prompt is not None else version.prompt

    job = create_job_with_rate_limit(session, user, JobType.GENERATE)
    record_audit(
        session, user.id, AuditAction.REPAINT, ResourceType.GENERATION, gen_id,
        f"range={req.repainting_start:.2f}-{req.repainting_end:.2f}",
    )
    session.commit()
    log.info("Repaint: gen=%s, range=%.2f-%.2f, job=%s",
             gen_id, req.repainting_start, req.repainting_end, job.id)

    try:
        pool = get_arq_pool()
        if not await is_music_worker_healthy():
            _fail_job(ctx, job.id)
            raise HTTPException(503, "Worker not running")
        if not await _has_online_acestep_worker(session):
            _fail_job(ctx, job.id)
            raise HTTPException(503, "No online ACE-Step workers")
        repaint_params: dict = {
            "src_wav_path": str(wav_path),
            "repainting_start": req.repainting_start,
            "repainting_end": req.repainting_end,
            "lyrics": lyrics,
            "prompt": prompt,
            "src_generation_id": gen_id,
        }
        if req.repaint_mode is not None:
            repaint_params["repaint_mode"] = req.repaint_mode
        if req.repaint_strength is not None:
            repaint_params["repaint_strength"] = req.repaint_strength
        if req.repaint_latent_crossfade_frames is not None:
            repaint_params["repaint_latent_crossfade_frames"] = req.repaint_latent_crossfade_frames
        if req.repaint_wav_crossfade_sec is not None:
            repaint_params["repaint_wav_crossfade_sec"] = req.repaint_wav_crossfade_sec
        await pool.enqueue_job(
            "generate", job.id, song.id, version.id, req.count, user.id,
            req.seed, req.model, repaint_params,
            _queue_name=ARQ_MUSIC_QUEUE_NAME,
        )
    except ConnectionError:
        _fail_job(ctx, job.id)
        raise HTTPException(503, "Job queue unavailable")

    return JobResponse.from_orm(job, queue_position=get_queue_position(session, job))


@router.post("/generations/{gen_id}/cover")
async def api_cover_generation(
    gen_id: str,
    req: CoverRequest,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> JobResponse:
    check_redis_health(request)
    gen = check_generation_access(session, gen_id, user)
    song = gen.song

    if req.version_id:
        version = next((v for v in song.versions if v.id == req.version_id), None)
        if not version:
            raise HTTPException(404, "Version not found")
    else:
        version = gen.version

    if not version:
        raise HTTPException(400, "Generation has no linked version")

    wav_path = _resolve_source_wav(ctx.audio_dir, gen, session)

    lyrics = req.lyrics if req.lyrics is not None else version.lyrics
    prompt = req.prompt if req.prompt is not None else version.prompt

    job = create_job_with_rate_limit(session, user, JobType.GENERATE)
    record_audit(
        session, user.id, AuditAction.COVER, ResourceType.GENERATION, gen_id,
        f"strength={req.audio_cover_strength:.2f}",
    )
    session.commit()
    log.info("Cover: gen=%s, strength=%.2f, job=%s",
             gen_id, req.audio_cover_strength, job.id)

    try:
        pool = get_arq_pool()
        if not await is_music_worker_healthy():
            _fail_job(ctx, job.id)
            raise HTTPException(503, "Worker not running")
        if not await _has_online_acestep_worker(session):
            _fail_job(ctx, job.id)
            raise HTTPException(503, "No online ACE-Step workers")
        cover_params: dict = {
            "src_wav_path": str(wav_path),
            "audio_cover_strength": req.audio_cover_strength,
            "lyrics": lyrics,
            "prompt": prompt,
            "src_generation_id": gen_id,
        }
        if req.cover_noise_strength is not None:
            cover_params["cover_noise_strength"] = req.cover_noise_strength
        await pool.enqueue_job(
            "generate", job.id, song.id, version.id, req.count, user.id,
            req.seed, req.model, None, cover_params,
            _queue_name=ARQ_MUSIC_QUEUE_NAME,
        )
    except ConnectionError:
        _fail_job(ctx, job.id)
        raise HTTPException(503, "Job queue unavailable")

    return JobResponse.from_orm(job, queue_position=get_queue_position(session, job))


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

    job = create_job_with_rate_limit(session, user, JobType.SCORE)
    record_audit(session, user.id, AuditAction.SCORE, ResourceType.GENERATION, gen_id)
    session.commit()

    try:
        if not await is_scoring_worker_healthy():
            _fail_job(ctx, job.id)
            raise HTTPException(503, "Worker not running")
        await get_arq_pool().enqueue_job(
            "score", job.id, gen_id, req.scorers,
            _queue_name=ARQ_SCORING_QUEUE_NAME,
        )
    except ConnectionError:
        _fail_job(ctx, job.id)
        raise HTTPException(503, "Job queue unavailable")

    return JobResponse.from_orm(job, queue_position=get_queue_position(session, job))


# ── Jobs ────────────────────────────────────────────────────────────


@router.get("/jobs/{job_id}")
def api_get_job(
    job_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> JobResponse:
    job = _check_job_access(session, job_id, user)
    return JobResponse.from_orm(job, queue_position=get_queue_position(session, job))


@router.get("/jobs/{job_id}/stream")
async def api_stream_job(
    job_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> StreamingResponse:
    _check_job_access(session, job_id, user)
    return StreamingResponse(
        _job_event_generator(ctx, job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _job_event_generator(ctx: AppContext, job_id: str) -> AsyncGenerator[str, None]:
    previous_status: str | None = None
    previous_progress: float | None = None
    try:
        while True:
            with ctx.db() as db_session:
                job = get_job(db_session, job_id)
                if not job:
                    return
                response = JobResponse.from_orm(job)

            status_changed = (
                response.status != previous_status
                or response.progress != previous_progress
            )
            if status_changed:
                previous_status = response.status
                previous_progress = response.progress
                yield f"data: {json.dumps(response.model_dump())}\n\n"

            if response.status in JOB_TERMINAL_STATUSES:
                return

            await asyncio.sleep(SSE_POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        return


@router.post("/jobs/{job_id}/cancel")
def api_cancel_job(
    job_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> JobResponse:
    job = _check_job_access(session, job_id, user)
    if job.status not in JOB_ACTIVE_STATUSES:
        raise HTTPException(409, "Only queued or running jobs can be cancelled")
    update_job_status(session, job_id, JobStatus.CANCELLED)
    record_audit(session, user.id, AuditAction.CANCEL, ResourceType.JOB, job_id)
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


def _toggle_generation(
    gen_id: str, user: AuthenticatedUser, session: Session,
    action: Callable[[Session, str], None],
) -> StatusResponse:
    check_generation_access(session, gen_id, user)
    try:
        action(session, gen_id)
    except ValueError:
        raise HTTPException(404, "Generation not found")
    session.commit()
    return StatusResponse()


@router.post("/generations/{gen_id}/pick")
def api_pick_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    return _toggle_generation(gen_id, user, session, pick_generation)


@router.post("/generations/{gen_id}/unpick")
def api_unpick_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    return _toggle_generation(gen_id, user, session, unpick_generation)


@router.post("/generations/{gen_id}/keep")
def api_keep_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    return _toggle_generation(gen_id, user, session, keep_generation)


@router.post("/generations/{gen_id}/unkeep")
def api_unkeep_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    return _toggle_generation(gen_id, user, session, unkeep_generation)


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
    record_audit(session, user.id, AuditAction.SHARE, ResourceType.GENERATION, gen_id)
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
    record_audit(session, user.id, AuditAction.UNSHARE, ResourceType.GENERATION, gen_id)
    session.commit()
    return StatusResponse()


def _fail_job(ctx: AppContext, job_id: str) -> None:
    try:
        with ctx.db() as session:
            update_job_status(session, job_id, JobStatus.FAILED, error="Job queue unavailable")
            session.commit()
    except Exception:
        log.error(
            "Failed to mark job %s as failed after enqueue error — "
            "job will remain in 'queued' until stale-job recovery picks it up",
            job_id, exc_info=True,
        )

"""Generation, scoring, rating, and pick API endpoints."""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Final

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from webauth.ports import AuthenticatedUser

from songmaker_cli.acestep_state import read_worker_state, worker_is_online
from songmaker_cli.api_helpers import (
    check_generation_access,
    check_generations_access,
    check_lora_ready_for_generation,
    check_song_access,
    cleanup_generation_files,
    create_job_with_rate_limit,
    resolve_public_base_url,
)
from songmaker_cli.api_models import (
    BulkDeleteRequest,
    BulkDeleteResponse,
    CoverRequest,
    CoverTaskParams,
    GenerateRequest,
    GenerationResponse,
    GenerationUnavailableResponse,
    JobResponse,
    LastFailedGenerationResponse,
    RateRequest,
    RateResponse,
    ReferenceAudioResponse,
    RepaintRequest,
    RepaintTaskParams,
    ScoreRequest,
    ScoringSchemaResponse,
    ShareResponse,
    StatusResponse,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.arq_pool import (
    get_arq_pool,
    is_music_worker_healthy,
    is_scoring_worker_healthy,
)
from songmaker_cli.auth_dependencies import get_current_user
from songmaker_cli.constants import (
    ARQ_MUSIC_QUEUE_NAME,
    ARQ_SCORING_QUEUE_NAME,
    AuditAction,
    JobFunction,
    JobStatus,
    JobType,
    ResourceType,
)
from songmaker_cli.db.models import Generation, Version
from songmaker_cli.db.queries.auth import record_audit
from songmaker_cli.db.queries.generations import (
    bulk_delete_generations,
    delete_generation,
    disable_generation_sharing,
    enable_generation_sharing,
    keep_generation,
    measure_generation_audio_duration,
    pick_generation,
    save_rating,
    unarchive_generation,
    unkeep_generation,
    unpick_generation,
)
from songmaker_cli.db.queries.jobs import (
    JobStatusUpdate,
    get_active_generate_job_for_song,
    get_last_generate_job_for_song,
    get_queue_position,
    update_job_status,
)
from songmaker_cli.db.queries.settings import list_active_models
from songmaker_cli.generation_params import BaseGenerationParams
from songmaker_cli.jobs.generation_failure import (
    generation_failure,
    is_visible_generation_failure,
    musician_job_response,
)
from songmaker_cli.scheduler import NO_ONLINE_ACESTEP_WORKERS_DETAIL, NoCapacityError
from songmaker_cli.settings import get_settings
from songmaker_cli.timestamps import aware_timestamp

log = logging.getLogger(__name__)

router = APIRouter()

GENERATION_NOT_FOUND_DETAIL: Final = "Generation not found"
WORKER_NOT_RUNNING_DETAIL: Final = "Worker not running"
JOB_QUEUE_UNAVAILABLE_DETAIL: Final = "Job queue unavailable"


def _check_model_active(session: Session, model: str) -> None:
    active_ids = {m.id for m in list_active_models(session)}
    if model not in active_ids:
        raise HTTPException(400, f"Model '{model}' is not currently available")


def _check_version_lora_ready(
    session: Session, version, user: AuthenticatedUser,
) -> None:
    params_dict = version.generation_params or {}
    try:
        params = BaseGenerationParams.model_validate(params_dict)
    except Exception:
        return
    check_lora_ready_for_generation(session, params.user_lora_id, user)


async def _has_online_acestep_worker(session: Session) -> bool:
    from songmaker_cli.db.queries.workers import list_worker_identities

    pool = get_arq_pool()
    for w in list_worker_identities(session):
        if worker_is_online(await read_worker_state(pool, w.id)):
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
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise HTTPException(503, "ffmpeg is not available")
        try:
            subprocess.run(
                [ffmpeg, "-y", "-i", str(mp3), str(wav)],
                check=True, capture_output=True,
            )
        except FileNotFoundError as exc:
            raise HTTPException(503, "ffmpeg is not available") from exc
        except subprocess.CalledProcessError as exc:
            raise HTTPException(500, "Failed to convert MP3 to WAV") from exc

    wav_rel = str(wav.relative_to(audio_dir))
    gen.wav_path = wav_rel
    session.flush()

    return wav


def _generation_version_or_error(gen: Generation, version_id: str | None) -> Version:
    if version_id:
        version = next((v for v in gen.song.versions if v.id == version_id), None)
        if not version:
            raise HTTPException(404, "Version not found")
    else:
        version = gen.version
    if not version:
        raise HTTPException(400, "Generation has no linked version")
    return version


# ── Reference audio upload ───────────────────────────────────────────


@router.post(
    "/audio/upload",
    responses={
        400: {"description": "Reference audio upload is invalid"},
        409: {"description": "Reference audio storage limit reached"},
        500: {"description": "Reference audio storage could not be checked"},
    },
)
async def api_upload_reference_audio(
    file: UploadFile,
    user: AuthenticatedUser = Depends(get_current_user),
    ctx: AppContext = Depends(get_app_context),
) -> ReferenceAudioResponse:
    from songmaker_cli.constants import (
        REFERENCE_AUDIO_EXTENSIONS,
        REFERENCE_AUDIO_MAX_BYTES,
    )
    from songmaker_cli.db.models import REFERENCE_FILENAME_MAX_LENGTH
    from songmaker_cli.reference_audio import (
        ReferenceAudioQuotaExceeded,
        ReferenceAudioStorageError,
        store_reference_audio,
    )

    if not file.filename:
        raise HTTPException(400, "No filename provided")

    original_filename = Path(file.filename).name
    if len(original_filename) > REFERENCE_FILENAME_MAX_LENGTH:
        raise HTTPException(
            400, f"Filename too long (max {REFERENCE_FILENAME_MAX_LENGTH} characters)",
        )
    ext = Path(original_filename).suffix.lower()
    if ext not in REFERENCE_AUDIO_EXTENSIONS:
        accepted = ", ".join(sorted(REFERENCE_AUDIO_EXTENSIONS))
        raise HTTPException(400, f"Unsupported format '{ext}'. Accepted: {accepted}")

    content = await file.read()
    if len(content) > REFERENCE_AUDIO_MAX_BYTES:
        max_mb = REFERENCE_AUDIO_MAX_BYTES // 1024 // 1024
        raise HTTPException(400, f"File too large (max {max_mb}MB)")
    if len(content) < 100:
        raise HTTPException(400, "File is empty or too small")

    try:
        stored = await run_in_threadpool(
            store_reference_audio,
            ctx.db,
            ctx.audio_dir,
            user.id,
            ext,
            content,
            get_settings(),
            original_filename,
        )
    except ReferenceAudioQuotaExceeded as exc:
        raise HTTPException(409, str(exc)) from exc
    except ReferenceAudioStorageError as exc:
        raise HTTPException(500, str(exc)) from exc

    return ReferenceAudioResponse(
        id=stored.id, path=stored.storage_path, filename=file.filename,
    )


# ── Generations ──────────────────────────────────────────────────────


@router.get("/generations/{gen_id}")
def api_get_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> GenerationResponse:
    gen = check_generation_access(session, gen_id, user)
    measure_generation_audio_duration(session, ctx.audio_dir, gen)
    session.commit()
    return GenerationResponse.from_orm(gen)


@router.delete(
    "/generations/{gen_id}",
    responses={404: {"description": "Generation does not exist"}},
)
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
        raise HTTPException(404, GENERATION_NOT_FOUND_DETAIL)
    record_audit(session, user.id, AuditAction.DELETE, ResourceType.GENERATION, gen_id)
    session.commit()
    cleanup_generation_files(ctx.audio_dir, paths)
    return StatusResponse()


@router.post(
    "/generations/bulk-delete",
    responses={404: {"description": "One or more generations do not exist"}},
)
def api_bulk_delete_generations(
    req: BulkDeleteRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> BulkDeleteResponse:
    if not req.generation_ids:
        return BulkDeleteResponse(deleted=0)
    deduplicated_ids = list(set(req.generation_ids))
    generations = check_generations_access(session, deduplicated_ids, user)
    paths = bulk_delete_generations(session, generations)
    for gen_id in deduplicated_ids:
        record_audit(session, user.id, AuditAction.DELETE, ResourceType.GENERATION, gen_id)
    session.commit()
    cleanup_generation_files(ctx.audio_dir, paths)
    return BulkDeleteResponse(deleted=len(generations))


# ── Generation + Scoring ─────────────────────────────────────────────


@router.post(
    "/songs/{song_id}/generate",
    response_model=JobResponse,
    responses={
        400: {"description": "Generation request is invalid"},
        404: {"description": "Version does not exist"},
        503: {"description": "Generation worker or job queue is unavailable"},
    },
)
async def api_generate_song(
    song_id: str,
    req: GenerateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> JobResponse | JSONResponse:
    song = check_song_access(session, song_id, user)
    if req.version_id:
        version = next((v for v in song.versions if v.id == req.version_id), None)
        if not version:
            raise HTTPException(404, "Version not found")
    else:
        version = song.latest_version
    if not version or not version.lyrics or not version.prompt:
        raise HTTPException(400, "Song needs lyrics and a style prompt before generating")

    _check_model_active(session, req.model)
    _check_version_lora_ready(session, version, user)

    job = create_job_with_rate_limit(
        session, user, JobType.GENERATE, song_id=song_id, redis=ctx.redis,
    )
    record_audit(
        session, user.id, AuditAction.GENERATE, ResourceType.SONG,
        song_id, f"count={req.count}",
    )
    session.commit()
    log.info("Generate: song='%s', count=%d, job=%s, model=%s",
             song.title, req.count, job.id, req.model)

    try:
        pool = get_arq_pool()
        rejection = await _generation_capacity_error(ctx, session, job.id)
        if rejection is not None:
            return rejection
        await pool.enqueue_job(
            JobFunction.GENERATE, job.id, song_id, version.id, req.count, user.id, req.seed,
            req.model,
            _queue_name=ARQ_MUSIC_QUEUE_NAME,
        )
    except ConnectionError:
        _fail_job(ctx, job.id)
        raise HTTPException(503, JOB_QUEUE_UNAVAILABLE_DETAIL)

    return JobResponse.from_orm(job, queue_position=get_queue_position(session, job))


@router.get("/songs/{song_id}/active-generation")
def api_active_generation(
    song_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> JobResponse | None:
    check_song_access(session, song_id, user)
    job = get_active_generate_job_for_song(session, song_id)
    if job is None:
        return None
    return JobResponse.from_orm(job, queue_position=get_queue_position(session, job))


@router.get("/songs/{song_id}/last-failed-generation")
def api_last_failed_generation(
    song_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> LastFailedGenerationResponse:
    """Recover the latest FAILED or typed OOM PARTIAL job after reload.

    Any newer attempt supersedes the failure. Only an unarchived take
    created strictly after completion hides it; the job's own saved takes
    remain available alongside its partial result. Historical jobs without
    a completion timestamp are not recoverable.
    """
    song = check_song_access(session, song_id, user)
    job = get_last_generate_job_for_song(session, song_id)
    if job is None or job.completed_at is None or not (
        job.status == JobStatus.FAILED
        or (job.status == JobStatus.PARTIAL and is_visible_generation_failure(job.error_type))
    ):
        return LastFailedGenerationResponse(job=None)
    newest_take = next((g for g in song.generations if not g.is_archived), None)
    if (
        newest_take is not None
        and aware_timestamp(newest_take.created_at) > aware_timestamp(job.completed_at)
    ):
        return LastFailedGenerationResponse(job=None)
    return LastFailedGenerationResponse(job=musician_job_response(job))


@router.post(
    "/generations/{gen_id}/repaint",
    response_model=JobResponse,
    responses={
        400: {"description": "Repaint request or source audio is invalid"},
        404: {"description": "Version does not exist"},
        500: {"description": "Source audio conversion failed"},
        503: {"description": "Generation worker or job queue is unavailable"},
    },
)
async def api_repaint_generation(
    gen_id: str,
    req: RepaintRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> JobResponse | JSONResponse:
    gen = check_generation_access(session, gen_id, user)
    song = gen.song

    version = _generation_version_or_error(gen, req.version_id)

    if req.repainting_start >= req.repainting_end:
        raise HTTPException(400, "repainting_start must be less than repainting_end")

    _check_model_active(session, req.model)
    _check_version_lora_ready(session, version, user)

    wav_path = _resolve_source_wav(ctx.audio_dir, gen, session)

    lyrics = req.lyrics if req.lyrics is not None else version.lyrics
    prompt = req.prompt if req.prompt is not None else version.prompt

    job = create_job_with_rate_limit(
        session, user, JobType.GENERATE, song_id=song.id, redis=ctx.redis,
    )
    record_audit(
        session, user.id, AuditAction.REPAINT, ResourceType.GENERATION, gen_id,
        f"range={req.repainting_start:.2f}-{req.repainting_end:.2f}",
    )
    session.commit()
    log.info("Repaint generation job enqueued")

    try:
        pool = get_arq_pool()
        rejection = await _generation_capacity_error(ctx, session, job.id)
        if rejection is not None:
            return rejection
        repaint_task = RepaintTaskParams(
            src_wav_path=str(wav_path),
            src_generation_id=gen_id,
            repainting_start=req.repainting_start,
            repainting_end=req.repainting_end,
            lyrics=lyrics,
            prompt=prompt,
            repaint_mode=req.repaint_mode,
            repaint_strength=req.repaint_strength,
            repaint_latent_crossfade_frames=req.repaint_latent_crossfade_frames,
            repaint_wav_crossfade_sec=req.repaint_wav_crossfade_sec,
        )
        await pool.enqueue_job(
            JobFunction.GENERATE, job.id, song.id, version.id, req.count, user.id,
            req.seed, req.model, repaint_task.model_dump(),
            _queue_name=ARQ_MUSIC_QUEUE_NAME,
        )
    except ConnectionError:
        _fail_job(ctx, job.id)
        raise HTTPException(503, JOB_QUEUE_UNAVAILABLE_DETAIL)

    return JobResponse.from_orm(job, queue_position=get_queue_position(session, job))


@router.post(
    "/generations/{gen_id}/cover",
    response_model=JobResponse,
    responses={
        400: {"description": "Cover request or source audio is invalid"},
        404: {"description": "Version does not exist"},
        500: {"description": "Source audio conversion failed"},
        503: {"description": "Generation worker or job queue is unavailable"},
    },
)
async def api_cover_generation(
    gen_id: str,
    req: CoverRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> JobResponse | JSONResponse:
    gen = check_generation_access(session, gen_id, user)
    song = gen.song

    version = _generation_version_or_error(gen, req.version_id)

    _check_model_active(session, req.model)
    _check_version_lora_ready(session, version, user)

    wav_path = _resolve_source_wav(ctx.audio_dir, gen, session)

    lyrics = req.lyrics if req.lyrics is not None else version.lyrics
    prompt = req.prompt if req.prompt is not None else version.prompt

    job = create_job_with_rate_limit(
        session, user, JobType.GENERATE, song_id=song.id, redis=ctx.redis,
    )
    record_audit(
        session, user.id, AuditAction.COVER, ResourceType.GENERATION, gen_id,
        f"strength={req.audio_cover_strength:.2f}",
    )
    session.commit()
    log.info("Cover generation job enqueued")

    try:
        pool = get_arq_pool()
        rejection = await _generation_capacity_error(ctx, session, job.id)
        if rejection is not None:
            return rejection
        cover_task = CoverTaskParams(
            src_wav_path=str(wav_path),
            src_generation_id=gen_id,
            audio_cover_strength=req.audio_cover_strength,
            lyrics=lyrics,
            prompt=prompt,
            cover_noise_strength=req.cover_noise_strength,
        )
        await pool.enqueue_job(
            JobFunction.GENERATE, job.id, song.id, version.id, req.count, user.id,
            req.seed, req.model, None, cover_task.model_dump(),
            _queue_name=ARQ_MUSIC_QUEUE_NAME,
        )
    except ConnectionError:
        _fail_job(ctx, job.id)
        raise HTTPException(503, JOB_QUEUE_UNAVAILABLE_DETAIL)

    return JobResponse.from_orm(job, queue_position=get_queue_position(session, job))


@router.get("/scoring/schema")
def api_scoring_schema() -> ScoringSchemaResponse:
    return ScoringSchemaResponse.from_registry()


@router.post(
    "/generations/{gen_id}/score",
    responses={503: {"description": "Scoring worker or job queue is unavailable"}},
)
async def api_score_generation(
    gen_id: str,
    req: ScoreRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> JobResponse:
    check_generation_access(session, gen_id, user)

    job = create_job_with_rate_limit(session, user, JobType.SCORE, redis=ctx.redis)
    record_audit(session, user.id, AuditAction.SCORE, ResourceType.GENERATION, gen_id)
    session.commit()

    try:
        if not await is_scoring_worker_healthy():
            _fail_job(ctx, job.id)
            raise HTTPException(503, WORKER_NOT_RUNNING_DETAIL)
        await get_arq_pool().enqueue_job(
            JobFunction.SCORE, job.id, gen_id, req.scorers,
            _queue_name=ARQ_SCORING_QUEUE_NAME,
        )
    except ConnectionError:
        _fail_job(ctx, job.id)
        raise HTTPException(503, JOB_QUEUE_UNAVAILABLE_DETAIL)

    return JobResponse.from_orm(job, queue_position=get_queue_position(session, job))


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
        raise HTTPException(404, GENERATION_NOT_FOUND_DETAIL)
    session.commit()
    return StatusResponse()


@router.post(
    "/generations/{gen_id}/pick",
    responses={404: {"description": "Generation does not exist"}},
)
def api_pick_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    return _toggle_generation(gen_id, user, session, pick_generation)


@router.post(
    "/generations/{gen_id}/unpick",
    responses={404: {"description": "Generation does not exist"}},
)
def api_unpick_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    return _toggle_generation(gen_id, user, session, unpick_generation)


@router.post(
    "/generations/{gen_id}/keep",
    responses={404: {"description": "Generation does not exist"}},
)
def api_keep_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    return _toggle_generation(gen_id, user, session, keep_generation)


@router.post(
    "/generations/{gen_id}/unkeep",
    responses={404: {"description": "Generation does not exist"}},
)
def api_unkeep_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    return _toggle_generation(gen_id, user, session, unkeep_generation)


@router.post(
    "/generations/{gen_id}/unarchive",
    responses={404: {"description": "Generation does not exist"}},
)
def api_unarchive_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    return _toggle_generation(gen_id, user, session, unarchive_generation)


@router.post(
    "/generations/{gen_id}/share",
    responses={404: {"description": "Generation does not exist"}},
)
def api_share_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ShareResponse:
    check_generation_access(session, gen_id, user)
    base_url = resolve_public_base_url()
    try:
        gen = enable_generation_sharing(session, gen_id)
    except ValueError:
        raise HTTPException(404, GENERATION_NOT_FOUND_DETAIL)
    record_audit(session, user.id, AuditAction.SHARE, ResourceType.GENERATION, gen_id)
    session.commit()
    return ShareResponse(
        share_url=f"{base_url}/share/gen/{gen.share_slug}",
        share_slug=gen.share_slug,
    )


@router.delete(
    "/generations/{gen_id}/share",
    responses={404: {"description": "Generation does not exist"}},
)
def api_unshare_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    check_generation_access(session, gen_id, user)
    try:
        disable_generation_sharing(session, gen_id)
    except ValueError:
        raise HTTPException(404, GENERATION_NOT_FOUND_DETAIL)
    record_audit(session, user.id, AuditAction.UNSHARE, ResourceType.GENERATION, gen_id)
    session.commit()
    return StatusResponse()


async def _generation_capacity_error(
    ctx: AppContext, session: Session, job_id: str,
) -> JSONResponse | None:
    try:
        if not await is_music_worker_healthy():
            raise NoCapacityError(WORKER_NOT_RUNNING_DETAIL)
        if not await _has_online_acestep_worker(session):
            raise NoCapacityError(NO_ONLINE_ACESTEP_WORKERS_DETAIL)
    except NoCapacityError as exc:
        failure = generation_failure(exc, job_id)
        _fail_job(ctx, job_id, error=failure.message, error_type=failure.error_type)
        response = GenerationUnavailableResponse(
            detail=failure.message, error_type=failure.error_type, job_id=job_id,
        )
        return JSONResponse(status_code=503, content=response.model_dump())
    return None


def _fail_job(
    ctx: AppContext,
    job_id: str,
    error: str = JOB_QUEUE_UNAVAILABLE_DETAIL,
    error_type: str | None = None,
) -> None:
    try:
        with ctx.db() as session:
            update_job_status(
                session,
                job_id,
                JobStatusUpdate(JobStatus.FAILED, error=error, error_type=error_type),
            )
            session.commit()
    except Exception:
        log.exception(
            "Failed to mark job %s as failed after enqueue error — "
            "job will remain in 'queued' until stale-job recovery picks it up",
            job_id,
        )

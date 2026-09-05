"""Generation, scoring, rating, and pick API endpoints."""

from __future__ import annotations

import logging
import shutil
import subprocess
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from songmaker_cli.acestep_state import read_worker_state, worker_is_online
from songmaker_cli.api_helpers import (
    check_generation_access,
    check_lora_ready_for_generation,
    check_redis_health,
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
    JobResponse,
    LastFailedGenerationResponse,
    RateRequest,
    RateResponse,
    RepaintRequest,
    RepaintTaskParams,
    ScoreRequest,
    ScoringSchemaResponse,
    ShareResponse,
    StatusResponse,
)
from songmaker_cli.api_models.generation_params import BaseGenerationParams
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.arq_pool import (
    get_arq_pool,
    is_music_worker_healthy,
    is_scoring_worker_healthy,
)
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
from songmaker_cli.db.queries import (
    bulk_delete_generations,
    delete_generation,
    disable_generation_sharing,
    enable_generation_sharing,
    get_last_generate_job_for_song,
    get_queue_position,
    keep_generation,
    list_active_models,
    measure_generation_audio_duration,
    pick_generation,
    record_audit,
    save_rating,
    unarchive_generation,
    unkeep_generation,
    unpick_generation,
    update_job_status,
)
from songmaker_cli.middleware import AuthenticatedUser, get_current_user

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


# Read verbatim by the frontend (ApiError.message -> addToast, issue #359) —
# never a component name like "No online ACE-Step workers".
NO_ONLINE_WORKER_DETAIL: Final = (
    "No worker can generate music right now. Check the worker pool."
)


async def _has_online_acestep_worker(session: Session) -> bool:
    from songmaker_cli.db.queries import list_worker_identities

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


class ReferenceAudioResponse(BaseModel):
    path: str
    filename: str


@router.post(
    "/audio/upload",
    responses={400: {"description": "Reference audio upload is invalid"}},
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
    from songmaker_cli.reference_audio import owner_reference_audio_root

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

    ref_dir = owner_reference_audio_root(ctx.audio_dir, user.id)
    ref_dir.mkdir(parents=True, exist_ok=True)
    file_id = str(uuid.uuid4())
    dest = ref_dir / f"{file_id}{ext}"
    rel_path = str(dest.relative_to(ctx.audio_dir))
    dest.write_bytes(content)

    log.info("Reference audio uploaded: %s (%d bytes)", rel_path, len(content))
    return ReferenceAudioResponse(path=rel_path, filename=file.filename)


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


@router.post(
    "/songs/{song_id}/generate",
    responses={
        400: {"description": "Generation request is invalid"},
        404: {"description": "Version does not exist"},
        503: {"description": "Generation worker or job queue is unavailable"},
    },
)
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
        if not await is_music_worker_healthy():
            _fail_job(ctx, job.id)
            raise HTTPException(503, WORKER_NOT_RUNNING_DETAIL)
        if not await _has_online_acestep_worker(session):
            _fail_job(ctx, job.id)
            raise HTTPException(503, NO_ONLINE_WORKER_DETAIL)
        await pool.enqueue_job(
            JobFunction.GENERATE, job.id, song_id, version.id, req.count, user.id, req.seed,
            req.model,
            _queue_name=ARQ_MUSIC_QUEUE_NAME,
        )
    except ConnectionError:
        _fail_job(ctx, job.id)
        raise HTTPException(503, JOB_QUEUE_UNAVAILABLE_DETAIL)

    return JobResponse.from_orm(job, queue_position=get_queue_position(session, job))


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


@router.get("/songs/{song_id}/last-failed-generation")
def api_last_failed_generation(
    song_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> LastFailedGenerationResponse:
    """Whether the song's last generate/repaint/cover job is a failure that
    is still the last word on the song's takes.

    A failed job leaving `activeJobs` is the only place the frontend learns
    of it live (see `jobs.ts`); this lets a page reload or a later visit
    recover the same cause. Two things supersede it: a newer job of any
    outcome (queued, running, or completed -- the failure is no longer the
    last attempt) and a non-archived take created after it (from an earlier
    successful attempt the failed job didn't replace).
    """
    song = check_song_access(session, song_id, user)
    job = get_last_generate_job_for_song(session, song_id)
    if job is None or job.status != JobStatus.FAILED or job.completed_at is None:
        return LastFailedGenerationResponse(job=None)
    newest_take = next((g for g in song.generations if not g.is_archived), None)
    if newest_take is not None and _as_utc(newest_take.created_at) >= _as_utc(job.completed_at):
        return LastFailedGenerationResponse(job=None)
    return LastFailedGenerationResponse(job=JobResponse.from_orm(job))


@router.post(
    "/generations/{gen_id}/repaint",
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
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> JobResponse:
    check_redis_health(request)
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
        if not await is_music_worker_healthy():
            _fail_job(ctx, job.id)
            raise HTTPException(503, WORKER_NOT_RUNNING_DETAIL)
        if not await _has_online_acestep_worker(session):
            _fail_job(ctx, job.id)
            raise HTTPException(503, NO_ONLINE_WORKER_DETAIL)
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
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> JobResponse:
    check_redis_health(request)
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
        if not await is_music_worker_healthy():
            _fail_job(ctx, job.id)
            raise HTTPException(503, WORKER_NOT_RUNNING_DETAIL)
        if not await _has_online_acestep_worker(session):
            _fail_job(ctx, job.id)
            raise HTTPException(503, NO_ONLINE_WORKER_DETAIL)
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
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> JobResponse:
    check_redis_health(request)
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


@router.post(
    "/generations/{gen_id}/remaster",
    responses={404: {"description": "Raw WAV does not exist for this generation"}},
)
def api_remaster_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> GenerationResponse:
    gen = check_generation_access(session, gen_id, user)

    raw_wav_path = Path(ctx.audio_dir) / gen.mp3_path.replace(".mp3", ".raw.wav")
    if not raw_wav_path.exists():
        raise HTTPException(404, "Raw WAV not found for this generation")

    import shutil

    from audio_engine import master_audio, read_wav_bytes, write_stereo_wav
    from audio_engine.audio_io import encode_mp3

    wav_path = Path(ctx.audio_dir) / gen.mp3_path.replace(".mp3", ".wav")
    mp3_path = Path(ctx.audio_dir) / gen.mp3_path
    pre_remaster_wav = Path(ctx.audio_dir) / gen.mp3_path.replace(".mp3", ".pre-remaster.wav")
    pre_remaster_mp3 = Path(ctx.audio_dir) / gen.mp3_path.replace(".mp3", ".pre-remaster.mp3")

    if wav_path.exists() and not pre_remaster_wav.exists():
        shutil.copy2(str(wav_path), str(pre_remaster_wav))
    if mp3_path.exists() and not pre_remaster_mp3.exists():
        shutil.copy2(str(mp3_path), str(pre_remaster_mp3))

    left, right, sample_rate = read_wav_bytes(raw_wav_path.read_bytes())
    mastered_left, mastered_right = master_audio(left, right, sample_rate=sample_rate)

    write_stereo_wav(str(wav_path), mastered_left, mastered_right, sample_rate)

    id3_metadata = {}
    if gen.song:
        id3_metadata["title"] = gen.song.title
        if gen.song.album:
            id3_metadata["artist"] = gen.song.album.artist
            id3_metadata["album"] = gen.song.album.title
    encode_mp3(
        mastered_left, mastered_right, str(mp3_path),
        sample_rate=sample_rate, metadata=id3_metadata,
    )

    record_audit(session, user.id, AuditAction.REMASTER, ResourceType.GENERATION, gen_id)
    session.commit()

    return GenerationResponse.from_orm(gen)


def _fail_job(ctx: AppContext, job_id: str) -> None:
    try:
        with ctx.db() as session:
            update_job_status(session, job_id, JobStatus.FAILED, error=JOB_QUEUE_UNAVAILABLE_DETAIL)
            session.commit()
    except Exception:
        log.exception(
            "Failed to mark job %s as failed after enqueue error — "
            "job will remain in 'queued' until stale-job recovery picks it up",
            job_id,
        )

"""User LoRA API endpoints — CRUD for adapters + audio samples + training kickoff."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Final

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import (
    check_lora_access,
    check_lora_sample_access,
    check_own_generation_access,
    lock_lora_capacity,
    raise_audio_file_http_error,
    unique_lora_slug_under_capacity_lock,
)
from songmaker_cli.api_models import (
    LoraCapacityErrorResponse,
    LoraCapacityReason,
    OwnPlayableTakeListResponse,
    OwnPlayableTakeResponse,
    StatusResponse,
    UserLoraCreateRequest,
    UserLoraListResponse,
    UserLoraResponse,
    UserLoraSampleFromGenerationRequest,
    UserLoraSamplePatchRequest,
    UserLoraSampleResponse,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.arq_pool import get_arq_pool
from songmaker_cli.audio_paths import AudioFileNotFoundError, resolve_audio_path
from songmaker_cli.constants import (
    ARQ_MUSIC_QUEUE_NAME,
    LORA_ACTIVE_STATUSES,
    USER_LORA_AUDIO_EXTENSIONS,
    USER_LORA_MAX_SAMPLES,
    USER_LORA_MIN_SAMPLES_FOR_TRAINING,
    USER_LORA_SAMPLE_MAX_BYTES,
    USER_LORA_SAMPLES_DIRNAME,
    USER_LORAS_DIRNAME,
    AuditAction,
    JobFunction,
    JobStatus,
    JobType,
    LoraStatus,
    ResourceType,
)
from songmaker_cli.db.queries import (
    add_user_lora_sample,
    count_active_user_loras,
    count_queued_lora_training_jobs,
    count_user_lora_samples,
    create_job,
    create_user_lora,
    delete_user_lora_sample,
    get_user_lora,
    get_user_lora_sample,
    list_own_playable_generations,
    list_user_loras_for_user,
    record_audit,
    soft_delete_user_lora,
    update_job_status,
    update_user_lora,
    update_user_lora_sample,
)
from songmaker_cli.db.queries.sharing import is_playable_take
from songmaker_cli.middleware import AuthenticatedUser, get_current_user
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)

router = APIRouter()

JOB_QUEUE_UNAVAILABLE_DETAIL: Final = "Job queue unavailable"


def _lora_capacity_error(
    detail: str, reason: LoraCapacityReason,
) -> JSONResponse:
    response = LoraCapacityErrorResponse(detail=detail, reason=reason)
    return JSONResponse(status_code=409, content=response.model_dump(mode="json"))


def _sample_dir(audio_dir: Path, user_id: str, lora_id: str) -> Path:
    return (
        audio_dir
        / USER_LORAS_DIRNAME
        / user_id
        / lora_id
        / USER_LORA_SAMPLES_DIRNAME
    )


def _reject_if_active_or_deleted(lora) -> None:
    if lora.deleted_at is not None:
        raise HTTPException(409, "LoRA is deleted")
    if lora.status in LORA_ACTIVE_STATUSES:
        raise HTTPException(409, f"LoRA is {lora.status} — cannot modify during training")


@router.post(
    "/loras",
    response_model=UserLoraResponse,
    responses={
        409: {
            "description": "LoRA capacity is unavailable",
            "model": LoraCapacityErrorResponse,
        },
        422: {"description": "LoRA request is invalid"},
    },
)
def api_create_lora(
    data: UserLoraCreateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> UserLoraResponse | JSONResponse:
    name = data.name.strip()
    if not name:
        raise HTTPException(422, "Name is required")
    lock_lora_capacity(session)
    max_user_loras = get_settings().max_user_loras
    if count_active_user_loras(session, user.id) >= max_user_loras:
        session.rollback()
        return _lora_capacity_error(
            "Could not create voice\n"
            f"You have reached the limit of {max_user_loras} voices. "
            "Delete a voice before creating another.",
            LoraCapacityReason.VOICE_LIMIT,
        )

    slug = unique_lora_slug_under_capacity_lock(session, user.id, name)
    try:
        lora = create_user_lora(session, user.id, name, slug)
        record_audit(session, user.id, AuditAction.CREATE, ResourceType.LORA, lora.id)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, f"LoRA slug conflict for '{name}'")
    return UserLoraResponse.from_orm(lora)


@router.get("/loras")
def api_list_loras(
    include_deleted: bool = False,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> UserLoraListResponse:
    loras = list_user_loras_for_user(
        session, user.id, include_deleted=include_deleted,
    )
    return UserLoraListResponse(
        loras=[UserLoraResponse.from_orm(lora) for lora in loras],
    )


@router.get("/loras/own-takes")
def api_list_own_playable_takes(
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> OwnPlayableTakeListResponse:
    takes = list_own_playable_generations(session, user.id)
    return OwnPlayableTakeListResponse(
        takes=[OwnPlayableTakeResponse.from_orm(take) for take in takes],
    )


@router.get("/loras/{lora_id}")
def api_get_lora(
    lora_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> UserLoraResponse:
    lora = get_user_lora(session, lora_id, include_deleted_rows=True)
    check_lora_access(lora, user)
    return UserLoraResponse.from_orm(lora)


@router.delete(
    "/loras/{lora_id}",
    responses={409: {"description": "LoRA cannot be deleted"}},
)
def api_delete_lora(
    lora_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    lora = get_user_lora(session, lora_id)
    check_lora_access(lora, user)
    if lora.status in LORA_ACTIVE_STATUSES:
        raise HTTPException(
            409, f"LoRA is {lora.status} — cannot delete during training",
        )
    soft_delete_user_lora(session, lora_id)
    record_audit(session, user.id, AuditAction.DELETE, ResourceType.LORA, lora_id)
    session.commit()
    return StatusResponse()


@router.post(
    "/loras/{lora_id}/samples/from-generation",
    responses={
        404: {"description": "Generation does not exist"},
        409: {"description": "LoRA cannot accept another sample"},
        422: {"description": "Generation cannot be used as a sample"},
    },
)
def api_add_sample_from_generation(
    lora_id: str,
    data: UserLoraSampleFromGenerationRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> UserLoraSampleResponse:
    lora = get_user_lora(session, lora_id, include_deleted_rows=True)
    check_lora_access(lora, user)
    _reject_if_active_or_deleted(lora)

    generation = check_own_generation_access(session, data.generation_id, user)
    if not is_playable_take(generation):
        raise HTTPException(422, "Generation is not playable")

    try:
        source = resolve_audio_path(ctx.audio_dir, generation.mp3_path)
    except AudioFileNotFoundError as exc:
        raise_audio_file_http_error(exc, public=False)
    if not source.is_file():
        raise HTTPException(404, "Generation not found")

    if count_user_lora_samples(session, lora_id) >= USER_LORA_MAX_SAMPLES:
        raise HTTPException(
            409, f"LoRA already has the maximum of {USER_LORA_MAX_SAMPLES} samples",
        )

    destination: Path | None = None
    try:
        sample = add_user_lora_sample(
            session,
            lora_id,
            "",
            caption=generation.version.prompt if generation.version else "",
            lyrics=generation.version.lyrics if generation.version else "",
        )
        relative_path = (
            Path(USER_LORAS_DIRNAME)
            / user.id / lora_id / USER_LORA_SAMPLES_DIRNAME
            / f"{sample.id}{source.suffix.lower()}"
        )
        sample.audio_path = str(relative_path)
        session.flush()

        destination = ctx.audio_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        session.commit()
    except Exception:
        session.rollback()
        if destination is not None:
            destination.unlink(missing_ok=True)
        raise

    return UserLoraSampleResponse.from_orm(sample)


@router.post(
    "/loras/{lora_id}/samples",
    responses={
        409: {"description": "LoRA cannot accept another sample"},
        413: {"description": "Sample file is too large"},
        422: {"description": "Sample upload is invalid"},
    },
)
async def api_add_sample(
    lora_id: str,
    caption: str = Form(...),
    lyrics: str = Form(...),
    position: int | None = Form(default=None),
    audio: UploadFile = File(...),
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> UserLoraSampleResponse:
    lora = get_user_lora(session, lora_id, include_deleted_rows=True)
    check_lora_access(lora, user)
    _reject_if_active_or_deleted(lora)

    caption_clean = caption.strip()
    lyrics_clean = lyrics.strip()
    if not caption_clean:
        raise HTTPException(422, "Caption is required")
    if not lyrics_clean:
        raise HTTPException(422, "Lyrics are required")

    filename = audio.filename or ""
    ext = Path(filename).suffix.lower()
    if ext not in USER_LORA_AUDIO_EXTENSIONS:
        accepted = ", ".join(sorted(USER_LORA_AUDIO_EXTENSIONS))
        raise HTTPException(
            422, f"Unsupported audio format '{ext}'. Accepted: {accepted}",
        )

    content = await audio.read()
    if len(content) > USER_LORA_SAMPLE_MAX_BYTES:
        max_mb = USER_LORA_SAMPLE_MAX_BYTES // 1024 // 1024
        raise HTTPException(413, f"Audio file too large (max {max_mb}MB)")
    if len(content) == 0:
        raise HTTPException(422, "Audio file is empty")

    if count_user_lora_samples(session, lora_id) >= USER_LORA_MAX_SAMPLES:
        raise HTTPException(
            409, f"LoRA already has the maximum of {USER_LORA_MAX_SAMPLES} samples",
        )

    pending_path = ""
    try:
        sample = add_user_lora_sample(
            session, lora_id, pending_path,
            caption=caption_clean, lyrics=lyrics_clean, position=position,
        )
        rel_path = str(
            Path(USER_LORAS_DIRNAME)
            / user.id / lora_id / USER_LORA_SAMPLES_DIRNAME / f"{sample.id}{ext}"
        )
        sample.audio_path = rel_path
        session.flush()

        dest_dir = _sample_dir(ctx.audio_dir, user.id, lora_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = ctx.audio_dir / rel_path
        dest.write_bytes(content)

        session.commit()
    except Exception:
        session.rollback()
        raise

    return UserLoraSampleResponse.from_orm(sample)


@router.patch(
    "/loras/{lora_id}/samples/{sample_id}",
    responses={
        404: {"description": "Sample does not exist"},
        409: {"description": "LoRA cannot be modified during training"},
        422: {"description": "Sample update is invalid"},
    },
)
def api_patch_sample(
    lora_id: str,
    sample_id: str,
    data: UserLoraSamplePatchRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> UserLoraSampleResponse:
    sample = get_user_lora_sample(session, sample_id)
    check_lora_sample_access(sample, user)
    if sample.user_lora_id != lora_id:
        raise HTTPException(404, "LoRA sample not found")
    _reject_if_active_or_deleted(sample.user_lora)

    caption = data.caption.strip() if data.caption is not None else None
    if data.caption is not None and not caption:
        raise HTTPException(422, "Caption cannot be empty")
    lyrics = data.lyrics.strip() if data.lyrics is not None else None
    if data.lyrics is not None and not lyrics:
        raise HTTPException(422, "Lyrics cannot be empty")

    updated = update_user_lora_sample(
        session, sample_id,
        caption=caption, lyrics=lyrics, position=data.position,
    )
    session.commit()
    return UserLoraSampleResponse.from_orm(updated)


@router.delete(
    "/loras/{lora_id}/samples/{sample_id}",
    responses={
        404: {"description": "Sample does not exist"},
        409: {"description": "LoRA cannot be modified during training"},
    },
)
def api_delete_sample(
    lora_id: str,
    sample_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> StatusResponse:
    sample = get_user_lora_sample(session, sample_id)
    check_lora_sample_access(sample, user)
    if sample.user_lora_id != lora_id:
        raise HTTPException(404, "LoRA sample not found")
    _reject_if_active_or_deleted(sample.user_lora)

    rel_path = delete_user_lora_sample(session, sample_id)
    session.commit()

    file_path = ctx.audio_dir / rel_path
    try:
        file_path.unlink(missing_ok=True)
    except OSError:
        log.warning("Failed to unlink LoRA sample file: %s", rel_path)

    return StatusResponse()


@router.post(
    "/loras/{lora_id}/train",
    response_model=UserLoraResponse,
    responses={
        409: {
            "description": "LoRA capacity is unavailable",
            "model": LoraCapacityErrorResponse,
        },
        422: {"description": "LoRA training request is invalid"},
        503: {"description": "Training worker or job queue is unavailable"},
    },
)
async def api_train_lora(
    lora_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> UserLoraResponse | JSONResponse:
    lora = get_user_lora(session, lora_id)
    check_lora_access(lora, user)

    lock_lora_capacity(session)
    lora = get_user_lora(session, lora_id)
    check_lora_access(lora, user)

    if lora.status in LORA_ACTIVE_STATUSES:
        raise HTTPException(
            409, f"LoRA is {lora.status} — already training",
        )

    samples = list(lora.samples or [])
    if len(samples) < USER_LORA_MIN_SAMPLES_FOR_TRAINING:
        raise HTTPException(
            422,
            f"At least {USER_LORA_MIN_SAMPLES_FOR_TRAINING} samples required "
            f"for training (have {len(samples)})",
        )
    for sample in samples:
        if not sample.caption.strip() or not sample.lyrics.strip():
            raise HTTPException(
                422,
                "All samples must have non-empty caption and lyrics before training",
            )

    max_queued_lora_training_jobs = get_settings().max_queued_lora_training_jobs
    if count_queued_lora_training_jobs(session) >= max_queued_lora_training_jobs:
        session.rollback()
        return _lora_capacity_error(
            "Training queue is full\n"
            f"{max_queued_lora_training_jobs} trainings are already waiting. "
            "Try again when one training starts or finishes.",
            LoraCapacityReason.TRAINING_QUEUE_FULL,
        )

    job = create_job(session, JobType.LORA_TRAINING, user_id=user.id)
    update_user_lora(
        session, lora_id,
        status=LoraStatus.QUEUED, training_job_id=job.id, clear_error=True,
    )
    record_audit(session, user.id, AuditAction.TRAIN_LORA, ResourceType.LORA, lora_id)
    session.commit()

    try:
        await get_arq_pool().enqueue_job(
            JobFunction.LORA_TRAINING, job.id, lora_id, user.id,
            _queue_name=ARQ_MUSIC_QUEUE_NAME,
        )
    except ConnectionError:
        _fail_training_job(ctx, job.id, lora_id)
        raise HTTPException(503, JOB_QUEUE_UNAVAILABLE_DETAIL)

    refreshed = get_user_lora(session, lora_id)
    return UserLoraResponse.from_orm(refreshed)


def _fail_training_job(ctx: AppContext, job_id: str, lora_id: str) -> None:
    try:
        with ctx.db() as session:
            update_job_status(
                session, job_id, JobStatus.FAILED, error=JOB_QUEUE_UNAVAILABLE_DETAIL,
            )
            update_user_lora(
                session, lora_id,
                status=LoraStatus.FAILED, error=JOB_QUEUE_UNAVAILABLE_DETAIL,
            )
            session.commit()
    except Exception:
        log.exception(
            "Failed to mark LoRA training job %s as failed after enqueue error",
            job_id,
        )

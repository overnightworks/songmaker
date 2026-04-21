"""LoRA training job runner — materialize dataset, dispatch to worker, persist."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis
from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.constants import (
    MODEL_DEFAULT_MODE,
    USER_LORA_DATASET_DIRNAME,
    USER_LORA_OUTPUT_DIRNAME,
    USER_LORAS_DIRNAME,
    AuditAction,
    JobStatus,
    JobType,
    LoraStatus,
    ResourceType,
)
from songmaker_cli.db.queries import (
    record_audit,
    update_user_lora,
)
from songmaker_cli.scheduler import (
    DispatchOptions,
    NoCapacityError,
    WorkerProtocolError,
    WorkerTaskFailed,
    _internal_headers,
    _iterate_task_events,
    pick_worker,
)

from ._runtime import _sanitize_error, _touch_heartbeat, _update_job

log = logging.getLogger(__name__)

_LORA_PROGRESS_THROTTLE_SECONDS = 2.0
_LORA_SUBMIT_TIMEOUT_SECONDS = 30.0


class TrainLoraTaskResultDTO(BaseModel):
    mode: str
    adapter_dir: str
    num_samples: int = 0
    final_loss: float | None = None


@dataclass
class _WorkerHandle:
    base_url: str
    id: str


ProgressCallback = Callable[[float], Awaitable[None] | None]
HeartbeatCallback = Callable[[], Awaitable[None] | None]


def _lora_root(audio_dir: Path, user_id: str, lora_id: str) -> Path:
    return audio_dir / USER_LORAS_DIRNAME / user_id / lora_id


def _dataset_dir(audio_dir: Path, user_id: str, lora_id: str) -> Path:
    return _lora_root(audio_dir, user_id, lora_id) / USER_LORA_DATASET_DIRNAME


def _output_dir(audio_dir: Path, user_id: str, lora_id: str) -> Path:
    return _lora_root(audio_dir, user_id, lora_id) / USER_LORA_OUTPUT_DIRNAME


def _tmp_training_dir(audio_dir: Path, user_id: str, lora_id: str) -> Path:
    return _lora_root(audio_dir, user_id, lora_id) / "training_tmp"


def _materialize_dataset(
    *, audio_dir: Path, user_id: str, lora_id: str, samples: list,
) -> Path:
    dataset_dir = _dataset_dir(audio_dir, user_id, lora_id)
    if dataset_dir.exists():
        shutil.rmtree(dataset_dir)
    dataset_dir.mkdir(parents=True, exist_ok=True)

    for sample in samples:
        src = (audio_dir / sample.audio_path).resolve()
        if not src.exists():
            raise FileNotFoundError(f"Missing LoRA sample audio: {sample.audio_path}")
        ext = Path(sample.audio_path).suffix or ".wav"
        base = sample.id
        dst_audio = dataset_dir / f"{base}{ext}"
        try:
            os.symlink(src, dst_audio)
        except (OSError, NotImplementedError):
            shutil.copy2(src, dst_audio)
        (dataset_dir / f"{base}.caption.txt").write_text(
            sample.caption.strip() + "\n", encoding="utf-8",
        )
        (dataset_dir / f"{base}.lyrics.txt").write_text(
            sample.lyrics.strip() + "\n", encoding="utf-8",
        )
    return dataset_dir


async def _pick_and_call_worker(
    *,
    target_mode: str,
    request_payload: dict,
    redis: Redis,
    db_factory: sessionmaker[Session],
    on_progress: ProgressCallback,
    on_heartbeat: HeartbeatCallback,
) -> TrainLoraTaskResultDTO:
    import httpx

    with db_factory() as session:
        worker = await pick_worker(session, redis, target_mode)

    headers = _internal_headers()
    async with httpx.AsyncClient(timeout=_LORA_SUBMIT_TIMEOUT_SECONDS) as client:
        submit = await client.post(
            f"{worker.base_url}/tasks/train_lora",
            json=request_payload,
            headers=headers,
        )
        submit.raise_for_status()
        task_id = submit.json()["task_id"]

    last_result: TrainLoraTaskResultDTO | None = None
    async for event_type, data in _iterate_task_events(
        worker, task_id, options=DispatchOptions(),
    ):
        if on_heartbeat is not None:
            maybe = on_heartbeat()
            if asyncio.iscoroutine(maybe):
                await maybe
        if event_type == "progress":
            fraction = float(data.get("progress", 0.0))
            maybe = on_progress(fraction)
            if asyncio.iscoroutine(maybe):
                await maybe
        elif event_type == "done":
            if "result" not in data:
                raise WorkerProtocolError(
                    "Worker done event missing 'result' field",
                )
            try:
                last_result = TrainLoraTaskResultDTO.model_validate(data["result"])
            except ValidationError as exc:
                raise WorkerTaskFailed(
                    f"Worker returned invalid train_lora result: {exc}",
                ) from exc
            break
        elif event_type == "error":
            raise WorkerTaskFailed(data.get("error") or "train_lora failed")
    if last_result is None:
        raise WorkerTaskFailed("SSE stream ended without done/error event")
    return last_result


def _validate_export_path(
    *, audio_dir: Path, user_id: str, reported: str,
) -> Path:
    """Reject paths that do not live inside the user's LoRA dir."""
    user_root = (audio_dir / USER_LORAS_DIRNAME / user_id).resolve()
    resolved = Path(reported).resolve()
    if not str(resolved).startswith(str(user_root) + os.sep) and resolved != user_root:
        raise ValueError(
            f"Worker-reported export path escapes user dir: {reported}",
        )
    return resolved


def _cleanup_failed_lora_paths(
    audio_dir: Path, user_id: str, lora_id: str,
) -> None:
    for path in (
        _dataset_dir(audio_dir, user_id, lora_id),
        _output_dir(audio_dir, user_id, lora_id),
        _tmp_training_dir(audio_dir, user_id, lora_id),
    ):
        try:
            if path.exists():
                shutil.rmtree(path)
        except OSError:
            log.warning("Failed to remove %s during LoRA cleanup", path, exc_info=True)


def cleanup_failed_lora(
    *,
    lora_id: str,
    user_id: str,
    audio_dir: Path,
    db_factory: sessionmaker[Session],
    error_message: str,
) -> None:
    """Mark the LoRA FAILED, remove its working dirs, emit audit failure.

    Idempotent: safe to call from crash recovery and from the runner
    itself. Does not touch sample audio files — samples live at their
    own path outside the dataset dir.
    """
    _cleanup_failed_lora_paths(audio_dir, user_id, lora_id)
    try:
        with db_factory() as session:
            update_user_lora(
                session, lora_id,
                status=LoraStatus.FAILED, error=error_message,
                completed_at=datetime.now(timezone.utc),
            )
            record_audit(
                session, user_id, AuditAction.TRAIN_LORA,
                ResourceType.LORA, lora_id, f"failed: {error_message}",
            )
            session.commit()
    except Exception:
        log.exception("Failed to mark LoRA %s as FAILED", lora_id)


async def run_lora_training_job(
    ctx, job_id: str, lora_id: str, user_id: str,
    *,
    db_factory: sessionmaker[Session] | None = None,
    audio_dir: Path | None = None,
    redis: Redis | None = None,
    target_mode: str = MODEL_DEFAULT_MODE,
) -> None:
    """ARQ job: materialize dataset, dispatch training to a worker, persist.

    Status transitions:
        QUEUED -> PREPROCESSING -> TRAINING -> EXPORTING -> READY / FAILED

    Registered under :class:`JobFunction.LORA_TRAINING` in the music
    worker's settings.
    """
    import structlog

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        job_id=job_id, job_type=JobType.LORA_TRAINING, lora_id=lora_id,
    )

    if db_factory is None or audio_dir is None or redis is None:
        raise RuntimeError(
            "run_lora_training_job requires db_factory, audio_dir, redis",
        )

    _update_job(db_factory, job_id, JobStatus.RUNNING, worker_pid=os.getpid())

    from songmaker_cli.db.queries import get_user_lora

    try:
        with db_factory() as session:
            lora = get_user_lora(session, lora_id, include_deleted_rows=True)
            if lora is None:
                _update_job(
                    db_factory, job_id, JobStatus.FAILED,
                    error="LoRA not found", error_type="lora_missing",
                )
                return
            if lora.deleted_at is not None:
                _update_job(
                    db_factory, job_id, JobStatus.FAILED,
                    error="LoRA is deleted", error_type="lora_deleted",
                )
                return
            samples = list(lora.samples or [])

        dataset_dir = await asyncio.to_thread(
            _materialize_dataset,
            audio_dir=audio_dir, user_id=user_id, lora_id=lora_id, samples=samples,
        )

        with db_factory() as session:
            update_user_lora(
                session, lora_id, status=LoraStatus.PREPROCESSING, clear_error=True,
            )
            session.commit()
        _update_job(db_factory, job_id, JobStatus.RUNNING, progress=0.05)

        output_dir = _output_dir(audio_dir, user_id, lora_id)
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        tmp_output = _tmp_training_dir(audio_dir, user_id, lora_id)
        if tmp_output.exists():
            shutil.rmtree(tmp_output)
        tmp_output.mkdir(parents=True, exist_ok=True)

        last_update = 0.0
        last_status_name: str = LoraStatus.PREPROCESSING

        def _on_progress(fraction: float) -> None:
            nonlocal last_update, last_status_name
            import time as _t
            now = _t.monotonic()
            if now - last_update < _LORA_PROGRESS_THROTTLE_SECONDS:
                return
            last_update = now
            new_status = LoraStatus.PREPROCESSING
            if fraction >= 0.90:
                new_status = LoraStatus.EXPORTING
            elif fraction >= 0.20:
                new_status = LoraStatus.TRAINING
            if new_status != last_status_name:
                with db_factory() as s:
                    update_user_lora(s, lora_id, status=new_status)
                    s.commit()
                last_status_name = new_status
            _update_job(db_factory, job_id, JobStatus.RUNNING, progress=fraction)

        def _on_heartbeat() -> None:
            _touch_heartbeat(db_factory, job_id)

        request_payload = {
            "mode": target_mode,
            "dataset_dir": str(dataset_dir),
            "output_dir": str(tmp_output),
        }

        try:
            worker_result = await _pick_and_call_worker(
                target_mode=target_mode,
                request_payload=request_payload,
                redis=redis,
                db_factory=db_factory,
                on_progress=_on_progress,
                on_heartbeat=_on_heartbeat,
            )
        except NoCapacityError as exc:
            cleanup_failed_lora(
                lora_id=lora_id, user_id=user_id, audio_dir=audio_dir,
                db_factory=db_factory, error_message=str(exc),
            )
            _update_job(
                db_factory, job_id, JobStatus.FAILED,
                error=_sanitize_error(exc), error_type="no_workers",
            )
            return

        adapter_src = _validate_export_path(
            audio_dir=audio_dir, user_id=user_id,
            reported=worker_result.adapter_dir,
        )
        if not adapter_src.exists():
            raise RuntimeError(
                f"Worker reported adapter at {adapter_src} but path is missing",
            )

        final_dir = _output_dir(audio_dir, user_id, lora_id)
        if final_dir.exists():
            shutil.rmtree(final_dir)
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(adapter_src), str(final_dir))

        try:
            shutil.rmtree(tmp_output)
        except OSError:
            log.warning("Failed to remove tmp training dir %s", tmp_output)
        try:
            shutil.rmtree(dataset_dir)
        except OSError:
            log.warning("Failed to remove dataset dir %s", dataset_dir)

        storage_rel = str(
            Path(USER_LORAS_DIRNAME) / user_id / lora_id / USER_LORA_OUTPUT_DIRNAME,
        )
        with db_factory() as session:
            update_user_lora(
                session, lora_id,
                status=LoraStatus.READY,
                storage_path=storage_rel,
                completed_at=datetime.now(timezone.utc),
                clear_error=True,
            )
            record_audit(
                session, user_id, AuditAction.TRAIN_LORA,
                ResourceType.LORA, lora_id,
                f"ready: samples={worker_result.num_samples}",
            )
            session.commit()

        _update_job(db_factory, job_id, JobStatus.COMPLETED, progress=1.0)

    except asyncio.CancelledError:
        log.warning("LoRA training job %s cancelled", job_id)
        cleanup_failed_lora(
            lora_id=lora_id, user_id=user_id, audio_dir=audio_dir,
            db_factory=db_factory,
            error_message="Job cancelled: exceeded ARQ_JOB_TIMEOUT or worker shutdown",
        )
        _update_job(
            db_factory, job_id, JobStatus.FAILED,
            error="Job cancelled: exceeded ARQ_JOB_TIMEOUT or worker shutdown",
            error_type="timeout",
        )
        raise
    except Exception as exc:
        log.exception("LoRA training job %s failed: %s", job_id, exc)
        cleanup_failed_lora(
            lora_id=lora_id, user_id=user_id, audio_dir=audio_dir,
            db_factory=db_factory, error_message=_sanitize_error(exc),
        )
        _update_job(
            db_factory, job_id, JobStatus.FAILED,
            error=_sanitize_error(exc), error_type="lora_training_error",
        )

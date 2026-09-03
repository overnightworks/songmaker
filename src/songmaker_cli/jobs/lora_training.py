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
    list_active_user_loras,
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
) -> bool:
    """Remove disposable training paths and report whether all removals worked."""
    removed_cleanly = True
    for path in (
        _dataset_dir(audio_dir, user_id, lora_id),
        _output_dir(audio_dir, user_id, lora_id),
        _tmp_training_dir(audio_dir, user_id, lora_id),
    ):
        try:
            if path.exists():
                shutil.rmtree(path)
        except OSError:
            removed_cleanly = False
            log.exception("Failed to remove %s during LoRA cleanup", path)
    return removed_cleanly


def cleanup_failed_lora(
    *,
    session: Session,
    lora_id: str,
    user_id: str,
    error_message: str,
) -> None:
    """Mark one LoRA FAILED and write its audit record in ``session``.

    The caller owns the transaction and decides when to commit.  This core
    deliberately does not touch disk, so its failed status and audit become
    durable before any slow or fallible filesystem cleanup begins.
    """
    update_user_lora(
        session, lora_id,
        status=LoraStatus.FAILED, error=error_message,
        completed_at=datetime.now(timezone.utc),
    )
    record_audit(
        session, user_id, AuditAction.TRAIN_LORA,
        ResourceType.LORA, lora_id, f"failed: {error_message}",
    )


def cleanup_failed_lora_with_factory(
    *,
    lora_id: str,
    user_id: str,
    audio_dir: Path,
    db_factory: sessionmaker[Session],
    error_message: str,
) -> None:
    """Persist a LoRA failure, then remove its disposable working paths.

    Database failures propagate to the caller.  Filesystem failures are
    logged with their traceback and followed by an orphan-work-dir audit;
    sample audio is never removed.
    """
    with db_factory() as session:
        cleanup_failed_lora(
            session=session,
            lora_id=lora_id,
            user_id=user_id,
            error_message=error_message,
        )
        session.commit()

    if not _cleanup_failed_lora_paths(audio_dir, user_id, lora_id):
        _audit_failed_lora_cleanup(db_factory, audio_dir)


def audit_orphaned_lora_work_dirs(
    db_factory: sessionmaker[Session], audio_dir: Path,
) -> None:
    """Log disposable LoRA work dirs whose LoRA is missing or no longer active."""
    loras_root = audio_dir / USER_LORAS_DIRNAME
    if not loras_root.exists():
        return

    with db_factory() as session:
        active_ids = {lora.id for lora in list_active_user_loras(session)}

    orphaned: list[Path] = []
    for user_dir in loras_root.iterdir():
        if not user_dir.is_dir():
            continue
        for lora_dir in user_dir.iterdir():
            if not lora_dir.is_dir() or lora_dir.name in active_ids:
                continue
            for work_dirname in (USER_LORA_DATASET_DIRNAME, "training_tmp"):
                work_dir = lora_dir / work_dirname
                if work_dir.exists():
                    orphaned.append(work_dir)

    if orphaned:
        log.warning(
            "Found %d orphaned LoRA work dir(s): %s",
            len(orphaned), ", ".join(str(path) for path in orphaned[:10]),
        )


def _audit_failed_lora_cleanup(
    db_factory: sessionmaker[Session], audio_dir: Path,
) -> None:
    """Log an audit failure without blocking later LoRA reconciliation rows."""
    try:
        audit_orphaned_lora_work_dirs(db_factory, audio_dir)
    except Exception:
        log.exception("Failed to audit orphaned LoRA work dirs after cleanup error")


def reconcile_crashed_loras(
    db_factory: sessionmaker[Session], audio_dir: Path,
) -> int:
    """Fail terminal-job LoRAs one locked row and transaction at a time."""
    reconciled = 0
    excluded_ids: set[str] = set()
    error_message = "Training crashed or was interrupted"

    while True:
        lora_id: str | None = None
        user_id: str | None = None
        try:
            with db_factory() as session:
                candidates = list_active_user_loras(
                    session,
                    reconcilable_only=True,
                    excluded_ids=excluded_ids,
                    limit=1,
                )
                if not candidates:
                    return reconciled
                lora = candidates[0]
                lora_id = lora.id
                user_id = lora.user_id
                cleanup_failed_lora(
                    session=session,
                    lora_id=lora_id,
                    user_id=user_id,
                    error_message=error_message,
                )
                session.commit()
        except Exception:
            if lora_id is None:
                log.exception("Failed to select a crashed LoRA for reconciliation")
                return reconciled
            log.exception("Failed to reconcile crashed LoRA %s", lora_id)
            excluded_ids.add(lora_id)
            continue

        reconciled += 1
        if not _cleanup_failed_lora_paths(audio_dir, user_id, lora_id):
            _audit_failed_lora_cleanup(db_factory, audio_dir)


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
            cleanup_failed_lora_with_factory(
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
        cleanup_failed_lora_with_factory(
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
        cleanup_failed_lora_with_factory(
            lora_id=lora_id, user_id=user_id, audio_dir=audio_dir,
            db_factory=db_factory, error_message=_sanitize_error(exc),
        )
        _update_job(
            db_factory, job_id, JobStatus.FAILED,
            error=_sanitize_error(exc), error_type="lora_training_error",
        )

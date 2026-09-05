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
from typing import Final

from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis
from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.constants import (
    ARQ_MUSIC_QUEUE_NAME,
    GPU_HOLD_POLL_INTERVAL_SECONDS,
    JOB_ERROR_WORKER_TRAINING_FAILED,
    LORA_TRAINING_MODEL_MODES,
    LORA_WAITING_FOR_GENERATION_QUEUE_REASON,
    MODEL_DEFAULT_MODE,
    STALE_JOB_THRESHOLDS,
    USER_LORA_DATASET_DIRNAME,
    USER_LORA_OUTPUT_DIRNAME,
    USER_LORA_TRAINING_TMP_DIRNAME,
    USER_LORAS_DIRNAME,
    AuditAction,
    JobFunction,
    JobStatus,
    JobType,
    LoraStatus,
    ResourceType,
)
from songmaker_cli.db.queries import (
    count_queued_generation_jobs,
    get_job,
    list_active_user_loras,
    record_audit,
    update_user_lora,
)
from songmaker_cli.scheduler import (
    AllWorkersHeld,
    DispatchOptions,
    NoCapacityError,
    WorkerProtocolError,
    WorkerTaskFailed,
    _internal_headers,
    _iterate_task_events,
    pick_worker,
)
from songmaker_cli.settings import LoraTrainingJobConfig

from ._runtime import _sanitize_error, _touch_heartbeat, _update_job

log = logging.getLogger(__name__)


def _sanitize_training_error(exc: Exception, job_id: str) -> str:
    """Keep a worker failure truthful to the training task the musician started."""
    if isinstance(
        exc,
        LoraTrainingModelModeError,
    ):
        return str(exc)
    message = _sanitize_error(exc, job_id)
    if isinstance(exc, WorkerTaskFailed):
        return JOB_ERROR_WORKER_TRAINING_FAILED
    return message


WORKER_PROGRESS_INVALID_TRAINING_START_DETAIL: Final = (
    "Worker progress event has invalid training start time"
)
LORA_ADAPTER_DESCRIPTION: Final = "LoRA adapter"

_LORA_PROGRESS_THROTTLE_SECONDS = 2.0
_LORA_SUBMIT_TIMEOUT_SECONDS = 30.0
_COMPLETED_TRAINING_MODE_FILENAME = "training_tmp.model_mode"


class TrainLoraTaskResultDTO(BaseModel):
    mode: str
    adapter_dir: str
    num_samples: int = 0
    final_loss: float | None = None


class CompletedLoraTrainingModeRecord(BaseModel):
    job_id: str
    model_mode: str


class PreviousAdapterRestoredError(RuntimeError):
    def __init__(self, message: str, previous_model_mode: str | None) -> None:
        super().__init__(message)
        self.previous_model_mode = previous_model_mode


class LoraTrainingModelModeError(ValueError):
    """A completed training job did not preserve the voice's model identity."""

    error_type: str


class UnsupportedLoraTrainingModelModeError(LoraTrainingModelModeError):
    """The worker completed training in a mode no voice can represent."""

    error_type = "lora_mode_invalid"


class LoraTrainingModelModeMismatchError(LoraTrainingModelModeError):
    """The worker completed a different training mode than was requested."""

    error_type = "lora_mode_mismatch"


@dataclass
class _WorkerHandle:
    base_url: str
    id: str


@dataclass
class _LoraHoldHandover:
    complete: bool = False


@dataclass
class _LoraSubmissionAttempt:
    transmission_started: bool = False


@dataclass(frozen=True)
class _LoraHandoverProbe:
    claimed: bool | None
    task_id: str | None = None


ProgressCallback = Callable[[float, int, int, datetime | None], Awaitable[None] | None]
HeartbeatCallback = Callable[[], Awaitable[None] | None]


def _worker_training_started_at(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise WorkerProtocolError(WORKER_PROGRESS_INVALID_TRAINING_START_DETAIL)
    try:
        training_started_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkerProtocolError(
            WORKER_PROGRESS_INVALID_TRAINING_START_DETAIL,
        ) from exc
    if training_started_at.tzinfo is None:
        raise WorkerProtocolError(WORKER_PROGRESS_INVALID_TRAINING_START_DETAIL)
    return training_started_at


def _lora_root(audio_dir: Path, user_id: str, lora_id: str) -> Path:
    return audio_dir / USER_LORAS_DIRNAME / user_id / lora_id


def _dataset_dir(audio_dir: Path, user_id: str, lora_id: str) -> Path:
    return _lora_root(audio_dir, user_id, lora_id) / USER_LORA_DATASET_DIRNAME


def _output_dir(audio_dir: Path, user_id: str, lora_id: str) -> Path:
    return _lora_root(audio_dir, user_id, lora_id) / USER_LORA_OUTPUT_DIRNAME


def _tmp_training_dir(audio_dir: Path, user_id: str, lora_id: str) -> Path:
    return _lora_root(audio_dir, user_id, lora_id) / USER_LORA_TRAINING_TMP_DIRNAME


def _completed_training_mode_path(audio_dir: Path, user_id: str, lora_id: str) -> Path:
    return _lora_root(audio_dir, user_id, lora_id) / _COMPLETED_TRAINING_MODE_FILENAME


def _completed_training_mode_tmp_path(audio_dir: Path, user_id: str, lora_id: str) -> Path:
    path = _completed_training_mode_path(audio_dir, user_id, lora_id)
    return path.with_name(f"{path.name}.new")


def _record_completed_training_model_mode(
    audio_dir: Path,
    user_id: str,
    lora_id: str,
    job_id: str,
    model_mode: str,
) -> None:
    path = _completed_training_mode_path(audio_dir, user_id, lora_id)
    temporary_path = _completed_training_mode_tmp_path(audio_dir, user_id, lora_id)
    record = CompletedLoraTrainingModeRecord(job_id=job_id, model_mode=model_mode)
    try:
        temporary_path.write_text(record.model_dump_json(), encoding="utf-8")
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _read_completed_training_model_mode(
    audio_dir: Path,
    user_id: str,
    lora_id: str,
) -> CompletedLoraTrainingModeRecord | None:
    path = _completed_training_mode_path(audio_dir, user_id, lora_id)
    if not path.exists():
        return None
    try:
        record = CompletedLoraTrainingModeRecord.model_validate_json(
            path.read_text(encoding="utf-8"),
        )
    except ValidationError as exc:
        raise ValueError("Completed LoRA training mode record is invalid") from exc
    if record.model_mode not in LORA_TRAINING_MODEL_MODES:
        raise ValueError(
            f"Completed LoRA training recorded invalid model mode: {record.model_mode!r}",
        )
    return record


def _clear_completed_training_model_mode(
    audio_dir: Path,
    user_id: str,
    lora_id: str,
) -> None:
    try:
        _completed_training_mode_path(audio_dir, user_id, lora_id).unlink(missing_ok=True)
    except OSError:
        log.exception("Failed to remove completed LoRA training mode record")


def _validate_completed_training_model_mode(
    *,
    requested_mode: str,
    worker_mode: str,
) -> str:
    """Accept only a supported worker mode that preserves the request's identity."""
    if worker_mode not in LORA_TRAINING_MODEL_MODES:
        raise UnsupportedLoraTrainingModelModeError(
            f"Worker completed LoRA training with unsupported model mode: {worker_mode!r}",
        )
    if worker_mode != requested_mode:
        raise LoraTrainingModelModeMismatchError(
            "Worker completed LoRA training with model mode "
            f"{worker_mode!r}, expected {requested_mode!r}",
        )
    return worker_mode


def _materialize_dataset(
    *,
    audio_dir: Path,
    user_id: str,
    lora_id: str,
    samples: list,
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
            sample.caption.strip() + "\n",
            encoding="utf-8",
        )
        (dataset_dir / f"{base}.lyrics.txt").write_text(
            sample.lyrics.strip() + "\n",
            encoding="utf-8",
        )
    return dataset_dir


async def _pick_and_call_worker(
    *,
    target_mode: str,
    request_payload: dict,
    worker: _WorkerHandle,
    hold_token: str,
    renew_task: asyncio.Task[None],
    handover: _LoraHoldHandover | None = None,
    on_progress: ProgressCallback,
    on_heartbeat: HeartbeatCallback,
) -> TrainLoraTaskResultDTO:
    if handover is None:
        handover = _LoraHoldHandover()
    submission = _LoraSubmissionAttempt()
    task_id: str | None = None
    try:
        await _load_lora_training_model(worker, target_mode, renew_task)
        task_id = await _submit_lora_training(
            worker,
            request_payload,
            hold_token,
            renew_task,
            submission,
        )
        handover.complete = True
    except BaseException:
        task_id = await _recover_lora_submission(
            worker,
            hold_token,
            handover,
            task_id,
            submission.transmission_started,
        )
        if task_id is None:
            raise
    finally:
        await _stop_lora_renewal(renew_task, suppress_failure=handover.complete)

    return await _read_lora_training_events(
        worker,
        task_id,
        on_progress,
        on_heartbeat,
    )


async def _load_lora_training_model(
    worker: _WorkerHandle,
    target_mode: str,
    renew_task: asyncio.Task[None],
) -> None:
    import httpx

    options = DispatchOptions()
    async with httpx.AsyncClient(timeout=options.load_model_timeout_seconds) as client:
        response = await _race_with_renewal(
            client.post(
                f"{worker.base_url}/load_model",
                json={"mode": target_mode},
                headers=_internal_headers(),
            ),
            renew_task,
        )
        response.raise_for_status()


async def _submit_lora_training(
    worker: _WorkerHandle,
    request_payload: dict,
    hold_token: str,
    renew_task: asyncio.Task[None],
    submission: _LoraSubmissionAttempt,
) -> str:
    import httpx

    async with httpx.AsyncClient(timeout=_LORA_SUBMIT_TIMEOUT_SECONDS) as client:
        submission.transmission_started = True
        response = await _race_with_renewal(
            client.post(
                f"{worker.base_url}/tasks/train_lora",
                json={**request_payload, "hold_token": hold_token},
                headers=_internal_headers(),
            ),
            renew_task,
        )
        response.raise_for_status()
        return response.json()["task_id"]


async def _recover_lora_submission(
    worker: _WorkerHandle,
    hold_token: str,
    handover: _LoraHoldHandover,
    task_id: str | None,
    submit_transmission_started: bool,
) -> str | None:
    if submit_transmission_started:
        handover.complete = True
        probe = await _worker_claimed_lora_handover(worker, hold_token)
        if probe.task_id is not None:
            task_id = probe.task_id
        elif probe.claimed is False:
            handover.complete = False
    if not handover.complete:
        await _release_lora_hold(worker, hold_token, best_effort=True)
    return task_id


async def _read_lora_training_events(
    worker: _WorkerHandle,
    task_id: str,
    on_progress: ProgressCallback,
    on_heartbeat: HeartbeatCallback,
) -> TrainLoraTaskResultDTO:
    async for event_type, data in _iterate_task_events(
        worker,
        task_id,
        options=DispatchOptions(),
    ):
        result = await _handle_lora_training_event(event_type, data, on_progress)
        await _await_lora_callback(on_heartbeat)
        if result is not None:
            return result
    raise WorkerTaskFailed("SSE stream ended without done/error event")


async def _handle_lora_training_event(
    event_type: str,
    data: dict,
    on_progress: ProgressCallback,
) -> TrainLoraTaskResultDTO | None:
    if event_type == "progress":
        await _report_lora_training_progress(data, on_progress)
        return None
    if event_type == "done":
        return _read_lora_training_result(data)
    if event_type == "error":
        raise WorkerTaskFailed(data.get("error") or "train_lora failed")
    return None


async def _report_lora_training_progress(
    data: dict,
    on_progress: ProgressCallback,
) -> None:
    fraction = float(data.get("progress", 0.0))
    current_epoch, train_epochs = _read_lora_training_epochs(data)
    training_started_at = _worker_training_started_at(data.get("training_started_at"))
    await _await_lora_callback(
        on_progress,
        fraction,
        current_epoch,
        train_epochs,
        training_started_at,
    )


def _read_lora_training_epochs(data: dict) -> tuple[int, int]:
    current_epoch = data.get("current_epoch")
    train_epochs = data.get("train_epochs")
    if (
        isinstance(current_epoch, bool)
        or not isinstance(current_epoch, int)
        or isinstance(train_epochs, bool)
        or not isinstance(train_epochs, int)
        or current_epoch < 0
        or train_epochs < 1
        or current_epoch > train_epochs
    ):
        raise WorkerProtocolError("Worker progress event has invalid training epoch fields")
    return current_epoch, train_epochs


def _read_lora_training_result(data: dict) -> TrainLoraTaskResultDTO:
    if "result" not in data:
        raise WorkerProtocolError("Worker done event missing 'result' field")
    try:
        return TrainLoraTaskResultDTO.model_validate(data["result"])
    except ValidationError as exc:
        raise WorkerTaskFailed(f"Worker returned invalid train_lora result: {exc}") from exc


async def _await_lora_callback(callback, *args) -> None:
    if callback is None:
        return
    result = callback(*args)
    if asyncio.iscoroutine(result):
        await result


async def _race_with_renewal(awaitable, renew_task: asyncio.Task[None]):
    operation_task = asyncio.create_task(awaitable)
    done, _ = await asyncio.wait(
        {operation_task, renew_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if operation_task in done:
        return await operation_task
    if renew_task in done:
        operation_task.cancel()
        try:
            await operation_task
        except asyncio.CancelledError:  # NOSONAR Renewal owns this intentional cancellation.
            pass
        return await renew_task
    return await operation_task


async def _stop_lora_renewal(
    renew_task: asyncio.Task[None],
    *,
    suppress_failure: bool = False,
) -> None:
    if not renew_task.done():
        renew_task.cancel()
    try:
        await renew_task
    except asyncio.CancelledError:
        current_task = asyncio.current_task()
        if current_task is not None and current_task.cancelling():
            raise
    except Exception:
        if not suppress_failure:
            raise


async def _worker_claimed_lora_handover(
    worker: _WorkerHandle,
    hold_token: str,
) -> _LoraHandoverProbe:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=_LORA_SUBMIT_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{worker.base_url}/gpu_hold/handover",
                json={"token": hold_token},
                headers=_internal_headers(),
            )
            response.raise_for_status()
    except httpx.HTTPError:
        log.exception("Could not confirm LoRA hold handover for worker %s", worker.id)
        return _LoraHandoverProbe(claimed=None)
    try:
        payload = response.json()
    except ValueError:
        log.error("Worker %s returned invalid JSON for LoRA handover status", worker.id)
        return _LoraHandoverProbe(claimed=None)
    if not isinstance(payload, dict) or not isinstance(payload.get("claimed"), bool):
        log.error("Worker %s returned an invalid LoRA handover status", worker.id)
        return _LoraHandoverProbe(claimed=None)
    if payload["claimed"] is not True:
        return _LoraHandoverProbe(claimed=False)
    task_id = payload.get("task_id")
    return _LoraHandoverProbe(
        claimed=True,
        task_id=task_id if isinstance(task_id, str) else None,
    )


async def _release_lora_hold(
    worker: _WorkerHandle,
    hold_token: str,
    *,
    best_effort: bool = False,
) -> None:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=_LORA_SUBMIT_TIMEOUT_SECONDS) as client:
            release = await client.post(
                f"{worker.base_url}/gpu_hold/release",
                json={"token": hold_token},
                headers=_internal_headers(),
            )
            release.raise_for_status()
    except httpx.HTTPError:
        if not best_effort:
            raise
        log.exception("Could not release LoRA hold for worker %s during cleanup", worker.id)


async def _renew_lora_hold(worker: _WorkerHandle, hold_token: str) -> None:
    import httpx

    while True:
        await asyncio.sleep(GPU_HOLD_POLL_INTERVAL_SECONDS)
        async with httpx.AsyncClient(timeout=_LORA_SUBMIT_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{worker.base_url}/gpu_hold/renew",
                json={"token": hold_token},
                headers=_internal_headers(),
            )
            response.raise_for_status()


async def _start_lora_hold_renewal(
    worker: _WorkerHandle,
    hold_token: str,
) -> asyncio.Task[None]:
    started = asyncio.Event()

    async def renew() -> None:
        started.set()
        await _renew_lora_hold(worker, hold_token)

    task = asyncio.create_task(renew())
    await started.wait()
    return task


async def _reserve_lora_worker(
    *,
    target_mode: str,
    redis: Redis,
    db_factory: sessionmaker[Session],
) -> tuple[_WorkerHandle, str]:
    import httpx

    with db_factory() as session:
        picked = await pick_worker(session, redis, target_mode)
        if count_queued_generation_jobs(session) > 0:
            raise AllWorkersHeld("A generation is waiting before LoRA training")
    async with httpx.AsyncClient(timeout=_LORA_SUBMIT_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{picked.base_url}/gpu_hold/reserve",
            headers=_internal_headers(),
        )
        if response.status_code == 409:
            raise AllWorkersHeld("ACE-Step worker is busy or held")
        response.raise_for_status()
    return _WorkerHandle(base_url=picked.base_url, id=picked.id), response.json()["token"]


async def _prepare_and_submit_lora(
    *,
    audio_dir: Path,
    db_factory: sessionmaker[Session],
    hold_token: str,
    job_id: str,
    lora_id: str,
    samples: list,
    target_mode: str,
    user_id: str,
    worker: _WorkerHandle,
    training_config: LoraTrainingJobConfig,
) -> tuple[TrainLoraTaskResultDTO, Path, Path] | None:
    renew_task: asyncio.Task[None] | None = None
    handover = _LoraHoldHandover()
    try:
        renew_task = await _start_lora_hold_renewal(worker, hold_token)
        if not _update_job(db_factory, job_id, JobStatus.RUNNING, worker_pid=os.getpid()):
            return None
        dataset_dir = await _race_with_renewal(
            asyncio.to_thread(
                _materialize_dataset,
                audio_dir=audio_dir,
                user_id=user_id,
                lora_id=lora_id,
                samples=samples,
            ),
            renew_task,
        )
        with db_factory() as session:
            update_user_lora(
                session,
                lora_id,
                status=LoraStatus.PREPROCESSING,
                clear_error=True,
            )
            session.commit()
        _update_job(db_factory, job_id, JobStatus.RUNNING, progress=0.05)

        output_dir = _output_dir(audio_dir, user_id, lora_id)
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        tmp_output = _tmp_training_dir(audio_dir, user_id, lora_id)
        if tmp_output.exists():
            shutil.rmtree(tmp_output)

        last_update = 0.0
        last_epoch: int | None = None
        last_training_started_at: datetime | None = None
        last_status_name: str = LoraStatus.PREPROCESSING

        def on_progress(
            fraction: float,
            current_epoch: int,
            train_epochs: int,
            training_started_at: datetime | None,
        ) -> None:
            nonlocal last_epoch, last_training_started_at, last_update, last_status_name
            import time as _t

            now = _t.monotonic()
            if (
                current_epoch == last_epoch
                and training_started_at == last_training_started_at
                and now - last_update < _LORA_PROGRESS_THROTTLE_SECONDS
            ):
                return
            last_update = now
            last_epoch = current_epoch
            last_training_started_at = training_started_at
            new_status = LoraStatus.PREPROCESSING
            if fraction >= 0.90:
                new_status = LoraStatus.EXPORTING
            elif fraction >= 0.20:
                new_status = LoraStatus.TRAINING
            if new_status != last_status_name:
                with db_factory() as session:
                    update_user_lora(session, lora_id, status=new_status)
                    session.commit()
                last_status_name = new_status
            _update_job(
                db_factory,
                job_id,
                JobStatus.RUNNING,
                progress=fraction,
                current_epoch=current_epoch,
                train_epochs=train_epochs,
                training_started_at=training_started_at,
            )

        def on_heartbeat() -> None:
            _touch_heartbeat(db_factory, job_id)

        request_payload = {
            "mode": target_mode,
            "dataset_dir": str(dataset_dir),
            "output_dir": str(tmp_output),
            **training_config.payload(),
        }
        worker_result = await _pick_and_call_worker(
            target_mode=target_mode,
            request_payload=request_payload,
            worker=worker,
            hold_token=hold_token,
            renew_task=renew_task,
            handover=handover,
            on_progress=on_progress,
            on_heartbeat=on_heartbeat,
        )
        return worker_result, dataset_dir, tmp_output
    finally:
        if not handover.complete:
            await _release_lora_hold(worker, hold_token, best_effort=True)
        if renew_task is not None:
            await _stop_lora_renewal(renew_task, suppress_failure=True)


def _validate_export_path(
    *,
    audio_dir: Path,
    user_id: str,
    reported: str,
) -> Path:
    """Reject paths that do not live inside the user's LoRA dir."""
    user_root = (audio_dir / USER_LORAS_DIRNAME / user_id).resolve()
    resolved = Path(reported).resolve()
    if resolved == user_root or not resolved.is_relative_to(user_root):
        raise ValueError(
            f"Worker-reported export path escapes user dir: {reported}",
        )
    return resolved


def _cleanup_failed_lora_paths(
    audio_dir: Path,
    user_id: str,
    lora_id: str,
) -> bool:
    """Remove disposable training paths and report whether all removals worked."""
    removed_cleanly = True
    for path in (
        _dataset_dir(audio_dir, user_id, lora_id),
        _tmp_training_dir(audio_dir, user_id, lora_id),
        _completed_training_mode_path(audio_dir, user_id, lora_id),
        _completed_training_mode_tmp_path(audio_dir, user_id, lora_id),
    ):
        try:
            if path.exists():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
        except OSError:
            removed_cleanly = False
            log.exception("Failed to remove %s during LoRA cleanup", path)
    return removed_cleanly


def _recover_complete_lora_adapter(
    audio_dir: Path,
    user_id: str,
    lora_id: str,
    completed_model_mode: str | None = None,
) -> bool:
    final_dir = _output_dir(audio_dir, user_id, lora_id)
    previous_dir = final_dir.with_name(f"{final_dir.name}.previous")
    tmp_output = _tmp_training_dir(audio_dir, user_id, lora_id)
    if completed_model_mode is not None:
        return _recover_recorded_lora_adapter(final_dir, previous_dir, tmp_output)
    return _restore_previous_lora_adapter(final_dir, previous_dir)


def _recover_recorded_lora_adapter(
    final_dir: Path,
    previous_dir: Path,
    tmp_output: Path,
) -> bool:
    _require_lora_adapter_directory(final_dir, LORA_ADAPTER_DESCRIPTION)
    _require_lora_adapter_directory(previous_dir, "Previous LoRA adapter")
    _require_lora_adapter_directory(tmp_output, "Temporary LoRA adapter")
    if tmp_output.is_dir():
        if final_dir.exists():
            os.rename(final_dir, previous_dir)
        os.rename(tmp_output, final_dir)
    if previous_dir.exists():
        shutil.rmtree(previous_dir)
    return final_dir.is_dir()


def _restore_previous_lora_adapter(final_dir: Path, previous_dir: Path) -> bool:
    if not previous_dir.exists():
        return final_dir.is_dir()
    if final_dir.exists():
        _require_lora_adapter_directory(final_dir, LORA_ADAPTER_DESCRIPTION)
        shutil.rmtree(previous_dir)
    else:
        os.rename(previous_dir, final_dir)
    return final_dir.is_dir()


def _require_lora_adapter_directory(path: Path, description: str) -> None:
    if path.exists() and not path.is_dir():
        raise RuntimeError(f"{description} path is not a directory: {path}")


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
        session,
        lora_id,
        status=LoraStatus.FAILED,
        error=error_message,
        completed_at=datetime.now(timezone.utc),
    )
    record_audit(
        session,
        user_id,
        AuditAction.TRAIN_LORA,
        ResourceType.LORA,
        lora_id,
        f"failed: {error_message}",
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
        _log_failed_lora_cleanup(db_factory, audio_dir)


def log_orphaned_lora_work_dirs(
    db_factory: sessionmaker[Session],
    audio_dir: Path,
) -> None:
    """Log disposable LoRA work dirs whose LoRA is missing or no longer active."""
    loras_root = audio_dir / USER_LORAS_DIRNAME
    if not loras_root.exists():
        return

    with db_factory() as session:
        active_ids = {lora.id for lora in list_active_user_loras(session)}

    orphaned = _find_orphaned_lora_work_dirs(loras_root, active_ids)
    if orphaned:
        log.warning(
            "Found %d orphaned LoRA work dir(s): %s",
            len(orphaned),
            ", ".join(str(path) for path in orphaned[:10]),
        )


def _find_orphaned_lora_work_dirs(loras_root: Path, active_ids: set[str]) -> list[Path]:
    orphaned: list[Path] = []
    for user_dir in loras_root.iterdir():
        if not user_dir.is_dir():
            continue
        for lora_dir in user_dir.iterdir():
            orphaned.extend(_orphaned_lora_work_dirs(lora_dir, active_ids))
    return orphaned


def _orphaned_lora_work_dirs(lora_dir: Path, active_ids: set[str]) -> list[Path]:
    if not lora_dir.is_dir() or lora_dir.name in active_ids:
        return []
    return [
        work_dir
        for work_dirname in (
            USER_LORA_DATASET_DIRNAME,
            USER_LORA_TRAINING_TMP_DIRNAME,
        )
        if (work_dir := lora_dir / work_dirname).exists()
    ]


def _log_failed_lora_cleanup(
    db_factory: sessionmaker[Session],
    audio_dir: Path,
) -> None:
    """Log an audit failure without blocking later LoRA reconciliation rows."""
    try:
        log_orphaned_lora_work_dirs(db_factory, audio_dir)
    except Exception:
        log.exception("Failed to audit orphaned LoRA work dirs after cleanup error")


def reconcile_crashed_loras(
    db_factory: sessionmaker[Session],
    audio_dir: Path,
) -> int:
    """Reconcile terminal-job LoRAs one locked row and transaction at a time."""
    reconciled = 0
    excluded_ids: set[str] = set()
    error_message = "Training crashed or was interrupted"

    while True:
        lora_id: str | None = None
        user_id: str | None = None
        recovered_adapter = False
        completed_model_mode: str | None = None
        try:
            with db_factory() as session:
                lora = _next_reconcilable_lora(session, excluded_ids)
                if lora is None:
                    return reconciled
                lora_id = lora.id
                user_id = lora.user_id
                completed_model_mode = _completed_model_mode_for_lora(
                    audio_dir,
                    user_id,
                    lora_id,
                    lora.training_job_id,
                )
                recovered_adapter = _recover_complete_lora_adapter(
                    audio_dir,
                    user_id,
                    lora_id,
                    completed_model_mode,
                )
                _persist_crashed_lora_reconciliation(
                    session,
                    lora_id,
                    user_id,
                    completed_model_mode,
                    recovered_adapter,
                    error_message,
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
        if recovered_adapter and completed_model_mode is not None:
            _clear_completed_training_model_mode(audio_dir, user_id, lora_id)
        if not _cleanup_failed_lora_paths(audio_dir, user_id, lora_id):
            _log_failed_lora_cleanup(db_factory, audio_dir)


def _next_reconcilable_lora(session: Session, excluded_ids: set[str]):
    candidates = list_active_user_loras(
        session,
        reconcilable_only=True,
        excluded_ids=excluded_ids,
        limit=1,
    )
    return candidates[0] if candidates else None


def _completed_model_mode_for_lora(
    audio_dir: Path,
    user_id: str,
    lora_id: str,
    training_job_id: str | None,
) -> str | None:
    completed_mode_record = _read_completed_training_model_mode(audio_dir, user_id, lora_id)
    if completed_mode_record is None:
        return None
    if completed_mode_record.job_id == training_job_id:
        return completed_mode_record.model_mode
    log.warning(
        "Ignoring stale completed LoRA training mode record for job %s",
        completed_mode_record.job_id,
    )
    return None


def _persist_crashed_lora_reconciliation(
    session: Session,
    lora_id: str,
    user_id: str,
    completed_model_mode: str | None,
    recovered_adapter: bool,
    error_message: str,
) -> None:
    if not recovered_adapter:
        cleanup_failed_lora(
            session=session,
            lora_id=lora_id,
            user_id=user_id,
            error_message=error_message,
        )
        return
    storage_rel = str(
        Path(USER_LORAS_DIRNAME) / user_id / lora_id / USER_LORA_OUTPUT_DIRNAME,
    )
    update_user_lora(
        session,
        lora_id,
        status=LoraStatus.READY,
        storage_path=storage_rel,
        completed_at=datetime.now(timezone.utc),
        model_mode=completed_model_mode,
        clear_error=True,
    )
    record_audit(
        session,
        user_id,
        AuditAction.TRAIN_LORA,
        ResourceType.LORA,
        lora_id,
        "ready: recovered complete adapter after interrupted training",
    )


async def run_lora_training_job(
    _ctx,
    job_id: str,
    lora_id: str,
    user_id: str,
    *,
    db_factory: sessionmaker[Session] | None = None,
    audio_dir: Path | None = None,
    redis: Redis | None = None,
    target_mode: str = MODEL_DEFAULT_MODE,
    training_config: LoraTrainingJobConfig,
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
        job_id=job_id,
        job_type=JobType.LORA_TRAINING,
        lora_id=lora_id,
    )

    if db_factory is None or audio_dir is None or redis is None:
        raise RuntimeError(
            "run_lora_training_job requires db_factory, audio_dir, redis",
        )

    try:
        await _run_lora_training(
            audio_dir=audio_dir,
            db_factory=db_factory,
            job_id=job_id,
            lora_id=lora_id,
            redis=redis,
            target_mode=target_mode,
            training_config=training_config,
            user_id=user_id,
        )

    except asyncio.CancelledError:
        _handle_cancelled_lora_training(db_factory, audio_dir, job_id, lora_id, user_id)
        raise
    except PreviousAdapterRestoredError as exc:
        _keep_restored_lora_adapter(db_factory, audio_dir, exc, job_id, lora_id, user_id)
    except LoraTrainingModelModeError as exc:
        log.exception("LoRA training job %s returned an invalid model mode: %s", job_id, exc)
        _fail_lora_training(db_factory, audio_dir, exc, exc.error_type, job_id, lora_id, user_id)
    except Exception as exc:
        log.exception("LoRA training job %s failed: %s", job_id, exc)
        _fail_lora_training(
            db_factory,
            audio_dir,
            exc,
            "lora_training_error",
            job_id,
            lora_id,
            user_id,
        )


async def _run_lora_training(
    *,
    audio_dir: Path,
    db_factory: sessionmaker[Session],
    job_id: str,
    lora_id: str,
    redis: Redis,
    target_mode: str,
    training_config: LoraTrainingJobConfig,
    user_id: str,
) -> None:
    samples = _load_lora_training_samples(db_factory, job_id, lora_id)
    if samples is None:
        return
    try:
        worker, hold_token = await _reserve_lora_worker(
            target_mode=target_mode,
            redis=redis,
            db_factory=db_factory,
        )
    except AllWorkersHeld:
        await _defer_lora_training_for_generation(
            audio_dir,
            db_factory,
            job_id,
            lora_id,
            redis,
            target_mode,
            user_id,
        )
        return
    submitted = await _submit_lora_training_job(
        audio_dir,
        db_factory,
        hold_token,
        job_id,
        lora_id,
        samples,
        target_mode,
        training_config,
        user_id,
        worker,
    )
    if submitted is not None:
        _complete_lora_training(
            audio_dir,
            db_factory,
            job_id,
            lora_id,
            target_mode,
            user_id,
            submitted,
        )


def _load_lora_training_samples(
    db_factory: sessionmaker[Session],
    job_id: str,
    lora_id: str,
) -> list | None:
    from songmaker_cli.db.queries import get_user_lora

    with db_factory() as session:
        lora = get_user_lora(session, lora_id, include_deleted_rows=True)
        if lora is None:
            _update_job(
                db_factory,
                job_id,
                JobStatus.FAILED,
                error="LoRA not found",
                error_type="lora_missing",
            )
            return None
        if lora.deleted_at is not None:
            _update_job(
                db_factory,
                job_id,
                JobStatus.FAILED,
                error="LoRA is deleted",
                error_type="lora_deleted",
            )
            return None
        return list(lora.samples or [])


async def _defer_lora_training_for_generation(
    audio_dir: Path,
    db_factory: sessionmaker[Session],
    job_id: str,
    lora_id: str,
    redis: Redis,
    target_mode: str,
    user_id: str,
) -> None:
    waited_seconds = _lora_queue_wait_seconds(db_factory, job_id)
    if waited_seconds is None:
        return
    if waited_seconds >= STALE_JOB_THRESHOLDS[JobType.LORA_TRAINING].queued_seconds:
        error_message = "Generation queue did not drain before LoRA training could start"
        cleanup_failed_lora_with_factory(
            lora_id=lora_id,
            user_id=user_id,
            audio_dir=audio_dir,
            db_factory=db_factory,
            error_message=error_message,
        )
        _update_job(
            db_factory,
            job_id,
            JobStatus.FAILED,
            error=error_message,
            error_type="generation_queue_timeout",
        )
        return
    _update_job(
        db_factory,
        job_id,
        JobStatus.QUEUED,
        queue_reason=LORA_WAITING_FOR_GENERATION_QUEUE_REASON,
    )
    await redis.enqueue_job(
        JobFunction.LORA_TRAINING,
        job_id,
        lora_id,
        user_id,
        target_mode,
        _queue_name=ARQ_MUSIC_QUEUE_NAME,
        _defer_by=GPU_HOLD_POLL_INTERVAL_SECONDS,
    )


def _lora_queue_wait_seconds(
    db_factory: sessionmaker[Session],
    job_id: str,
) -> float | None:
    with db_factory() as session:
        job = get_job(session, job_id)
        if job is None:
            return None
        queued_at = job.started_at
    if queued_at.tzinfo is None:
        queued_at = queued_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - queued_at).total_seconds()


async def _submit_lora_training_job(
    audio_dir: Path,
    db_factory: sessionmaker[Session],
    hold_token: str,
    job_id: str,
    lora_id: str,
    samples: list,
    target_mode: str,
    training_config: LoraTrainingJobConfig,
    user_id: str,
    worker: _WorkerHandle,
) -> tuple[TrainLoraTaskResultDTO, Path, Path] | None:
    try:
        return await _prepare_and_submit_lora(
            audio_dir=audio_dir,
            db_factory=db_factory,
            hold_token=hold_token,
            job_id=job_id,
            lora_id=lora_id,
            samples=samples,
            target_mode=target_mode,
            user_id=user_id,
            worker=worker,
            training_config=training_config,
        )
    except NoCapacityError as exc:
        _fail_lora_training(db_factory, audio_dir, exc, "no_workers", job_id, lora_id, user_id)
        return None


def _complete_lora_training(
    audio_dir: Path,
    db_factory: sessionmaker[Session],
    job_id: str,
    lora_id: str,
    target_mode: str,
    user_id: str,
    submitted: tuple[TrainLoraTaskResultDTO, Path, Path],
) -> None:
    worker_result, dataset_dir, tmp_output = submitted
    completed_model_mode = _validate_completed_training_model_mode(
        requested_mode=target_mode,
        worker_mode=worker_result.mode,
    )
    _validated_lora_adapter_handoff(audio_dir, user_id, tmp_output, worker_result)
    _record_completed_training_model_mode(
        audio_dir,
        user_id,
        lora_id,
        job_id,
        completed_model_mode,
    )
    previous_model_mode = _save_lora_model_mode(
        db_factory,
        lora_id,
        completed_model_mode,
    )
    final_dir = _output_dir(audio_dir, user_id, lora_id)
    _replace_lora_adapter(final_dir, tmp_output, previous_model_mode)
    _remove_replaced_lora_paths(dataset_dir, final_dir)
    _clear_completed_training_model_mode(audio_dir, user_id, lora_id)
    _mark_lora_training_complete(
        db_factory,
        job_id,
        lora_id,
        user_id,
        completed_model_mode,
        worker_result.num_samples,
    )


def _validated_lora_adapter_handoff(
    audio_dir: Path,
    user_id: str,
    tmp_output: Path,
    worker_result: TrainLoraTaskResultDTO,
) -> Path:
    adapter_src = _validate_export_path(
        audio_dir=audio_dir,
        user_id=user_id,
        reported=worker_result.adapter_dir,
    )
    if not adapter_src.exists():
        raise RuntimeError(f"Worker reported adapter at {adapter_src} but path is missing")
    if adapter_src != tmp_output.resolve():
        raise RuntimeError(f"Worker reported unexpected training handoff path: {adapter_src}")
    if not adapter_src.is_dir():
        raise RuntimeError(f"Worker reported adapter at {adapter_src} but it is not a directory")
    return adapter_src


def _save_lora_model_mode(
    db_factory: sessionmaker[Session],
    lora_id: str,
    completed_model_mode: str,
) -> str | None:
    from songmaker_cli.db.queries import get_user_lora

    with db_factory() as session:
        lora = get_user_lora(session, lora_id, include_deleted_rows=True)
        if lora is None:
            raise RuntimeError(f"LoRA disappeared before adapter adoption: {lora_id}")
        previous_model_mode = lora.model_mode
        update_user_lora(session, lora_id, model_mode=completed_model_mode)
        session.commit()
    return previous_model_mode


def _replace_lora_adapter(
    final_dir: Path,
    tmp_output: Path,
    previous_model_mode: str | None,
) -> None:
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    previous_dir = final_dir.with_name(f"{final_dir.name}.previous")
    _stage_current_lora_adapter(final_dir, previous_dir)
    _move_lora_adapter(tmp_output, final_dir, previous_dir, previous_model_mode)


def _stage_current_lora_adapter(final_dir: Path, previous_dir: Path) -> None:
    if previous_dir.exists():
        raise RuntimeError(f"Previous LoRA adapter handoff is still pending at {previous_dir}")
    if final_dir.exists():
        _require_lora_adapter_directory(final_dir, LORA_ADAPTER_DESCRIPTION)
        os.rename(final_dir, previous_dir)


def _move_lora_adapter(
    tmp_output: Path,
    final_dir: Path,
    previous_dir: Path,
    previous_model_mode: str | None,
) -> None:
    try:
        os.rename(tmp_output, final_dir)
    except OSError as exc:
        if not final_dir.exists() and previous_dir.is_dir():
            os.rename(previous_dir, final_dir)
            raise PreviousAdapterRestoredError(
                "Failed to replace LoRA adapter; restored the previous adapter",
                previous_model_mode,
            ) from exc
        raise


def _remove_replaced_lora_paths(dataset_dir: Path, final_dir: Path) -> None:
    previous_dir = final_dir.with_name(f"{final_dir.name}.previous")
    if previous_dir.exists():
        try:
            shutil.rmtree(previous_dir)
        except OSError:
            log.exception("Failed to remove previous LoRA adapter %s", previous_dir)
    try:
        shutil.rmtree(dataset_dir)
    except OSError:
        log.warning("Failed to remove dataset dir %s", dataset_dir)


def _mark_lora_training_complete(
    db_factory: sessionmaker[Session],
    job_id: str,
    lora_id: str,
    user_id: str,
    completed_model_mode: str,
    sample_count: int,
) -> None:
    storage_rel = str(
        Path(USER_LORAS_DIRNAME) / user_id / lora_id / USER_LORA_OUTPUT_DIRNAME,
    )
    with db_factory() as session:
        update_user_lora(
            session,
            lora_id,
            status=LoraStatus.READY,
            storage_path=storage_rel,
            completed_at=datetime.now(timezone.utc),
            model_mode=completed_model_mode,
            clear_error=True,
        )
        record_audit(
            session,
            user_id,
            AuditAction.TRAIN_LORA,
            ResourceType.LORA,
            lora_id,
            f"ready: samples={sample_count}",
        )
        session.commit()
    _update_job(db_factory, job_id, JobStatus.COMPLETED, progress=1.0)


def _handle_cancelled_lora_training(
    db_factory: sessionmaker[Session],
    audio_dir: Path,
    job_id: str,
    lora_id: str,
    user_id: str,
) -> None:
    error_message = "Job cancelled: exceeded LORA_TRAINING_JOB_TIMEOUT or worker shutdown"
    log.warning("LoRA training job %s cancelled", job_id)
    cleanup_failed_lora_with_factory(
        lora_id=lora_id,
        user_id=user_id,
        audio_dir=audio_dir,
        db_factory=db_factory,
        error_message=error_message,
    )
    _update_job(
        db_factory,
        job_id,
        JobStatus.FAILED,
        error=error_message,
        error_type="timeout",
    )


def _keep_restored_lora_adapter(
    db_factory: sessionmaker[Session],
    audio_dir: Path,
    exc: PreviousAdapterRestoredError,
    job_id: str,
    lora_id: str,
    user_id: str,
) -> None:
    log.exception("LoRA training job %s kept its previous adapter: %s", job_id, exc)
    if not _cleanup_failed_lora_paths(audio_dir, user_id, lora_id):
        _log_failed_lora_cleanup(db_factory, audio_dir)
    if exc.previous_model_mode is None:
        raise RuntimeError("LoRA adapter restoration lost its previous model mode") from exc
    storage_rel = str(
        Path(USER_LORAS_DIRNAME) / user_id / lora_id / USER_LORA_OUTPUT_DIRNAME,
    )
    with db_factory() as session:
        update_user_lora(
            session,
            lora_id,
            status=LoraStatus.READY,
            storage_path=storage_rel,
            model_mode=exc.previous_model_mode,
            clear_error=True,
        )
        record_audit(
            session,
            user_id,
            AuditAction.TRAIN_LORA,
            ResourceType.LORA,
            lora_id,
            "ready: retained previous adapter after failed replacement",
        )
        session.commit()
    _update_job(
        db_factory,
        job_id,
        JobStatus.FAILED,
        error=_sanitize_training_error(exc, job_id),
        error_type="lora_training_error",
    )


def _fail_lora_training(
    db_factory: sessionmaker[Session],
    audio_dir: Path,
    exc: Exception,
    error_type: str,
    job_id: str,
    lora_id: str,
    user_id: str,
) -> None:
    sanitized_error = _sanitize_training_error(exc, job_id)
    cleanup_failed_lora_with_factory(
        lora_id=lora_id,
        user_id=user_id,
        audio_dir=audio_dir,
        db_factory=db_factory,
        error_message=sanitized_error,
    )
    _update_job(
        db_factory,
        job_id,
        JobStatus.FAILED,
        error=sanitized_error,
        error_type=error_type,
    )

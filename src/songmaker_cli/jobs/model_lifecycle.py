"""Worker model lifecycle jobs — load and download model weights on a worker."""

from __future__ import annotations

import asyncio
import logging

from songmaker_cli.job_types import JobStatus
from songmaker_cli.worker_liveness import JobOwner

from ._runtime import _sanitize_error, _touch_heartbeat, _update_job

log = logging.getLogger(__name__)

DOWNLOAD_MAX_ATTEMPTS = 3
DOWNLOAD_RETRY_BASE_DELAY_SECONDS = 5.0
DOWNLOAD_LOCK_LOST_MESSAGE = "The download of '{mode}' lost its lock and stopped"


async def load_model_on_worker(
    _ctx,
    job_id: str,
    worker_id: str,
    mode: str,
    *,
    db_factory,
    owner: JobOwner,
) -> None:
    import httpx

    from songmaker_cli.db.queries.workers import get_worker_identity
    from songmaker_cli.scheduler import (
        WorkerTaskFailed,
        worker_request_headers,
        worker_response_cause,
    )

    factory = db_factory
    _update_job(factory, job_id, JobStatus.RUNNING, owner=owner)

    with factory() as session:
        worker = get_worker_identity(session, worker_id)
    if worker is None:
        missing = RuntimeError(f"Worker '{worker_id}' not registered")
        _update_job(
            factory, job_id, JobStatus.FAILED,
            error_message=_sanitize_error(missing, job_id), error_type="worker_missing",
        )
        return

    url = f"http://{worker.host}:{worker.port}/load_model"  # NOSONAR(S5332) Compose network only.

    try:
        async with httpx.AsyncClient(timeout=960) as client:
            response = await client.post(url, json={"mode": mode}, headers=worker_request_headers())
    except httpx.HTTPError as exc:
        _update_job(
            factory,
            job_id,
            JobStatus.FAILED,
            error_message=_sanitize_error(ConnectionError(str(exc)), job_id),
            error_type="worker_unreachable",
        )
        return

    if response.status_code >= 400:
        _update_job(
            factory,
            job_id,
            JobStatus.FAILED,
            error_message=_sanitize_error(
                WorkerTaskFailed(worker_response_cause(response)),
                job_id,
            ),
            error_type="worker_error",
        )
        return

    _update_job(factory, job_id, JobStatus.COMPLETED, progress=1.0)


async def download_model_on_worker(
    ctx,
    job_id: str,
    mode: str,
    *,
    db_factory,
    owner: JobOwner,
) -> None:
    from songmaker_cli.acestep_state import (
        DownloadAlreadyRunning,
        DownloadLockLost,
        single_flight_download,
    )
    from songmaker_cli.constants import MODEL_CONFIG_PATHS

    factory = db_factory
    _update_job(factory, job_id, JobStatus.RUNNING, owner=owner)

    if not _valid_download_mode(factory, job_id, mode, MODEL_CONFIG_PATHS):
        return

    redis = ctx["redis"]
    try:
        async with single_flight_download(redis, mode, job_id):
            await _download_with_retries(factory, redis, job_id, mode)
    except DownloadAlreadyRunning as running:
        _update_job(
            factory,
            job_id,
            JobStatus.FAILED,
            error_message=_sanitize_error(
                RuntimeError(
                    f"Another download for '{mode}' is already in progress (job {running.job_id})",
                ),
                job_id,
            ),
            error_type="duplicate_download",
        )
    except DownloadLockLost:
        _update_job(
            factory,
            job_id,
            JobStatus.FAILED,
            error_message=_sanitize_error(
                RuntimeError(DOWNLOAD_LOCK_LOST_MESSAGE.format(mode=mode)), job_id,
            ),
            error_type="download_lock_lost",
        )


async def _download_with_retries(factory, redis, job_id: str, mode: str) -> None:
    def _on_progress(fraction: float) -> None:
        _update_job(factory, job_id, JobStatus.RUNNING, progress=fraction)
        _touch_heartbeat(factory, job_id)

    def _on_heartbeat() -> None:
        _touch_heartbeat(factory, job_id)

    last_error: Exception | None = None
    for attempt in range(1, DOWNLOAD_MAX_ATTEMPTS + 1):
        outcome = await _run_download_attempt(
            factory, redis, job_id, mode, _on_progress, _on_heartbeat,
        )
        if outcome is None:
            return
        last_error = outcome
        log.warning(
            "Download job %s attempt %d/%d for %s failed: %s",
            job_id,
            attempt,
            DOWNLOAD_MAX_ATTEMPTS,
            mode,
            outcome,
        )

        if attempt < DOWNLOAD_MAX_ATTEMPTS:
            await asyncio.sleep(DOWNLOAD_RETRY_BASE_DELAY_SECONDS * attempt)

    _update_job(
        factory,
        job_id,
        JobStatus.FAILED,
        error_message=_sanitize_error(
            last_error or RuntimeError("All download attempts exhausted"),
            job_id,
        ),
        error_type="download_error",
    )


def _valid_download_mode(factory, job_id: str, mode: str, model_config_paths) -> bool:
    if mode in model_config_paths:
        return True
    _update_job(
        factory,
        job_id,
        JobStatus.FAILED,
        error_message=_sanitize_error(ValueError(f"Unknown model mode '{mode}'"), job_id),
        error_type="invalid_mode",
    )
    return False


async def _run_download_attempt(
    factory,
    redis,
    job_id: str,
    mode: str,
    on_progress,
    on_heartbeat,
) -> Exception | None:
    import httpx

    from songmaker_cli.scheduler import (
        DispatchOptions,
        NoCapacityError,
        WorkerTaskFailed,
        consume_download_task_stream,
        pick_any_online_worker,
        worker_request_headers,
        worker_response_cause,
    )

    try:
        with factory() as session:
            worker = await pick_any_online_worker(session, redis)
    except NoCapacityError as exc:
        _update_job(
            factory,
            job_id,
            JobStatus.FAILED,
            error_message=_sanitize_error(exc, job_id),
            error_type="no_workers",
        )
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            submit = await client.post(
                f"{worker.base_url}/download_model",
                json={"mode": mode},
                headers=worker_request_headers(),
            )
    except httpx.HTTPError as exc:
        _update_job(
            factory,
            job_id,
            JobStatus.FAILED,
            error_message=_sanitize_error(ConnectionError(str(exc)), job_id),
            error_type="worker_unreachable",
        )
        return None
    if submit.status_code >= 400:
        _update_job(
            factory,
            job_id,
            JobStatus.FAILED,
            error_message=_sanitize_error(WorkerTaskFailed(worker_response_cause(submit)), job_id),
            error_type="worker_error",
        )
        return None
    try:
        await consume_download_task_stream(
            worker,
            submit.json()["task_id"],
            on_progress=on_progress,
            on_heartbeat=on_heartbeat,
            options=DispatchOptions(),
        )
    except WorkerTaskFailed as exc:
        return exc
    except (httpx.RemoteProtocolError, httpx.ReadError) as exc:
        return ConnectionError(str(exc))
    except httpx.HTTPError as exc:
        _update_job(
            factory,
            job_id,
            JobStatus.FAILED,
            error_message=_sanitize_error(ConnectionError(str(exc)), job_id),
            error_type="sse_transport",
        )
        return None
    _update_job(factory, job_id, JobStatus.COMPLETED, progress=1.0)
    return None

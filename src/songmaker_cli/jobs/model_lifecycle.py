"""Worker model lifecycle jobs — load and download model weights on a worker."""

from __future__ import annotations

import asyncio
import logging
import os

from songmaker_cli.constants import JobStatus

from ._runtime import _touch_heartbeat, _update_job

log = logging.getLogger(__name__)

DOWNLOAD_MAX_ATTEMPTS = 3
DOWNLOAD_RETRY_BASE_DELAY_SECONDS = 5.0


async def load_model_on_worker(
    ctx, job_id: str, worker_id: str, mode: str, *, db_factory,
) -> None:
    import httpx

    from songmaker_cli.db.queries import get_worker_identity
    from songmaker_cli.internal_api import INTERNAL_TOKEN_HEADER
    from songmaker_cli.settings import get_settings

    factory = db_factory
    _update_job(factory, job_id, JobStatus.RUNNING, worker_pid=os.getpid())

    with factory() as session:
        worker = get_worker_identity(session, worker_id)
    if worker is None:
        _update_job(
            factory, job_id, JobStatus.FAILED,
            error=f"Worker '{worker_id}' not registered",
            error_type="worker_missing",
        )
        return

    token = get_settings().songmaker_internal_token.get_secret_value()
    headers = {INTERNAL_TOKEN_HEADER: token}
    url = f"http://{worker.host}:{worker.port}/load_model"

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(url, json={"mode": mode}, headers=headers)
    except httpx.HTTPError as exc:
        _update_job(
            factory, job_id, JobStatus.FAILED,
            error=f"Worker unreachable: {exc}",
            error_type="worker_unreachable",
        )
        return

    if response.status_code >= 400:
        _update_job(
            factory, job_id, JobStatus.FAILED,
            error=f"Worker returned {response.status_code}: {response.text[:200]}",
            error_type="worker_error",
        )
        return

    _update_job(factory, job_id, JobStatus.COMPLETED, progress=1.0)


async def download_model_on_worker(
    ctx, job_id: str, mode: str, *, db_factory,
) -> None:
    import httpx

    from songmaker_cli.acestep_state import (
        clear_download_in_progress,
        read_download_in_progress,
        set_download_in_progress,
    )
    from songmaker_cli.constants import MODEL_CONFIG_PATHS
    from songmaker_cli.internal_api import INTERNAL_TOKEN_HEADER
    from songmaker_cli.scheduler import (
        DispatchOptions,
        NoCapacityError,
        WorkerTaskFailed,
        consume_download_task_stream,
        pick_any_online_worker,
    )
    from songmaker_cli.settings import get_settings

    factory = db_factory
    _update_job(factory, job_id, JobStatus.RUNNING, worker_pid=os.getpid())

    if mode not in MODEL_CONFIG_PATHS:
        _update_job(
            factory, job_id, JobStatus.FAILED,
            error=f"Unknown model mode '{mode}'",
            error_type="invalid_mode",
        )
        return

    redis = ctx["redis"]
    acquired = await set_download_in_progress(redis, mode, job_id)
    if not acquired:
        existing = await read_download_in_progress(redis, mode)
        _update_job(
            factory, job_id, JobStatus.FAILED,
            error=f"Another download for '{mode}' is already in progress (job {existing})",
            error_type="duplicate_download",
        )
        return

    def _on_progress(fraction: float) -> None:
        _update_job(factory, job_id, JobStatus.RUNNING, progress=fraction)
        _touch_heartbeat(factory, job_id)

    def _on_heartbeat() -> None:
        _touch_heartbeat(factory, job_id)

    last_error: str | None = None
    try:
        for attempt in range(1, DOWNLOAD_MAX_ATTEMPTS + 1):
            try:
                with factory() as session:
                    worker = await pick_any_online_worker(session, redis)
            except NoCapacityError as exc:
                _update_job(
                    factory, job_id, JobStatus.FAILED,
                    error=str(exc),
                    error_type="no_workers",
                )
                return

            token = get_settings().songmaker_internal_token.get_secret_value()
            headers = {INTERNAL_TOKEN_HEADER: token}
            submit_url = f"{worker.base_url}/download_model"

            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    submit = await client.post(
                        submit_url, json={"mode": mode}, headers=headers,
                    )
            except httpx.HTTPError as exc:
                _update_job(
                    factory, job_id, JobStatus.FAILED,
                    error=f"Worker unreachable: {exc}",
                    error_type="worker_unreachable",
                )
                return

            if submit.status_code >= 400:
                _update_job(
                    factory, job_id, JobStatus.FAILED,
                    error=f"Worker returned {submit.status_code}: {submit.text[:200]}",
                    error_type="worker_error",
                )
                return

            task_id = submit.json()["task_id"]

            try:
                await consume_download_task_stream(
                    worker,
                    task_id,
                    on_progress=_on_progress,
                    on_heartbeat=_on_heartbeat,
                    options=DispatchOptions(),
                )
                _update_job(factory, job_id, JobStatus.COMPLETED, progress=1.0)
                return
            except WorkerTaskFailed as exc:
                last_error = (
                    f"Download attempt {attempt}/{DOWNLOAD_MAX_ATTEMPTS} failed: {exc}"
                )
                log.warning(
                    "download attempt %d/%d for %s failed: %s",
                    attempt, DOWNLOAD_MAX_ATTEMPTS, mode, exc,
                )
            except (httpx.RemoteProtocolError, httpx.ReadError) as exc:
                last_error = (
                    f"SSE drop on attempt {attempt}/{DOWNLOAD_MAX_ATTEMPTS}: {exc}"
                )
                log.warning(
                    "SSE drop on download attempt %d/%d for %s: %s",
                    attempt, DOWNLOAD_MAX_ATTEMPTS, mode, exc,
                )
            except httpx.HTTPError as exc:
                _update_job(
                    factory, job_id, JobStatus.FAILED,
                    error=f"SSE transport failed: {exc}",
                    error_type="sse_transport",
                )
                return

            if attempt < DOWNLOAD_MAX_ATTEMPTS:
                await asyncio.sleep(DOWNLOAD_RETRY_BASE_DELAY_SECONDS * attempt)

        _update_job(
            factory, job_id, JobStatus.FAILED,
            error=last_error or "All download attempts exhausted",
            error_type="download_error",
        )
    finally:
        await clear_download_in_progress(redis, mode)

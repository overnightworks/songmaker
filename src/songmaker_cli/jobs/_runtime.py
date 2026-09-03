"""Job runtime helpers — DB status updates, heartbeats, error sanitization."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from sqlalchemy.orm import Session

from acestep_engine.errors import AudioDownloadError
from songmaker_cli.constants import (
    JOB_ERROR_AUDIO_DOWNLOAD_FAILED,
    JOB_ERROR_GENERATION_TIMED_OUT,
    JOB_ERROR_INTERNAL,
    JOB_ERROR_JUDGE_FAILED,
    JOB_ERROR_NO_WORKERS,
    JOB_ERROR_REFERENCE_AUDIO_NOT_FOUND,
    JOB_ERROR_SERVER_UNREACHABLE,
    JOB_ERROR_SONG_NOT_FOUND,
    JOB_ERROR_UNEXPECTED,
    JOB_ERROR_VERSION_NOT_FOUND,
    JOB_ERROR_WORKER_GENERATION_FAILED,
    JOB_ERROR_WORKER_STREAM_SILENT,
    JOB_HEARTBEAT_INTERVAL_SECONDS,
    JOB_TERMINAL_STATUSES,
    JUDGE_FAILURE_TIMEOUT,
    JobStatus,
)
from songmaker_cli.db.queries import get_job, update_job_heartbeat, update_job_status
from songmaker_cli.scheduler import (
    NoCapacityError,
    WorkerTaskFailed,
)

log = logging.getLogger(__name__)

_USER_FACING_ERRORS: tuple[tuple[type[Exception], str], ...] = (
    (AudioDownloadError, JOB_ERROR_AUDIO_DOWNLOAD_FAILED),
    (ConnectionError, JOB_ERROR_SERVER_UNREACHABLE),
    (TimeoutError, JOB_ERROR_GENERATION_TIMED_OUT),
    (NoCapacityError, JOB_ERROR_NO_WORKERS),
    (WorkerTaskFailed, JOB_ERROR_WORKER_GENERATION_FAILED),
    (RuntimeError, JOB_ERROR_INTERNAL),
)

_GENERATION_SETUP_MESSAGES: frozenset[str] = frozenset({
    JOB_ERROR_SONG_NOT_FOUND,
    JOB_ERROR_VERSION_NOT_FOUND,
    JOB_ERROR_REFERENCE_AUDIO_NOT_FOUND,
})


class GenerationSetupError(Exception):
    pass


class JudgeFailureError(Exception):
    pass


def _sanitize_error(exc: Exception, job_id: str) -> str:
    """Return the fixed musician-facing message and log the raw failure."""
    log.error("Job %s failed: %s", job_id, exc, exc_info=exc)
    if isinstance(exc, GenerationSetupError):
        if str(exc) in _GENERATION_SETUP_MESSAGES:
            return str(exc)
        return JOB_ERROR_UNEXPECTED
    if isinstance(exc, JudgeFailureError):
        if str(exc) == JUDGE_FAILURE_TIMEOUT:
            return str(exc)
        return JOB_ERROR_JUDGE_FAILED
    if isinstance(exc, WorkerTaskFailed) and str(exc) == JOB_ERROR_WORKER_STREAM_SILENT:
        return JOB_ERROR_WORKER_STREAM_SILENT
    for exc_type, message in _USER_FACING_ERRORS:
        if isinstance(exc, exc_type):
            return message
    return JOB_ERROR_UNEXPECTED


def _job_is_terminal(factory, job_id: str) -> bool:
    with factory() as session:
        job = get_job(session, job_id)
        return job is None or job.status in JOB_TERMINAL_STATUSES


def _update_job(factory, job_id: str, status: str, **kwargs) -> bool:
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            with factory() as session:
                applied = update_job_status(session, job_id, status, **kwargs)
                session.commit()
            return applied
        except Exception as exc:
            last_exc = exc
            if attempt == 0:
                log.warning("Retrying job %s status update to %s", job_id, status)
    log.exception("Failed to update job %s to %s after retry", job_id, status)
    raise RuntimeError(
        f"Job {job_id} status update to {status!r} failed after 2 attempts"
    ) from last_exc


def _touch_heartbeat(factory, job_id: str) -> None:
    try:
        with factory() as session:
            update_job_heartbeat(session, job_id)
            session.commit()
    except Exception:
        log.error(
            "Heartbeat update failed for job %s — "
            "worker may be falsely declared stale if DB stays unreachable",
            job_id, exc_info=True,
        )


def _write_chat_job_heartbeat(db_factory, job_id: str) -> None:
    with db_factory() as session:
        update_job_heartbeat(session, job_id)
        session.commit()


async def _keep_chat_job_heartbeat(
    db_factory,
    job_id: str,
    *,
    interval_seconds: float = JOB_HEARTBEAT_INTERVAL_SECONDS,
) -> None:
    """Keep an inline chat request alive without using its request session."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            _write_chat_job_heartbeat(db_factory, job_id)
        except Exception:
            log.warning("Chat heartbeat update failed for job %s", job_id, exc_info=True)


async def _stop_chat_job_heartbeat(task: asyncio.Task[None], job_id: str) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        try:
            await task
        except Exception:
            log.warning("Chat heartbeat task failed for job %s", job_id, exc_info=True)


async def _cancel_chat_job(
    session: Session, heartbeat_task: asyncio.Task[None], job_id: str,
) -> None:
    try:
        _fail_chat_job(
            session,
            job_id,
            "Turn cancelled by the client.",
            "cancelled",
        )
    finally:
        await _stop_chat_job_heartbeat(heartbeat_task, job_id)


def _fail_chat_job(
    session: Session, job_id: str, error: str, error_type: str,
) -> None:
    session.rollback()
    update_job_status(
        session,
        job_id,
        JobStatus.FAILED,
        error=error,
        error_type=error_type,
    )
    session.commit()

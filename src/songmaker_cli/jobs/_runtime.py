"""Job runtime helpers — DB status updates, heartbeats, error sanitization."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any, Final

from sqlalchemy.orm import Session

from acestep_engine.errors import AudioDownloadError
from songmaker_cli.constants import (
    JOB_ERROR_REFERENCE_AUDIO_NOT_FOUND,
    JOB_ERROR_SONG_NOT_FOUND,
    JOB_ERROR_USER_LORA_UNAVAILABLE,
    JOB_ERROR_VERSION_NOT_FOUND,
)
from songmaker_cli.db.queries.jobs import (
    JobStatusUpdate,
    get_job,
    update_job_heartbeat,
    update_job_status,
)
from songmaker_cli.job_timing import JOB_HEARTBEAT_INTERVAL_SECONDS
from songmaker_cli.job_types import JOB_TERMINAL_STATUSES, JobStatus
from songmaker_cli.messages import Message, message
from songmaker_cli.scheduler import (
    NoCapacityError,
    WorkerTaskFailed,
)

log = logging.getLogger(__name__)

_UNEXPECTED_FAILURE: Final = message("jobFailure.unexpected")

_USER_FACING_ERRORS: tuple[tuple[type[Exception], Message], ...] = (
    (AudioDownloadError, message("jobFailure.audioDownloadFailed")),
    (ConnectionError, message("jobFailure.serverUnreachable")),
    (TimeoutError, message("jobFailure.generationTimedOut")),
    (NoCapacityError, message("jobFailure.noWorkers")),
    (RuntimeError, message("jobFailure.internal")),
)

JOB_ERROR_REFERENCE_DELETED_DURING_TAKE: Final[str] = (
    "The reference track was deleted while this take was generating."
)

_GENERATION_SETUP_MESSAGES: frozenset[str] = frozenset({
    JOB_ERROR_SONG_NOT_FOUND,
    JOB_ERROR_VERSION_NOT_FOUND,
    JOB_ERROR_REFERENCE_AUDIO_NOT_FOUND,
    JOB_ERROR_REFERENCE_DELETED_DURING_TAKE,
    JOB_ERROR_USER_LORA_UNAVAILABLE,
})


def generation_error_messages() -> frozenset[str]:
    """Expose the runtime-owned messages allowed on Generate reads."""
    return (
        _GENERATION_SETUP_MESSAGES
        | {_UNEXPECTED_FAILURE.sentence()}
        | {failure.sentence() for _, failure in _USER_FACING_ERRORS}
    )


class GenerationSetupError(Exception):
    pass


class ReferenceDeletedDuringTake(GenerationSetupError):
    """The take's reference row was gone when the take reached persistence; it ends the job."""


def _sanitize_error(
    exc: Exception, job_id: str, *, reported: Message | None = None,
) -> Message:
    """Log the raw failure in full; return the catalog message that words it for the musician.

    A worker's account of its task and a setup message the runtime vetted already are the
    musician's line: they come back as `reported`, by default `jobFailure.reported` with that
    text as its cause.
    """
    log.error("Job %s failed: %s", job_id, exc, exc_info=exc)
    reported = reported or message("jobFailure.reported", cause=str(exc))
    if isinstance(exc, WorkerTaskFailed):
        return reported
    if isinstance(exc, GenerationSetupError):
        return reported if str(exc) in _GENERATION_SETUP_MESSAGES else _UNEXPECTED_FAILURE
    for exc_type, failure in _USER_FACING_ERRORS:
        if isinstance(exc, exc_type):
            return failure
    return _UNEXPECTED_FAILURE


def _failure_sentence(exc: Exception, job_id: str) -> str:
    """The sentence a Text column (`jobs.error`) stores for a failure."""
    return _sanitize_error(exc, job_id).sentence()


def _job_is_terminal(factory, job_id: str) -> bool:
    with factory() as session:
        job = get_job(session, job_id)
        return job is None or job.status in JOB_TERMINAL_STATUSES


def _update_job(factory, job_id: str, status: JobStatus, **fields: Any) -> bool:
    update = JobStatusUpdate(status, **fields)
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            with factory() as session:
                applied = update_job_status(session, job_id, update)
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
        log.exception(
            "Heartbeat update failed for job %s — "
            "worker may be falsely declared stale if DB stays unreachable",
            job_id,
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
        JobStatusUpdate(JobStatus.FAILED, error=error, error_type=error_type),
    )
    session.commit()

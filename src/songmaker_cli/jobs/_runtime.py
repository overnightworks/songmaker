"""Job runtime helpers — DB status updates, heartbeats, error sanitization."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import timedelta
from typing import Any, Final

from sqlalchemy.orm import Session

from songmaker_acestep_engine.errors import AudioDownloadError
from songmaker_cli.db.queries.jobs import (
    JobStatusUpdate,
    get_job,
    update_job_heartbeat,
    update_job_status,
)
from songmaker_cli.db.queries.sentinels import unset_if_none
from songmaker_cli.job_payloads import JobPayload
from songmaker_cli.job_timing import GPU_HOLD_POLL_INTERVAL_SECONDS, JOB_HEARTBEAT_INTERVAL_SECONDS
from songmaker_cli.job_types import JOB_TERMINAL_STATUSES, JobStatus
from songmaker_cli.messages import Message, message
from songmaker_cli.scheduler import (
    NoCapacityError,
    WorkerTaskFailed,
)
from songmaker_cli.timestamps import utcnow

log = logging.getLogger(__name__)

_UNEXPECTED_FAILURE: Final = message("jobFailure.unexpected")

_USER_FACING_ERRORS: tuple[tuple[type[Exception], Message], ...] = (
    (AudioDownloadError, message("jobFailure.audioDownloadFailed")),
    (ConnectionError, message("jobFailure.serverUnreachable")),
    (TimeoutError, message("jobFailure.generationTimedOut")),
    (NoCapacityError, message("jobFailure.noWorkers")),
    (RuntimeError, message("jobFailure.internal")),
)

SONG_NOT_FOUND: Final = message("jobFailure.songNotFound")
VERSION_NOT_FOUND: Final = message("jobFailure.versionNotFound")
REFERENCE_AUDIO_NOT_FOUND: Final = message("jobFailure.referenceAudioNotFound")
REFERENCE_DELETED_DURING_TAKE: Final = message("jobFailure.referenceDeletedDuringTake")
USER_LORA_UNAVAILABLE: Final = message("jobFailure.voiceUnavailable")


class GenerationSetupError(Exception):
    """A setup failure the runtime words itself: it carries the catalog message of its reason."""

    def __init__(self, reason: Message) -> None:
        super().__init__(reason.sentence())
        self.reason = reason


class ReferenceDeletedDuringTake(GenerationSetupError):
    """The take's reference row was gone when the take reached persistence; it ends the job."""


def _sanitize_error(
    exc: Exception, job_id: str, *, reported: Message | None = None,
) -> Message:
    """Log the raw failure in full; return the catalog message that words it for the musician.

    A worker's account of its task is the musician's line: it comes back as `reported`, by
    default `jobFailure.workerReported` with that text as its cause. A setup error comes back as the
    message it carries.
    """
    log.error("Job %s failed: %s", job_id, exc, exc_info=exc)
    reported = reported or message("jobFailure.workerReported", cause=str(exc))
    if isinstance(exc, WorkerTaskFailed):
        return reported
    if isinstance(exc, GenerationSetupError):
        return exc.reason
    for exc_type, failure in _USER_FACING_ERRORS:
        if isinstance(exc, exc_type):
            return failure
    return _UNEXPECTED_FAILURE


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


def _defer_job(
    factory, job_id: str, reason: Message, payload: JobPayload | None = None,
) -> bool:
    """Put the job back in the queue for one poll of the GPU hold, saying why it waits.

    A job that comes back with fewer arguments than it left with passes them as ``payload``; the
    row is the only copy of the work, since a requeue sends no queue message.
    """
    return _update_job(
        factory, job_id, JobStatus.QUEUED, queue_reason_message=reason,
        payload=unset_if_none(payload),
        run_after=utcnow() + timedelta(seconds=GPU_HOLD_POLL_INTERVAL_SECONDS),
    )


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
    session: Session,
    heartbeat_task: asyncio.Task[None],
    job_id: str,
    failure: Message,
    error_type: str,
) -> None:
    try:
        _fail_chat_job(session, job_id, failure, error_type)
    finally:
        await _stop_chat_job_heartbeat(heartbeat_task, job_id)


def _fail_chat_job(
    session: Session, job_id: str, error_message: Message, error_type: str,
) -> None:
    session.rollback()
    update_job_status(
        session,
        job_id,
        JobStatusUpdate(JobStatus.FAILED, error_message=error_message, error_type=error_type),
    )
    session.commit()

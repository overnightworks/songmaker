"""Job runtime helpers — DB status updates, heartbeats, error sanitization."""

from __future__ import annotations

import logging

from acestep_engine.errors import AudioDownloadError
from songmaker_cli.constants import JOB_TERMINAL_STATUSES
from songmaker_cli.db.queries import get_job, update_job_heartbeat, update_job_status
from songmaker_cli.scheduler import (
    NoCapacityError,
    WorkerGenerationFailed,
    WorkerTaskFailed,
)

log = logging.getLogger(__name__)

_USER_FACING_ERRORS: tuple[tuple[type[Exception], str], ...] = (
    (AudioDownloadError, "Failed to download generated audio"),
    (ConnectionError, "ACE-Step server not reachable"),
    (TimeoutError, "Generation timed out"),
    (NoCapacityError, "No ACE-Step workers available"),
    (WorkerTaskFailed, "Worker generation failed"),
    (RuntimeError, "Internal error during processing"),
)


class GenerationSetupError(Exception):
    pass


_PASSTHROUGH_ERRORS: tuple[type[Exception], ...] = (
    GenerationSetupError,
    WorkerGenerationFailed,
)


def _sanitize_error(exc: Exception) -> str:
    """Return a user-safe error message, logging the full exception.

    A passthrough error's message is already written for the user — our
    own setup validation, or ACE-Step's cause for a failed generation —
    and is the only thing that makes the failure diagnosable, so it is
    kept verbatim.
    """
    if isinstance(exc, _PASSTHROUGH_ERRORS):
        return str(exc)
    for exc_type, message in _USER_FACING_ERRORS:
        if isinstance(exc, exc_type):
            return message
    return "An unexpected error occurred"


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

"""Query functions for background jobs."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from songmaker_cli.db.models import Job

log = logging.getLogger(__name__)


def create_job(session: Session, job_type: str, user_id: str | None = None) -> Job:
    job = Job(type=job_type, user_id=user_id)
    session.add(job)
    session.flush()
    return job


def count_user_jobs_in_window(
    session: Session, user_id: str, job_type: str, window_seconds: int = 3600,
) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    return (
        session.query(Job)
        .filter(
            Job.user_id == user_id,
            Job.type == job_type,
            Job.started_at >= cutoff,
        )
        .count()
    )


def count_user_active_jobs(session: Session, user_id: str) -> int:
    return (
        session.query(Job)
        .filter(
            Job.user_id == user_id,
            Job.status.in_(("queued", "running")),
        )
        .count()
    )


def count_total_queued_jobs(session: Session) -> int:
    return (
        session.query(Job)
        .filter(Job.status.in_(("queued", "running")))
        .count()
    )


def update_job_status(
    session: Session, job_id: str, status: str,
    progress: float = 0.0, error: str | None = None,
    error_type: str | None = None,
) -> None:
    job = session.query(Job).filter_by(id=job_id).first()
    if not job:
        return
    job.status = status
    job.progress = progress
    job.error = error
    job.error_type = error_type
    if status in ("completed", "failed"):
        job.completed_at = datetime.now(timezone.utc)
    session.flush()


def get_job(session: Session, job_id: str) -> Job | None:
    return session.query(Job).filter_by(id=job_id).first()


def recover_stale_jobs(session: Session) -> int:
    """Mark all running/queued jobs as failed on startup. Returns count recovered."""
    now = datetime.now(timezone.utc)
    stale = (
        session.query(Job)
        .filter(Job.status.in_(("queued", "running")))
        .all()
    )
    for job in stale:
        job.status = "failed"
        job.error = "Server restarted while job was in progress"
        job.error_type = "server_restart"
        job.completed_at = now
    session.flush()
    if stale:
        log.info("Recovered %d stale jobs", len(stale))
    return len(stale)

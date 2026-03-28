"""Query functions for background jobs."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
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


STALE_JOB_THRESHOLD_SECONDS = int(
    os.environ.get("STALE_JOB_THRESHOLD_SECONDS", 600),
)


def recover_stale_jobs_by_age(
    session: Session, threshold_seconds: int = STALE_JOB_THRESHOLD_SECONDS,
) -> int:
    """Mark running jobs older than threshold as failed. Returns count recovered."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=threshold_seconds)
    stale = (
        session.query(Job)
        .filter(
            Job.status == "running",
            Job.started_at < cutoff,
        )
        .all()
    )
    for job in stale:
        job.status = "failed"
        job.error = "Job timed out (exceeded maximum run time)"
        job.error_type = "stale_timeout"
        job.completed_at = now
    session.flush()
    if stale:
        log.info("Recovered %d stale jobs (threshold=%ds)", len(stale), threshold_seconds)
    return len(stale)


def job_counts_by_type_and_status(session: Session) -> dict[str, dict[str, int]]:
    """Return {type: {status: count}} for all jobs."""
    rows = (
        session.query(Job.type, Job.status, func.count())
        .group_by(Job.type, Job.status)
        .all()
    )
    result: dict[str, dict[str, int]] = {}
    for job_type, status, count in rows:
        result.setdefault(job_type, {})[status] = count
    return result


def _duration_seconds_expr(session: Session):
    """Duration expression in seconds.

    SQLite branch exists only for test databases (production uses PostgreSQL).
    """
    if session.bind.dialect.name == "sqlite":
        days = func.julianday(Job.completed_at) - func.julianday(Job.started_at)
        return days * 86400.0
    return func.extract("epoch", Job.completed_at - Job.started_at)


def job_duration_stats(session: Session) -> dict[str, float | None]:
    """Return avg/min/max duration in seconds for completed jobs."""
    duration_expr = _duration_seconds_expr(session)
    row = (
        session.query(
            func.avg(duration_expr),
            func.min(duration_expr),
            func.max(duration_expr),
        )
        .filter(Job.status == "completed", Job.completed_at.isnot(None))
        .one()
    )
    return {
        "avg": round(row[0], 1) if row[0] is not None else None,
        "min": round(row[1], 1) if row[1] is not None else None,
        "max": round(row[2], 1) if row[2] is not None else None,
    }

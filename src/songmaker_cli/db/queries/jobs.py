"""Query functions for background jobs."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
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


def count_user_active_jobs(session: Session, user_id: str, job_type: str | None = None) -> int:
    query = session.query(Job).filter(
        Job.user_id == user_id,
        Job.status.in_(("queued", "running")),
    )
    if job_type is not None:
        query = query.filter(Job.type == job_type)
    return query.count()


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
    worker_pid: int | None = None,
) -> None:
    job = session.query(Job).filter_by(id=job_id).first()
    if not job:
        return
    job.status = status
    job.progress = progress
    job.error = error
    job.error_type = error_type
    if worker_pid is not None:
        job.worker_pid = worker_pid
    if status in ("completed", "failed"):
        job.completed_at = datetime.now(timezone.utc)
    session.flush()


def get_job(session: Session, job_id: str) -> Job | None:
    return session.query(Job).filter_by(id=job_id).first()


def get_queue_position(session: Session, job: Job) -> int | None:
    """Return 1-based queue position for a queued job, or None if not queued."""
    if job.status != "queued":
        return None
    ahead = (
        session.query(Job)
        .filter(
            Job.status == "queued",
            Job.started_at < job.started_at,
        )
        .count()
    )
    return ahead + 1


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
    os.environ.get("STALE_JOB_THRESHOLD_SECONDS", 360),
)


def clear_stale_user_jobs(
    session: Session, user_id: str,
    threshold_seconds: int = STALE_JOB_THRESHOLD_SECONDS,
) -> int:
    """Mark stale running/queued jobs for a user as failed. Returns count cleared.

    Called at job submission time so users auto-unblock without waiting
    for the periodic cron cleanup.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=threshold_seconds)
    stale = (
        session.query(Job)
        .filter(
            Job.user_id == user_id,
            Job.status.in_(("queued", "running")),
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
        log.info("Cleared %d stale jobs for user %s", len(stale), user_id)
    return len(stale)


def _is_worker_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def recover_stale_jobs_by_age(
    session: Session, threshold_seconds: int = STALE_JOB_THRESHOLD_SECONDS,
) -> int:
    """Mark running/queued jobs older than threshold as failed. Returns count recovered.

    Jobs whose worker_pid is still alive are skipped — the worker may be
    legitimately slow (e.g. GPU mode switching, long scoring pipeline).
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=threshold_seconds)
    candidates = (
        session.query(Job)
        .filter(
            Job.status.in_(("queued", "running")),
            Job.started_at < cutoff,
        )
        .all()
    )
    recovered = 0
    for job in candidates:
        if _is_worker_alive(job.worker_pid):
            log.info("Skipping stale job %s — worker PID %d still alive", job.id, job.worker_pid)
            continue
        job.status = "failed"
        job.error = "Job timed out (exceeded maximum run time)"
        job.error_type = "stale_timeout"
        job.completed_at = now
        recovered += 1
    session.flush()
    if recovered:
        log.info("Recovered %d stale jobs (threshold=%ds)", recovered, threshold_seconds)
    return recovered


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


@dataclass(frozen=True)
class JobDurationStats:
    """Avg/min/max duration in seconds for completed jobs."""

    avg: float | None
    min: float | None
    max: float | None


def job_duration_stats(session: Session) -> JobDurationStats:
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
    return JobDurationStats(
        avg=round(row[0], 1) if row[0] is not None else None,
        min=round(row[1], 1) if row[1] is not None else None,
        max=round(row[2], 1) if row[2] is not None else None,
    )

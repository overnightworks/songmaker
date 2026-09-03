"""Query functions for background jobs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from songmaker_cli.constants import (
    JOB_ACTIVE_STATUSES,
    JOB_TERMINAL_STATUSES,
    JobStatus,
    JobType,
)
from songmaker_cli.db.models import Job

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StaleThresholds:
    queued_seconds: int
    heartbeat_seconds: int


def has_active_job_of_type(session: Session, job_type: str) -> bool:
    return (
        session.query(Job)
        .filter(Job.type == job_type, Job.status.in_(JOB_ACTIVE_STATUSES))
        .first()
    ) is not None


def create_job(
    session: Session, job_type: str, user_id: str | None = None, song_id: str | None = None,
) -> Job:
    job = Job(type=job_type, user_id=user_id, song_id=song_id)
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
        Job.status.in_(JOB_ACTIVE_STATUSES),
    )
    if job_type is not None:
        query = query.filter(Job.type == job_type)
    return query.count()


def count_total_queued_jobs(session: Session) -> int:
    return (
        session.query(Job)
        .filter(Job.status.in_(JOB_ACTIVE_STATUSES))
        .count()
    )


def update_job_status(
    session: Session, job_id: str, status: str,
    progress: float = 0.0, error: str | None = None,
    error_type: str | None = None,
    worker_pid: int | None = None,
) -> bool:
    job = (
        session.query(Job)
        .filter_by(id=job_id)
        .with_for_update()
        .first()
    )
    if job is None or job.status in JOB_TERMINAL_STATUSES:
        return False
    now = datetime.now(timezone.utc)
    job.status = status
    job.progress = progress
    job.error = error
    job.error_type = error_type
    if worker_pid is not None:
        job.worker_pid = worker_pid
    if status in (JobStatus.RUNNING, JobStatus.PARTIAL):
        job.heartbeat_at = now
    if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
        job.completed_at = now
    session.flush()
    return True


def update_job_heartbeat(session: Session, job_id: str) -> None:
    job = (
        session.query(Job)
        .filter_by(id=job_id)
        .with_for_update()
        .first()
    )
    if job is None or job.status in JOB_TERMINAL_STATUSES:
        return
    job.heartbeat_at = datetime.now(timezone.utc)
    session.flush()


def get_job(session: Session, job_id: str) -> Job | None:
    return session.query(Job).filter_by(id=job_id).first()


def get_last_generate_job_for_song(session: Session, song_id: str) -> Job | None:
    """Return the song's most recent generate/repaint/cover job, regardless
    of outcome.

    Used to hydrate the failure banner when a song is opened after the
    generating job's SSE stream is long gone (page reload, new visit): the
    caller checks whether this job is a FAILED one to show -- any newer job
    (queued, running, completed) means a failure, if any, is superseded.
    """
    return (
        session.query(Job)
        .filter(Job.song_id == song_id, Job.type == JobType.GENERATE)
        .order_by(Job.started_at.desc())
        .first()
    )


def lock_active_job(session: Session, job_id: str) -> Job | None:
    job = (
        session.query(Job)
        .filter_by(id=job_id)
        .with_for_update()
        .first()
    )
    if job is None or job.status in JOB_TERMINAL_STATUSES:
        return None
    return job


def get_queue_position(session: Session, job: Job) -> int | None:
    """Return 1-based queue position for a queued job, or None if not queued.

    Filtered by ``job.type`` — music and scoring queues are independent
    worker pools, so ordering across them is meaningless.
    """
    if job.status != JobStatus.QUEUED:
        return None
    ahead = (
        session.query(Job)
        .filter(
            Job.status == JobStatus.QUEUED,
            Job.type == job.type,
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
        .filter(Job.status.in_(JOB_ACTIVE_STATUSES))
        .all()
    )
    for job in stale:
        job.status = JobStatus.FAILED
        job.error = "Server restarted while job was in progress"
        job.error_type = "server_restart"
        job.completed_at = now
    session.flush()
    if stale:
        log.info("Recovered %d stale jobs", len(stale))
    return len(stale)


def clear_stale_user_jobs(
    session: Session, user_id: str,
    threshold_seconds: int | None = None,
) -> int:
    """Mark stale running/queued jobs for a user as failed. Returns count cleared.

    Called at job submission time so users auto-unblock without waiting
    for the periodic cron cleanup.
    """
    if threshold_seconds is None:
        from songmaker_cli.settings import get_settings
        threshold_seconds = get_settings().stale_job_threshold_seconds
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=threshold_seconds)
    stale = (
        session.query(Job)
        .filter(
            Job.user_id == user_id,
            Job.status.in_(JOB_ACTIVE_STATUSES),
            Job.started_at < cutoff,
        )
        .all()
    )
    for job in stale:
        job.status = JobStatus.FAILED
        job.error = "Job timed out (exceeded maximum run time)"
        job.error_type = "stale_timeout"
        job.completed_at = now
    session.flush()
    if stale:
        log.info("Cleared %d stale jobs for user %s", len(stale), user_id)
    return len(stale)


def _is_heartbeat_stale(job: Job, cutoff: datetime) -> bool:
    """Check if the job's heartbeat indicates a hung worker.

    heartbeat_at is now NOT NULL (backfilled from started_at on migration,
    populated on every insert via SQLAlchemy default). Old PID-based
    fallback removed — PID reuse on long-running containers made it
    unreliable.
    """
    hb = job.heartbeat_at
    if hb.tzinfo is None:
        hb = hb.replace(tzinfo=timezone.utc)
    return hb < cutoff


def _is_started_stale(job: Job, cutoff: datetime) -> bool:
    started_at = job.started_at
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return started_at < cutoff


def recover_stale_jobs_by_age(
    session: Session, threshold_seconds: int | None = None,
) -> int:
    """Mark running/queued jobs older than threshold as failed. Returns count recovered.

    Uses heartbeat_at to detect hung workers (alive but not progressing).
    """
    if threshold_seconds is None:
        from songmaker_cli.settings import get_settings
        threshold_seconds = get_settings().stale_job_threshold_seconds
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=threshold_seconds)
    candidates = (
        session.query(Job)
        .filter(
            Job.status.in_(JOB_ACTIVE_STATUSES),
            Job.started_at < cutoff,
        )
        .all()
    )
    recovered = 0
    for job in candidates:
        if not _is_heartbeat_stale(job, cutoff):
            log.info("Skipping stale job %s — recent heartbeat or worker alive", job.id)
            continue
        was_queued = job.status == JobStatus.QUEUED
        job.status = JobStatus.FAILED
        if was_queued:
            job.error = "No worker available — please retry."
            job.error_type = "no_worker_available"
        else:
            job.error = "Job timed out (exceeded maximum run time)"
            job.error_type = "stale_timeout"
        job.completed_at = now
        recovered += 1
    session.flush()
    if recovered:
        log.info("Recovered %d stale jobs (threshold=%ds)", recovered, threshold_seconds)
    return recovered


def recover_stale_jobs_by_type(session: Session, job_type: str) -> int:
    """Mark all running/queued jobs of a given type as failed. Returns count recovered."""
    now = datetime.now(timezone.utc)
    stale = (
        session.query(Job)
        .filter(
            Job.status.in_(JOB_ACTIVE_STATUSES),
            Job.type == job_type,
        )
        .all()
    )
    for job in stale:
        job.status = JobStatus.FAILED
        job.error = "Server restarted while job was in progress"
        job.error_type = "server_restart"
        job.completed_at = now
    session.flush()
    if stale:
        log.info("Recovered %d stale %s jobs", len(stale), job_type)
    return len(stale)


def recover_stale_jobs_by_age_and_type(
    session: Session, job_type: str,
    threshold_seconds: int | None = None,
    *,
    stale_thresholds: StaleThresholds | None = None,
    now: datetime | None = None,
) -> int:
    """Recover jobs with baseline defaults or explicit chat liveness thresholds."""
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if stale_thresholds is None:
        if threshold_seconds is None:
            from songmaker_cli.settings import get_settings
            threshold_seconds = get_settings().stale_job_threshold_seconds
        cutoff = now - timedelta(seconds=threshold_seconds)
        candidates = (
            session.query(Job)
            .filter(
                Job.status.in_(JOB_ACTIVE_STATUSES),
                Job.type == job_type,
                Job.started_at < cutoff,
            )
            .all()
        )
        recovered = 0
        for job in candidates:
            if not _is_heartbeat_stale(job, cutoff):
                log.info("Skipping stale job %s — recent heartbeat or worker alive", job.id)
                continue
            was_queued = job.status == JobStatus.QUEUED
            job.status = JobStatus.FAILED
            if was_queued:
                job.error = "No worker available — please retry."
                job.error_type = "no_worker_available"
            else:
                job.error = "Job timed out (exceeded maximum run time)"
                job.error_type = "stale_timeout"
            job.completed_at = now
            recovered += 1
        session.flush()
        if recovered:
            log.info(
                "Recovered %d stale %s jobs (threshold=%ds)",
                recovered, job_type, threshold_seconds,
            )
        return recovered

    queued_cutoff = now - timedelta(seconds=stale_thresholds.queued_seconds)
    heartbeat_cutoff = now - timedelta(seconds=stale_thresholds.heartbeat_seconds)
    candidates = (
        session.query(Job)
        .filter(
            Job.status.in_(JOB_ACTIVE_STATUSES),
            Job.type == job_type,
        )
        .all()
    )
    recovered = 0
    for job in candidates:
        if job.status == JobStatus.QUEUED:
            is_stale = _is_started_stale(job, queued_cutoff)
        else:
            is_stale = _is_heartbeat_stale(job, heartbeat_cutoff)
        if not is_stale:
            log.info("Skipping stale job %s — it is still making progress", job.id)
            continue
        was_queued = job.status == JobStatus.QUEUED
        job.status = JobStatus.FAILED
        if was_queued:
            job.error = "No worker available — please retry."
            job.error_type = "no_worker_available"
        elif job_type == JobType.CHAT:
            job.error = "Heartbeat lost — please retry."
            job.error_type = "heartbeat_lost"
        else:
            job.error = "Job timed out (exceeded maximum run time)"
            job.error_type = "stale_timeout"
        job.completed_at = now
        recovered += 1
    session.flush()
    if recovered:
        log.info(
            "Recovered %d stale %s jobs (queued=%ds, heartbeat=%ds)",
            recovered,
            job_type,
            stale_thresholds.queued_seconds,
            stale_thresholds.heartbeat_seconds,
        )
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


def last_job_failure_time(session: Session) -> datetime | None:
    """When the most recent failed job finished, or None if none ever did.

    Every path that marks a job FAILED also stamps completed_at, so the
    newest of those is the newest failure.
    """
    newest = (
        session.query(func.max(Job.completed_at))
        .filter(Job.status == JobStatus.FAILED)
        .scalar()
    )
    if newest is None:
        return None
    if newest.tzinfo is None:
        return newest.replace(tzinfo=timezone.utc)
    return newest


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
        .filter(Job.status == JobStatus.COMPLETED, Job.completed_at.isnot(None))
        .one()
    )
    return JobDurationStats(
        avg=round(row[0], 1) if row[0] is not None else None,
        min=round(row[1], 1) if row[1] is not None else None,
        max=round(row[2], 1) if row[2] is not None else None,
    )

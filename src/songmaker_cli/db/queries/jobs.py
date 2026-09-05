"""Query functions for background jobs."""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from songmaker_cli.constants import (
    JOB_ACTIVE_STATUSES,
    JOB_TERMINAL_STATUSES,
    JobStaleThresholds,
    JobStatus,
    JobType,
    stale_job_thresholds,
)
from songmaker_cli.db.models import Job
from songmaker_cli.settings import get_settings
from songmaker_cli.worker_liveness import WorkerLiveness, liveness_for_job_type

log = logging.getLogger(__name__)


def create_job(
    session: Session,
    job_type: str,
    user_id: str | None = None,
    song_id: str | None = None,
    album_id: str | None = None,
) -> Job:
    job = Job(type=job_type, user_id=user_id, song_id=song_id, album_id=album_id)
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


def count_cover_jobs_since(session: Session, album_id: str, since: datetime) -> int:
    return (
        session.query(Job)
        .filter(
            Job.album_id == album_id,
            Job.type == JobType.COVER,
            Job.started_at >= since,
        )
        .count()
    )


def has_active_cover_job(session: Session, album_id: str) -> bool:
    return (
        session.query(Job)
        .filter(
            Job.album_id == album_id,
            Job.type == JobType.COVER,
            Job.status.in_(JOB_ACTIVE_STATUSES),
        )
        .first()
        is not None
    )


def get_last_cover_job_for_album(session: Session, album_id: str) -> Job | None:
    return (
        session.query(Job)
        .filter(Job.album_id == album_id, Job.type == JobType.COVER)
        .order_by(Job.started_at.desc())
        .first()
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


def count_queued_generation_jobs(session: Session) -> int:
    return (
        session.query(Job)
        .filter(Job.status == JobStatus.QUEUED, Job.type == JobType.GENERATE)
        .count()
    )


def count_queued_lora_training_jobs(session: Session) -> int:
    """Count globally waiting LoRA trainings, excluding running jobs."""
    return (
        session.query(Job)
        .filter(Job.status == JobStatus.QUEUED, Job.type == JobType.LORA_TRAINING)
        .count()
    )


def claim_next_cover_job(session: Session) -> Job | None:
    """Atomically move the oldest queued cover job to running.

    The status predicate is deliberately repeated on the UPDATE.  Competing
    web processes may select the same candidate, but only one can change its
    queued row and receive it through RETURNING.
    """
    candidate_id = (
        session.query(Job.id)
        .filter(Job.type == JobType.COVER, Job.status == JobStatus.QUEUED)
        .order_by(Job.started_at.asc(), Job.id.asc())
        .limit(1)
        .scalar_subquery()
    )
    now = datetime.now(timezone.utc)
    claimed_id = session.execute(
        update(Job)
        .where(
            Job.id == candidate_id,
            Job.type == JobType.COVER,
            Job.status == JobStatus.QUEUED,
        )
        .values(status=JobStatus.RUNNING, heartbeat_at=now)
        .returning(Job.id),
    ).scalar_one_or_none()
    if claimed_id is None:
        return None
    session.flush()
    return session.get(Job, claimed_id)


def update_job_status(
    session: Session, job_id: str, status: str,
    progress: float = 0.0, error: str | None = None,
    error_type: str | None = None,
    queue_reason: str | None = None,
    worker_pid: int | None = None,
    current_epoch: int | None = None,
    train_epochs: int | None = None,
    training_started_at: datetime | None = None,
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
    job.queue_reason = queue_reason
    if current_epoch is not None:
        job.current_epoch = current_epoch
    if train_epochs is not None:
        job.train_epochs = train_epochs
    if training_started_at is not None:
        job.training_started_at = training_started_at
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
    session.flush()
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


@dataclass(frozen=True)
class QueuedJobVerdict:
    error: str
    error_type: str


def _queued_verdict(
    job: Job,
    thresholds: JobStaleThresholds,
    liveness: WorkerLiveness,
    now: datetime,
    max_queue_depth: int | None,
) -> QueuedJobVerdict | None:
    if thresholds.liveness_signal is None:
        liveness = WorkerLiveness.UNKNOWN
    if liveness is WorkerLiveness.DEAD:
        return QueuedJobVerdict(
            error="No worker alive for this job type — please retry.",
            error_type="no_worker_alive",
        )
    if liveness is WorkerLiveness.ALIVE:
        if max_queue_depth is None:
            max_queue_depth = get_settings().max_queue_depth
        full_queue_cutoff = now - timedelta(
            seconds=thresholds.full_queue_bound_seconds(max_queue_depth),
        )
        if _is_started_stale(job, full_queue_cutoff):
            return QueuedJobVerdict(
                error="Queued longer than a full queue could take — please retry.",
                error_type="queued_full_queue_bound",
            )
        return None
    age_cutoff = now - timedelta(seconds=thresholds.queued_seconds)
    if _is_started_stale(job, age_cutoff):
        return QueuedJobVerdict(
            error="Queued too long — please retry.",
            error_type="queued_too_long",
        )
    return None


def _is_started_stale(job: Job, cutoff: datetime) -> bool:
    started_at = job.started_at
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return started_at < cutoff


def _before_stale_job_recovery_update(_job: Job) -> None:
    """Provide a deterministic seam between stale-candidate read and update."""


def _recover_stale_job_if_unchanged(
    session: Session,
    job: Job,
    *,
    status: str,
    heartbeat_at: datetime | None,
    error: str,
    error_type: str,
    completed_at: datetime,
) -> bool:
    result = session.execute(
        update(Job)
        .where(
            Job.id == job.id,
            Job.status == status,
            Job.heartbeat_at.is_not_distinct_from(heartbeat_at),
        )
        .values(
            status=JobStatus.FAILED,
            error=error,
            error_type=error_type,
            completed_at=completed_at,
            queue_reason=None,
        )
        .execution_options(synchronize_session=False),
    )
    session.expire(job)
    if result.rowcount != 1:
        log.debug("Skipped stale-job recovery because job %s changed", job.id)
        return False
    return True


def recover_stale_jobs_by_type(
    session: Session,
    recoverable_statuses: Mapping[str, Collection[str]],
) -> dict[str, int]:
    """Fail restart-interrupted jobs and return recovery counts keyed by type.

    Each job type declares the active statuses a worker may recover at process
    startup or shutdown.  This keeps a queued job eligible to a new worker
    unless its owner explicitly says that queueing is unsafe to resume.
    """
    now = datetime.now(timezone.utc)
    recovered: dict[str, int] = {}
    for job_type, statuses in recoverable_statuses.items():
        stale = (
            session.query(Job)
            .filter(Job.type == job_type, Job.status.in_(statuses))
            .all()
        )
        for job in stale:
            job.status = JobStatus.FAILED
            job.error = "Server restarted while job was in progress"
            job.error_type = "server_restart"
            job.completed_at = now
            job.queue_reason = None
        if stale:
            recovered[job_type] = len(stale)
    session.flush()
    if recovered:
        log.info("Recovered stale jobs by type: %s", recovered)
    return recovered


def recover_stale_jobs_by_age_and_type(
    session: Session,
    *,
    user_id: str | None = None,
    now: datetime | None = None,
    worker_liveness: Mapping[JobType, WorkerLiveness] | None = None,
    max_queue_depth: int | None = None,
) -> dict[str, int]:
    """Recover stale jobs using the one per-type liveness policy.

    Queued jobs fail immediately when their execution worker is known dead.
    Unknown signals use the #446 age guard; alive signals allow one full queue
    before failing. The lifecycle reaper uses the configured global queue
    depth; a submission supplies its resolved per-user queue depth. Running
    jobs fail only when their heartbeat is old.
    ``user_id`` lets the submission path apply that exact policy before
    enforcing an active-job limit, without defining a second freshness bound.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    query = session.query(Job).filter(
        Job.status.in_(JOB_ACTIVE_STATUSES),
    )
    if user_id is not None:
        query = query.filter(Job.user_id == user_id)
    candidates = query.all()
    thresholds_by_type = stale_job_thresholds(get_settings().cover_executor)
    candidates_with_thresholds: list[tuple[Job, JobStaleThresholds]] = []
    for job in candidates:
        try:
            thresholds = thresholds_by_type[JobType(job.type)]
        except (KeyError, ValueError) as exc:
            raise RuntimeError(
                f"Active job {job.id} has no stale-job threshold for type {job.type!r}",
            ) from exc
        candidates_with_thresholds.append((job, thresholds))

    recovered_by_type: dict[str, int] = {}
    for job, thresholds in candidates_with_thresholds:
        status = job.status
        heartbeat_at = job.heartbeat_at
        if job.status == JobStatus.QUEUED:
            liveness = liveness_for_job_type(JobType(job.type), worker_liveness)
            verdict = _queued_verdict(
                job, thresholds, liveness, now, max_queue_depth,
            )
            if verdict is None:
                continue
            error = verdict.error
            error_type = verdict.error_type
        else:
            cutoff = now - timedelta(seconds=thresholds.heartbeat_seconds)
            if not _is_heartbeat_stale(job, cutoff):
                continue
            error = "Heartbeat lost — please retry."
            error_type = "heartbeat_lost"
        _before_stale_job_recovery_update(job)
        if not _recover_stale_job_if_unchanged(
            session,
            job,
            status=status,
            heartbeat_at=heartbeat_at,
            error=error,
            error_type=error_type,
            completed_at=now,
        ):
            continue
        recovered_by_type[job.type] = recovered_by_type.get(job.type, 0) + 1
    session.flush()
    if recovered_by_type:
        log.info(
            "Recovered %d stale job(s) by liveness policy: %s",
            sum(recovered_by_type.values()),
            recovered_by_type,
        )
    return recovered_by_type


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

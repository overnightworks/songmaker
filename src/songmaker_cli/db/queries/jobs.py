"""Query functions for background jobs."""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping
from dataclasses import KW_ONLY, dataclass, fields
from datetime import datetime, timedelta, timezone
from typing import Final

from sqlalchemy import and_, func, not_, or_, update
from sqlalchemy.orm import Session

from songmaker_cli.db.models import Job
from songmaker_cli.db.queries.sentinels import UNSET, _Unset
from songmaker_cli.job_timing import STALE_JOB_THRESHOLDS, JobStaleThresholds
from songmaker_cli.job_types import (
    JOB_ACTIVE_STATUSES,
    JOB_TERMINAL_STATUSES,
    AgentProblem,
    GenerationPhase,
    JobStatus,
    JobType,
)
from songmaker_cli.messages import Message, message
from songmaker_cli.settings import get_settings
from songmaker_cli.timestamps import aware_timestamp
from songmaker_cli.worker_liveness import WorkerLiveness, liveness_for_job_type

log = logging.getLogger(__name__)

_GENERATING_PHASES: Final = frozenset(
    {GenerationPhase.WRITING, GenerationPhase.RENDERING, GenerationPhase.SAVING_TAKE}
)


def create_job(
    session: Session,
    job_type: str,
    user_id: str | None = None,
    song_id: str | None = None,
    album_id: str | None = None,
    version_id: str | None = None,
    session_id: str | None = None,
    owner_id: str | None = None,
) -> Job:
    job = Job(
        type=job_type, user_id=user_id, song_id=song_id, album_id=album_id,
        version_id=version_id, session_id=session_id, owner_id=owner_id,
    )
    session.add(job)
    session.flush()
    return job


class ActiveJobError(Exception):
    """A queued or running job still points at the songs; their purge waits for a later run."""


def has_active_job_for_songs(
    session: Session, song_ids: Collection[str], album_id: str | None = None,
) -> bool:
    """True while a queued or running job points at one of the songs or at the album."""
    owner = Job.song_id.in_(song_ids)
    if album_id is not None:
        owner = or_(owner, Job.album_id == album_id)
    return session.query(
        session.query(Job).filter(owner, Job.status.in_(JOB_ACTIVE_STATUSES)).exists()
    ).scalar()


def has_active_job_for_version(session: Session, version_id: str) -> bool:
    return session.query(
        session.query(Job)
        .filter(Job.version_id == version_id, Job.status.in_(JOB_ACTIVE_STATUSES))
        .exists()
    ).scalar()


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


def claim_next_cover_job(session: Session, owner_id: str) -> Job | None:
    """Atomically move the oldest queued cover job to running, owned by ``owner_id``.

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
        .values(status=JobStatus.RUNNING, heartbeat_at=now, owner_id=owner_id)
        .returning(Job.id),
    ).scalar_one_or_none()
    if claimed_id is None:
        return None
    session.flush()
    return session.get(Job, claimed_id)


@dataclass(frozen=True)
class JobStatusUpdate:
    """One status write for a job; each field names the job column it writes.

    Progress, error, error type, the wait a busy refusal named and queue reason
    describe the job at this write, so leaving them out resets them. The remaining fields only some
    writers know; ``UNSET`` keeps what the job already holds.
    """

    status: JobStatus
    _: KW_ONLY
    progress: float = 0.0
    error: Message | None = None
    error_type: str | None = None
    retry_after_seconds: int | None = None
    queue_reason_message: Message | None = None
    owner_id: str | _Unset = UNSET
    current_epoch: int | _Unset = UNSET
    train_epochs: int | _Unset = UNSET
    training_started_at: datetime | _Unset = UNSET
    take_index: int | _Unset = UNSET
    take_count: int | _Unset = UNSET
    phase: GenerationPhase | _Unset = UNSET


def update_job_status(session: Session, job_id: str, update: JobStatusUpdate) -> bool:
    job = (
        session.query(Job)
        .filter_by(id=job_id)
        .execution_options(populate_existing=True)
        .with_for_update()
        .first()
    )
    if job is None or job.status in JOB_TERMINAL_STATUSES:
        return False
    now = datetime.now(timezone.utc)
    status = update.status
    _move_generation_start(job, status, update.phase, now)
    if _enters_running(job, status):
        job.phase = None
    if status == JobStatus.QUEUED:
        job.take_index = None
        job.take_count = None
    for column in fields(update):
        value = getattr(update, column.name)
        if value is not UNSET:
            setattr(job, column.name, _error_text(value) if column.name == "error" else value)
    if status in (JobStatus.RUNNING, JobStatus.PARTIAL):
        job.heartbeat_at = now
    if status in JOB_TERMINAL_STATUSES:
        _apply_terminal_values(job, now)
    session.flush()
    return True


def _error_text(error: Message | None) -> str | None:
    """The sentence the Text column `jobs.error` stores for a failure's message."""
    return None if error is None else error.sentence()


def _terminal_values(now: datetime) -> dict[str, object]:
    """The columns every write that ends a job sets."""
    return {
        "completed_at": now,
        "queue_reason_message": None,
        "generation_started_at": None,
        "session_id": None,
    }


def _apply_terminal_values(job: Job, now: datetime) -> None:
    for column, value in _terminal_values(now).items():
        setattr(job, column, value)


def _enters_running(job: Job, status: str) -> bool:
    return status == JobStatus.RUNNING and job.status != JobStatus.RUNNING


def _move_generation_start(
    job: Job, status: str, phase: GenerationPhase | _Unset, now: datetime,
) -> None:
    """Anchor the remaining-time estimate at the first generating phase.

    Each RUNNING entry starts without an anchor, so a requeue excludes the
    earlier queue time, and loading the model never counts: a cold start
    and a warm one reach the same progress in the same generating time.
    """
    if status != JobStatus.RUNNING or _enters_running(job, status):
        job.generation_started_at = None
    if (
        status == JobStatus.RUNNING
        and phase in _GENERATING_PHASES
        and job.generation_started_at is None
    ):
        job.generation_started_at = now


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
    caller decides whether its failure is recoverable; any newer attempt
    supersedes an older failure, regardless of outcome.
    """
    return (
        session.query(Job)
        .filter(Job.song_id == song_id, Job.type == JobType.GENERATE)
        .order_by(Job.started_at.desc())
        .first()
    )


def get_active_generate_job_for_song(session: Session, song_id: str) -> Job | None:
    """Return the song's newest queued/running generate job; used to
    recover the SSE stream after a reload."""
    return (
        session.query(Job)
        .filter(
            Job.song_id == song_id,
            Job.type == JobType.GENERATE,
            Job.status.in_(JOB_ACTIVE_STATUSES),
        )
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
    return job.heartbeat_at < cutoff


@dataclass(frozen=True)
class JobVerdict:
    error: Message
    error_type: str


JOB_ERROR_SERVER_RESTARTED: Final = JobVerdict(
    error=message("jobFailure.serverRestarted"), error_type="server_restart",
)


def _queued_verdict(
    job: Job,
    thresholds: JobStaleThresholds,
    liveness: WorkerLiveness,
    now: datetime,
    max_queue_depth: int | None,
) -> JobVerdict | None:
    if thresholds.liveness_signal is None:
        liveness = WorkerLiveness.UNKNOWN
    if liveness is WorkerLiveness.DEAD:
        return JobVerdict(
            error=message("jobFailure.noWorkerAlive"),
            error_type="no_worker_alive",
        )
    if liveness is WorkerLiveness.ALIVE:
        if max_queue_depth is None:
            max_queue_depth = get_settings().max_queue_depth
        full_queue_cutoff = now - timedelta(
            seconds=thresholds.full_queue_bound_seconds(max_queue_depth),
        )
        if _is_started_stale(job, full_queue_cutoff):
            return JobVerdict(
                error=message("jobFailure.queuedFullQueueBound"),
                error_type="queued_full_queue_bound",
            )
        return None
    age_cutoff = now - timedelta(seconds=thresholds.queued_seconds)
    if _is_started_stale(job, age_cutoff):
        return JobVerdict(
            error=message("jobFailure.queuedTooLong"),
            error_type="queued_too_long",
        )
    return None


def _is_started_stale(job: Job, cutoff: datetime) -> bool:
    return job.started_at < cutoff


def _before_stale_job_recovery_update(_job: Job) -> None:
    """Provide a deterministic seam between stale-candidate read and update."""


def _recover_stale_job_if_unchanged(
    session: Session,
    job: Job,
    *,
    status: str,
    heartbeat_at: datetime | None,
    error: Message,
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
            error=_error_text(error),
            error_type=error_type,
            **_terminal_values(completed_at),
        )
        .execution_options(synchronize_session=False),
    )
    session.expire(job)
    if result.rowcount != 1:
        log.debug("Skipped stale-job recovery because job %s changed", job.id)
        return False
    return True


def active_job_owner_ids(session: Session) -> set[str]:
    """The processes that own a queued or running job; a job without an owner names none."""
    return {
        owner_id
        for (owner_id,) in session.query(Job.owner_id)
        .filter(Job.owner_id.is_not(None), Job.status.in_(JOB_ACTIVE_STATUSES))
        .distinct()
    }


def _owner_gone_verdict(
    job: Job, owner_liveness: Mapping[str, WorkerLiveness] | None,
) -> JobVerdict | None:
    """Fail a job only for an owner read as DEAD; an owner the map lacks reads UNKNOWN."""
    if job.owner_id is None or owner_liveness is None:
        return None
    if owner_liveness.get(job.owner_id, WorkerLiveness.UNKNOWN) is WorkerLiveness.DEAD:
        return JOB_ERROR_SERVER_RESTARTED
    return None


def recover_jobs_of_dead_owners(
    session: Session, owner_liveness: Mapping[str, WorkerLiveness],
) -> dict[str, int]:
    """Fail the active jobs of every owner read as DEAD and return counts keyed by type."""
    if not owner_liveness:
        return {}
    now = datetime.now(timezone.utc)
    jobs = (
        session.query(Job)
        .filter(Job.owner_id.in_(list(owner_liveness)), Job.status.in_(JOB_ACTIVE_STATUSES))
        .all()
    )
    recovered: dict[str, int] = {}
    for job in jobs:
        verdict = _owner_gone_verdict(job, owner_liveness)
        if verdict is None:
            continue
        job_type = job.type
        if _recover_stale_job_if_unchanged(
            session, job, status=job.status, heartbeat_at=job.heartbeat_at,
            error=verdict.error, error_type=verdict.error_type,
            completed_at=now,
        ):
            recovered[job_type] = recovered.get(job_type, 0) + 1
    session.flush()
    if recovered:
        log.warning("Failed the jobs of owners that are gone: %s", recovered)
    return recovered


def recover_stale_jobs_by_age_and_type(
    session: Session,
    *,
    user_id: str | None = None,
    now: datetime | None = None,
    worker_liveness: Mapping[JobType, WorkerLiveness] | None = None,
    owner_liveness: Mapping[str, WorkerLiveness] | None = None,
    max_queue_depth: int | None = None,
) -> dict[str, int]:
    """Recover stale jobs using the one per-type liveness policy.

    Queued jobs fail immediately when their execution worker is known dead.
    Unknown signals use the #446 age guard; alive signals allow one full queue
    before failing. The lifecycle reaper uses the configured global queue
    depth; a submission supplies its resolved per-user queue depth. Running
    jobs fail only when their heartbeat is old. A job whose owner ``owner_liveness``
    reads as DEAD fails at once.
    ``user_id`` lets the submission path apply that exact policy before
    enforcing an active-job limit, without defining a second freshness bound.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    else:
        now = aware_timestamp(now)

    recovered_by_type: dict[str, int] = {}
    for job, thresholds in _active_jobs_with_thresholds(session, user_id):
        if _recover_stale_job(
            session, job, thresholds, now, worker_liveness, owner_liveness, max_queue_depth,
        ):
            recovered_by_type[job.type] = recovered_by_type.get(job.type, 0) + 1
    session.flush()
    if recovered_by_type:
        log.info(
            "Recovered %d stale job(s) by liveness policy: %s",
            sum(recovered_by_type.values()),
            recovered_by_type,
        )
    return recovered_by_type


def _active_jobs_with_thresholds(
    session: Session,
    user_id: str | None,
) -> list[tuple[Job, JobStaleThresholds]]:
    query = session.query(Job).filter(Job.status.in_(JOB_ACTIVE_STATUSES))
    if user_id is not None:
        query = query.filter(Job.user_id == user_id)
    candidates: list[tuple[Job, JobStaleThresholds]] = []
    for job in query.all():
        try:
            thresholds = STALE_JOB_THRESHOLDS[JobType(job.type)]
        except (KeyError, ValueError) as exc:
            raise RuntimeError(
                f"Active job {job.id} has no stale-job threshold for type {job.type!r}",
            ) from exc
        candidates.append((job, thresholds))
    return candidates


def _recover_stale_job(
    session: Session,
    job: Job,
    thresholds: JobStaleThresholds,
    now: datetime,
    worker_liveness: Mapping[JobType, WorkerLiveness] | None,
    owner_liveness: Mapping[str, WorkerLiveness] | None,
    max_queue_depth: int | None,
) -> bool:
    status = job.status
    heartbeat_at = job.heartbeat_at
    verdict = _owner_gone_verdict(job, owner_liveness) or _stale_job_verdict(
        job, thresholds, now, worker_liveness, max_queue_depth,
    )
    if verdict is None:
        return False
    _before_stale_job_recovery_update(job)
    return _recover_stale_job_if_unchanged(
        session,
        job,
        status=status,
        heartbeat_at=heartbeat_at,
        error=verdict.error,
        error_type=verdict.error_type,
        completed_at=now,
    )


def _stale_job_verdict(
    job: Job,
    thresholds: JobStaleThresholds,
    now: datetime,
    worker_liveness: Mapping[JobType, WorkerLiveness] | None,
    max_queue_depth: int | None,
) -> JobVerdict | None:
    if job.status == JobStatus.QUEUED:
        liveness = liveness_for_job_type(JobType(job.type), worker_liveness)
        return _queued_verdict(job, thresholds, liveness, now, max_queue_depth)
    cutoff = now - timedelta(seconds=thresholds.heartbeat_seconds)
    if not _is_heartbeat_stale(job, cutoff):
        return None
    return JobVerdict(message("jobFailure.tookTooLong"), "heartbeat_lost")


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


_AGENT_JOB_TYPES: Final = (JobType.CHAT, JobType.COVER)


def last_job_failure_time(session: Session) -> datetime | None:
    """When the most recent failed job finished, or None if none ever did.

    Every path that marks a job FAILED also stamps completed_at, so the
    newest of those is the newest failure. A co-writer turn or cover
    suggestion the gateway did not run (a named AgentProblem) is no failure
    of songmaker: the gateway's owner watches the gateway.
    """
    gateway_problem = and_(
        Job.type.in_(_AGENT_JOB_TYPES),
        Job.error_type.in_(list(AgentProblem)),
    )
    newest = (
        session.query(func.max(Job.completed_at))
        .filter(Job.status == JobStatus.FAILED, not_(gateway_problem))
        .scalar()
    )
    if newest is None:
        return None
    return newest


def _duration_seconds_expr():
    """Duration expression in seconds."""
    return func.extract("epoch", Job.completed_at - Job.started_at)


@dataclass(frozen=True)
class JobDurationStats:
    """Avg/min/max duration in seconds for completed jobs."""

    avg: float | None
    min: float | None
    max: float | None


def job_duration_stats(session: Session) -> JobDurationStats:
    """Return avg/min/max duration in seconds for completed jobs."""
    duration_expr = _duration_seconds_expr()
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

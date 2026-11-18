"""Shared infrastructure for arq workers.

Provides the WorkerBase class subclassed by MusicWorker and ScoringWorker.
Owns DB engine lifecycle, the worker's owner lease, orphan-file audit, and the
common arq startup/shutdown hooks. A web process fails the jobs of a worker
whose lease is gone; no worker fails another's jobs.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import threading
import uuid
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path
from typing import ClassVar

from logline import StepTimer, configure, unit_trace
from redis.asyncio import Redis as AsyncRedis
from tandem import WakeChannel

from songmaker_cli.arq_codec import TRACEPARENT_KWARG
from songmaker_cli.constants import ARQ_HEALTH_CHECK_INTERVAL_SECONDS
from songmaker_cli.db.database_url import connection_url_from_settings
from songmaker_cli.db.engine import init_db
from songmaker_cli.db.queries.jobs import claim_next_queued_job, claim_queued_job, get_job
from songmaker_cli.job_queue import ClaimedJob, app_wake_channel
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.redis_client import create_async_redis, stop_retrying
from songmaker_cli.settings import Settings, get_settings
from songmaker_cli.worker_liveness import JobOwner, keep_owner_lease, owner_leases

log = logging.getLogger(__name__)

JOB_ENDED_EVENT = "arq_job.ended"
JOB_FAILED_REASON = "job_failed"
JOB_STATUS_UNREADABLE_REASON = "status_unreadable"


def logged_job[Result](
    job_name: str,
    job: Callable[..., Awaitable[Result]],
    *,
    status_of: Callable[[str], JobStatus | None] | None = None,
) -> Callable[..., Awaitable[Result]]:
    """Wrap an arq job so it runs in its enqueuer's trace and writes its one ``arq_job.ended`` line.

    A job enqueued outside a trace, a cron job included, starts a trace of its own; the trace
    ends with the job, so a failed job leaves nothing for the next one.

    The line carries the job's function name and, for a queued job, its job id (the first
    argument; a cron job has none): ids only, never the job's content. A job records its result
    in its row and returns normally, so ``status_of`` names how that row reads once the job
    returned: ``failed`` ends the line as failed (reason ``job_failed``) and ``cancelled`` as
    cancelled; any other status, or none, leaves it ``ok``. A status that cannot be read never
    fails the job, which finished: the line ends as failed, reason ``status_unreadable``, as a
    warning, and a warning names the read's exception class.
    """

    @functools.wraps(job)
    async def run(ctx, *args, **kwargs) -> Result:
        fields = {"job_function": job_name}
        if args:
            fields["job_id"] = args[0]
        with unit_trace(kwargs.pop(TRACEPARENT_KWARG, None)):
            async with StepTimer(JOB_ENDED_EVENT, log, **fields) as timer:
                result = await job(ctx, *args, **kwargs)
                if status_of is not None and args:
                    status = await _read_status(status_of, args[0], timer)
                    if status is JobStatus.FAILED:
                        timer.fail(JOB_FAILED_REASON)
                    elif status is JobStatus.CANCELLED:
                        timer.end_cancelled()
                return result

    return run


async def _read_status(
    status_of: Callable[[str], JobStatus | None], job_id: str, timer: StepTimer
) -> JobStatus | None:
    try:
        return await asyncio.to_thread(status_of, job_id)
    except Exception as error:
        timer.handled()
        timer.fail(JOB_STATUS_UNREADABLE_REASON)
        log.warning(
            "arq_job.status_unreadable",
            extra={"job_id": job_id, "error_type": type(error).__name__},
        )
        return None


class WorkerBase:
    """Base class for arq workers.

    Subclasses set the ClassVars (service_name, job_types, queue_name, max_jobs) and add
    their own task methods. The instance owns the DB engine + factory and the
    process's owner id: its jobs carry the id from the moment they run, and its
    lease says the process lives.

    arq integration: instantiate once at module load, then expose the
    instance methods on a sibling WorkerSettings shim class so arq's
    inspection of `functions`, `on_startup`, `on_shutdown`, `cron_jobs`
    finds bound methods.
    """

    service_name: ClassVar[str]
    job_types: ClassVar[tuple[str, ...]]
    queue_name: ClassVar[str]
    max_jobs: ClassVar[int]
    health_check_interval: ClassVar[int] = ARQ_HEALTH_CHECK_INTERVAL_SECONDS

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._db_engine = None
        self._db_factory = None
        self._db_lock = threading.Lock()
        self.owner_id = str(uuid.uuid4())
        self.owner: JobOwner
        self._owner_redis: AsyncRedis | None = None
        self.wake_channel: WakeChannel
        self._lease_stack: AsyncExitStack | None = None

    def worker_name(self) -> str:
        """Return the stable, human-readable name derived from owned job types."""
        return "+".join(self.job_types)

    def get_db_factory(self):
        with self._db_lock:
            if self._db_factory is None:
                self._db_factory = init_db(connection_url_from_settings(self._settings))
                self._db_engine = self._db_factory.kw["bind"]
        return self._db_factory

    def audio_dir(self) -> Path:
        return Path(self._settings.audio_dir)

    def data_dir(self) -> Path:
        return Path(self._settings.data_dir)

    def job_status(self, job_id: str) -> JobStatus | None:
        """The status the job's row holds now, or none for a job without a row."""
        with self.get_db_factory()() as session:
            job = get_job(session, job_id)
            return None if job is None else JobStatus(job.status)

    def claim_job(self, job_id: str) -> bool:
        """Claim the job's queued row for this process; false means another delivery owns it.

        A job delivered twice, retried by the queue or already ended finds no queued row, and
        its handler returns without running it.
        """
        with self.get_db_factory()() as session:
            claimed = claim_queued_job(session, job_id, self.owner)
            session.commit()
        if not claimed:
            log.info("Job %s is not queued; this delivery runs nothing", job_id)
        return claimed

    def claim_next_job(self, job_type: JobType) -> ClaimedJob | None:
        """Claim the job of ``job_type`` that is due first for this process, or none.

        The row's arguments are read before the claim commits, so the caller needs no session.
        """
        with self.get_db_factory()() as session:
            job = claim_next_queued_job(session, self.owner, job_type)
            claimed = None if job is None else ClaimedJob(job.id, job.payload)
            session.commit()
        return claimed

    async def on_startup(self, ctx) -> None:
        configure(self.service_name)

        log.info("%s worker starting up...", self.worker_name())
        # arq runs on_startup inside the task a stop signal cancels, so its end marks the stop.
        asyncio.current_task().add_done_callback(lambda _stopped: stop_retrying(ctx["redis"]))
        # Opening the database may wait for it to start; the lease says "alive" only after.
        self.get_db_factory()
        await self._start_owner_lease()
        log.info("%s worker ready", self.worker_name())

    async def on_shutdown(self, _ctx) -> None:
        if self._lease_stack is not None:
            await self._release_owner_lease()

        if self._db_engine is not None:
            self._db_engine.dispose()
            log.info("Database connection pool disposed")

    async def _start_owner_lease(self) -> None:
        """Say this process lives, on a client of its own: arq's has no retry and no timeouts."""
        self._owner_redis = create_async_redis(self._settings.redis_url)
        self.wake_channel = app_wake_channel(self._owner_redis)
        self._lease_stack = AsyncExitStack()
        try:
            self.owner = await self._lease_stack.enter_async_context(
                keep_owner_lease(owner_leases(self._owner_redis), self.owner_id),
            )
        except BaseException:
            await self._owner_redis.aclose()
            raise

    async def _release_owner_lease(self) -> None:
        """End the lease so a web process fails this worker's jobs within one tick."""
        await self._lease_stack.aclose()
        await self._owner_redis.aclose()

    def audit_orphaned_files(self) -> None:
        """Log audio files on disk that have no matching DB record."""
        try:
            self._audit_orphaned_files_inner()
        except Exception:
            log.warning("Orphaned file audit failed", exc_info=True)

    def _audit_orphaned_files_inner(self) -> None:
        from songmaker_cli.db.queries.generations import all_generation_paths

        audio_dir = self.audio_dir()
        if not audio_dir.exists():
            return

        with self.get_db_factory()() as session:
            known_paths = all_generation_paths(session)

        orphans: list[Path] = []
        for user_dir in audio_dir.iterdir():
            if not user_dir.is_dir():
                continue
            for audio_file in user_dir.iterdir():
                if audio_file.suffix not in (".mp3", ".wav"):
                    continue
                rel = f"{user_dir.name}/{audio_file.name}"
                if rel not in known_paths:
                    orphans.append(audio_file)

        if orphans:
            log.warning(
                "Found %d orphaned audio files (no DB record): %s",
                len(orphans),
                ", ".join(str(f) for f in orphans[:10]),
            )

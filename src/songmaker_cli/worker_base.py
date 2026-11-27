"""Shared infrastructure for the workers.

Provides the WorkerBase class subclassed by MusicWorker and ScoringWorker.
Owns DB engine lifecycle, the worker's owner lease and readiness file, orphan-file audit and
``run``, the process's whole life from the stop-signal handlers to the end of the lease.
A web process fails the jobs of a worker whose lease is gone; no worker fails another's jobs.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import signal
import threading
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import AsyncExitStack
from pathlib import Path
from typing import ClassVar, Final

from logline import StepTimer, configure, unit_trace
from redis.asyncio import Redis as AsyncRedis
from tandem import WakeChannel

from songmaker_cli.constants import WORKER_READINESS_FILE
from songmaker_cli.db.database_url import connection_url_from_settings
from songmaker_cli.db.engine import init_db
from songmaker_cli.db.queries.jobs import (
    JobStatusUpdate,
    claim_next_queued_job,
    get_job,
    update_job_status,
)
from songmaker_cli.job_payloads import JobPayload
from songmaker_cli.job_queue import (
    QUEUE_POLL_INTERVAL_SECONDS,
    ClaimedJob,
    JobQueue,
    app_wake_channel,
    serve_queue,
)
from songmaker_cli.job_types import JobStatus, JobType, WorkerLivenessSignal
from songmaker_cli.messages import Message, message
from songmaker_cli.redis_client import create_async_redis
from songmaker_cli.settings import Settings, get_settings
from songmaker_cli.worker_liveness import (
    JobOwner,
    keep_kind_lease,
    keep_owner_lease,
    owner_leases,
    pid_one_start_ticks,
    worker_kind_leases,
    write_readiness_file,
)

log = logging.getLogger(__name__)

JOB_ENDED_EVENT = "queued_job.ended"
JOB_STATUS_UNREADABLE_EVENT = "queued_job.status_unreadable"
CRON_ENDED_EVENT = "cron_job.ended"
JOB_FAILED_REASON = "job_failed"
JOB_STATUS_UNREADABLE_REASON = "status_unreadable"
STOP_SIGNALS: Final = (signal.SIGINT, signal.SIGTERM)


class WorkerStopRequested(Exception):
    """A stop signal arrived while the worker waited for its database."""


def logged_job[Result](
    job_name: str,
    job: Callable[[str, JobPayload | None], Awaitable[Result]],
    *,
    status_of: Callable[[str], JobStatus | None] | None = None,
) -> Callable[[str, JobPayload | None], Awaitable[Result]]:
    """Wrap a claimed job so it runs in a trace of its own and writes one ``queued_job.ended`` line.

    The trace ends with the job, so a failed job leaves nothing for the next one.

    The line carries the job's function name and its job id: ids only, never the job's content.
    A job records its result in its row and returns normally, so ``status_of`` names how that
    row reads once the job returned: ``failed`` ends the line as failed (reason ``job_failed``)
    and ``cancelled`` as cancelled; any other status, or none, leaves it ``ok``. A status that
    cannot be read never fails the job, which finished: the line ends as failed, reason
    ``status_unreadable``, as a warning, and a warning names the read's exception class.
    """

    @functools.wraps(job)
    async def run(job_id: str, payload: JobPayload | None) -> Result:
        with unit_trace(None):
            async with StepTimer(
                JOB_ENDED_EVENT, log, job_function=job_name, job_id=job_id,
            ) as timer:
                result = await job(job_id, payload)
                if status_of is not None:
                    status = await _read_status(status_of, job_id, timer)
                    if status is JobStatus.FAILED:
                        timer.fail(JOB_FAILED_REASON)
                    elif status is JobStatus.CANCELLED:
                        timer.end_cancelled()
                return result

    return run


def logged_cron[Result](
    cron_name: str, body: Callable[[], Awaitable[Result]],
) -> Callable[[], Awaitable[Result]]:
    """Wrap a cron's body so it writes its one ``cron_job.ended`` line naming the cron.

    A cron runs inside the handling trace of the claiming loop that hands it over: this line
    opens no trace of its own but nests in that handling's span, so a failure line shares its
    ``trace_id`` with the loop's lines for the same key.
    """

    @functools.wraps(body)
    async def run() -> Result:
        async with StepTimer(CRON_ENDED_EVENT, log, job_function=cron_name):
            return await body()

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
            JOB_STATUS_UNREADABLE_EVENT,
            extra={"job_id": job_id, "error_type": type(error).__name__},
        )
        return None


class WorkerBase:
    """Base class of the workers that claim their queue's jobs from PostgreSQL.

    Subclasses set the ClassVars (service_name, queue, job_types, lease_kind) and implement
    ``run_claimed``. The instance owns the DB engine + factory and the process's owner id: its
    jobs carry the id from the moment they run, and its lease says the process lives.

    ``run`` is the entry point of the worker's process.
    """

    service_name: ClassVar[str]
    queue: ClassVar[JobQueue]
    job_types: ClassVar[tuple[JobType, ...]]
    lease_kind: ClassVar[WorkerLivenessSignal | None] = None
    """The worker kind whose lease family this worker renews beside its owner lease, if any.
    A kind without a row in ``WORKER_KINDS`` fails the worker's start."""

    def __init__(
        self, settings: Settings | None = None, *, readiness_file: Path = WORKER_READINESS_FILE,
    ) -> None:
        self._settings = settings or get_settings()
        self._readiness_file = readiness_file
        self._db_engine = None
        self._db_factory = None
        self._db_lock = threading.Lock()
        self.owner_id = str(uuid.uuid4())
        self.owner: JobOwner
        self._owner_redis: AsyncRedis
        self.wake_channel: WakeChannel
        self._lease_stack: AsyncExitStack | None = None
        self._stop_requested = threading.Event()
        self._places: asyncio.Semaphore

    def worker_name(self) -> str:
        """Return the stable, human-readable name derived from owned job types."""
        return "+".join(self.job_types)

    def get_db_factory(self):
        with self._db_lock:
            if self._db_factory is None:
                self._db_factory = init_db(
                    connection_url_from_settings(self._settings),
                    sleep=self._wait_unless_stop_requested,
                )
                self._db_engine = self._db_factory.kw["bind"]
        return self._db_factory

    def _wait_unless_stop_requested(self, seconds: float) -> None:
        """Pause between two tries to reach the database; a stop request ends the wait."""
        if self._stop_requested.wait(seconds):
            raise WorkerStopRequested

    def audio_dir(self) -> Path:
        return Path(self._settings.audio_dir)

    def data_dir(self) -> Path:
        return Path(self._settings.data_dir)

    def job_status(self, job_id: str) -> JobStatus | None:
        """The status the job's row holds now, or none for a job without a row."""
        with self.get_db_factory()() as session:
            job = get_job(session, job_id)
            return None if job is None else JobStatus(job.status)

    def fail_job(self, job_id: str, reason: Message, error_type: str) -> None:
        """End a claimed job as failed, saying why in the stored message and error type."""
        with self.get_db_factory()() as session:
            update_job_status(session, job_id, JobStatusUpdate(
                JobStatus.FAILED, error_message=reason, error_type=error_type,
            ))
            session.commit()

    def fail_job_without_payload(self, job_id: str) -> None:
        """End a claimed job whose row holds no arguments to run it with."""
        log.error("Job %s has no payload to run", job_id)
        self.fail_job(job_id, message("jobFailure.unexpected"), "setup_error")

    def claim_next_job(self) -> ClaimedJob | None:
        """Claim the job of this worker's types that is due first for this process, or none.

        The row's arguments are read before the claim commits, so the caller needs no session.
        """
        with self.get_db_factory()() as session:
            job = claim_next_queued_job(session, self.owner, *self.job_types)
            claimed = None if job is None else ClaimedJob(job.id, JobType(job.type), job.payload)
            session.commit()
        return claimed

    async def run_claimed(self, claimed: ClaimedJob) -> None:
        raise NotImplementedError

    async def serve_queued_jobs(self) -> None:
        """Claim and run the jobs queued for this worker until cancelled."""
        await serve_queue(
            self.wake_channel, self.queue,
            claim=self.claim_next_job, run=self.run_claimed,
            places=self._places, poll_interval=QUEUE_POLL_INTERVAL_SECONDS,
            drain_seconds=self._settings.arq_drain_timeout,
        )

    def servings(self) -> tuple[Coroutine[None, None, None], ...]:
        """What ``run`` serves together until a stop signal or the failure of one of them."""
        return (self.serve_queued_jobs(),)

    async def run(self) -> None:
        """Serve as a process: handle stop signals, start, serve until stopped, then stop.

        The stop-signal handlers are installed before ``start``, so a signal while the worker
        waits for its database or opens its lease ends it through ``stop`` like one while it
        serves. The servings are the tasks of one group: a stop cancels each once, which lets a
        running job drain, and a serving that raises cancels the others and ends the worker with
        its error, since a worker that serves only part of its work while its lease says it lives
        would be a silent failure. The database and the lease end only after every serving has.
        """
        lifecycle = asyncio.create_task(self._start_serve_and_stop())
        loop = asyncio.get_running_loop()
        for stop_signal in STOP_SIGNALS:
            loop.add_signal_handler(stop_signal, self._request_stop, lifecycle)
        try:
            await lifecycle
        except asyncio.CancelledError:
            if not self._stop_requested.is_set():
                raise
        finally:
            for stop_signal in STOP_SIGNALS:
                loop.remove_signal_handler(stop_signal)

    def _request_stop(self, lifecycle: asyncio.Task[None]) -> None:
        """Cancel the lifecycle once; a second cancel would cut the drain of its running jobs."""
        self._stop_requested.set()
        if not lifecycle.cancelling():
            lifecycle.cancel()

    async def _start_serve_and_stop(self) -> None:
        try:
            await self.start()
            async with asyncio.TaskGroup() as group:
                for serving in self.servings():
                    group.create_task(serving)
        finally:
            await self.stop()

    async def start(self) -> None:
        """Say which start this worker is, open the database, then say this process lives."""
        configure(self.service_name)

        log.info("%s worker starting up...", self.worker_name())
        write_readiness_file(self._readiness_file, self.owner_id, pid_one_start_ticks())
        # Opening the database may wait for it to start, in a thread so that a stop signal
        # reaches the loop; the lease says "alive" only after.
        await asyncio.to_thread(self.get_db_factory)
        await self._start_owner_lease()
        log.info("%s worker ready", self.worker_name())

    async def stop(self) -> None:
        if self._lease_stack is not None:
            await self._release_owner_lease()

        if self._db_engine is not None:
            self._db_engine.dispose()
            log.info("Database connection pool disposed")

    async def _start_owner_lease(self) -> None:
        """Say this process lives, on a client of its own with retries and timeouts.

        The wake channel gets a second client: its quiet subscription must not end on the
        owner client's socket timeout.
        """
        self._owner_redis = create_async_redis(self._settings.redis_url)
        wake_redis = create_async_redis(self._settings.redis_url, follows_wakes=True)
        self.wake_channel = app_wake_channel(wake_redis)
        self._lease_stack = AsyncExitStack()
        self._lease_stack.push_async_callback(wake_redis.aclose)
        try:
            self.owner = await self._lease_stack.enter_async_context(
                keep_owner_lease(owner_leases(self._owner_redis), self.owner_id),
            )
            if self.lease_kind is not None:
                await self._lease_stack.enter_async_context(
                    keep_kind_lease(
                        worker_kind_leases(self._owner_redis, self.lease_kind), self.owner_id,
                    ),
                )
        except BaseException:
            await self._owner_redis.aclose()
            await self._lease_stack.aclose()
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

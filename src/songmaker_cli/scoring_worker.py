"""Scoring worker — claims score jobs from their rows and runs them.

Started as a separate process:
    python -m songmaker_cli.arq_worker songmaker_cli.scoring_worker.ScoringWorkerSettings

arq hosts the process (its health key says the worker lives) and carries the ``score``
function for messages that web processes of the previous release still enqueue.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from functools import partial
from types import FrameType

from arq import func

from songmaker_cli.arq_codec import deserialize_arq, serialize_arq
from songmaker_cli.constants import ARQ_SCORING_QUEUE_NAME, SCORING_SERVICE_NAME
from songmaker_cli.db.queries.jobs import JobStatusUpdate, update_job_status
from songmaker_cli.job_payloads import ScorePayload
from songmaker_cli.job_queue import (
    QUEUE_POLL_INTERVAL_SECONDS,
    ClaimedJob,
    JobQueue,
    serve_queue,
)
from songmaker_cli.job_types import JobFunction, JobStatus, JobType
from songmaker_cli.jobs import run_scoring_job
from songmaker_cli.messages import message
from songmaker_cli.redis_client import build_arq_redis_settings
from songmaker_cli.settings import get_settings
from songmaker_cli.worker_base import WorkerBase, logged_job

log = logging.getLogger(__name__)


def stop_claiming(queue_task: asyncio.Task[None]) -> None:
    """Cancel the claiming loop once; a second cancel would cut the drain of its running jobs."""
    if not queue_task.cancelling():
        queue_task.cancel()


class ScoringWorker(WorkerBase):
    service_name = SCORING_SERVICE_NAME
    job_types = (JobType.SCORE,)
    queue_name = ARQ_SCORING_QUEUE_NAME

    def __init__(self, settings=None) -> None:
        super().__init__(settings)
        self._queue_task: asyncio.Task[None] | None = None
        # The one capacity of the process: the loop and the arq handler both take a place.
        self._places = asyncio.Semaphore(self._settings.scoring_max_jobs)
        self._run_logged = logged_job(
            JobFunction.SCORE, self._run_claimed, status_of=self.job_status,
        )

    async def score(self, _ctx, job_id, gen_id, scorers):
        """The arq message of a web process that still enqueues score jobs."""
        async with self._places:
            if not self.claim_job(job_id):
                return
            await self._score(job_id, gen_id, scorers)

    async def run_claimed(self, claimed: ClaimedJob) -> None:
        await self._run_logged(None, claimed.job_id, claimed.payload)

    async def _run_claimed(self, _ctx, job_id: str, payload) -> None:
        if not isinstance(payload, ScorePayload):
            log.error("Score job %s has no score payload", job_id)
            await asyncio.to_thread(self._fail_without_payload, job_id)
            return
        scorers = None if payload.scorers is None else list(payload.scorers)
        await self._score(job_id, payload.gen_id, scorers)

    def _fail_without_payload(self, job_id: str) -> None:
        with self.get_db_factory()() as session:
            update_job_status(session, job_id, JobStatusUpdate(
                JobStatus.FAILED, error_message=message("jobFailure.unexpected"),
                error_type="setup_error",
            ))
            session.commit()

    async def _score(self, job_id, gen_id, scorers) -> None:
        await asyncio.to_thread(
            run_scoring_job,
            job_id, gen_id, scorers,
            db_factory=self.get_db_factory(), audio_dir=self.audio_dir(),
            owner=self.owner, device=self._settings.scoring_device,
        )

    async def serve_queued_jobs(self) -> None:
        """Claim and run the queued score jobs until cancelled."""
        await serve_queue(
            self.wake_channel, JobQueue.SCORE,
            claim=partial(self.claim_next_job, JobType.SCORE), run=self.run_claimed,
            places=self._places, poll_interval=QUEUE_POLL_INTERVAL_SECONDS,
            drain_seconds=self._settings.arq_drain_timeout,
        )

    async def on_startup(self, ctx) -> None:
        from songmaker_cli.scoring.subprocess_runner import (
            ScorerProcess,
            set_scorer_process,
        )

        scorer = ScorerProcess()
        set_scorer_process(scorer)

        await super().on_startup(ctx)
        self._queue_task = asyncio.create_task(self.serve_queued_jobs())
        self.stop_claiming_on_stop_signal(self._queue_task)
        log.info("Scorer subprocess manager initialized")

    def stop_claiming_on_stop_signal(self, queue_task: asyncio.Task[None]) -> None:
        """End the claiming when a stop signal arrives, not when arq has drained its own jobs.

        arq stops picking its messages at the signal but runs on_shutdown only after they
        ended or ``job_completion_wait`` passed; without this the loop would go on starting
        jobs until then. The event loop reads signals from its wakeup descriptor, so arq's handler
        still runs beside this one.
        """
        loop = asyncio.get_running_loop()

        def stop(_signal_number: int, _frame: FrameType | None) -> None:
            loop.call_soon_threadsafe(stop_claiming, queue_task)

        for stop_signal in (signal.SIGINT, signal.SIGTERM):
            signal.signal(stop_signal, stop)

    async def on_shutdown(self, ctx) -> None:
        from songmaker_cli.scoring.subprocess_runner import get_scorer_process

        if self._queue_task is not None:
            stop_claiming(self._queue_task)
            await asyncio.gather(self._queue_task, return_exceptions=True)

        try:
            get_scorer_process().shutdown()
            log.info("Scorer subprocess shut down")
        except RuntimeError:
            pass

        await super().on_shutdown(ctx)


_settings = get_settings()
_scoring_worker = ScoringWorker(_settings)


class ScoringWorkerSettings:
    functions = [
        func(
            logged_job(
                JobFunction.SCORE, _scoring_worker.score, status_of=_scoring_worker.job_status,
            ),
            name=JobFunction.SCORE,
        ),
    ]
    on_startup = _scoring_worker.on_startup
    on_shutdown = _scoring_worker.on_shutdown
    job_serializer = staticmethod(serialize_arq)
    job_deserializer = staticmethod(deserialize_arq)
    redis_settings = build_arq_redis_settings(_settings.redis_url, ride_out_outage=True)
    queue_name = ScoringWorker.queue_name
    max_jobs = _settings.scoring_max_jobs
    job_timeout = _settings.arq_job_timeout
    job_completion_wait = _settings.arq_drain_timeout
    health_check_interval = ScoringWorker.health_check_interval
    cron_jobs = []

"""arq scoring worker — runs scoring jobs.

Started as a separate process:
    arq songmaker_cli.scoring_worker.ScoringWorkerSettings
"""

from __future__ import annotations

import asyncio
import logging
import os

from arq import cron

from songmaker_cli.constants import (
    ARQ_SCORING_QUEUE_NAME,
    RECOVERY_LOCK_SCORING_KEY,
    JobType,
)
from songmaker_cli.jobs import run_scoring_job
from songmaker_cli.worker_base import WorkerBase, build_redis_settings

log = logging.getLogger(__name__)

_SCORING_DEVICE_DEFAULT = "cpu"


class ScoringWorker(WorkerBase):
    job_type = JobType.SCORE
    recovery_lock_key = RECOVERY_LOCK_SCORING_KEY
    queue_name = ARQ_SCORING_QUEUE_NAME
    max_jobs = int(os.environ.get("SCORING_MAX_JOBS", "1"))

    async def score(self, ctx, job_id, gen_id, scorers):
        if not self.check_job_still_valid(job_id):
            return

        import structlog
        structlog.contextvars.bind_contextvars(job_id=job_id, task=JobType.SCORE)

        device = os.environ.get("SCORING_DEVICE", _SCORING_DEVICE_DEFAULT)
        await asyncio.to_thread(
            run_scoring_job,
            job_id, gen_id, scorers,
            db_factory=self.get_db_factory(), audio_dir=self.audio_dir(),
            device=device,
        )

    async def on_startup(self, ctx) -> None:
        from songmaker_cli.scoring.subprocess_runner import (
            ScorerProcess,
            set_scorer_process,
        )

        scorer = ScorerProcess()
        set_scorer_process(scorer)
        log.info("Scorer subprocess manager initialized")

        await super().on_startup(ctx)

    async def on_shutdown(self, ctx) -> None:
        from songmaker_cli.scoring.subprocess_runner import get_scorer_process

        try:
            get_scorer_process().shutdown()
            log.info("Scorer subprocess shut down")
        except RuntimeError:
            pass

        await super().on_shutdown(ctx)


_scoring_worker = ScoringWorker()


class ScoringWorkerSettings:
    functions = [_scoring_worker.score]
    on_startup = _scoring_worker.on_startup
    on_shutdown = _scoring_worker.on_shutdown
    redis_settings = build_redis_settings()
    queue_name = ScoringWorker.queue_name
    max_jobs = ScoringWorker.max_jobs
    job_timeout = ScoringWorker.job_timeout
    job_completion_wait = ScoringWorker.drain_timeout
    health_check_interval = ScoringWorker.health_check_interval
    cron_jobs = [
        cron(
            _scoring_worker.cleanup_stale_cron,
            minute={i for i in range(0, 60, 2)},
            second={0},
        ),
    ]

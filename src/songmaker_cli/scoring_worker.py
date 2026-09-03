"""arq scoring worker — runs scoring jobs.

Started as a separate process:
    arq songmaker_cli.scoring_worker.ScoringWorkerSettings
"""

from __future__ import annotations

import asyncio
import logging

from arq import cron, func

from songmaker_cli.constants import (
    ARQ_SCORING_QUEUE_NAME,
    RECOVERY_LOCK_SCORING_KEY,
    JobFunction,
    JobType,
)
from songmaker_cli.jobs import run_scoring_job
from songmaker_cli.settings import get_settings
from songmaker_cli.worker_base import WorkerBase, build_redis_settings

log = logging.getLogger(__name__)


class ScoringWorker(WorkerBase):
    job_types = (JobType.SCORE,)
    recovery_lock_key = RECOVERY_LOCK_SCORING_KEY
    queue_name = ARQ_SCORING_QUEUE_NAME

    async def score(self, ctx, job_id, gen_id, scorers):
        if not self.check_job_still_valid(job_id):
            return

        import structlog
        structlog.contextvars.bind_contextvars(job_id=job_id, task=JobType.SCORE)

        await asyncio.to_thread(
            run_scoring_job,
            job_id, gen_id, scorers,
            db_factory=self.get_db_factory(), audio_dir=self.audio_dir(),
            device=self._settings.scoring_device,
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


_settings = get_settings()
_scoring_worker = ScoringWorker(_settings)


class ScoringWorkerSettings:
    functions = [func(_scoring_worker.score, name=JobFunction.SCORE)]
    on_startup = _scoring_worker.on_startup
    on_shutdown = _scoring_worker.on_shutdown
    redis_settings = build_redis_settings(_settings)
    queue_name = ScoringWorker.queue_name
    max_jobs = _settings.scoring_max_jobs
    job_timeout = _settings.arq_job_timeout
    job_completion_wait = _settings.arq_drain_timeout
    health_check_interval = ScoringWorker.health_check_interval
    cron_jobs = [
        cron(
            _scoring_worker.cleanup_stale_cron,
            minute={i for i in range(0, 60, 2)},
            second={0},
        ),
    ]

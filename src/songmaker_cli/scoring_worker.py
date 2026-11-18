"""arq scoring worker — runs scoring jobs.

Started as a separate process:
    python -m songmaker_cli.arq_worker songmaker_cli.scoring_worker.ScoringWorkerSettings
"""

from __future__ import annotations

import asyncio
import logging

from arq import func

from songmaker_cli.arq_codec import deserialize_arq, serialize_arq
from songmaker_cli.constants import ARQ_SCORING_QUEUE_NAME, SCORING_SERVICE_NAME
from songmaker_cli.job_types import JobFunction, JobType
from songmaker_cli.jobs import run_scoring_job
from songmaker_cli.redis_client import build_arq_redis_settings
from songmaker_cli.settings import get_settings
from songmaker_cli.worker_base import WorkerBase, logged_job

log = logging.getLogger(__name__)


class ScoringWorker(WorkerBase):
    service_name = SCORING_SERVICE_NAME
    job_types = (JobType.SCORE,)
    queue_name = ARQ_SCORING_QUEUE_NAME

    async def score(self, _ctx, job_id, gen_id, scorers):
        if not self.claim_job(job_id):
            return

        await asyncio.to_thread(
            run_scoring_job,
            job_id, gen_id, scorers,
            db_factory=self.get_db_factory(), audio_dir=self.audio_dir(),
            owner=self.owner, device=self._settings.scoring_device,
        )

    async def on_startup(self, ctx) -> None:
        from songmaker_cli.scoring.subprocess_runner import (
            ScorerProcess,
            set_scorer_process,
        )

        scorer = ScorerProcess()
        set_scorer_process(scorer)

        await super().on_startup(ctx)
        log.info("Scorer subprocess manager initialized")

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

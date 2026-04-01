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
    RECOVERY_LOCK_TTL_SECONDS,
)
from songmaker_cli.jobs import run_scoring_job
from songmaker_cli.worker_base import (
    DRAIN_TIMEOUT_SECONDS,
    HEALTH_CHECK_INTERVAL_SECONDS,
    JOB_TIMEOUT_SECONDS,
    _audio_dir,
    _get_db_factory,
    build_redis_settings,
    check_job_still_valid,
    common_shutdown,
    common_startup,
)

log = logging.getLogger(__name__)

_IMPORT_TIME_REDIS_URL = os.environ.get("REDIS_URL")
_SCORING_DEVICE_DEFAULT = "cpu"


async def score(ctx, job_id, gen_id, scorers):
    if not check_job_still_valid(job_id):
        return

    import structlog
    structlog.contextvars.bind_contextvars(job_id=job_id, task="score")

    device = os.environ.get("SCORING_DEVICE", _SCORING_DEVICE_DEFAULT)
    await asyncio.to_thread(
        run_scoring_job,
        job_id, gen_id, scorers,
        db_factory=_get_db_factory(), audio_dir=_audio_dir(),
        device=device,
    )


async def cleanup_stale(ctx):
    from songmaker_cli.db.queries import recover_stale_jobs_by_age_and_type

    db_factory = _get_db_factory()
    with db_factory() as session:
        count = recover_stale_jobs_by_age_and_type(session, "score")
        if count:
            session.commit()


async def on_startup(ctx):
    await common_startup(ctx, _IMPORT_TIME_REDIS_URL)

    log.info("Scoring worker starting up...")

    from songmaker_cli.scoring.subprocess_runner import ScorerProcess, set_scorer_process
    scorer = ScorerProcess()
    set_scorer_process(scorer)
    log.info("Scorer subprocess manager initialized")

    redis = ctx["redis"]
    if await redis.set(RECOVERY_LOCK_SCORING_KEY, "1", ex=RECOVERY_LOCK_TTL_SECONDS, nx=True):
        try:
            from songmaker_cli.db.queries import recover_stale_jobs_by_type

            db_factory = _get_db_factory()
            with db_factory() as session:
                recovered = recover_stale_jobs_by_type(session, "score")
                if recovered:
                    log.info("Recovered %d stale score jobs", recovered)
                session.commit()
        finally:
            await redis.delete(RECOVERY_LOCK_SCORING_KEY)
    else:
        log.info("Stale job recovery skipped — another worker holds the lock")

    log.info("Scoring worker ready")


async def on_shutdown(ctx):
    redis = ctx["redis"]

    from songmaker_cli.scoring.subprocess_runner import get_scorer_process
    try:
        get_scorer_process().shutdown()
        log.info("Scorer subprocess shut down")
    except RuntimeError:
        pass

    await common_shutdown(RECOVERY_LOCK_SCORING_KEY, "score", redis)


class ScoringWorkerSettings:
    functions = [score]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = build_redis_settings()
    queue_name = ARQ_SCORING_QUEUE_NAME
    max_jobs = int(os.environ.get("SCORING_MAX_JOBS", "1"))
    job_timeout = JOB_TIMEOUT_SECONDS
    job_completion_wait = DRAIN_TIMEOUT_SECONDS
    health_check_interval = HEALTH_CHECK_INTERVAL_SECONDS
    cron_jobs = [
        cron(cleanup_stale, minute={i for i in range(0, 60, 2)}, second={0}),
    ]

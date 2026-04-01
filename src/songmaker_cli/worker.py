"""arq worker — backwards-compatible shim.

Delegates to music_worker and scoring_worker for task implementations.
Use music_worker.MusicWorkerSettings or scoring_worker.ScoringWorkerSettings
for new deployments.

Started as a separate process:
    arq songmaker_cli.worker.WorkerSettings
"""

from __future__ import annotations

import logging
import os
import threading

from arq import cron

from songmaker_cli.constants import (
    ACTIVE_MODEL_REDIS_KEY,
    ACTIVE_MODEL_TTL_SECONDS,
    RECOVERY_LOCK_KEY,
    RECOVERY_LOCK_TTL_SECONDS,
)
from songmaker_cli.db.queries import recover_stale_jobs
from songmaker_cli.music_worker import (
    _publish_acestep_status,
    generate,
    reinitialize_acestep,
)
from songmaker_cli.scoring_worker import score
from songmaker_cli.worker_base import (
    DRAIN_TIMEOUT_SECONDS,
    HEALTH_CHECK_INTERVAL_SECONDS,
    JOB_TIMEOUT_SECONDS,
    _get_db_factory,
    build_redis_settings,
    common_startup,
)

log = logging.getLogger(__name__)

_acestep_manager = None
_acestep_lock = threading.Lock()

_LEGACY_WORKER_DEPRECATION = (
    "Using legacy combined worker — migrate to music_worker/scoring_worker"
)

_MAX_CONCURRENT_JOBS = 1
_IMPORT_TIME_REDIS_URL = os.environ.get("REDIS_URL")


async def cleanup_stale(ctx):
    from songmaker_cli.db.queries import recover_stale_jobs_by_age

    db_factory = _get_db_factory()
    with db_factory() as session:
        count = recover_stale_jobs_by_age(session)
        if count:
            session.commit()
    mgr = _require_acestep_manager()
    model = mgr.active_model
    if model:
        await ctx["redis"].set(ACTIVE_MODEL_REDIS_KEY, model, ex=ACTIVE_MODEL_TTL_SECONDS)
    await _publish_acestep_status(ctx["redis"])


def _require_acestep_manager():
    with _acestep_lock:
        mgr = _acestep_manager
    if mgr is None:
        raise RuntimeError("ACE-Step manager not initialized — on_startup may have failed")
    return mgr


async def on_startup(ctx):
    log.warning(_LEGACY_WORKER_DEPRECATION)

    await common_startup(ctx, _IMPORT_TIME_REDIS_URL)

    log.info("Worker starting up...")

    from songmaker_cli.acestep_manager import AceStepManager
    mgr = AceStepManager()
    with _acestep_lock:
        global _acestep_manager
        _acestep_manager = mgr
    mgr.ensure()
    mgr.refresh_cached_model()

    from songmaker_cli.scoring.subprocess_runner import ScorerProcess, set_scorer_process
    scorer = ScorerProcess()
    set_scorer_process(scorer)
    log.info("Scorer subprocess manager initialized")

    model = mgr.active_model
    log.info("ACE-Step model: %s", model or "unknown")
    if model:
        await ctx["redis"].set(ACTIVE_MODEL_REDIS_KEY, model, ex=ACTIVE_MODEL_TTL_SECONDS)

    redis = ctx["redis"]
    if await redis.set(RECOVERY_LOCK_KEY, "1", ex=RECOVERY_LOCK_TTL_SECONDS, nx=True):
        try:
            db_factory = _get_db_factory()
            with db_factory() as session:
                recovered = recover_stale_jobs(session)
                if recovered:
                    log.info("Recovered %d stale jobs", recovered)
                session.commit()
        finally:
            await redis.delete(RECOVERY_LOCK_KEY)
    else:
        log.info("Stale job recovery skipped — another worker holds the lock")

    await _publish_acestep_status(ctx["redis"])
    log.info("Worker ready")


async def on_shutdown(ctx):
    redis = ctx["redis"]
    await redis.delete(ACTIVE_MODEL_REDIS_KEY)
    if await redis.set(RECOVERY_LOCK_KEY, "1", ex=RECOVERY_LOCK_TTL_SECONDS, nx=True):
        try:
            db_factory = _get_db_factory()
            with db_factory() as session:
                recovered = recover_stale_jobs(session)
                if recovered:
                    log.warning("Shutdown: marked %d in-progress jobs as failed", recovered)
                session.commit()
        finally:
            await redis.delete(RECOVERY_LOCK_KEY)
    else:
        log.warning("Shutdown recovery skipped — another worker holds the lock")

    from songmaker_cli.worker_base import _db_engine
    if _db_engine is not None:
        _db_engine.dispose()
        log.info("Database connection pool disposed")

    from songmaker_cli.scoring.subprocess_runner import get_scorer_process
    try:
        get_scorer_process().shutdown()
        log.info("Scorer subprocess shut down")
    except RuntimeError:
        pass

    if _acestep_manager:
        _acestep_manager.stop()


class WorkerSettings:
    functions = [generate, score, reinitialize_acestep]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = build_redis_settings()
    max_jobs = _MAX_CONCURRENT_JOBS
    job_timeout = JOB_TIMEOUT_SECONDS
    job_completion_wait = DRAIN_TIMEOUT_SECONDS
    health_check_interval = HEALTH_CHECK_INTERVAL_SECONDS
    cron_jobs = [
        cron(cleanup_stale, minute={i for i in range(0, 60, 2)}, second={0}),
    ]

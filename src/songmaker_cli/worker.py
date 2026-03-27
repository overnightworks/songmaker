"""arq worker — runs GPU-bound generation and scoring jobs.

Started as a separate process:
    arq songmaker_cli.worker.WorkerSettings
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from arq import cron
from arq.connections import RedisSettings

from songmaker_cli.constants import ACTIVE_MODEL_REDIS_KEY
from songmaker_cli.db.engine import init_db, resolve_database_url
from songmaker_cli.db.queries import get_job, recover_stale_jobs, recover_stale_jobs_by_age
from songmaker_cli.jobs import run_generation_job, run_scoring_job

log = logging.getLogger(__name__)

_db_factory = None
_acestep_manager = None
_current_mode: str | None = None

JOB_TIMEOUT_SECONDS = int(os.environ.get("ARQ_JOB_TIMEOUT", "300"))
HEALTH_CHECK_INTERVAL_SECONDS = 30
TERMINAL_STATUSES = frozenset({"completed", "partial", "failed"})


def _get_db_factory():
    global _db_factory
    if _db_factory is None:
        _db_factory = init_db(resolve_database_url(_output_dir()))
    return _db_factory


def _output_dir() -> Path:
    return Path(os.environ.get("OUTPUT_DIR", "_output"))


async def generate(ctx, job_id, song_id, version_id, count, user_id):
    db_factory = _get_db_factory()

    with db_factory() as session:
        job = get_job(session, job_id)
        if not job or job.status in TERMINAL_STATUSES:
            return

    global _current_mode
    if _current_mode != "generate":
        _acestep_manager.prepare_generate_mode()
        _current_mode = "generate"
        model = _acestep_manager.active_model
        if model:
            await ctx["redis"].set(ACTIVE_MODEL_REDIS_KEY, model)

    import structlog
    structlog.contextvars.bind_contextvars(job_id=job_id, task="generate")

    run_generation_job(
        job_id, song_id, version_id, count, user_id,
        db_factory=db_factory, output_dir=_output_dir(),
    )


async def score(ctx, job_id, gen_id, scorers):
    db_factory = _get_db_factory()

    with db_factory() as session:
        job = get_job(session, job_id)
        if not job or job.status in TERMINAL_STATUSES:
            return

    global _current_mode
    if _current_mode != "score":
        _acestep_manager.prepare_score_mode()
        _current_mode = "score"

    import structlog
    structlog.contextvars.bind_contextvars(job_id=job_id, task="score")

    run_scoring_job(
        job_id, gen_id, scorers,
        db_factory=db_factory, output_dir=_output_dir(),
    )


async def cleanup_stale(ctx):
    db_factory = _get_db_factory()
    with db_factory() as session:
        count = recover_stale_jobs_by_age(session)
        if count:
            session.commit()


async def on_startup(ctx):
    global _acestep_manager
    from songmaker_cli.acestep_manager import AceStepManager
    _acestep_manager = AceStepManager()
    _acestep_manager.start()
    _acestep_manager.wait_for_health()
    _acestep_manager.refresh_cached_model()

    model = _acestep_manager.active_model
    if model:
        await ctx["redis"].set(ACTIVE_MODEL_REDIS_KEY, model)

    db_factory = _get_db_factory()
    with db_factory() as session:
        recover_stale_jobs(session)
        session.commit()


async def on_shutdown(ctx):
    if _acestep_manager:
        _acestep_manager.stop()


class WorkerSettings:
    functions = [generate, score]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    )
    max_jobs = 1
    job_timeout = JOB_TIMEOUT_SECONDS
    health_check_interval = HEALTH_CHECK_INTERVAL_SECONDS
    cron_jobs = [
        cron(cleanup_stale, hour=None, minute={0, 15, 30, 45}),
    ]

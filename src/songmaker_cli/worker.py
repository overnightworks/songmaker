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

from songmaker_cli.constants import ACTIVE_MODEL_REDIS_KEY, AUDIO_ROOT, DATA_ROOT
from songmaker_cli.db.engine import init_db, resolve_database_url
from songmaker_cli.db.queries import get_job, recover_stale_jobs, recover_stale_jobs_by_age
from songmaker_cli.jobs import run_generation_job, run_scoring_job

log = logging.getLogger(__name__)

_db_factory = None
_db_engine = None
_acestep_manager = None

JOB_TIMEOUT_SECONDS = int(os.environ.get("ARQ_JOB_TIMEOUT", "300"))
HEALTH_CHECK_INTERVAL_SECONDS = 30
TERMINAL_STATUSES = frozenset({"completed", "partial", "failed"})


def _get_db_factory():
    global _db_factory, _db_engine
    if _db_factory is None:
        _db_factory = init_db(resolve_database_url())
        _db_engine = _db_factory.kw["bind"]
    return _db_factory


def _audio_dir() -> Path:
    return Path(os.environ.get("AUDIO_DIR", AUDIO_ROOT))


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", DATA_ROOT))


def _require_acestep_manager():
    if _acestep_manager is None:
        raise RuntimeError("ACE-Step manager not initialized — on_startup may have failed")
    return _acestep_manager


async def generate(ctx, job_id, song_id, version_id, count, user_id):
    db_factory = _get_db_factory()

    with db_factory() as session:
        job = get_job(session, job_id)
        if not job or job.status in TERMINAL_STATUSES:
            return

    mgr = _require_acestep_manager()
    mgr.prepare_generate_mode()
    model = mgr.active_model
    if model:
        await ctx["redis"].set(ACTIVE_MODEL_REDIS_KEY, model)

    import structlog
    structlog.contextvars.bind_contextvars(job_id=job_id, task="generate")

    run_generation_job(
        job_id, song_id, version_id, count, user_id,
        db_factory=db_factory, audio_dir=_audio_dir(), data_dir=_data_dir(),
    )


async def score(ctx, job_id, gen_id, scorers):
    db_factory = _get_db_factory()

    with db_factory() as session:
        job = get_job(session, job_id)
        if not job or job.status in TERMINAL_STATUSES:
            return

    mgr = _require_acestep_manager()
    mgr.prepare_score_mode()

    import structlog
    structlog.contextvars.bind_contextvars(job_id=job_id, task="score")

    run_scoring_job(
        job_id, gen_id, scorers,
        db_factory=db_factory, audio_dir=_audio_dir(),
    )


async def cleanup_stale(ctx):
    db_factory = _get_db_factory()
    with db_factory() as session:
        count = recover_stale_jobs_by_age(session)
        if count:
            session.commit()


async def on_startup(ctx):
    from songmaker_cli.config import find_project_root
    from songmaker_cli.logging_config import configure_logging
    from songmaker_cli.server import _load_env_file

    project_root = find_project_root(Path.cwd()) or Path.cwd()
    _load_env_file(project_root)
    configure_logging()

    log.info("Worker starting up...")

    global _acestep_manager
    from songmaker_cli.acestep_manager import AceStepManager
    _acestep_manager = AceStepManager()
    _acestep_manager.ensure()
    _acestep_manager.refresh_cached_model()

    model = _acestep_manager.active_model
    log.info("ACE-Step model: %s", model or "unknown")
    if model:
        await ctx["redis"].set(ACTIVE_MODEL_REDIS_KEY, model)

    db_factory = _get_db_factory()
    with db_factory() as session:
        recovered = recover_stale_jobs(session)
        if recovered:
            log.info("Recovered %d stale jobs", recovered)
        session.commit()

    log.info("Worker ready")


async def on_shutdown(ctx):
    if _db_engine is not None:
        _db_engine.dispose()
        log.info("Database connection pool disposed")

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

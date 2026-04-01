"""arq worker — runs GPU-bound generation and scoring jobs.

Started as a separate process:
    arq songmaker_cli.worker.WorkerSettings
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from arq import cron
from arq.connections import RedisSettings

from songmaker_cli.constants import (
    ACESTEP_STATUS_REDIS_KEY,
    ACESTEP_STATUS_TTL_SECONDS,
    ACTIVE_MODEL_REDIS_KEY,
    AUDIO_ROOT,
    DATA_ROOT,
    RECOVERY_LOCK_KEY,
    RECOVERY_LOCK_TTL_SECONDS,
    REDIS_URL_MISMATCH_WARNING,
)
from songmaker_cli.db.engine import init_db, resolve_database_url
from songmaker_cli.db.queries import get_job, recover_stale_jobs, recover_stale_jobs_by_age
from songmaker_cli.jobs import run_generation_job, run_scoring_job

log = logging.getLogger(__name__)

_db_factory = None
_db_engine = None
_db_lock = threading.Lock()
_acestep_manager = None
_acestep_lock = threading.Lock()

JOB_TIMEOUT_SECONDS = int(os.environ.get("ARQ_JOB_TIMEOUT", "300"))
DRAIN_TIMEOUT_SECONDS = int(os.environ.get("ARQ_DRAIN_TIMEOUT", "300"))
HEALTH_CHECK_INTERVAL_SECONDS = 30
TERMINAL_STATUSES = frozenset({"completed", "partial", "failed", "cancelled"})


def _get_db_factory():
    global _db_factory, _db_engine
    with _db_lock:
        if _db_factory is None:
            _db_factory = init_db(resolve_database_url())
            _db_engine = _db_factory.kw["bind"]
    return _db_factory


def _audio_dir() -> Path:
    return Path(os.environ.get("AUDIO_DIR", AUDIO_ROOT))


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", DATA_ROOT))


def _require_acestep_manager():
    with _acestep_lock:
        mgr = _acestep_manager
    if mgr is None:
        raise RuntimeError("ACE-Step manager not initialized — on_startup may have failed")
    return mgr


async def generate(ctx, job_id, song_id, version_id, count, user_id, seed=None):
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
        seed=seed,
    )


async def score(ctx, job_id, gen_id, scorers):
    db_factory = _get_db_factory()

    with db_factory() as session:
        job = get_job(session, job_id)
        if not job or job.status in TERMINAL_STATUSES:
            return

    import structlog
    structlog.contextvars.bind_contextvars(job_id=job_id, task="score")

    run_scoring_job(
        job_id, gen_id, scorers,
        db_factory=db_factory, audio_dir=_audio_dir(),
    )


async def reinitialize_acestep(ctx):
    import json
    from urllib.request import Request, urlopen

    from songmaker_cli.acestep_manager import _ACESTEP_PORT

    mgr = _require_acestep_manager()
    acestep_url = f"http://localhost:{_ACESTEP_PORT}/v1/reinitialize"
    req = Request(
        acestep_url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST",
    )
    with urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    if data.get("code") != 200:
        raise RuntimeError(f"ACE-Step reinitialize failed: {data}")
    mgr.refresh_cached_model()
    model = mgr.active_model
    if model:
        await ctx["redis"].set(ACTIVE_MODEL_REDIS_KEY, model)
    await _publish_acestep_status(ctx["redis"])


async def _publish_acestep_status(redis) -> None:
    import json
    from urllib.request import Request, urlopen

    from songmaker_cli.acestep_manager import _ACESTEP_PORT

    try:
        req = Request(f"http://localhost:{_ACESTEP_PORT}/health", method="GET")
        with urlopen(req, timeout=5) as resp:
            health = json.loads(resp.read())

        req2 = Request(f"http://localhost:{_ACESTEP_PORT}/v1/stats", method="GET")
        with urlopen(req2, timeout=5) as resp:
            stats = json.loads(resp.read())

        status = {
            "online": True,
            "model": health.get("data", {}).get("loaded_model"),
            "lm_model": health.get("data", {}).get("loaded_lm_model"),
            "jobs": stats.get("data", {}).get("jobs", {}),
        }
    except Exception:
        status = {"online": False, "model": None, "lm_model": None, "jobs": {}}

    await redis.set(
        ACESTEP_STATUS_REDIS_KEY, json.dumps(status), ex=ACESTEP_STATUS_TTL_SECONDS,
    )


async def cleanup_stale(ctx):
    db_factory = _get_db_factory()
    with db_factory() as session:
        count = recover_stale_jobs_by_age(session)
        if count:
            session.commit()
    await _publish_acestep_status(ctx["redis"])


async def on_startup(ctx):
    assert WorkerSettings.max_jobs == _MAX_CONCURRENT_JOBS, (
        f"max_jobs must be {_MAX_CONCURRENT_JOBS} — GPU mode switching and "
        "CUDA_VISIBLE_DEVICES mutation are not safe under concurrency"
    )

    from songmaker_cli.config import find_project_root, load_env_file
    from songmaker_cli.logging_config import configure_logging

    project_root = find_project_root(Path.cwd()) or Path.cwd()
    load_env_file(project_root)
    configure_logging()

    current_redis_url = os.environ.get("REDIS_URL")
    if current_redis_url and current_redis_url != _IMPORT_TIME_REDIS_URL:
        log.warning(
            REDIS_URL_MISMATCH_WARNING.format(
                env_value=current_redis_url,
                import_value=_IMPORT_TIME_REDIS_URL or "redis://localhost:6379/0",
            ),
        )

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
        await ctx["redis"].set(ACTIVE_MODEL_REDIS_KEY, model)

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


_MAX_CONCURRENT_JOBS = 1
_IMPORT_TIME_REDIS_URL = os.environ.get("REDIS_URL")


class WorkerSettings:
    functions = [generate, score, reinitialize_acestep]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    )
    max_jobs = _MAX_CONCURRENT_JOBS
    job_timeout = JOB_TIMEOUT_SECONDS
    job_completion_wait = DRAIN_TIMEOUT_SECONDS
    health_check_interval = HEALTH_CHECK_INTERVAL_SECONDS
    cron_jobs = [
        cron(cleanup_stale, minute={i for i in range(0, 60, 2)}, second={0}),
    ]

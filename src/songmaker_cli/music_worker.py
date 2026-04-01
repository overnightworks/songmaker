"""arq music worker — runs GPU-bound generation jobs.

Started as a separate process:
    arq songmaker_cli.music_worker.MusicWorkerSettings
"""

from __future__ import annotations

import logging
import os
import threading

from arq import cron

from songmaker_cli.constants import (
    ACESTEP_STATUS_REDIS_KEY,
    ACESTEP_STATUS_TTL_SECONDS,
    ACTIVE_MODEL_REDIS_KEY,
    ACTIVE_MODEL_TTL_SECONDS,
    ARQ_MUSIC_QUEUE_NAME,
    RECOVERY_LOCK_MUSIC_KEY,
    RECOVERY_LOCK_TTL_SECONDS,
)
from songmaker_cli.jobs import run_generation_job
from songmaker_cli.worker_base import (
    DRAIN_TIMEOUT_SECONDS,
    HEALTH_CHECK_INTERVAL_SECONDS,
    JOB_TIMEOUT_SECONDS,
    _audio_dir,
    _data_dir,
    _get_db_factory,
    build_redis_settings,
    check_job_still_valid,
    common_shutdown,
    common_startup,
)

log = logging.getLogger(__name__)

_acestep_manager = None
_acestep_lock = threading.Lock()

_IMPORT_TIME_REDIS_URL = os.environ.get("REDIS_URL")


def _require_acestep_manager():
    with _acestep_lock:
        mgr = _acestep_manager
    if mgr is None:
        raise RuntimeError("ACE-Step manager not initialized — on_startup may have failed")
    return mgr


async def generate(ctx, job_id, song_id, version_id, count, user_id, seed=None):
    if not check_job_still_valid(job_id):
        return

    mgr = _require_acestep_manager()
    mgr.prepare_generate_mode()
    model = mgr.active_model
    if model:
        await ctx["redis"].set(ACTIVE_MODEL_REDIS_KEY, model, ex=ACTIVE_MODEL_TTL_SECONDS)

    import structlog
    structlog.contextvars.bind_contextvars(job_id=job_id, task="generate")

    run_generation_job(
        job_id, song_id, version_id, count, user_id,
        db_factory=_get_db_factory(), audio_dir=_audio_dir(), data_dir=_data_dir(),
        seed=seed,
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
        await ctx["redis"].set(ACTIVE_MODEL_REDIS_KEY, model, ex=ACTIVE_MODEL_TTL_SECONDS)
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
    from songmaker_cli.db.queries import recover_stale_jobs_by_age_and_type

    db_factory = _get_db_factory()
    with db_factory() as session:
        count = recover_stale_jobs_by_age_and_type(session, "generate")
        if count:
            session.commit()
    mgr = _require_acestep_manager()
    model = mgr.active_model
    if model:
        await ctx["redis"].set(ACTIVE_MODEL_REDIS_KEY, model, ex=ACTIVE_MODEL_TTL_SECONDS)
    await _publish_acestep_status(ctx["redis"])


async def on_startup(ctx):
    await common_startup(ctx, _IMPORT_TIME_REDIS_URL)

    log.info("Music worker starting up...")

    from songmaker_cli.acestep_manager import AceStepManager
    mgr = AceStepManager()
    with _acestep_lock:
        global _acestep_manager
        _acestep_manager = mgr
    mgr.ensure()
    mgr.refresh_cached_model()

    model = mgr.active_model
    log.info("ACE-Step model: %s", model or "unknown")
    if model:
        await ctx["redis"].set(ACTIVE_MODEL_REDIS_KEY, model, ex=ACTIVE_MODEL_TTL_SECONDS)

    redis = ctx["redis"]
    if await redis.set(RECOVERY_LOCK_MUSIC_KEY, "1", ex=RECOVERY_LOCK_TTL_SECONDS, nx=True):
        try:
            from songmaker_cli.db.queries import recover_stale_jobs_by_type

            db_factory = _get_db_factory()
            with db_factory() as session:
                recovered = recover_stale_jobs_by_type(session, "generate")
                if recovered:
                    log.info("Recovered %d stale generate jobs", recovered)
                session.commit()
        finally:
            await redis.delete(RECOVERY_LOCK_MUSIC_KEY)
    else:
        log.info("Stale job recovery skipped — another worker holds the lock")

    await _publish_acestep_status(ctx["redis"])
    log.info("Music worker ready")


async def on_shutdown(ctx):
    redis = ctx["redis"]
    await redis.delete(ACTIVE_MODEL_REDIS_KEY)

    await common_shutdown(RECOVERY_LOCK_MUSIC_KEY, "generate", redis)

    if _acestep_manager:
        _acestep_manager.stop()


class MusicWorkerSettings:
    functions = [generate, reinitialize_acestep]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = build_redis_settings()
    queue_name = ARQ_MUSIC_QUEUE_NAME
    max_jobs = int(os.environ.get("MUSIC_MAX_JOBS", "2"))
    job_timeout = JOB_TIMEOUT_SECONDS
    job_completion_wait = DRAIN_TIMEOUT_SECONDS
    health_check_interval = HEALTH_CHECK_INTERVAL_SECONDS
    cron_jobs = [
        cron(cleanup_stale, minute={i for i in range(0, 60, 2)}, second={0}),
    ]

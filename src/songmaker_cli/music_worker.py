"""arq music worker — runs GPU-bound generation jobs.

Started as a separate process:
    arq songmaker_cli.music_worker.MusicWorkerSettings
"""

from __future__ import annotations

import asyncio
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
)
from songmaker_cli.jobs import load_model_on_worker, run_generation_job
from songmaker_cli.worker_base import (
    DRAIN_TIMEOUT_SECONDS,
    HEALTH_CHECK_INTERVAL_SECONDS,
    JOB_TIMEOUT_SECONDS,
    _audio_dir,
    _data_dir,
    _get_db_factory,
    audit_orphaned_files,
    build_redis_settings,
    check_job_still_valid,
    common_shutdown,
    common_startup,
    make_cleanup_cron,
    recover_on_startup,
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


async def generate(ctx, job_id, song_id, version_id, count, user_id, seed=None,
                   requested_model=None, repaint_params=None, cover_params=None):
    if not check_job_still_valid(job_id):
        return

    mgr = _require_acestep_manager()
    mgr.prepare_generate_mode()

    if requested_model and requested_model != mgr.active_model:
        log.info("Auto-switching model: %s -> %s", mgr.active_model, requested_model)
        from songmaker_cli.db.queries import update_job_status
        db_factory = _get_db_factory()
        with db_factory() as session:
            update_job_status(session, job_id, "running", worker_pid=os.getpid())
            session.commit()
        await asyncio.to_thread(mgr.switch_model, requested_model)

    model = mgr.active_model
    if model:
        await ctx["redis"].set(ACTIVE_MODEL_REDIS_KEY, model, ex=ACTIVE_MODEL_TTL_SECONDS)

    import structlog
    structlog.contextvars.bind_contextvars(job_id=job_id, task="generate")

    await asyncio.to_thread(
        run_generation_job,
        job_id, song_id, version_id, count, user_id,
        db_factory=_get_db_factory(), audio_dir=_audio_dir(), data_dir=_data_dir(),
        seed=seed, repaint_params=repaint_params, cover_params=cover_params,
    )


async def reinitialize_acestep(ctx, job_id, target_model=None):
    import httpx

    from songmaker_cli.acestep_manager import _ACESTEP_PORT
    from songmaker_cli.db.queries import update_job_status

    db_factory = _get_db_factory()

    with db_factory() as session:
        update_job_status(session, job_id, "running", worker_pid=os.getpid())
        session.commit()

    try:
        mgr = _require_acestep_manager()

        if target_model is not None and target_model != mgr.active_model:
            with db_factory() as session:
                update_job_status(session, job_id, "running", progress=0.0)
                session.commit()
            await asyncio.to_thread(mgr.switch_model, target_model)
        else:
            acestep_url = f"http://localhost:{_ACESTEP_PORT}/v1/reinitialize"
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(acestep_url, json={})
            data = resp.json()
            if data.get("code") != 200:
                raise RuntimeError(f"ACE-Step reinitialize failed: {data}")
            mgr.refresh_cached_model()

        model = mgr.active_model
        if model:
            await ctx["redis"].set(ACTIVE_MODEL_REDIS_KEY, model, ex=ACTIVE_MODEL_TTL_SECONDS)
        await _publish_acestep_status(ctx["redis"])

        with db_factory() as session:
            update_job_status(session, job_id, "completed", progress=1.0)
            session.commit()
    except Exception as exc:
        with db_factory() as session:
            update_job_status(session, job_id, "failed", error=str(exc))
            session.commit()
        raise


async def _publish_acestep_status(redis) -> None:
    import json

    import httpx

    from songmaker_cli.acestep_manager import _ACESTEP_PORT

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            base = f"http://localhost:{_ACESTEP_PORT}"
            health_resp, stats_resp = await asyncio.gather(
                client.get(f"{base}/health"),
                client.get(f"{base}/v1/stats"),
            )
        health = health_resp.json()
        stats = stats_resp.json()

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


_base_cleanup = make_cleanup_cron("generate")


async def cleanup_stale(ctx):
    await _base_cleanup(ctx)
    await asyncio.to_thread(audit_orphaned_files)


async def publish_acestep_heartbeat(ctx):
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

    await recover_on_startup(ctx, RECOVERY_LOCK_MUSIC_KEY, "generate")

    await _publish_acestep_status(ctx["redis"])
    log.info("Music worker ready")


async def on_shutdown(ctx):
    redis = ctx["redis"]
    await redis.delete(ACTIVE_MODEL_REDIS_KEY)

    await common_shutdown(RECOVERY_LOCK_MUSIC_KEY, "generate", redis)

    if _acestep_manager:
        _acestep_manager.stop()


class MusicWorkerSettings:
    functions = [generate, reinitialize_acestep, load_model_on_worker]
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
        cron(publish_acestep_heartbeat, second={i for i in range(0, 60, 45)}),
    ]

"""arq music worker — runs GPU-bound generation jobs.

Started as a separate process:
    arq songmaker_cli.music_worker.MusicWorkerSettings
"""

from __future__ import annotations

import logging
import os

from arq import cron

from songmaker_cli.constants import (
    ARQ_MUSIC_QUEUE_NAME,
    RECOVERY_LOCK_MUSIC_KEY,
)
from songmaker_cli.jobs import (
    download_model_on_worker,
    load_model_on_worker,
    run_generation_job,
)
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

_IMPORT_TIME_REDIS_URL = os.environ.get("REDIS_URL")


async def generate(ctx, job_id, song_id, version_id, count, user_id, seed=None,
                   requested_model=None, repaint_params=None, cover_params=None):
    if not check_job_still_valid(job_id):
        return

    import structlog
    structlog.contextvars.bind_contextvars(job_id=job_id, task="generate")

    await run_generation_job(
        job_id, song_id, version_id, count, user_id,
        db_factory=_get_db_factory(),
        audio_dir=_audio_dir(),
        data_dir=_data_dir(),
        seed=seed,
        repaint_params=repaint_params,
        cover_params=cover_params,
        target_model=requested_model,
        redis=ctx["redis"],
    )


_base_cleanup = make_cleanup_cron("generate")


async def cleanup_stale(ctx):
    import asyncio

    await _base_cleanup(ctx)
    await asyncio.to_thread(audit_orphaned_files)


async def on_startup(ctx):
    await common_startup(ctx, _IMPORT_TIME_REDIS_URL)
    log.info("Music worker starting up...")
    await recover_on_startup(ctx, RECOVERY_LOCK_MUSIC_KEY, "generate")
    log.info("Music worker ready")


async def on_shutdown(ctx):
    await common_shutdown(RECOVERY_LOCK_MUSIC_KEY, "generate", ctx["redis"])


class MusicWorkerSettings:
    functions = [generate, load_model_on_worker, download_model_on_worker]
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

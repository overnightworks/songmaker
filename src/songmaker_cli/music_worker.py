"""arq music worker — runs GPU-bound generation jobs.

Started as a separate process:
    arq songmaker_cli.music_worker.MusicWorkerSettings
"""

from __future__ import annotations

import asyncio
import logging
import os

from arq import cron

from songmaker_cli.constants import (
    ARQ_MUSIC_QUEUE_NAME,
    RECOVERY_LOCK_MUSIC_KEY,
    JobType,
)
from songmaker_cli.jobs import (
    download_model_on_worker as _download_model_on_worker_impl,
)
from songmaker_cli.jobs import (
    load_model_on_worker as _load_model_on_worker_impl,
)
from songmaker_cli.jobs import (
    run_generation_job,
)
from songmaker_cli.worker_base import WorkerBase, build_redis_settings

log = logging.getLogger(__name__)


class MusicWorker(WorkerBase):
    job_type = JobType.GENERATE
    recovery_lock_key = RECOVERY_LOCK_MUSIC_KEY
    queue_name = ARQ_MUSIC_QUEUE_NAME
    max_jobs = int(os.environ.get("MUSIC_MAX_JOBS", "2"))

    async def generate(self, ctx, job_id, song_id, version_id, count, user_id, seed,
                       requested_model, repaint_params=None, cover_params=None):
        if not self.check_job_still_valid(job_id):
            return

        import structlog
        structlog.contextvars.bind_contextvars(job_id=job_id, task=JobType.GENERATE)

        await run_generation_job(
            job_id, song_id, version_id, count, user_id,
            db_factory=self.get_db_factory(),
            audio_dir=self.audio_dir(),
            data_dir=self.data_dir(),
            seed=seed,
            repaint_params=repaint_params,
            cover_params=cover_params,
            target_model=requested_model,
            redis=ctx["redis"],
        )

    async def load_model_on_worker(
        self, ctx, job_id: str, worker_id: str, mode: str,
    ) -> None:
        await _load_model_on_worker_impl(
            ctx, job_id, worker_id, mode, db_factory=self.get_db_factory(),
        )

    async def download_model_on_worker(self, ctx, job_id: str, mode: str) -> None:
        await _download_model_on_worker_impl(
            ctx, job_id, mode, db_factory=self.get_db_factory(),
        )

    async def cleanup_stale_cron(self, ctx) -> int:
        from songmaker_cli.cleanup import run_cleanup_expired

        count = await super().cleanup_stale_cron(ctx)
        await asyncio.to_thread(self.audit_orphaned_files)
        await asyncio.to_thread(
            run_cleanup_expired, self.get_db_factory(), self.audio_dir(),
        )
        return count


_music_worker = MusicWorker()


class MusicWorkerSettings:
    functions = [
        _music_worker.generate,
        _music_worker.load_model_on_worker,
        _music_worker.download_model_on_worker,
    ]
    on_startup = _music_worker.on_startup
    on_shutdown = _music_worker.on_shutdown
    redis_settings = build_redis_settings()
    queue_name = MusicWorker.queue_name
    max_jobs = MusicWorker.max_jobs
    job_timeout = MusicWorker.job_timeout
    job_completion_wait = MusicWorker.drain_timeout
    health_check_interval = MusicWorker.health_check_interval
    cron_jobs = [
        cron(
            _music_worker.cleanup_stale_cron,
            minute={i for i in range(0, 60, 2)},
            second={0},
        ),
    ]

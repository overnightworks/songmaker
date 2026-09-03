"""arq music worker — runs GPU-bound generation jobs.

Started as a separate process:
    arq songmaker_cli.music_worker.MusicWorkerSettings
"""

from __future__ import annotations

import asyncio
import logging

from arq import cron, func

from songmaker_cli.api_models import CoverTaskParams, RepaintTaskParams
from songmaker_cli.constants import (
    ARQ_MUSIC_QUEUE_NAME,
    JOB_ACTIVE_STATUSES,
    RECOVERY_LOCK_MUSIC_KEY,
    JobFunction,
    JobStatus,
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
    run_lora_training_job,
)
from songmaker_cli.jobs.lora_training import reconcile_crashed_loras
from songmaker_cli.settings import get_settings
from songmaker_cli.worker_base import WorkerBase, build_redis_settings

log = logging.getLogger(__name__)


class MusicWorker(WorkerBase):
    job_types = (JobType.GENERATE, JobType.LORA_TRAINING)
    recovery_lock_key = RECOVERY_LOCK_MUSIC_KEY
    queue_name = ARQ_MUSIC_QUEUE_NAME

    def recovery_statuses_by_type(self) -> dict[str, frozenset[str]]:
        """Keep queued LoRA work available to a freshly started worker."""
        return {
            JobType.GENERATE: JOB_ACTIVE_STATUSES,
            JobType.LORA_TRAINING: frozenset({JobStatus.RUNNING}),
        }

    async def _reconcile_recovered_jobs(self, recovered: dict[str, int]) -> None:
        if not recovered.get(JobType.LORA_TRAINING):
            return

        await asyncio.to_thread(
            reconcile_crashed_loras,
            self.get_db_factory(),
            self.audio_dir(),
        )

    async def generate(self, ctx, job_id, song_id, version_id, count, user_id, seed,
                       requested_model, repaint_params=None, cover_params=None):
        if not self.check_job_still_valid(job_id):
            return

        import structlog
        structlog.contextvars.bind_contextvars(job_id=job_id, task=JobType.GENERATE)

        typed_repaint = (
            RepaintTaskParams.model_validate(repaint_params)
            if repaint_params is not None else None
        )
        typed_cover = (
            CoverTaskParams.model_validate(cover_params)
            if cover_params is not None else None
        )

        await run_generation_job(
            job_id, song_id, version_id, count, user_id,
            db_factory=self.get_db_factory(),
            audio_dir=self.audio_dir(),
            data_dir=self.data_dir(),
            seed=seed,
            repaint_params=typed_repaint,
            cover_params=typed_cover,
            target_model=requested_model,
            redis=ctx["redis"],
        )

    async def train_lora(
        self, ctx, job_id: str, lora_id: str, user_id: str,
    ) -> None:
        if not self.check_job_still_valid(job_id):
            return

        import structlog
        structlog.contextvars.bind_contextvars(
            job_id=job_id, task=JobType.LORA_TRAINING,
        )

        await run_lora_training_job(
            ctx, job_id, lora_id, user_id,
            db_factory=self.get_db_factory(),
            audio_dir=self.audio_dir(),
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

    async def generation_retention_cron(self, ctx) -> int:
        from songmaker_cli.cleanup import run_generation_retention

        report = await asyncio.to_thread(
            run_generation_retention, self.get_db_factory(), self.audio_dir(),
        )
        return report.archived_count + report.deleted_count


_settings = get_settings()
_music_worker = MusicWorker(_settings)


class MusicWorkerSettings:
    functions = [
        func(_music_worker.generate, name=JobFunction.GENERATE),
        func(_music_worker.load_model_on_worker, name=JobFunction.LOAD_MODEL_ON_WORKER),
        func(_music_worker.download_model_on_worker, name=JobFunction.DOWNLOAD_MODEL_ON_WORKER),
        func(_music_worker.train_lora, name=JobFunction.LORA_TRAINING),
    ]
    on_startup = _music_worker.on_startup
    on_shutdown = _music_worker.on_shutdown
    redis_settings = build_redis_settings(_settings)
    queue_name = MusicWorker.queue_name
    max_jobs = _settings.music_max_jobs
    job_timeout = _settings.arq_job_timeout
    job_completion_wait = _settings.arq_drain_timeout
    health_check_interval = MusicWorker.health_check_interval
    cron_jobs = [
        cron(
            _music_worker.cleanup_stale_cron,
            minute={i for i in range(0, 60, 2)},
            second={0},
        ),
        cron(
            _music_worker.generation_retention_cron,
            hour={3},
            minute={0},
            second={0},
        ),
    ]

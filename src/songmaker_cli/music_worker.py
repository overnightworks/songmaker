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
    MODEL_DEFAULT_MODE,
    RECOVERY_LOCK_MUSIC_KEY,
    CoverExecutor,
    JobFunction,
    JobType,
)
from songmaker_cli.jobs import (
    download_model_on_worker as _download_model_on_worker_impl,
)
from songmaker_cli.jobs import (
    load_model_on_worker as _load_model_on_worker_impl,
)
from songmaker_cli.jobs import (
    run_cover_suggestion_job,
    run_generation_job,
    run_lora_training_job,
)
from songmaker_cli.jobs.lora_training import reconcile_crashed_loras
from songmaker_cli.settings import Settings, get_settings
from songmaker_cli.worker_base import WorkerBase, build_redis_settings

log = logging.getLogger(__name__)


class MusicWorker(WorkerBase):
    job_types = (
        JobType.GENERATE,
        JobType.LORA_TRAINING,
        JobType.LOAD_MODEL_ON_WORKER,
        JobType.DOWNLOAD_MODEL_ON_WORKER,
    )
    recovery_lock_key = RECOVERY_LOCK_MUSIC_KEY
    queue_name = ARQ_MUSIC_QUEUE_NAME

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings)
        if self._settings.cover_executor is CoverExecutor.MUSIC:
            self.job_types = (JobType.COVER, *self.job_types)

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

    async def generate_cover_suggestions(self, _ctx, job_id: str) -> None:
        if not self.check_job_still_valid(job_id):
            return

        import structlog
        structlog.contextvars.bind_contextvars(job_id=job_id, task=JobType.COVER)

        await run_cover_suggestion_job(
            job_id,
            db_factory=self.get_db_factory(),
            audio_dir=self.audio_dir(),
            settings=self._settings,
        )

    async def train_lora(
        self,
        ctx,
        job_id: str,
        lora_id: str,
        user_id: str,
        target_mode: str = MODEL_DEFAULT_MODE,
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
            target_mode=target_mode,
            training_config=self._settings.lora_training_config,
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

    async def cleanup_files_cron(self, _ctx) -> None:
        from songmaker_cli.cleanup import run_cleanup_expired

        await asyncio.to_thread(self.audit_orphaned_files)
        await asyncio.to_thread(
            run_cleanup_expired, self.get_db_factory(), self.audio_dir(),
        )

    async def generation_retention_cron(self, _ctx) -> int:
        from songmaker_cli.cleanup import run_generation_retention

        report = await asyncio.to_thread(
            run_generation_retention, self.get_db_factory(), self.audio_dir(),
        )
        return report.archived_count + report.deleted_count


_settings = get_settings()
_music_worker = MusicWorker(_settings)


def _music_worker_functions(worker: MusicWorker, settings: Settings):
    functions = [
        func(worker.generate, name=JobFunction.GENERATE),
        func(worker.load_model_on_worker, name=JobFunction.LOAD_MODEL_ON_WORKER),
        func(worker.download_model_on_worker, name=JobFunction.DOWNLOAD_MODEL_ON_WORKER),
        func(
            worker.train_lora,
            name=JobFunction.LORA_TRAINING,
            timeout=settings.lora_training_job_timeout,
        ),
    ]
    if settings.cover_executor is CoverExecutor.MUSIC:
        functions.insert(
            0,
            func(
                worker.generate_cover_suggestions,
                name=JobFunction.COVER,
                timeout=settings.cover_job_budget_seconds,
            ),
        )
    return functions


class MusicWorkerSettings:
    functions = _music_worker_functions(_music_worker, _settings)
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
            _music_worker.cleanup_files_cron,
            minute=set(range(0, 60, 2)),
            second={0},
        ),
        cron(
            _music_worker.generation_retention_cron,
            hour={3},
            minute={0},
            second={0},
        ),
    ]

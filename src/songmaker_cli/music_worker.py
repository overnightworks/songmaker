"""Music worker — claims GPU-bound jobs from their rows and runs them.

Started as a separate process:
    python -m songmaker_cli.arq_worker songmaker_cli.music_worker.MusicWorkerSettings

arq hosts the process (its health key says the worker lives) and runs its cron jobs; the jobs
of the music queue come from PostgreSQL, claimed by ``serve_queue``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC

from arq import cron
from arq.worker import Function

from songmaker_cli.arq_codec import deserialize_arq, serialize_arq
from songmaker_cli.cleanup import DAILY_CLEANUP_HOUR_UTC
from songmaker_cli.constants import ARQ_MUSIC_QUEUE_NAME, MUSIC_WORKER_READINESS_FILE
from songmaker_cli.job_payloads import (
    DownloadModelPayload,
    GeneratePayload,
    JobPayload,
    LoadModelPayload,
    LoraTrainingPayload,
)
from songmaker_cli.job_queue import ClaimedJob, JobQueue
from songmaker_cli.job_types import JobFunction, JobType
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
from songmaker_cli.redis_client import build_arq_redis_settings
from songmaker_cli.settings import get_settings
from songmaker_cli.timestamps import utcnow
from songmaker_cli.worker_base import WorkerBase, logged_job
from songmaker_cli.worker_liveness import (
    MUSIC_WORKER_KIND,
    pid_one_start_ticks,
    write_readiness_file,
)

log = logging.getLogger(__name__)


class MusicWorker(WorkerBase):
    service_name = "songmaker-music-worker"
    queue = JobQueue.MUSIC
    job_types = queue.job_types
    queue_name = ARQ_MUSIC_QUEUE_NAME
    lease_kind = MUSIC_WORKER_KIND

    def __init__(self, settings=None) -> None:
        super().__init__(settings)
        self._places = asyncio.Semaphore(self._settings.music_max_jobs)
        self._arq_context: dict = {}
        self._run_logged = {
            job_type: logged_job(
                JobFunction(job_type), self._run_payload, status_of=self.job_status,
            )
            for job_type in self.job_types
        }

    async def run_claimed(self, claimed: ClaimedJob) -> None:
        """Run the claimed row within its type's time limit."""
        async with asyncio.timeout(self._timeout_seconds(claimed.job_type)):
            await self._run_logged[claimed.job_type](
                self._arq_context, claimed.job_id, claimed.payload,
            )

    def _timeout_seconds(self, job_type: JobType) -> int:
        if job_type is JobType.LORA_TRAINING:
            return self._settings.lora_training_job_timeout
        return self._settings.arq_job_timeout

    async def _run_payload(self, ctx, job_id: str, payload: JobPayload | None) -> None:
        match payload:
            case GeneratePayload():
                await run_generation_job(
                    job_id, payload.song_id, payload.version_id, payload.count, payload.user_id,
                    db_factory=self.get_db_factory(),
                    audio_dir=self.audio_dir(),
                    data_dir=self.data_dir(),
                    owner=self.owner,
                    seed=payload.seed,
                    task_params=payload.task_params,
                    target_model=payload.target_model,
                    redis=ctx["redis"],
                )
            case LoraTrainingPayload():
                await run_lora_training_job(
                    ctx, job_id, payload.lora_id, payload.user_id,
                    db_factory=self.get_db_factory(),
                    audio_dir=self.audio_dir(),
                    owner=self.owner,
                    redis=ctx["redis"],
                    target_mode=payload.target_mode,
                    training_config=self._settings.lora_training_config,
                )
            case LoadModelPayload():
                await _load_model_on_worker_impl(
                    ctx, job_id, payload.worker_id, payload.mode,
                    db_factory=self.get_db_factory(), owner=self.owner,
                )
            case DownloadModelPayload():
                await _download_model_on_worker_impl(
                    ctx, job_id, payload.mode,
                    db_factory=self.get_db_factory(), owner=self.owner,
                )
            case _:
                await asyncio.to_thread(self.fail_job_without_payload, job_id)

    async def on_startup(self, ctx) -> None:
        write_readiness_file(MUSIC_WORKER_READINESS_FILE, self.owner_id, pid_one_start_ticks())
        await super().on_startup(ctx)
        self._arq_context = ctx
        self.start_serving(self.serve_queued_jobs())

    async def on_shutdown(self, ctx) -> None:
        await self.stop_serving()
        await super().on_shutdown(ctx)

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

    async def reference_remnant_cron(self, _ctx) -> int:
        from songmaker_cli.reference_audio import reconcile_reference_remnants

        report = await asyncio.to_thread(
            reconcile_reference_remnants, self.get_db_factory(), self.audio_dir(),
        )
        return report.removed

    async def reference_unused_cron(self, _ctx) -> int:
        return await asyncio.to_thread(self._reconcile_then_delete_unused_references)

    def _reconcile_then_delete_unused_references(self) -> int:
        """Stamp and clear first, then delete what the announced dates release."""
        from songmaker_cli.reference_audio import (
            delete_announced_references,
            reconcile_unused_stamps,
        )

        factory = self.get_db_factory()
        reconciled = reconcile_unused_stamps(factory)
        deleted = delete_announced_references(
            factory, self.audio_dir(), days=self._settings.final_deletion_days,
            hour=DAILY_CLEANUP_HOUR_UTC, now=utcnow(),
        )
        return reconciled.stamped + reconciled.cleared + deleted.deleted


_settings = get_settings()
_music_worker = MusicWorker(_settings)


class MusicWorkerSettings:
    functions: list[Function] = []
    on_startup = _music_worker.on_startup
    on_shutdown = _music_worker.on_shutdown
    job_serializer = staticmethod(serialize_arq)
    job_deserializer = staticmethod(deserialize_arq)
    redis_settings = build_arq_redis_settings(_settings.redis_url, ride_out_outage=True)
    queue_name = MusicWorker.queue_name
    job_timeout = _settings.arq_job_timeout
    job_completion_wait = _settings.arq_drain_timeout
    health_check_interval = MusicWorker.health_check_interval
    timezone = UTC
    cron_jobs = [
        cron(
            logged_job("cleanup_files_cron", _music_worker.cleanup_files_cron),
            minute=set(range(0, 60, 2)),
            second={0},
        ),
        cron(
            logged_job("generation_retention_cron", _music_worker.generation_retention_cron),
            hour={DAILY_CLEANUP_HOUR_UTC},
            minute={0},
            second={0},
        ),
        cron(
            logged_job("reference_remnant_cron", _music_worker.reference_remnant_cron),
            hour={DAILY_CLEANUP_HOUR_UTC},
            minute={0},
            second={0},
        ),
        cron(
            logged_job("reference_unused_cron", _music_worker.reference_unused_cron),
            hour={DAILY_CLEANUP_HOUR_UTC},
            minute={0},
            second={0},
        ),
    ]

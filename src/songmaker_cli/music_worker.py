"""Music worker — claims GPU-bound jobs from their rows and runs them.

Started as a separate process:
    python -m songmaker_cli.music_worker

The jobs of the music queue come from PostgreSQL, claimed by ``serve_queue``; the four crons
are tandem Deadlines, claimed by ``serve_due_crons``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from pathlib import Path

from songmaker_cli.cleanup import DAILY_CLEANUP_HOUR_UTC
from songmaker_cli.constants import WORKER_READINESS_FILE
from songmaker_cli.cron_schedule import Cron, CronBody, serve_due_crons
from songmaker_cli.job_payloads import (
    DownloadModelPayload,
    GeneratePayload,
    JobPayload,
    LoadModelPayload,
    LoraTrainingPayload,
)
from songmaker_cli.job_queue import ClaimedJob, JobQueue
from songmaker_cli.job_types import JobFunction, JobType, WorkerLivenessSignal
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
from songmaker_cli.timestamps import utcnow
from songmaker_cli.worker_base import WorkerBase, logged_job

log = logging.getLogger(__name__)


class MusicWorker(WorkerBase):
    service_name = "songmaker-music-worker"
    queue = JobQueue.MUSIC
    job_types = queue.job_types
    lease_kind = WorkerLivenessSignal.MUSIC

    def __init__(self, settings=None, *, readiness_file: Path = WORKER_READINESS_FILE) -> None:
        super().__init__(settings, readiness_file=readiness_file)
        self._places = asyncio.Semaphore(self._settings.music_max_jobs)
        self._run_logged = {
            job_type: logged_job(
                JobFunction(job_type), self._run_payload, status_of=self.job_status,
            )
            for job_type in self.job_types
        }

    async def run_claimed(self, claimed: ClaimedJob) -> None:
        """Run the claimed row within its type's time limit."""
        async with asyncio.timeout(self._timeout_seconds(claimed.job_type)):
            await self._run_logged[claimed.job_type](claimed.job_id, claimed.payload)

    def _timeout_seconds(self, job_type: JobType) -> int:
        if job_type is JobType.LORA_TRAINING:
            return self._settings.lora_training_job_timeout
        return self._settings.arq_job_timeout

    async def _run_payload(self, job_id: str, payload: JobPayload | None) -> None:
        redis = self._owner_redis
        assert redis is not None  # noqa: S101 - jobs run only after start
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
                    redis=redis,
                )
            case LoraTrainingPayload():
                await run_lora_training_job(
                    job_id, payload.lora_id, payload.user_id,
                    db_factory=self.get_db_factory(),
                    audio_dir=self.audio_dir(),
                    owner=self.owner,
                    redis=redis,
                    target_mode=payload.target_mode,
                    training_config=self._settings.lora_training_config,
                )
            case LoadModelPayload():
                await _load_model_on_worker_impl(
                    job_id, payload.worker_id, payload.mode,
                    db_factory=self.get_db_factory(), owner=self.owner,
                )
            case DownloadModelPayload():
                await _download_model_on_worker_impl(
                    job_id, payload.mode,
                    db_factory=self.get_db_factory(), owner=self.owner,
                    redis=redis,
                )
            case _:
                await asyncio.to_thread(self.fail_job_without_payload, job_id)

    def servings(self) -> tuple[Coroutine[None, None, None], ...]:
        assert self._owner_redis is not None  # noqa: S101 - run serves only after start
        crons = serve_due_crons(self._owner_redis, self.cron_bodies())
        return (*super().servings(), crons)

    def cron_bodies(self) -> dict[Cron, CronBody]:
        return {
            Cron.CLEANUP_FILES: self.cleanup_files_cron,
            Cron.GENERATION_RETENTION: self.generation_retention_cron,
            Cron.REFERENCE_REMNANT: self.reference_remnant_cron,
            Cron.REFERENCE_UNUSED: self.reference_unused_cron,
        }

    async def cleanup_files_cron(self) -> None:
        from songmaker_cli.cleanup import run_cleanup_expired

        await asyncio.to_thread(self.audit_orphaned_files)
        await asyncio.to_thread(
            run_cleanup_expired, self.get_db_factory(), self.audio_dir(),
        )

    async def generation_retention_cron(self) -> int:
        from songmaker_cli.cleanup import run_generation_retention

        report = await asyncio.to_thread(
            run_generation_retention, self.get_db_factory(), self.audio_dir(),
        )
        return report.archived_count + report.deleted_count

    async def reference_remnant_cron(self) -> int:
        from songmaker_cli.reference_audio import reconcile_reference_remnants

        report = await asyncio.to_thread(
            reconcile_reference_remnants, self.get_db_factory(), self.audio_dir(),
        )
        return report.removed

    async def reference_unused_cron(self) -> int:
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


def main() -> None:
    asyncio.run(MusicWorker().run())


if __name__ == "__main__":
    main()

"""Scoring worker — claims score jobs from their rows and runs them.

Started as a separate process:
    python -m songmaker_cli.scoring_worker

The worker's lease in the ``scoring-worker`` family says it lives. The scorer subprocess exists
before the first job is claimed and ends after the last one has.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from songmaker_cli.constants import SCORING_SERVICE_NAME, WORKER_READINESS_FILE
from songmaker_cli.job_payloads import ScorePayload
from songmaker_cli.job_queue import ClaimedJob, JobQueue
from songmaker_cli.job_types import JobFunction, WorkerLivenessSignal
from songmaker_cli.jobs import run_scoring_job
from songmaker_cli.messages import message
from songmaker_cli.scoring.subprocess_runner import ScorerProcess, set_scorer_process
from songmaker_cli.worker_base import WorkerBase, logged_job

log = logging.getLogger(__name__)

TIMEOUT_ERROR_TYPE = "timeout"


class ScoringWorker(WorkerBase):
    service_name = SCORING_SERVICE_NAME
    queue = JobQueue.SCORE
    job_types = queue.job_types
    lease_kind = WorkerLivenessSignal.SCORING

    def __init__(
        self, settings=None, *, scorer: ScorerProcess | None = None,
        readiness_file: Path = WORKER_READINESS_FILE,
    ) -> None:
        super().__init__(settings, readiness_file=readiness_file)
        self._places = asyncio.Semaphore(self._settings.scoring_max_jobs)
        self._scorer = ScorerProcess() if scorer is None else scorer
        self._run_logged = logged_job(
            JobFunction.SCORE, self._run_payload, status_of=self.job_status,
        )

    async def run_claimed(self, claimed: ClaimedJob) -> None:
        """Run the claimed row within the job time limit.

        The scorer thread of a job cut at the limit cannot be cancelled; its late result
        writes nothing, because the row has ended.
        """
        try:
            async with asyncio.timeout(self._settings.arq_job_timeout):
                await self._run_logged(None, claimed.job_id, claimed.payload)
        except TimeoutError:
            log.error("Scoring job %s outlasted its time limit", claimed.job_id)
            await asyncio.to_thread(
                self.fail_job, claimed.job_id, message("jobFailure.tookTooLong"),
                TIMEOUT_ERROR_TYPE,
            )

    async def _run_payload(self, _ctx, job_id: str, payload) -> None:
        if not isinstance(payload, ScorePayload):
            await asyncio.to_thread(self.fail_job_without_payload, job_id)
            return
        scorers = None if payload.scorers is None else list(payload.scorers)
        await asyncio.to_thread(
            run_scoring_job,
            job_id, payload.gen_id, scorers,
            db_factory=self.get_db_factory(), audio_dir=self.audio_dir(),
            owner=self.owner, device=self._settings.scoring_device,
        )

    async def start(self) -> None:
        set_scorer_process(self._scorer)
        await super().start()
        log.info("Scorer subprocess manager initialized")

    async def stop(self) -> None:
        await asyncio.to_thread(self._scorer.shutdown)
        log.info("Scorer subprocess shut down")
        await super().stop()


def main() -> None:
    asyncio.run(ScoringWorker().run())


if __name__ == "__main__":
    main()

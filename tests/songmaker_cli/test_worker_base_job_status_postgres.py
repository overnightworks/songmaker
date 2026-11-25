"""A worker's job line follows the job's row on PostgreSQL."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from songmaker_cli.db.queries.jobs import JobStatusUpdate, create_job, update_job_status
from songmaker_cli.job_payloads import LoraTrainingPayload, ScorePayload
from songmaker_cli.job_queue import ClaimedJob
from songmaker_cli.job_types import JobFunction, JobStatus, JobType
from songmaker_cli.music_worker import MusicWorker
from songmaker_cli.scoring_worker import ScoringWorker
from songmaker_cli.worker_base import JOB_ENDED_EVENT


@pytest.fixture
def job_rows(pg_factory, workers_on_db):
    """The helper stores a job on this test's database."""
    def store(status: JobStatus) -> str:
        with pg_factory() as session:
            job = create_job(session, JobType.GENERATE)
            update_job_status(session, job.id, JobStatusUpdate(status))
            session.commit()
            return job.id

    return store


@pytest.mark.parametrize(
    "row_status", [JobStatus.FAILED, JobStatus.COMPLETED, JobStatus.CANCELLED],
)
def test_job_status_reads_the_status_of_the_jobs_row(row_status, job_rows) -> None:
    from songmaker_cli.settings import get_settings

    assert MusicWorker(get_settings()).job_status(job_rows(row_status)) is row_status


def test_job_status_is_none_for_a_job_without_a_row(pg_factory, job_rows) -> None:
    from songmaker_cli.settings import get_settings

    assert MusicWorker(get_settings()).job_status("no-such-job") is None


def test_a_score_job_ends_its_line_failed_when_its_row_failed(job_rows, caplog) -> None:
    job_id = job_rows(JobStatus.FAILED)
    claimed = ClaimedJob(
        job_id, JobType.SCORE, ScorePayload(gen_id="generation", scorers=("scorer",)),
    )

    with caplog.at_level("INFO"):
        asyncio.run(ScoringWorker().run_claimed(claimed))

    (ended,) = [record for record in caplog.records if record.getMessage() == JOB_ENDED_EVENT]
    assert (ended.job_function, ended.outcome) == (JobFunction.SCORE, "failed")


def test_a_music_job_ends_its_line_failed_when_its_run_failed_the_row(job_rows, caplog) -> None:
    job_id = job_rows(JobStatus.RUNNING)
    claimed = ClaimedJob(
        job_id, JobType.LORA_TRAINING,
        LoraTrainingPayload(lora_id="missing-voice", user_id="user", target_mode="turbo"),
    )
    worker = MusicWorker()
    worker._job_context = {"redis": AsyncMock()}

    with caplog.at_level("INFO"):
        asyncio.run(worker.run_claimed(claimed))

    (ended,) = [record for record in caplog.records if record.getMessage() == JOB_ENDED_EVENT]
    assert (ended.job_function, ended.outcome) == (JobFunction.LORA_TRAINING, "failed")

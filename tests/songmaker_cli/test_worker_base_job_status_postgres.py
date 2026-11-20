"""A worker's job line follows the job's row on PostgreSQL."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from support.job_owner import an_owner

from songmaker_cli.db.queries.jobs import JobStatusUpdate, create_job, update_job_status
from songmaker_cli.job_payloads import LoraTrainingPayload
from songmaker_cli.job_queue import ClaimedJob
from songmaker_cli.job_types import JobFunction, JobStatus, JobType
from songmaker_cli.music_worker import MusicWorker
from songmaker_cli.scoring_worker import ScoringWorker, ScoringWorkerSettings
from songmaker_cli.worker_base import JOB_ENDED_EVENT

REGISTERED_ARGUMENTS = {JobFunction.SCORE: ("generation", ["scorer"])}


@pytest.fixture
def job_rows(pg_factory, monkeypatch):
    """Workers read this test's database and hold an owner; the helper stores a job."""
    for worker_class in (MusicWorker, ScoringWorker):
        monkeypatch.setattr(worker_class, "get_db_factory", lambda self: pg_factory)
        monkeypatch.setattr(worker_class, "owner", an_owner("worker"), raising=False)

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


@pytest.mark.parametrize(
    "function",
    ScoringWorkerSettings.functions,
    ids=lambda function: function.name,
)
def test_every_registered_job_ends_its_line_failed_when_its_row_failed(
    function, job_rows, caplog,
) -> None:
    job_id = job_rows(JobStatus.FAILED)

    with caplog.at_level("INFO"):
        asyncio.run(function.coroutine({}, job_id, *REGISTERED_ARGUMENTS[function.name]))

    (ended,) = [record for record in caplog.records if record.getMessage() == JOB_ENDED_EVENT]
    assert (ended.job_function, ended.outcome) == (function.name, "failed")


def test_a_music_job_ends_its_line_failed_when_its_run_failed_the_row(job_rows, caplog) -> None:
    job_id = job_rows(JobStatus.RUNNING)
    claimed = ClaimedJob(
        job_id, JobType.LORA_TRAINING,
        LoraTrainingPayload(lora_id="missing-voice", user_id="user", target_mode="turbo"),
    )
    worker = MusicWorker()
    worker._arq_context = {"redis": AsyncMock()}

    with caplog.at_level("INFO"):
        asyncio.run(worker.run_claimed(claimed))

    (ended,) = [record for record in caplog.records if record.getMessage() == JOB_ENDED_EVENT]
    assert (ended.job_function, ended.outcome) == (JobFunction.LORA_TRAINING, "failed")

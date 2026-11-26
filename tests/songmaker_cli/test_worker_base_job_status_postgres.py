"""A worker's job line follows the job's row on PostgreSQL."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from logline import current_traceparent

from songmaker_cli.db.queries.jobs import JobStatusUpdate, create_job, update_job_status
from songmaker_cli.job_payloads import LoraTrainingPayload, ScorePayload
from songmaker_cli.job_queue import ClaimedJob
from songmaker_cli.job_types import JobFunction, JobStatus, JobType
from songmaker_cli.music_worker import MusicWorker
from songmaker_cli.scoring_worker import ScoringWorker
from songmaker_cli.worker_base import JOB_ENDED_EVENT, JOB_STATUS_UNREADABLE_EVENT


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
    worker._owner_redis = AsyncMock()

    with caplog.at_level("INFO"):
        asyncio.run(worker.run_claimed(claimed))

    (ended,) = [record for record in caplog.records if record.getMessage() == JOB_ENDED_EVENT]
    assert (ended.job_function, ended.outcome) == (JobFunction.LORA_TRAINING, "failed")


def a_score_claim(job_id: str) -> ClaimedJob:
    return ClaimedJob(
        job_id, JobType.SCORE, ScorePayload(gen_id="generation", scorers=("scorer",)),
    )


def ended_lines(caplog):
    return [record for record in caplog.records if record.getMessage() == JOB_ENDED_EVENT]


@pytest.mark.parametrize(
    ("row_status", "raises", "outcome", "reason"),
    [
        (JobStatus.COMPLETED, False, "ok", None),
        (JobStatus.RUNNING, True, "failed", None),
        (JobStatus.FAILED, False, "failed", "job_failed"),
        (JobStatus.CANCELLED, False, "cancelled", None),
    ],
    ids=["row-completed", "job-raised", "row-failed", "row-cancelled"],
)
def test_a_claimed_job_ends_with_one_line_carrying_its_id_and_outcome(
    row_status, raises, outcome, reason, job_rows, monkeypatch, caplog
) -> None:
    def run_scoring_job(*_arguments, **_keywords) -> None:
        if raises:
            raise ValueError("private content")

    monkeypatch.setattr("songmaker_cli.scoring_worker.run_scoring_job", run_scoring_job)
    job_id = job_rows(row_status)

    with caplog.at_level("INFO"):
        try:
            asyncio.run(ScoringWorker().run_claimed(a_score_claim(job_id)))
        except ValueError:
            assert raises

    (ended,) = ended_lines(caplog)
    assert (ended.job_id, ended.job_function, ended.outcome, getattr(ended, "reason", None)) == (
        job_id, JobFunction.SCORE, outcome, reason,
    )
    assert ended.duration_ms >= 0
    assert "private content" not in "".join(
        str(value) for value in vars(ended).values() if isinstance(value, str)
    )


def test_a_job_whose_row_status_cannot_be_read_ends_failed_and_finishes(
    job_rows, monkeypatch, caplog
) -> None:
    class UnreadableStatusWorker(ScoringWorker):
        def job_status(self, job_id: str):
            raise OSError("private content")

    finished = []
    monkeypatch.setattr(
        "songmaker_cli.scoring_worker.run_scoring_job",
        lambda *arguments, **keywords: finished.append(True),
    )
    job_id = job_rows(JobStatus.COMPLETED)

    with caplog.at_level("INFO"):
        asyncio.run(UnreadableStatusWorker().run_claimed(a_score_claim(job_id)))

    (ended,) = ended_lines(caplog)
    (warning,) = [
        record for record in caplog.records
        if record.getMessage() == JOB_STATUS_UNREADABLE_EVENT
    ]
    assert finished == [True]
    assert (ended.outcome, ended.reason, ended.levelname) == (
        "failed", "status_unreadable", "WARNING",
    )
    assert (warning.job_id, warning.error_type) == (job_id, "OSError")


def test_each_job_runs_in_a_trace_of_its_own_and_none_outlives_a_failed_job(
    job_rows, monkeypatch
) -> None:
    seen_traceparents = []

    def run_scoring_job(*_arguments, **_keywords) -> None:
        seen_traceparents.append(current_traceparent())
        if len(seen_traceparents) == 1:
            raise ValueError("deliberate failure")

    async def run_both() -> None:
        worker = ScoringWorker()
        with pytest.raises(ValueError, match="deliberate failure"):
            await worker.run_claimed(a_score_claim(job_rows(JobStatus.RUNNING)))
        assert current_traceparent() is None
        await worker.run_claimed(a_score_claim(job_rows(JobStatus.COMPLETED)))
        assert current_traceparent() is None

    monkeypatch.setattr("songmaker_cli.scoring_worker.run_scoring_job", run_scoring_job)

    asyncio.run(run_both())

    first, second = seen_traceparents
    assert first.split("-")[1] != second.split("-")[1]

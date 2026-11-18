"""A worker's job line follows the job's row on PostgreSQL."""

from __future__ import annotations

import pytest
from support.job_owner import an_owner

from songmaker_cli.db.queries.jobs import JobStatusUpdate, create_job, update_job_status
from songmaker_cli.job_types import JobFunction, JobStatus, JobType
from songmaker_cli.music_worker import MusicWorker
from songmaker_cli.scoring_worker import ScoringWorker

REGISTERED_ARGUMENTS = {
    JobFunction.GENERATE: ("song", "version", 1, "user", None, "turbo"),
    JobFunction.LOAD_MODEL_ON_WORKER: ("no-such-worker", "turbo"),
    JobFunction.DOWNLOAD_MODEL_ON_WORKER: ("no-such-mode",),
    JobFunction.LORA_TRAINING: ("lora", "user"),
    JobFunction.SCORE: ("generation", ["scorer"]),
}


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

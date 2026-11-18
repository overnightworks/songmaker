"""A job handler runs its job only when it claims the job's queued row."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from support.job_owner import an_owner
from support.score_jobs import a_scoreable_take, queued_score_job

from songmaker_cli.db.queries.jobs import (
    JobStatusUpdate,
    claim_queued_job,
    create_job,
    get_job,
    update_job_status,
)
from songmaker_cli.job_payloads import ScorePayload
from songmaker_cli.job_queue import ClaimedJob
from songmaker_cli.job_types import JobFunction, JobStatus, JobType
from songmaker_cli.music_worker import MusicWorker, MusicWorkerSettings
from songmaker_cli.scoring_worker import ScoringWorker, ScoringWorkerSettings

WORK = {
    JobFunction.GENERATE: (
        "songmaker_cli.music_worker.run_generation_job", AsyncMock,
        ("song", "version", 1, "user", None, "turbo"),
    ),
    JobFunction.LORA_TRAINING: (
        "songmaker_cli.music_worker.run_lora_training_job", AsyncMock, ("lora", "user"),
    ),
    JobFunction.LOAD_MODEL_ON_WORKER: (
        "songmaker_cli.music_worker._load_model_on_worker_impl", AsyncMock, ("gpu", "turbo"),
    ),
    JobFunction.DOWNLOAD_MODEL_ON_WORKER: (
        "songmaker_cli.music_worker._download_model_on_worker_impl", AsyncMock, ("turbo",),
    ),
    JobFunction.SCORE: (
        "songmaker_cli.scoring_worker.run_scoring_job", MagicMock, ("take", None),
    ),
}
HANDLERS = {
    function.name: function
    for function in [*MusicWorkerSettings.functions, *ScoringWorkerSettings.functions]
}


@pytest.fixture
def job_rows(pg_factory, monkeypatch):
    """Workers read this test's database and hold an owner; the helper stores a queued job."""
    for worker_class in (MusicWorker, ScoringWorker):
        monkeypatch.setattr(worker_class, "get_db_factory", lambda self: pg_factory)
        monkeypatch.setattr(worker_class, "owner", an_owner("worker"), raising=False)

    def store(status: JobStatus = JobStatus.QUEUED) -> str:
        with pg_factory() as session:
            job = create_job(session, JobType.GENERATE)
            if status is not JobStatus.QUEUED:
                update_job_status(session, job.id, JobStatusUpdate(status))
            session.commit()
            return job.id

    return store


def _deliver(function: JobFunction, job_id: str, times: int) -> MagicMock:
    """Deliver the job's message `times` times to its handler; return the work that ran."""
    target, work_type, arguments = WORK[function]
    with patch(target, new_callable=work_type) as work:
        for _ in range(times):
            asyncio.run(HANDLERS[function].coroutine({"redis": AsyncMock()}, job_id, *arguments))
    return work


@pytest.mark.parametrize("function", list(WORK))
def test_a_job_delivered_twice_runs_once(function, job_rows) -> None:
    work = _deliver(function, job_rows(), times=2)

    assert work.call_count == 1


@pytest.mark.parametrize("function", list(WORK))
def test_a_delivered_job_runs_for_the_worker_that_claimed_it(function, job_rows, pg_factory):
    job_id = job_rows()

    _deliver(function, job_id, times=1)

    with pg_factory() as session:
        job = get_job(session, job_id)
        assert (job.status, job.owner_id) == (JobStatus.RUNNING, "worker")


@pytest.mark.parametrize("function", list(WORK))
@pytest.mark.parametrize(
    "status", [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED],
)
def test_a_job_that_ended_runs_nothing(function, status, job_rows) -> None:
    work = _deliver(function, job_rows(status), times=1)

    work.assert_not_called()


@pytest.mark.parametrize("function", list(WORK))
def test_a_job_another_process_runs_is_left_to_it(function, job_rows, pg_factory) -> None:
    job_id = job_rows()
    with pg_factory() as session:
        assert claim_queued_job(session, job_id, an_owner("other-worker"))
        session.commit()

    work = _deliver(function, job_id, times=1)

    work.assert_not_called()
    with pg_factory() as session:
        assert get_job(session, job_id).owner_id == "other-worker"


@pytest.fixture
def scoring_worker(job_rows):
    """A scoring worker on this test's database; ``job_rows`` binds the class to it."""
    return ScoringWorker()


def _score_job_with_payload(pg_factory, payload: ScorePayload | None) -> str:
    with pg_factory() as session:
        job = queued_score_job(session, payload=payload)
        session.commit()
        return job.id


def test_a_worker_claims_the_next_due_job_for_itself_with_the_payload_of_its_row(
    scoring_worker, pg_factory,
) -> None:
    payload = ScorePayload(gen_id="take", scorers=("silence",))
    job_id = _score_job_with_payload(pg_factory, payload)

    claimed = scoring_worker.claim_next_job(JobType.SCORE)

    with pg_factory() as session:
        row = get_job(session, job_id)
        assert (claimed, row.status, row.owner_id) == (
            ClaimedJob(job_id, payload), JobStatus.RUNNING, "worker",
        )


def test_a_worker_with_no_due_job_claims_nothing(scoring_worker) -> None:
    assert scoring_worker.claim_next_job(JobType.SCORE) is None


def test_a_claimed_score_job_asks_the_scorer_for_the_scorers_its_row_names(
    scoring_worker, pg_factory, scorer_requests, tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(ScoringWorker, "audio_dir", lambda self: tmp_path)
    take = a_scoreable_take(pg_factory, tmp_path)
    job_id = _score_job_with_payload(pg_factory, ScorePayload(gen_id=take, scorers=("silence",)))

    claimed = scoring_worker.claim_next_job(JobType.SCORE)
    asyncio.run(scoring_worker.run_claimed(claimed))

    assert scorer_requests.call_args.kwargs["scorers"] == ["silence"]
    with pg_factory() as session:
        assert get_job(session, job_id).status == JobStatus.COMPLETED


def test_a_claimed_score_job_without_a_score_payload_fails_and_runs_nothing(
    scoring_worker, pg_factory, scorer_requests,
) -> None:
    job_id = _score_job_with_payload(pg_factory, None)

    asyncio.run(scoring_worker.run_claimed(ClaimedJob(job_id, None)))

    scorer_requests.assert_not_called()
    with pg_factory() as session:
        assert get_job(session, job_id).status == JobStatus.FAILED

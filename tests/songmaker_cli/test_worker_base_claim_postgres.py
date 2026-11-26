"""A worker claims the due rows of its queue from PostgreSQL and runs each from its row."""

from __future__ import annotations

import asyncio

import pytest
from support.job_owner import given_owner_redis
from support.score_jobs import a_scoreable_take, queued_score_job

from songmaker_cli.db.queries.jobs import (
    create_job,
    get_job,
)
from songmaker_cli.job_payloads import ScorePayload
from songmaker_cli.job_queue import ClaimedJob
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.music_worker import MusicWorker
from songmaker_cli.scoring_worker import ScoringWorker
from songmaker_cli.settings import get_settings


@pytest.fixture
def scoring_worker(workers_on_db):
    """A scoring worker on this test's database."""
    return ScoringWorker()


def _scoring_worker_with_one_place(audio_dir) -> ScoringWorker:
    settings = get_settings().model_copy(update={"audio_dir": audio_dir, "scoring_max_jobs": 1})
    return ScoringWorker(settings)


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

    claimed = scoring_worker.claim_next_job()

    with pg_factory() as session:
        row = get_job(session, job_id)
        assert (claimed, row.status, row.owner_id) == (
            ClaimedJob(job_id, JobType.SCORE, payload), JobStatus.RUNNING, "worker",
        )


def test_a_worker_with_no_due_job_claims_nothing(scoring_worker) -> None:
    assert scoring_worker.claim_next_job() is None


def test_a_claimed_score_job_asks_the_scorer_for_the_scorers_its_row_names(
    workers_on_db, pg_factory, scorer_requests, tmp_path,
) -> None:
    scoring_worker = _scoring_worker_with_one_place(tmp_path)
    take = a_scoreable_take(pg_factory, tmp_path)
    job_id = _score_job_with_payload(pg_factory, ScorePayload(gen_id=take, scorers=("silence",)))

    claimed = scoring_worker.claim_next_job()
    asyncio.run(scoring_worker.run_claimed(claimed))

    assert scorer_requests.call_args.kwargs["scorers"] == ["silence"]
    with pg_factory() as session:
        assert get_job(session, job_id).status == JobStatus.COMPLETED


def test_a_claimed_score_job_without_a_score_payload_fails_and_runs_nothing(
    scoring_worker, pg_factory, scorer_requests,
) -> None:
    job_id = _score_job_with_payload(pg_factory, None)

    asyncio.run(scoring_worker.run_claimed(ClaimedJob(job_id, JobType.SCORE, None)))

    scorer_requests.assert_not_called()
    with pg_factory() as session:
        assert get_job(session, job_id).status == JobStatus.FAILED


@pytest.mark.parametrize("job_type", MusicWorker.job_types)
def test_a_music_worker_claims_a_due_job_of_each_music_type(
    job_type, workers_on_db, pg_factory,
) -> None:
    with pg_factory() as session:
        job_id = create_job(session, job_type).id
        session.commit()

    claimed = MusicWorker().claim_next_job()

    assert claimed == ClaimedJob(job_id, job_type, None)


def test_a_music_worker_leaves_the_jobs_of_other_queues_alone(workers_on_db, pg_factory) -> None:
    with pg_factory() as session:
        create_job(session, JobType.SCORE)
        session.commit()

    assert MusicWorker().claim_next_job() is None


@pytest.mark.parametrize("written_before_rows_carried_arguments", [False, True])
@pytest.mark.parametrize(
    ("worker_class", "job_type"),
    [(MusicWorker, JobType.GENERATE), (ScoringWorker, JobType.SCORE)],
    ids=["music", "scoring"],
)
def test_a_claimed_job_without_a_payload_fails_with_a_setup_error(
    worker_class, job_type, written_before_rows_carried_arguments, workers_on_db, pg_factory,
) -> None:
    with pg_factory() as session:
        job = create_job(session, job_type)
        if written_before_rows_carried_arguments:
            job.run_after = None
        session.commit()
        job_id = job.id
    worker = given_owner_redis(worker_class())

    asyncio.run(worker.run_claimed(worker.claim_next_job()))

    with pg_factory() as session:
        job = get_job(session, job_id)
        assert (job.status, job.error_type) == (JobStatus.FAILED, "setup_error")

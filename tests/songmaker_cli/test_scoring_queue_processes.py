"""Scoring workers claim their jobs from PostgreSQL: Redis holds no job."""

from __future__ import annotations

import json

import pytest
from redis import Redis
from support.app_processes import WorkerProcess, poll_until
from support.score_jobs import queued_score_job

from songmaker_cli.db.models import Job
from songmaker_cli.job_queue import QUEUE_POLL_INTERVAL_SECONDS
from songmaker_cli.job_types import JobStatus
from songmaker_cli.worker_base import JOB_ENDED_EVENT

JOB_COUNT = 8
START_MARGIN_SECONDS = 20.0
RUN_MARGIN_SECONDS = 2.0
MISSING_GENERATION_KEY = "jobFailure.scoringGenerationMissing"


@pytest.fixture
def redis_client(redis_url: str):
    with Redis.from_url(redis_url, decode_responses=True) as client:
        yield client


def _queue_score_jobs(factory, count: int) -> list[str]:
    with factory() as session:
        jobs = [queued_score_job(session) for _ in range(count)]
        session.commit()
        return [job.id for job in jobs]


def _ended_without_a_take(factory, job_ids: list[str]) -> bool:
    with factory() as session:
        jobs = [session.get(Job, job_id) for job_id in job_ids]
        return all(
            job.status == JobStatus.FAILED and job.error_message.key == MISSING_GENERATION_KEY
            for job in jobs
        )


def _times_run(workers: list[WorkerProcess], job_id: str) -> int:
    """How many of the workers' ``arq_job.ended`` lines name the job: one per run."""
    ended = (
        json.loads(line)
        for worker in workers
        for line in worker.log_text().splitlines()
        if line.startswith("{")
    )
    return sum(1 for entry in ended if entry.get("event") == JOB_ENDED_EVENT
               and entry.get("job_id") == job_id)


def _owners(factory, job_ids: list[str]) -> set[str | None]:
    with factory() as session:
        return {session.get(Job, job_id).owner_id for job_id in job_ids}


def test_a_queued_score_job_survives_a_redis_flush_and_runs(web_cluster, redis_client) -> None:
    cluster, factory = web_cluster
    [job_id] = _queue_score_jobs(factory, 1)
    redis_client.flushdb()

    worker = cluster.start_scoring_worker("scoring")

    assert poll_until(
        lambda: _ended_without_a_take(factory, [job_id]), deadline_seconds=START_MARGIN_SECONDS,
    ), worker.log_tail()
    assert _owners(factory, [job_id]) == {worker.owner_id}


def test_a_job_queued_with_no_wake_is_claimed_within_one_poll_interval(web_cluster) -> None:
    cluster, factory = web_cluster
    worker = cluster.start_scoring_worker("scoring")
    [first] = _queue_score_jobs(factory, 1)
    assert poll_until(
        lambda: _times_run([worker], first) == 1, deadline_seconds=START_MARGIN_SECONDS,
    ), worker.log_tail()

    [job_id] = _queue_score_jobs(factory, 1)

    assert poll_until(
        lambda: _ended_without_a_take(factory, [job_id]),
        deadline_seconds=QUEUE_POLL_INTERVAL_SECONDS + RUN_MARGIN_SECONDS,
    ), worker.log_tail()


def test_two_scoring_workers_run_each_job_exactly_once(web_cluster) -> None:
    cluster, factory = web_cluster
    workers = [cluster.start_scoring_worker("first"), cluster.start_scoring_worker("second")]

    job_ids = _queue_score_jobs(factory, JOB_COUNT)

    assert poll_until(
        lambda: _ended_without_a_take(factory, job_ids),
        deadline_seconds=QUEUE_POLL_INTERVAL_SECONDS * JOB_COUNT + START_MARGIN_SECONDS,
    ), [worker.log_tail() for worker in workers]
    assert [_times_run(workers, job_id) for job_id in job_ids] == [1] * JOB_COUNT
    assert _owners(factory, job_ids) <= {worker.owner_id for worker in workers}


def test_a_cancelled_score_job_is_never_run(web_cluster) -> None:
    cluster, factory = web_cluster
    worker = cluster.start_scoring_worker("scoring")
    with factory() as session:
        cancelled_job, later_job = queued_score_job(session), queued_score_job(session)
        cancelled_job.status = JobStatus.CANCELLED
        session.commit()
        cancelled, later = cancelled_job.id, later_job.id

    assert poll_until(
        lambda: _ended_without_a_take(factory, [later]),
        deadline_seconds=QUEUE_POLL_INTERVAL_SECONDS + START_MARGIN_SECONDS,
    ), worker.log_tail()
    assert (_times_run([worker], cancelled), _owners(factory, [cancelled])) == (0, {None})

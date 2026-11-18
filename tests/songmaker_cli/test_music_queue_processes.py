"""Music workers claim their jobs from PostgreSQL: Redis holds no job."""

from __future__ import annotations

import json

import pytest
from redis import Redis
from support.app_processes import WorkerProcess, poll_until
from support.music_jobs import MISSING_VOICE_KEY, queued_music_job

from songmaker_cli.db.models import Job
from songmaker_cli.job_queue import QUEUE_POLL_INTERVAL_SECONDS
from songmaker_cli.job_types import JobStatus
from songmaker_cli.worker_base import JOB_ENDED_EVENT

JOB_COUNT = 8
START_MARGIN_SECONDS = 20.0
RUN_MARGIN_SECONDS = 2.0
WAIT_SECONDS = 2 * QUEUE_POLL_INTERVAL_SECONDS


@pytest.fixture
def redis_client(redis_url: str):
    with Redis.from_url(redis_url, decode_responses=True) as client:
        yield client


def _queue_music_jobs(factory, count: int, *, due_in: float = 0) -> list[str]:
    with factory() as session:
        jobs = [queued_music_job(session, due_in=due_in) for _ in range(count)]
        session.commit()
        return [job.id for job in jobs]


def _ended_without_the_voice(factory, job_ids: list[str]) -> bool:
    with factory() as session:
        jobs = [session.get(Job, job_id) for job_id in job_ids]
        return all(
            job.status == JobStatus.FAILED and job.error_message.key == MISSING_VOICE_KEY
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


def test_a_queued_music_job_survives_a_redis_flush_and_runs(web_cluster, redis_client) -> None:
    cluster, factory = web_cluster
    [job_id] = _queue_music_jobs(factory, 1)
    redis_client.flushdb()

    worker = cluster.start_music_worker("music")

    assert poll_until(
        lambda: _ended_without_the_voice(factory, [job_id]),
        deadline_seconds=START_MARGIN_SECONDS,
    ), worker.log_tail()
    assert _owners(factory, [job_id]) == {worker.owner_id}


def test_a_music_job_queued_with_no_wake_is_claimed_within_one_poll_interval(web_cluster) -> None:
    cluster, factory = web_cluster
    worker = cluster.start_music_worker("music")
    [first] = _queue_music_jobs(factory, 1)
    assert poll_until(
        lambda: _times_run([worker], first) == 1, deadline_seconds=START_MARGIN_SECONDS,
    ), worker.log_tail()

    [job_id] = _queue_music_jobs(factory, 1)

    assert poll_until(
        lambda: _ended_without_the_voice(factory, [job_id]),
        deadline_seconds=QUEUE_POLL_INTERVAL_SECONDS + RUN_MARGIN_SECONDS,
    ), worker.log_tail()


def test_two_music_workers_run_each_job_exactly_once(web_cluster) -> None:
    cluster, factory = web_cluster
    workers = [cluster.start_music_worker("first"), cluster.start_music_worker("second")]

    job_ids = _queue_music_jobs(factory, JOB_COUNT)

    assert poll_until(
        lambda: _ended_without_the_voice(factory, job_ids),
        deadline_seconds=QUEUE_POLL_INTERVAL_SECONDS * JOB_COUNT + START_MARGIN_SECONDS,
    ), [worker.log_tail() for worker in workers]
    assert [_times_run(workers, job_id) for job_id in job_ids] == [1] * JOB_COUNT
    assert _owners(factory, job_ids) <= {worker.owner_id for worker in workers}


def test_a_music_job_that_waits_is_not_claimed_before_its_wait_ends(web_cluster) -> None:
    cluster, factory = web_cluster
    worker = cluster.start_music_worker("music")
    [job_id] = _queue_music_jobs(factory, 1, due_in=WAIT_SECONDS)
    with factory() as session:
        wait_ends = session.get(Job, job_id).run_after

    assert poll_until(
        lambda: _ended_without_the_voice(factory, [job_id]),
        deadline_seconds=WAIT_SECONDS + QUEUE_POLL_INTERVAL_SECONDS + START_MARGIN_SECONDS,
    ), worker.log_tail()
    with factory() as session:
        assert session.get(Job, job_id).completed_at >= wait_ends


def test_a_cancelled_music_job_is_never_run(web_cluster) -> None:
    cluster, factory = web_cluster
    worker = cluster.start_music_worker("music")
    with factory() as session:
        cancelled_job, later_job = queued_music_job(session), queued_music_job(session)
        cancelled_job.status = JobStatus.CANCELLED
        session.commit()
        cancelled, later = cancelled_job.id, later_job.id

    assert poll_until(
        lambda: _ended_without_the_voice(factory, [later]),
        deadline_seconds=QUEUE_POLL_INTERVAL_SECONDS + START_MARGIN_SECONDS,
    ), worker.log_tail()
    assert (_times_run([worker], cancelled), _owners(factory, [cancelled])) == (0, {None})

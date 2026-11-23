"""Workers claim their queue's jobs from PostgreSQL: Redis holds no job."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pytest
from redis import Redis
from support.app_processes import (
    WorkerProcess,
    owners_of,
    poll_until,
    times_cron_ran,
    times_run,
)
from support.music_jobs import MISSING_VOICE_KEY, queued_music_job
from support.redis_clock import most_runs_between, redis_datetime
from support.score_jobs import queued_score_job

from songmaker_cli.constants import CRON_EVERY_SECONDS
from songmaker_cli.cron_schedule import Cron
from songmaker_cli.db.models import Job
from songmaker_cli.job_queue import QUEUE_POLL_INTERVAL_SECONDS
from songmaker_cli.job_types import JobStatus

JOB_COUNT = 8
START_MARGIN_SECONDS = 20.0
RUN_MARGIN_SECONDS = 2.0
MISSING_GENERATION_KEY = "jobFailure.scoringGenerationMissing"
SUBSCRIPTION_CONFIRMED_EVENT = "wake_subscription.confirmed"
IDLE_OBSERVATION_SECONDS = 30.0
WAIT_SECONDS = 2 * QUEUE_POLL_INTERVAL_SECONDS


@dataclass(frozen=True)
class QueueUnderTest:
    """What differs between the queues: the worker, a job that ends at once and how it fails."""

    start_worker: Callable[..., WorkerProcess]
    queue_job: Callable[..., Job]
    failure_key: str

    def queue_jobs(self, factory, count: int, *, due_in: float = 0) -> list[str]:
        with factory() as session:
            jobs = [self.queue_job(session, due_in=due_in) for _ in range(count)]
            session.commit()
            return [job.id for job in jobs]

    def ended_without_running(self, factory, job_ids: list[str]) -> bool:
        with factory() as session:
            jobs = [session.get(Job, job_id) for job_id in job_ids]
            return all(
                job.status == JobStatus.FAILED and job.error_message.key == self.failure_key
                for job in jobs
            )


@pytest.fixture(params=["score", "music"])
def queue(request, web_cluster) -> QueueUnderTest:
    cluster, _ = web_cluster
    if request.param == "score":
        return QueueUnderTest(
            cluster.start_scoring_worker, queued_score_job, MISSING_GENERATION_KEY,
        )
    return QueueUnderTest(cluster.start_music_worker, queued_music_job, MISSING_VOICE_KEY)


@pytest.fixture
def redis_client(redis_url: str):
    with Redis.from_url(redis_url, decode_responses=True) as client:
        yield client


def _subscriptions_confirmed(worker: WorkerProcess) -> int:
    """How often Redis confirmed the worker's wake subscription: once, then once per resync."""
    return worker.log_text().count(SUBSCRIPTION_CONFIRMED_EVENT)


def test_a_queued_job_survives_a_redis_flush_and_runs(queue, web_cluster, redis_client) -> None:
    _, factory = web_cluster
    [job_id] = queue.queue_jobs(factory, 1)
    redis_client.flushdb()

    worker = queue.start_worker("worker")

    assert poll_until(
        lambda: queue.ended_without_running(factory, [job_id]),
        deadline_seconds=START_MARGIN_SECONDS,
    ), worker.log_tail()
    assert owners_of(factory, [job_id]) == {worker.owner_id}


def test_a_job_queued_with_no_wake_is_claimed_within_one_poll_interval(queue, web_cluster) -> None:
    _, factory = web_cluster
    worker = queue.start_worker("worker")
    [first] = queue.queue_jobs(factory, 1)
    assert poll_until(
        lambda: times_run([worker], first) == 1, deadline_seconds=START_MARGIN_SECONDS,
    ), worker.log_tail()
    subscriptions = _subscriptions_confirmed(worker)

    [job_id] = queue.queue_jobs(factory, 1)

    assert poll_until(
        lambda: queue.ended_without_running(factory, [job_id]),
        deadline_seconds=QUEUE_POLL_INTERVAL_SECONDS + RUN_MARGIN_SECONDS,
    ), worker.log_tail()
    assert _subscriptions_confirmed(worker) == subscriptions, worker.log_tail()


def test_an_idle_worker_follows_the_wake_channel_without_subscribing_again(
    queue, web_cluster,
) -> None:
    worker = queue.start_worker("worker")
    assert poll_until(
        lambda: _subscriptions_confirmed(worker) == 1, deadline_seconds=START_MARGIN_SECONDS,
    ), worker.log_tail()

    confirmation_count_changed = poll_until(
        lambda: _subscriptions_confirmed(worker) != 1,
        deadline_seconds=IDLE_OBSERVATION_SECONDS,
    )

    assert not confirmation_count_changed, worker.log_tail()


def test_two_workers_run_each_job_exactly_once(queue, web_cluster) -> None:
    _, factory = web_cluster
    workers = [queue.start_worker("first"), queue.start_worker("second")]

    job_ids = queue.queue_jobs(factory, JOB_COUNT)

    # The worker commits the job's end before it logs `arq_job.ended`: wait for both.
    assert poll_until(
        lambda: queue.ended_without_running(factory, job_ids)
        and all(times_run(workers, job_id) >= 1 for job_id in job_ids),
        deadline_seconds=QUEUE_POLL_INTERVAL_SECONDS * JOB_COUNT + START_MARGIN_SECONDS,
    ), [worker.log_tail() for worker in workers]
    assert [times_run(workers, job_id) for job_id in job_ids] == [1] * JOB_COUNT
    assert owners_of(factory, job_ids) <= {worker.owner_id for worker in workers}


def test_a_job_that_waits_is_not_claimed_before_its_wait_ends(queue, web_cluster) -> None:
    _, factory = web_cluster
    worker = queue.start_worker("worker")
    [job_id] = queue.queue_jobs(factory, 1, due_in=WAIT_SECONDS)
    with factory() as session:
        wait_ends = session.get(Job, job_id).run_after

    assert poll_until(
        lambda: queue.ended_without_running(factory, [job_id]),
        deadline_seconds=WAIT_SECONDS + QUEUE_POLL_INTERVAL_SECONDS + START_MARGIN_SECONDS,
    ), worker.log_tail()
    with factory() as session:
        assert session.get(Job, job_id).completed_at >= wait_ends


def test_a_cancelled_job_is_never_run(queue, web_cluster) -> None:
    _, factory = web_cluster
    worker = queue.start_worker("worker")
    with factory() as session:
        cancelled_job = queue.queue_job(session)
        later_job = queue.queue_job(session)
        cancelled_job.status = JobStatus.CANCELLED
        session.commit()
        cancelled, later = cancelled_job.id, later_job.id

    assert poll_until(
        lambda: queue.ended_without_running(factory, [later]),
        deadline_seconds=QUEUE_POLL_INTERVAL_SECONDS + START_MARGIN_SECONDS,
    ), worker.log_tail()
    assert (times_run([worker], cancelled), owners_of(factory, [cancelled])) == (0, {None})


def test_two_music_workers_start_together_and_each_cron_ends_once_per_due_time(
    web_cluster, redis_client,
) -> None:
    cluster, _ = web_cluster
    started_at = redis_datetime(redis_client)
    workers = [cluster.start_music_worker("first"), cluster.start_music_worker("second")]

    def more_than_the_due_times_allow() -> bool:
        now = redis_datetime(redis_client)
        return any(
            times_cron_ran(workers, cron) > most_runs_between(cron, started_at, now)
            for cron in Cron
        )

    assert poll_until(
        lambda: all(times_cron_ran(workers, cron) >= 1 for cron in Cron),
        deadline_seconds=START_MARGIN_SECONDS,
    ), [worker.log_tail() for worker in workers]
    more_than_once_per_due_time = poll_until(
        more_than_the_due_times_allow, deadline_seconds=2 * CRON_EVERY_SECONDS,
    )

    assert not more_than_once_per_due_time, [worker.log_tail() for worker in workers]

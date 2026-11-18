"""A queue loop claims due rows from PostgreSQL; a wake only makes it look sooner."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress

import pytest
from support.job_owner import an_owner
from support.score_jobs import queued_score_job
from tandem.testing import FakeWakeBus

from songmaker_cli import job_queue
from songmaker_cli.db.queries.jobs import claim_next_queued_job, get_job
from songmaker_cli.job_queue import JobQueue, publish_queue_wake, serve_queue
from songmaker_cli.job_types import JobStatus, JobType

OWNER = an_owner("queue-worker")
REACHED_WITHIN_SECONDS = 10
HOURS = 3600
DRAIN_SECONDS = 5


class Served:
    """The jobs a loop ran and the handle to let them finish."""

    def __init__(self) -> None:
        self.ran: asyncio.Queue[str] = asyncio.Queue()
        self.finish = asyncio.Event()
        self.finish.set()

    async def next_run(self) -> str:
        return await asyncio.wait_for(self.ran.get(), REACHED_WITHIN_SECONDS)


@pytest.fixture
def poll_every(monkeypatch) -> Callable[[float], None]:
    return lambda seconds: monkeypatch.setattr(job_queue, "QUEUE_POLL_INTERVAL_SECONDS", seconds)


def _queue_score_job(factory, *, due_in: float = 0) -> str:
    with factory() as session:
        job = queued_score_job(session, due_in=due_in)
        session.commit()
        return job.id


def _claim_one(factory):
    def claim() -> str | None:
        with factory() as session:
            job = claim_next_queued_job(session, OWNER, JobType.SCORE)
            session.commit()
            return None if job is None else job.id

    return claim


@asynccontextmanager
async def _serving(factory, channel, *, capacity: int = 1) -> AsyncIterator[Served]:
    served = Served()

    async def run(job_id: str) -> None:
        served.ran.put_nowait(job_id)
        await served.finish.wait()

    loop = asyncio.create_task(
        serve_queue(
            channel, JobQueue.SCORE, claim=_claim_one(factory), run=run,
            capacity=capacity, drain_seconds=DRAIN_SECONDS,
        ),
    )
    try:
        yield served
    finally:
        served.finish.set()
        loop.cancel()
        with suppress(asyncio.CancelledError):
            await loop


def test_a_wake_makes_the_loop_claim_a_job_before_its_poll(pg_factory, poll_every) -> None:
    poll_every(HOURS)
    bus = FakeWakeBus()
    server, sender = bus.pod(), bus.pod()

    async def scenario() -> tuple[str, str]:
        async with _serving(pg_factory, server) as served:
            await asyncio.sleep(0)
            job_id = _queue_score_job(pg_factory)
            await publish_queue_wake(sender, JobQueue.SCORE)
            return job_id, await served.next_run()

    queued, ran = asyncio.run(scenario())

    assert ran == queued


def test_a_job_whose_wake_was_lost_is_claimed_by_the_poll(pg_factory, poll_every) -> None:
    poll_every(0.05)
    server = FakeWakeBus().pod()

    async def scenario() -> tuple[str, str]:
        async with _serving(pg_factory, server) as served:
            job_id = _queue_score_job(pg_factory)
            return job_id, await served.next_run()

    queued, ran = asyncio.run(scenario())

    assert ran == queued


def test_a_job_queued_while_the_subscription_was_down_is_claimed_when_it_is_back(
    pg_factory, poll_every,
) -> None:
    poll_every(HOURS)
    server = FakeWakeBus().pod()

    async def scenario() -> tuple[str, str]:
        async with _serving(pg_factory, server) as served:
            await asyncio.sleep(0)
            job_id = _queue_score_job(pg_factory)
            server.resync()
            return job_id, await served.next_run()

    queued, ran = asyncio.run(scenario())

    assert ran == queued


def test_a_loop_whose_channel_is_refused_still_claims_by_poll(pg_factory, poll_every) -> None:
    poll_every(0.05)
    server = FakeWakeBus().pod()
    server.refuse()

    async def scenario() -> tuple[str, str]:
        async with _serving(pg_factory, server) as served:
            job_id = _queue_score_job(pg_factory)
            return job_id, await served.next_run()

    queued, ran = asyncio.run(scenario())

    assert ran == queued


def test_a_job_whose_wait_is_running_is_claimed_only_after_the_wait(pg_factory, poll_every) -> None:
    poll_every(0.05)
    server = FakeWakeBus().pod()
    wait = 0.4

    async def scenario() -> tuple[float, float]:
        async with _serving(pg_factory, server) as served:
            started = asyncio.get_running_loop().time()
            _queue_score_job(pg_factory, due_in=wait)
            await served.next_run()
            return wait, asyncio.get_running_loop().time() - started

    wait, waited = asyncio.run(scenario())

    assert waited >= wait


def test_a_loop_at_capacity_claims_no_further_job_until_one_ends(pg_factory, poll_every) -> None:
    poll_every(0.05)
    server = FakeWakeBus().pod()

    async def scenario() -> tuple[JobStatus, str, str]:
        async with _serving(pg_factory, server) as served:
            served.finish.clear()
            first, second = _queue_score_job(pg_factory), _queue_score_job(pg_factory)
            running = await served.next_run()
            await asyncio.sleep(0.3)
            with pg_factory() as session:
                waiting_status = get_job(session, ({first, second} - {running}).pop()).status
            served.finish.set()
            return waiting_status, running, await served.next_run()

    waiting_status, first_run, second_run = asyncio.run(scenario())

    assert (waiting_status, first_run != second_run) == (JobStatus.QUEUED, True)


def test_a_stopping_loop_lets_its_running_job_end_and_claims_no_more(
    pg_factory, poll_every,
) -> None:
    poll_every(0.05)
    server = FakeWakeBus().pod()

    async def scenario() -> tuple[bool, JobStatus]:
        served = Served()
        ended = asyncio.Event()

        async def run(_job_id: str) -> None:
            served.ran.put_nowait(_job_id)
            await served.finish.wait()
            ended.set()

        loop = asyncio.create_task(serve_queue(
            server, JobQueue.SCORE, claim=_claim_one(pg_factory), run=run,
            capacity=1, drain_seconds=DRAIN_SECONDS,
        ))
        served.finish.clear()
        first, second = _queue_score_job(pg_factory), _queue_score_job(pg_factory)
        running = await served.next_run()
        loop.cancel()
        await asyncio.sleep(0)
        served.finish.set()
        with suppress(asyncio.CancelledError):
            await loop
        with pg_factory() as session:
            return ended.is_set(), get_job(session, ({first, second} - {running}).pop()).status

    finished, waiting_status = asyncio.run(scenario())

    assert (finished, waiting_status) == (True, JobStatus.QUEUED)

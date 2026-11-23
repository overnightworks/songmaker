"""The music worker's crons: when each is due, and how two workers share their due times."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis
from support.redis_clock import (
    redis_ms,
    until,
    until_no_file_cleanup_tick_within,
    until_redis_has_passed,
    until_redis_ms,
)

from songmaker_cli import cron_schedule
from songmaker_cli.cleanup import DAILY_CLEANUP_HOUR_UTC
from songmaker_cli.cron_schedule import Cron, cron_deadlines, next_tick, serve_due_crons
from songmaker_cli.redis_client import create_async_redis
from songmaker_cli.worker_base import CRON_ENDED_EVENT

DAILY = (Cron.GENERATION_RETENTION, Cron.REFERENCE_REMNANT, Cron.REFERENCE_UNUSED)


def _at(hour: int, minute: int = 0, second: int = 0, *, day: int = 23, micro: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, second, micro, tzinfo=UTC)


# ── the due times, pure ───────────────────────────────────────────

# (the cron, now, the next tick): the file cleanup ticks at second 0 of every even minute, the
# daily jobs at the daily cleanup hour.
NEXT_TICKS = [
    pytest.param(Cron.CLEANUP_FILES, _at(12, 34, 56), _at(12, 36), id="cleanup-between-two-ticks"),
    pytest.param(Cron.CLEANUP_FILES, _at(12, 35, 10, micro=500_000), _at(12, 36),
                 id="cleanup-in-the-same-interval"),
    pytest.param(Cron.CLEANUP_FILES, _at(12, 36), _at(12, 38), id="cleanup-on-a-tick"),
    pytest.param(Cron.CLEANUP_FILES, _at(23, 59, 59), _at(0, day=24), id="cleanup-over-midnight"),
    *[
        pytest.param(cron, now, expected, id=f"{cron}-{label}")
        for cron in DAILY
        for label, now, expected in [
            ("before-the-hour", _at(DAILY_CLEANUP_HOUR_UTC - 1, 59, 59),
             _at(DAILY_CLEANUP_HOUR_UTC)),
            ("on-the-hour", _at(DAILY_CLEANUP_HOUR_UTC), _at(DAILY_CLEANUP_HOUR_UTC, day=24)),
            ("after-the-hour", _at(DAILY_CLEANUP_HOUR_UTC, 0, 1),
             _at(DAILY_CLEANUP_HOUR_UTC, day=24)),
            ("at-the-end-of-the-day", _at(23, 59, 59), _at(DAILY_CLEANUP_HOUR_UTC, day=24)),
        ]
    ],
]


@pytest.mark.parametrize(("cron", "now", "expected"), NEXT_TICKS)
def test_the_next_tick_is_the_first_one_strictly_after_now(
    cron: Cron, now: datetime, expected: datetime,
) -> None:
    assert next_tick(cron, now) == expected


# ── two workers on a real Redis ───────────────────────────────────

EVERY = timedelta(milliseconds=20)
HELD_CLAIM_FOR = timedelta(seconds=30)
SHORT_CLAIM_FOR = timedelta(milliseconds=1500)
STOP_WAIT = SHORT_CLAIM_FOR * 2 / 3
SETTLED = timedelta(milliseconds=300)
# Longer than any scenario that counts runs: the file cleanup recurs to the next even minute.
COUNTED_WINDOW = timedelta(seconds=5)
DUE_NOW = timedelta(0)
FAR_AWAY = timedelta(hours=1)
Body = Callable[[], Awaitable[object]]


@dataclass
class Runs:
    """The runs a worker's bodies recorded, in the order they started."""

    started: list[Cron] = field(default_factory=list)
    actions: dict[Cron, Body] = field(default_factory=dict)

    def count(self, cron: Cron) -> int:
        return self.started.count(cron)

    def counts(self) -> Counter[Cron]:
        return Counter(self.started)

    def bodies(self) -> Mapping[Cron, Body]:
        return {cron: self._body(cron) for cron in Cron}

    def _body(self, cron: Cron) -> Body:
        async def run() -> None:
            self.started.append(cron)
            if cron in self.actions:
                await self.actions[cron]()

        return run


@dataclass
class Serving:
    task: asyncio.Task[None]

    async def stop(self) -> None:
        self.task.cancel()
        await asyncio.wait({self.task})


@asynccontextmanager
async def serving(
    redis_url: str, runs: Runs, *, claim_for: timedelta = HELD_CLAIM_FOR,
    stop_wait: timedelta = STOP_WAIT,
) -> AsyncIterator[Serving]:
    """One music worker's crons, on a client of its own, until the block ends."""
    redis = create_async_redis(redis_url)
    task = asyncio.create_task(serve_due_crons(
        redis, runs.bodies(), claim_for=claim_for, every=EVERY, stop_wait=stop_wait,
    ))
    worker = Serving(task)
    try:
        yield worker
    finally:
        await worker.stop()
        await redis.aclose()


@asynccontextmanager
async def reading(redis_url: str) -> AsyncIterator[Redis]:
    redis = create_async_redis(redis_url)
    try:
        yield redis
    finally:
        await redis.aclose()


def _every_cron_ran(runs: Runs, times: int = 1) -> Callable[[], bool]:
    return lambda: all(runs.count(cron) >= times for cron in Cron)


def _run_within_a_minute(scenario: Awaitable[None]) -> None:
    async def bounded() -> None:
        async with asyncio.timeout(60):
            await scenario

    asyncio.run(bounded())


@pytest.mark.parametrize("due_time", ["absent", "passed while no worker ran"])
def test_each_cron_runs_once_across_two_workers_that_start_together(
    redis_url: str, due_time: str,
) -> None:
    runs = Runs()

    async def scenario() -> None:
        async with reading(redis_url) as redis:
            await until_no_file_cleanup_tick_within(redis, COUNTED_WINDOW)
            if due_time == "passed while no worker ran":
                for cron in Cron:
                    await cron_deadlines(redis).set(cron, DUE_NOW)
            async with serving(redis_url, runs), serving(redis_url, runs):
                await until(_every_cron_ran(runs))
                await until_redis_has_passed(redis, SETTLED)

    _run_within_a_minute(scenario())

    assert runs.counts() == dict.fromkeys(Cron, 1)


def test_a_due_time_missed_while_the_worker_was_down_runs_once_after_its_restart(
    redis_url: str,
) -> None:
    runs = Runs()

    async def scenario() -> None:
        async with reading(redis_url) as redis:
            await until_no_file_cleanup_tick_within(redis, COUNTED_WINDOW)
            async with serving(redis_url, runs):
                await until(_every_cron_ran(runs))
            await cron_deadlines(redis).set(Cron.CLEANUP_FILES, DUE_NOW)
            async with serving(redis_url, runs):
                await until(lambda: runs.count(Cron.CLEANUP_FILES) == 2)
                await until_redis_has_passed(redis, SETTLED)

    _run_within_a_minute(scenario())

    assert runs.counts() == {**dict.fromkeys(Cron, 1), Cron.CLEANUP_FILES: 2}


def test_a_cron_that_is_not_yet_due_does_not_run(redis_url: str) -> None:
    runs = Runs()

    async def scenario() -> None:
        async with reading(redis_url) as redis:
            for cron in Cron:
                await cron_deadlines(redis).set(cron, FAR_AWAY)
            async with serving(redis_url, runs):
                await until_redis_has_passed(redis, SETTLED)

    _run_within_a_minute(scenario())

    assert runs.started == []


def test_reconciling_while_a_claim_is_held_neither_voids_it_nor_runs_the_cron_twice(
    redis_url: str,
) -> None:
    runs = Runs()
    release = asyncio.Event()
    runs.actions[Cron.CLEANUP_FILES] = release.wait
    counts_while_held: list[int] = []

    async def scenario() -> None:
        async with reading(redis_url) as redis:
            await until_no_file_cleanup_tick_within(redis, COUNTED_WINDOW)
            async with serving(redis_url, runs), serving(redis_url, runs):
                await until(lambda: runs.count(Cron.CLEANUP_FILES) >= 1)
                await until_redis_has_passed(redis, SETTLED)
                counts_while_held.append(runs.count(Cron.CLEANUP_FILES))
                release.set()
                await until_redis_has_passed(redis, SETTLED)

    _run_within_a_minute(scenario())

    assert counts_while_held == [1]
    assert runs.count(Cron.CLEANUP_FILES) == 1


def test_a_redis_flush_costs_each_cron_one_more_run(redis_url: str) -> None:
    runs = Runs()

    async def scenario() -> None:
        async with reading(redis_url) as redis:
            await until_no_file_cleanup_tick_within(redis, COUNTED_WINDOW)
            async with serving(redis_url, runs):
                await until(_every_cron_ran(runs))
                await until_redis_has_passed(redis, SETTLED)
                await redis.flushdb()
                await until(_every_cron_ran(runs, times=2))
                await until_redis_has_passed(redis, SETTLED)

    _run_within_a_minute(scenario())

    assert runs.counts() == dict.fromkeys(Cron, 2)


def test_a_raising_body_writes_one_failure_line_naming_its_cron_and_waits_for_its_next_tick(
    redis_url: str, caplog: pytest.LogCaptureFixture,
) -> None:
    failing = Cron.GENERATION_RETENTION
    runs = Runs()

    async def raises() -> None:
        raise RuntimeError("the body failed")

    runs.actions[failing] = raises

    async def scenario() -> None:
        async with reading(redis_url) as redis:
            async with serving(redis_url, runs, claim_for=SHORT_CLAIM_FOR):
                await until(_every_cron_ran(runs))
                await until_redis_has_passed(redis, SHORT_CLAIM_FOR + SETTLED)

    with caplog.at_level(logging.INFO):
        _run_within_a_minute(scenario())

    ended = [record for record in caplog.records if record.getMessage() == CRON_ENDED_EVENT]
    (failed,) = [record for record in ended if record.outcome == "failed"]
    (failed_handling,) = [
        record for record in caplog.records
        if record.getMessage() == "deadline_handling.ended" and record.outcome == "failed"
    ]
    assert failed.job_function == failing.value
    assert failed.parent_span_id == failed_handling.span_id
    assert runs.count(failing) == 1


def test_a_stop_waits_for_the_running_body_recurs_it_and_starts_no_further_key(
    redis_url: str,
) -> None:
    first_worker, second_worker = Runs(), Runs()
    release = asyncio.Event()
    for cron in Cron:
        first_worker.actions[cron] = release.wait
    stopped_while_waiting: list[bool] = []

    async def scenario() -> None:
        async with reading(redis_url) as redis:
            await until_no_file_cleanup_tick_within(redis, COUNTED_WINDOW)
            async with serving(redis_url, first_worker, claim_for=SHORT_CLAIM_FOR) as worker:
                await until(lambda: len(first_worker.started) == 1)
                cancelled_at_ms = await redis_ms(redis)
                worker.task.cancel()
                await until_redis_has_passed(redis, SETTLED)
                stopped_while_waiting.append(worker.task.done())
                release.set()
                await asyncio.wait({worker.task})
                assert worker.task.cancelled()
            async with serving(redis_url, second_worker, claim_for=SHORT_CLAIM_FOR):
                await until(lambda: len(second_worker.started) >= len(Cron) - 1)
                # Until a claim the stop left unrecurred has run out and come due again.
                run_out_ms = int((SHORT_CLAIM_FOR + SETTLED).total_seconds() * 1000)
                await until_redis_ms(redis, cancelled_at_ms + run_out_ms)

    _run_within_a_minute(scenario())

    held, = first_worker.started
    assert stopped_while_waiting == [False]
    assert sorted(second_worker.started) == sorted(set(Cron) - {held})


def test_a_stop_stays_a_stop_when_the_ended_body_cannot_be_recurred(
    redis_url: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    runs = Runs()
    release = asyncio.Event()
    for cron in Cron:
        runs.actions[cron] = release.wait

    async def clock_is_unreadable(_redis: Redis) -> datetime:
        raise ConnectionError("Redis TIME is unreadable")

    async def scenario() -> None:
        async with serving(redis_url, runs, claim_for=SHORT_CLAIM_FOR) as worker:
            await until(lambda: len(runs.started) == 1)
            monkeypatch.setattr(cron_schedule, "redis_now", clock_is_unreadable)
            worker.task.cancel()
            release.set()
            await until(worker.task.done)
            assert worker.task.cancelled()

    with caplog.at_level(logging.ERROR):
        _run_within_a_minute(scenario())

    assert len(runs.started) == 1
    assert [record.cron_key for record in caplog.records if record.levelno == logging.ERROR] == [
        runs.started[0].value,
    ]


def test_a_body_that_outlasts_the_stop_wait_is_cut_not_recurred_and_not_run_elsewhere_meanwhile(
    redis_url: str,
) -> None:
    long_cron = Cron.CLEANUP_FILES
    first_worker, second_worker = Runs(), Runs()
    never = asyncio.Event()
    cut_bodies: list[Cron] = []
    stopped_at_ms: list[int] = []
    first_ended_at_ms: list[int] = []
    second_started_at_ms: list[int] = []

    async def runs_until_cut() -> None:
        try:
            await never.wait()
        except asyncio.CancelledError:
            cut_bodies.append(long_cron)
            raise

    first_worker.actions[long_cron] = runs_until_cut

    async def scenario() -> None:
        async with reading(redis_url) as redis:
            async def note_start() -> None:
                second_started_at_ms.append(await redis_ms(redis))

            second_worker.actions[long_cron] = note_start
            async with serving(redis_url, first_worker, claim_for=SHORT_CLAIM_FOR) as first:
                await until(lambda: first_worker.count(long_cron) == 1)
                async with serving(redis_url, second_worker, claim_for=SHORT_CLAIM_FOR):
                    stopped_at_ms.append(await redis_ms(redis))
                    first.task.cancel()
                    await asyncio.wait({first.task})
                    first_ended_at_ms.append(await redis_ms(redis))
                    await until(lambda: second_started_at_ms)

    _run_within_a_minute(scenario())

    wait_ms = int(STOP_WAIT.total_seconds() * 1000)
    assert cut_bodies == [long_cron]
    assert first_ended_at_ms[0] >= stopped_at_ms[0] + wait_ms
    assert second_started_at_ms[0] >= stopped_at_ms[0] + wait_ms
    assert second_worker.count(long_cron) == 1


def test_an_unknown_due_key_is_cancelled_with_one_warning_naming_it(
    redis_url: str, caplog: pytest.LogCaptureFixture,
) -> None:
    unknown_key = "retired-cron"
    runs = Runs()

    async def scenario() -> None:
        async with reading(redis_url) as redis:
            await cron_deadlines(redis).set(unknown_key, DUE_NOW)
            async with serving(redis_url, runs, claim_for=SHORT_CLAIM_FOR):
                await until(_every_cron_ran(runs))
                await until_redis_has_passed(redis, SHORT_CLAIM_FOR + SETTLED)
            assert not await cron_deadlines(redis).cancel(unknown_key)

    with caplog.at_level(logging.WARNING):
        _run_within_a_minute(scenario())

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert [warning.cron_key for warning in warnings] == [unknown_key]

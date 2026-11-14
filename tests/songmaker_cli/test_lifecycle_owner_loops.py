"""The two loops that keep a process's owner lease and end the jobs of an owner that is gone."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

from redis.exceptions import ConnectionError as RedisConnectionError
from support.loop_ticks import run_ticks_observing_status

from songmaker_cli.constants import BACKGROUND_LOOP_FAILURE_THRESHOLD
from songmaker_cli.db.queries.jobs import create_job
from songmaker_cli.health_types import (
    BackgroundLoopName,
    BackgroundLoopRegistry,
    BackgroundLoopStatus,
)
from songmaker_cli.job_timing import OWNER_LEASE_TTL_SECONDS
from songmaker_cli.job_types import JobType
from songmaker_cli.lifecycle import owner_gone_reaper_loop, owner_lease_loop
from songmaker_cli.worker_liveness import owner_lease_key

OWNER = "this-process"
BLOCK_LIMIT_SECONDS = 10


class _RecordingRedis:
    """Keeps the leases set on it and the threads that set them."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.leases: dict[str, int] = {}
        self.threads: list[str] = []

    def set(self, key: str, value: str, *, ex: int) -> bool:
        if self.fail:
            raise RedisConnectionError("down")
        self.threads.append(threading.current_thread().name)
        self.leases[key] = ex
        return True

    def mget(self, keys: list[str]) -> list[str | None]:
        raise RedisConnectionError("down")


class _BlockingRedis(_RecordingRedis):
    """Holds a SET until released, as a slow Redis does."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def set(self, key: str, value: str, *, ex: int) -> bool:
        self.entered.set()
        assert self.release.wait(timeout=BLOCK_LIMIT_SECONDS)
        return super().set(key, value, ex=ex)


def _loop_app(redis) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(
        ctx=SimpleNamespace(redis=redis, owner_id=OWNER),
        background_loop_registry=BackgroundLoopRegistry(tuple(BackgroundLoopName)),
    ))


def test_the_lease_loop_renews_the_lease_off_the_event_loop(monkeypatch) -> None:
    redis = _RecordingRedis()
    app = _loop_app(redis)

    run_ticks_observing_status(
        monkeypatch, owner_lease_loop(app), app.state.background_loop_registry,
        BackgroundLoopName.OWNER_LEASE, 2,
    )

    assert redis.leases == {owner_lease_key(OWNER): OWNER_LEASE_TTL_SECONDS}
    assert threading.main_thread().name not in redis.threads


def test_the_lease_loop_keeps_ticking_and_shows_failing_while_redis_is_down(monkeypatch) -> None:
    app = _loop_app(_RecordingRedis(fail=True))

    statuses = run_ticks_observing_status(
        monkeypatch, owner_lease_loop(app), app.state.background_loop_registry,
        BackgroundLoopName.OWNER_LEASE, BACKGROUND_LOOP_FAILURE_THRESHOLD,
    )

    assert statuses[-1] is BackgroundLoopStatus.FAILING


def test_the_owner_pass_keeps_ticking_and_shows_failing_while_redis_is_down(
    monkeypatch, pg_factory,
) -> None:
    with pg_factory() as session:
        create_job(session, JobType.CHAT, owner_id="another-process")
        session.commit()
    app = _loop_app(_RecordingRedis(fail=True))
    app.state.ctx.db = pg_factory

    statuses = run_ticks_observing_status(
        monkeypatch, owner_gone_reaper_loop(app), app.state.background_loop_registry,
        BackgroundLoopName.OWNER_GONE_REAPER, BACKGROUND_LOOP_FAILURE_THRESHOLD,
    )

    assert statuses[-1] is BackgroundLoopStatus.FAILING


def test_cancelling_the_lease_loop_waits_for_the_refresh_in_flight(monkeypatch) -> None:
    redis = _BlockingRedis()
    app = _loop_app(redis)
    real_sleep = asyncio.sleep

    async def no_wait(_seconds: float) -> None:
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", no_wait)

    async def cancel_while_the_refresh_is_blocked() -> bool:
        loop_task = asyncio.ensure_future(owner_lease_loop(app))
        assert await asyncio.to_thread(redis.entered.wait, BLOCK_LIMIT_SECONDS)
        loop_task.cancel()
        for _ in range(10):
            await real_sleep(0)
        ended_while_blocked = loop_task.done()
        redis.release.set()
        await asyncio.gather(loop_task, return_exceptions=True)
        return ended_while_blocked

    ended_while_blocked = asyncio.run(cancel_while_the_refresh_is_blocked())

    assert (ended_while_blocked, redis.leases) == (
        False, {owner_lease_key(OWNER): OWNER_LEASE_TTL_SECONDS},
    )

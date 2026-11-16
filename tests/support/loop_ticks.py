"""Drive a background loop for a fixed number of ticks on a fake clock."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine

import fakeredis
import pytest
from support.owner_lease_epoch import settled_epoch

from songmaker_cli.health_types import (
    BackgroundLoopName,
    BackgroundLoopRegistry,
    BackgroundLoopStatus,
)
from songmaker_cli.lifecycle import tick_locks


def run_ticks_observing_status(
    monkeypatch: pytest.MonkeyPatch,
    loop: Coroutine[None, None, None],
    registry: BackgroundLoopRegistry,
    name: BackgroundLoopName,
    ticks: int,
    *,
    before_tick: Callable[[int], Awaitable[None]] | None = None,
) -> list[BackgroundLoopStatus]:
    """Run ``loop`` for ``ticks`` ticks; return its status before each tick and after the last.

    ``before_tick`` arranges the world of tick ``n`` once the loop has slept before it.
    """
    statuses: list[BackgroundLoopStatus] = []

    async def fake_sleep(_seconds: float) -> None:
        statuses.append(registry.loop_health()[name].status)
        if len(statuses) > ticks:
            raise asyncio.CancelledError()
        if before_tick is not None:
            await before_tick(len(statuses) - 1)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(loop)
    return statuses


class ScriptedTickLock:
    """The Redis of a loop's tick lock, which other processes and an outage take turn by turn.

    ``answers`` has one entry per tick: ``"generation"`` leaves the lock free so the tick runs,
    None has another process hold it, and an exception makes Redis unreachable. ``async_redis``
    is the client the loop under test is given; ``before_tick`` goes to
    ``run_ticks_observing_status``.
    """

    def __init__(self, lock_name: str, answers: list[object]) -> None:
        self._lock_name = lock_name
        self._answers = answers
        self._server = fakeredis.FakeServer()
        fakeredis.FakeRedis(server=self._server).set(*settled_epoch())
        self.async_redis = fakeredis.FakeAsyncRedis(server=self._server)
        self._other_process = fakeredis.FakeAsyncRedis(server=self._server)

    async def before_tick(self, tick: int) -> None:
        answer = self._answers[tick]
        self._server.connected = not isinstance(answer, BaseException)
        if not self._server.connected:
            return
        locks = tick_locks(self._other_process)
        await self._other_process.zrem(locks.keys.expiry, self._lock_name)
        if answer is None:
            assert await locks.acquire(self._lock_name) is not None

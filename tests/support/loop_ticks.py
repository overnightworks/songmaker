"""Drive a background loop for a fixed number of ticks on a fake clock."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from types import SimpleNamespace

import pytest

from songmaker_cli.health_types import (
    BackgroundLoopName,
    BackgroundLoopRegistry,
    BackgroundLoopStatus,
)


def run_ticks_observing_status(
    monkeypatch: pytest.MonkeyPatch,
    loop: Coroutine[None, None, None],
    registry: BackgroundLoopRegistry,
    name: BackgroundLoopName,
    ticks: int,
) -> list[BackgroundLoopStatus]:
    """Run ``loop`` for ``ticks`` ticks; return its status before each tick and after the last."""
    statuses: list[BackgroundLoopStatus] = []

    async def fake_sleep(_seconds: float) -> None:
        statuses.append(registry.loop_health()[name].status)
        if len(statuses) > ticks:
            raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(loop)
    return statuses


def scripted_tick_locks(results: list[object]) -> object:
    """A stand-in for ``lifecycle.tick_locks`` whose ``acquire`` answers ``results`` in order.

    An answer is a generation (the tick runs), None (another process holds the lock, or Redis
    restarted a moment ago) or an exception to raise (Redis is unreachable).
    """
    remaining = iter(results)

    async def acquire(_name: str) -> object:
        answer = next(remaining)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    return lambda _redis: SimpleNamespace(acquire=acquire)

"""Drive a background loop for a fixed number of ticks on a fake clock."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine

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

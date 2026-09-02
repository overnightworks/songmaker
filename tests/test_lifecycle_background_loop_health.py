"""Tests for the background-loop health registry."""

from __future__ import annotations

import asyncio

from songmaker_cli.constants import BACKGROUND_LOOP_FAILURE_THRESHOLD
from songmaker_cli.lifecycle import (
    BackgroundLoopName,
    BackgroundLoopRegistry,
    BackgroundLoopStatus,
)
from songmaker_cli.server import _record_background_loop_completion


async def _failing_loop_tick(registry: BackgroundLoopRegistry) -> None:
    try:
        raise RuntimeError("redis unavailable")
    except RuntimeError as exc:
        registry.record_failure(BackgroundLoopName.SCORE_BACKFILL, exc)


def test_fake_loop_becomes_failing_after_the_named_failure_threshold() -> None:
    registry = BackgroundLoopRegistry()

    for _ in range(BACKGROUND_LOOP_FAILURE_THRESHOLD):
        asyncio.run(_failing_loop_tick(registry))

    health = registry.metrics_snapshot()[BackgroundLoopName.SCORE_BACKFILL.value]
    assert health.status is BackgroundLoopStatus.FAILING
    assert health.consecutive_failures == BACKGROUND_LOOP_FAILURE_THRESHOLD
    assert health.last_error == "redis unavailable"


def test_successful_fake_tick_resets_a_failing_loop() -> None:
    registry = BackgroundLoopRegistry()
    for _ in range(BACKGROUND_LOOP_FAILURE_THRESHOLD):
        asyncio.run(_failing_loop_tick(registry))

    registry.record_success(BackgroundLoopName.SCORE_BACKFILL)

    health = registry.metrics_snapshot()[BackgroundLoopName.SCORE_BACKFILL.value]
    assert health.status is BackgroundLoopStatus.OK
    assert health.consecutive_failures == 0
    assert health.last_error is None


async def _stopped_fake_loop() -> None:
    return None


async def _never_ending_fake_loop() -> None:
    await asyncio.Future()


def test_finished_fake_loop_is_dead_outside_shutdown() -> None:
    registry = BackgroundLoopRegistry()

    async def run() -> None:
        task = asyncio.create_task(_stopped_fake_loop())
        await task
        _record_background_loop_completion(
            task, BackgroundLoopName.STALE_JOB_REAPER, registry,
        )

    asyncio.run(run())

    health = registry.metrics_snapshot()[BackgroundLoopName.STALE_JOB_REAPER.value]
    assert health.status is BackgroundLoopStatus.DEAD
    assert health.is_alive is False
    assert health.last_error == "task ended"


def test_externally_cancelled_fake_loop_is_dead_outside_shutdown() -> None:
    registry = BackgroundLoopRegistry()

    async def run() -> None:
        task = asyncio.create_task(_never_ending_fake_loop())
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        _record_background_loop_completion(task, BackgroundLoopName.SESSION_SYNC, registry)

    asyncio.run(run())

    health = registry.metrics_snapshot()[BackgroundLoopName.SESSION_SYNC.value]
    assert health.status is BackgroundLoopStatus.DEAD
    assert health.is_alive is False


def test_shutdown_does_not_mark_a_cancelled_loop_dead() -> None:
    registry = BackgroundLoopRegistry()

    async def run() -> None:
        task = asyncio.create_task(_never_ending_fake_loop())
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        registry.begin_shutdown()
        _record_background_loop_completion(task, BackgroundLoopName.SESSION_SYNC, registry)

    asyncio.run(run())

    health = registry.metrics_snapshot()[BackgroundLoopName.SESSION_SYNC.value]
    assert health.status is BackgroundLoopStatus.OK
    assert health.is_alive is True

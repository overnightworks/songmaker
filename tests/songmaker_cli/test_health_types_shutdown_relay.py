"""The shutdown state of the background loop registry and the stream relay that follows it."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from songmaker_cli.health_types import BackgroundLoopRegistry

FRAMES = ["first", "second"]


async def _finite_frames() -> AsyncGenerator[str, None]:
    for frame in FRAMES:
        yield frame


async def _silent_frames(
    waiting: asyncio.Event, closed: asyncio.Event,
) -> AsyncGenerator[str, None]:
    try:
        waiting.set()
        await asyncio.Event().wait()
        yield "never"
    finally:
        closed.set()


async def _relayed(registry: BackgroundLoopRegistry, frames) -> list[str]:
    return [frame async for frame in registry.ending_at_shutdown(frames)]


def test_a_stream_that_finishes_before_the_shutdown_relays_every_frame() -> None:
    relayed = asyncio.run(_relayed(BackgroundLoopRegistry(), _finite_frames()))

    assert relayed == FRAMES


def test_a_silent_stream_ends_and_closes_its_source_once_the_shutdown_begins() -> None:
    async def scenario() -> tuple[list[str], bool]:
        registry = BackgroundLoopRegistry()
        waiting, closed = asyncio.Event(), asyncio.Event()
        relay = asyncio.ensure_future(_relayed(registry, _silent_frames(waiting, closed)))
        await waiting.wait()
        registry.begin_shutdown()
        return await asyncio.wait_for(relay, 5), closed.is_set()

    relayed, source_closed = asyncio.run(scenario())

    assert (relayed, source_closed) == ([], True)


def test_a_second_shutdown_call_keeps_the_first_ones_start() -> None:
    registry = BackgroundLoopRegistry()
    assert registry.seconds_since_shutdown_began() == 0.0

    registry.begin_shutdown()
    first = registry.seconds_since_shutdown_began()
    registry.begin_shutdown()

    assert registry.shutting_down
    assert 0.0 <= first <= registry.seconds_since_shutdown_began()

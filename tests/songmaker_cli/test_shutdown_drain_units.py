"""The shutdown's in-process parts: stream relay, turn drain, server and cancelled turn."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import uvicorn

from songmaker_cli.conversation_api import (
    ChatTurnLifecycle,
    _running_chat_turns,
    end_running_chat_turns,
)
from songmaker_cli.health_types import BackgroundLoopRegistry
from songmaker_cli.messages import message
from songmaker_cli.server import _DrainingServer

FRAMES = ["first", "second"]


async def _finite_frames() -> AsyncGenerator[str, None]:
    for frame in FRAMES:
        yield frame


async def _silent_frames(closed: asyncio.Event) -> AsyncGenerator[str, None]:
    try:
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
        registry, closed = BackgroundLoopRegistry(), asyncio.Event()
        relay = asyncio.ensure_future(_relayed(registry, _silent_frames(closed)))
        await asyncio.sleep(0)
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


def test_the_turn_drain_returns_at_once_without_running_turns() -> None:
    asyncio.run(asyncio.wait_for(end_running_chat_turns(60), 5))


def test_the_turn_drain_lets_a_turn_finish_within_the_bound_and_cancels_the_rest() -> None:
    async def scenario() -> tuple[bool, bool]:
        quick = asyncio.ensure_future(asyncio.sleep(0))
        stuck = asyncio.ensure_future(asyncio.Event().wait())
        _running_chat_turns.update({quick, stuck})
        try:
            await end_running_chat_turns(-1)
        finally:
            _running_chat_turns.difference_update({quick, stuck})
        return quick.cancelled(), stuck.cancelled()

    assert asyncio.run(scenario()) == (False, True)


def test_the_draining_server_begins_the_shutdown_before_it_closes_its_connections() -> None:
    registry = BackgroundLoopRegistry()
    server = _DrainingServer(uvicorn.Config(MagicMock()), registry)
    seen: list[bool] = []

    async def closing(self, sockets=None) -> None:
        seen.append(registry.shutting_down)

    with patch.object(uvicorn.Server, "shutdown", closing):
        asyncio.run(server.shutdown())

    assert seen == [True]


@pytest.mark.parametrize(
    ("shutting_down", "failure", "error_type"),
    [
        pytest.param(
            True, message("chatFailure.serverRestarted"), "server_restarted",
            id="a-turn-cancelled-in-the-shutdown-fails-as-a-restart",
        ),
        pytest.param(
            False, message("chatFailure.clientCancelled"), "cancelled",
            id="a-turn-cancelled-by-its-client-fails-as-cancelled",
        ),
    ],
)
def test_a_cancelled_turn_fails_by_what_cut_it(
    shutting_down: bool, failure, error_type: str,
) -> None:
    registry = BackgroundLoopRegistry()
    if shutting_down:
        registry.begin_shutdown()
    session, heartbeat = MagicMock(), MagicMock()
    lifecycle = ChatTurnLifecycle(session, "job-1", heartbeat, registry)

    with patch("songmaker_cli.jobs._runtime._cancel_chat_job", new=AsyncMock()) as cancel:
        asyncio.run(lifecycle.finish(cancelled=True))

    cancel.assert_awaited_once_with(session, heartbeat, "job-1", failure, error_type)

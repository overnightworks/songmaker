from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from acestep_worker.child_tasks import settle_child_task

_STOPPING_YIELDS = 3


def _run(coro):
    return asyncio.run(coro)


async def _start_child(body: Callable[[], Awaitable[None]]) -> asyncio.Task[None]:
    started = asyncio.Event()

    async def run() -> None:
        started.set()
        await body()

    child = asyncio.create_task(run())
    await started.wait()
    return child


async def _wait_forever() -> None:
    await asyncio.Event().wait()


async def _stop_after_a_few_yields_when_cancelled() -> None:
    try:
        await _wait_forever()
    except asyncio.CancelledError:
        for _ in range(_STOPPING_YIELDS):
            await asyncio.sleep(0)
        raise


async def _fail_when_cancelled() -> None:
    try:
        await _wait_forever()
    except asyncio.CancelledError:
        raise OSError("failed while stopping") from None


async def _fail_at_once() -> None:
    raise OSError("failed before the cancel")


def test_settling_a_cancelled_child_returns_normally() -> None:
    """defect:#1509 -- the owner's own cancellation of its child is not an error."""

    async def go() -> bool:
        child = await _start_child(_stop_after_a_few_yields_when_cancelled)
        child.cancel()
        await settle_child_task(child)
        return child.cancelled()

    assert _run(go())


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(_fail_at_once, id="failed-before-the-cancel"),
        pytest.param(_fail_when_cancelled, id="failed-while-stopping"),
    ],
)
def test_settling_a_failed_child_raises_the_childs_own_failure(
    body: Callable[[], Awaitable[None]],
) -> None:
    """defect:#1509 -- a child that failed must not end silently after the owner cancelled it."""

    async def go() -> None:
        child = await _start_child(body)
        child.cancel()
        await settle_child_task(child)

    with pytest.raises(OSError, match="failed"):
        _run(go())


def test_cancelled_waiter_ends_cancelled_once_its_child_has_ended() -> None:
    """defect:#1509 -- cancelling the waiter was swallowed, and must not outrun the child."""

    async def go() -> bool:
        child = await _start_child(_stop_after_a_few_yields_when_cancelled)
        waiter = asyncio.create_task(settle_child_task(child))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        return child.cancelled()

    assert _run(go())

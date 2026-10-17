from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import pytest

from acestep_worker.child_tasks import settle_child_task

_STOPPING_YIELDS = 3
_HANG_GUARD_SECONDS = 5
_CHILD_TASKS_LOGGER = "acestep_worker.child_tasks"


def _run(coro):
    return asyncio.run(asyncio.wait_for(coro, _HANG_GUARD_SECONDS))


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


@dataclass
class _ChildIgnoringCancelsUntilReleased:
    """Reports each cancel it receives, and ends only once released."""

    fails_when_released: bool = False
    release: asyncio.Event = field(default_factory=asyncio.Event)
    cancels: asyncio.Queue[None] = field(default_factory=asyncio.Queue)

    async def __call__(self) -> None:
        while not self.release.is_set():
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancels.put_nowait(None)
        if self.fails_when_released:
            raise OSError("failed when released")


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
    caplog: pytest.LogCaptureFixture,
) -> None:
    """defect:#1509 -- a child that failed must not end silently after the owner cancelled it."""

    async def go() -> None:
        child = await _start_child(body)
        child.cancel()
        await settle_child_task(child)

    settling_a_failed_child = go()
    with pytest.raises(OSError, match="failed"):
        _run(settling_a_failed_child)
    assert caplog.records == []


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


@pytest.mark.parametrize("waiter_cancels", [1, 2, 3])
def test_cancelled_waiter_stays_pending_until_its_child_has_ended(waiter_cancels: int) -> None:
    """defect:#1509 -- a repeated cancel of the waiter escaped while the child still ran."""

    async def go() -> bool:
        body = _ChildIgnoringCancelsUntilReleased()
        child = await _start_child(body)
        waiter = asyncio.create_task(settle_child_task(child))
        await asyncio.sleep(0)
        try:
            for _ in range(waiter_cancels):
                waiter.cancel()
                await body.cancels.get()
            assert not waiter.done()
        finally:
            body.release.set()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        return waiter.cancelled() and child.done()

    assert _run(go())


@pytest.mark.parametrize(
    "child_stopping",
    [pytest.param(False, id="child-running"), pytest.param(True, id="child-stopping")],
)
@pytest.mark.parametrize(
    "waiter_cancelled_first",
    [
        pytest.param(False, id="failure-lands-with-the-cancel"),
        pytest.param(True, id="cancel-lands-first"),
    ],
)
def test_child_failure_behind_a_cancelled_waiter_is_logged_and_the_waiter_ends_cancelled(
    child_stopping: bool,
    waiter_cancelled_first: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """defect:#1509 -- cancelling the waiter erased a failure of the child without a trace."""

    async def go() -> bool:
        body = _ChildIgnoringCancelsUntilReleased(fails_when_released=True)
        child = await _start_child(body)
        if child_stopping:
            child.cancel()
            await body.cancels.get()
        waiter = asyncio.create_task(settle_child_task(child))
        await asyncio.sleep(0)
        if waiter_cancelled_first:
            waiter.cancel()
            await body.cancels.get()
            body.release.set()
        else:
            body.release.set()
            waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        return waiter.cancelled()

    with caplog.at_level(logging.ERROR):
        assert _run(go())
    assert [(record.name, record.levelno) for record in caplog.records] == [
        (_CHILD_TASKS_LOGGER, logging.ERROR)
    ]
    assert "OSError: failed when released" in caplog.text

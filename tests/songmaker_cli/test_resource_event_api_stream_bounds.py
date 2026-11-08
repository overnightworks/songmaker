from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest
from test_resource_event_api import _authenticated_clients, _collect, _create_event, _parse_sse

import songmaker_cli.resource_event_api as resource_api
from songmaker_cli.constants import (
    RESOURCE_EVENT_STREAM_CONNECTION_SECONDS,
    RESOURCE_EVENT_STREAM_PATH,
    SSE_HEARTBEAT_SECONDS,
)
from songmaker_cli.db.models import ResourceEvent


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _install_fake_clock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    clock = _FakeClock()
    monkeypatch.setattr(resource_api, "monotonic", clock)
    return clock


def _empty_page_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _empty_page(*_args, **_kwargs):
        return resource_api.ResourceEventPage(high_water_mark=0, events=())

    monkeypatch.setattr(resource_api, "_read_event_page_before", _empty_page)


async def _frames_until_end(generator) -> list[dict]:
    return [_parse_sse(frame) async for frame in generator]


def test_quiet_stream_sends_its_first_heartbeat_only_when_the_interval_is_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _install_fake_clock(monkeypatch)
    _empty_page_reads(monkeypatch)
    polls = 0

    async def _poll_passes(_deadline: float) -> None:
        nonlocal polls
        polls += 1
        clock.now += resource_api.RESOURCE_EVENT_STREAM_POLL_SECONDS

    monkeypatch.setattr(resource_api, "_wait_for_next_resource_poll", _poll_passes)
    generator = resource_api._resource_event_generator(None, "alice", None, 0, None)

    frames = _collect(generator, 2)

    assert frames[1] == {"comment": "heartbeat"}
    assert clock.now >= SSE_HEARTBEAT_SECONDS
    assert polls > 1


@pytest.mark.parametrize(
    ("remaining_polls", "slept_polls"),
    [(2, 1), (0.5, 0.5)],
    ids=["wall-far", "wall-within-one-poll"],
)
def test_poll_wait_never_outlasts_the_wall(
    monkeypatch: pytest.MonkeyPatch,
    remaining_polls: float,
    slept_polls: float,
) -> None:
    poll = resource_api.RESOURCE_EVENT_STREAM_POLL_SECONDS
    clock = _install_fake_clock(monkeypatch)
    deadline = RESOURCE_EVENT_STREAM_CONNECTION_SECONDS
    clock.now = deadline - remaining_polls * poll
    slept: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _record_sleep)

    asyncio.run(resource_api._wait_for_next_resource_poll(deadline))

    assert slept == [slept_polls * poll]


def test_idle_stream_ends_at_the_wall_after_a_poll_wait_cut_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    poll = resource_api.RESOURCE_EVENT_STREAM_POLL_SECONDS
    clock = _install_fake_clock(monkeypatch)
    slept: list[float] = []

    async def _read_leaving_half_a_poll(*_args, **_kwargs):
        clock.now = RESOURCE_EVENT_STREAM_CONNECTION_SECONDS - poll / 2
        return resource_api.ResourceEventPage(high_water_mark=0, events=())

    async def _record_sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.now += seconds

    monkeypatch.setattr(resource_api, "_read_event_page_before", _read_leaving_half_a_poll)
    monkeypatch.setattr(asyncio, "sleep", _record_sleep)

    frames = asyncio.run(
        _frames_until_end(resource_api._resource_event_generator(None, "alice", None, 0, None))
    )

    assert [frame["event"] for frame in frames if "event" in frame] == ["hello"]
    assert slept == [poll / 2]
    assert clock.now == RESOURCE_EVENT_STREAM_CONNECTION_SECONDS


def test_read_that_outlasts_the_wall_ends_the_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pg_factory,
) -> None:
    clients, _, users = _authenticated_clients(tmp_path, pg_factory)
    clock = _install_fake_clock(monkeypatch)
    read_may_finish = threading.Event()
    monkeypatch.setattr(resource_api, "_read_event_page", lambda *_args: read_may_finish.wait())
    generator = resource_api._resource_event_generator(
        clients["alice"].app.state.ctx, users["alice"], None, 0, None
    )

    async def _run() -> list[dict]:
        hello = _parse_sse(await anext(generator))
        clock.now = RESOURCE_EVENT_STREAM_CONNECTION_SECONDS - 0.001
        try:
            with pytest.raises(StopAsyncIteration):
                await anext(generator)
        finally:
            read_may_finish.set()
        return [hello]

    assert asyncio.run(_run())[0]["event"] == "hello"


def test_second_gap_in_one_stream_ends_it_after_the_first_resync(
    tmp_path: Path,
    pg_factory,
) -> None:
    clients, factory, users = _authenticated_clients(tmp_path, pg_factory)
    _create_event(factory, users["alice"], 1)
    _create_event(factory, users["alice"], 2)
    generator = resource_api._resource_event_generator(
        clients["alice"].app.state.ctx, users["alice"], 0, 2, 2
    )

    async def _run() -> list[dict]:
        frames = [_parse_sse(await anext(generator)), _parse_sse(await anext(generator))]
        _create_event(factory, users["alice"], 3)
        _create_event(factory, users["alice"], 4)
        with factory() as session:
            session.query(ResourceEvent).filter_by(user_id=users["alice"], sequence=3).delete()
            session.commit()
        with pytest.raises(StopAsyncIteration):
            await anext(generator)
        return frames

    frames = asyncio.run(_run())
    assert [frame["event"] for frame in frames] == ["hello", "resync"]


def test_stream_at_its_concurrent_lease_limit_is_refused_with_retry_after(
    tmp_path: Path,
    pg_factory,
) -> None:
    clients, _, _ = _authenticated_clients(tmp_path, pg_factory)

    class _FullLeaseLimiter:
        def acquire(self, _scope: str) -> None:
            return None

    clients["alice"].app.state._resource_stream_lease_limiter = _FullLeaseLimiter()
    response = clients["alice"].get(RESOURCE_EVENT_STREAM_PATH)
    assert response.status_code == 429
    assert response.json()["detail"] == resource_api.RESOURCE_EVENT_STREAM_LIMIT_DETAIL
    assert int(response.headers["Retry-After"]) > 0

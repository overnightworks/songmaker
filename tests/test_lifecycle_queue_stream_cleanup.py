"""Tests for the queue-stream cache sweep running in the periodic maintenance
loop instead of inline on every snapshot request."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import TEST_SECRET, make_fake_redis

import songmaker_cli.lifecycle as lifecycle
import songmaker_cli.queue_streams as queue_streams
from songmaker_cli.app_context import AppContext
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.lifecycle import BackgroundLoopRegistry


@pytest.fixture
def ctx(tmp_path: Path) -> AppContext:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    factory = init_test_db(tmp_path / "songmaker.db")
    return AppContext(
        db=factory, audio_dir=audio_dir, data_dir=tmp_path / "data",
        session_secret=TEST_SECRET, redis=make_fake_redis(),
    )


def _run_loop_for_n_ticks(monkeypatch, app: SimpleNamespace, n: int) -> None:
    """Drive resource_event_cleanup_loop for exactly n sleep/tick cycles."""
    tick_count = 0

    async def _fake_sleep(_seconds: float) -> None:
        nonlocal tick_count
        tick_count += 1
        if tick_count > n:
            raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(lifecycle.resource_event_cleanup_loop(app))


def test_periodic_loop_runs_resource_event_cleanup_every_tick(ctx, monkeypatch) -> None:
    calls: list[AppContext] = []
    monkeypatch.setattr(lifecycle, "cleanup_expired_resource_events", calls.append)
    monkeypatch.setattr(queue_streams, "cleanup_expired_queue_streams", lambda _ctx: None)
    app = SimpleNamespace(
        state=SimpleNamespace(ctx=ctx, background_loop_registry=BackgroundLoopRegistry()),
    )

    _run_loop_for_n_ticks(monkeypatch, app, n=3)

    assert calls == [ctx, ctx, ctx]


def test_periodic_loop_runs_queue_stream_cleanup_on_its_own_slower_interval(
    ctx, monkeypatch
) -> None:
    """Queue-stream cleanup must run on QUEUE_STREAM_CLEANUP_INTERVAL_SECONDS,
    not on every resource-event tick -- proving the two cadences are decoupled."""
    queue_stream_calls: list[AppContext] = []
    monkeypatch.setattr(lifecycle, "cleanup_expired_resource_events", lambda _ctx: 0)
    monkeypatch.setattr(
        queue_streams, "cleanup_expired_queue_streams", queue_stream_calls.append,
    )
    app = SimpleNamespace(
        state=SimpleNamespace(ctx=ctx, background_loop_registry=BackgroundLoopRegistry()),
    )
    every_n_ticks = lifecycle._QUEUE_STREAM_CLEANUP_EVERY_N_TICKS
    assert every_n_ticks > 1, "test assumes the queue-stream interval is a slower multiple"

    _run_loop_for_n_ticks(monkeypatch, app, n=every_n_ticks - 1)
    assert queue_stream_calls == [], "must not run before its own interval has elapsed"

    queue_stream_calls.clear()
    _run_loop_for_n_ticks(monkeypatch, app, n=every_n_ticks)
    assert queue_stream_calls == [ctx], "must run exactly once its own interval has elapsed"


def test_periodic_loop_survives_a_failing_queue_stream_cleanup(ctx, monkeypatch) -> None:
    """A queue-stream cleanup failure must not stop resource-event cleanup
    from running on the next tick."""
    resource_event_calls: list[AppContext] = []
    monkeypatch.setattr(lifecycle, "cleanup_expired_resource_events", resource_event_calls.append)

    def _broken_cleanup(_ctx: AppContext) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(queue_streams, "cleanup_expired_queue_streams", _broken_cleanup)
    app = SimpleNamespace(
        state=SimpleNamespace(ctx=ctx, background_loop_registry=BackgroundLoopRegistry()),
    )

    _run_loop_for_n_ticks(
        monkeypatch, app, n=lifecycle._QUEUE_STREAM_CLEANUP_EVERY_N_TICKS + 1,
    )

    assert len(resource_event_calls) == lifecycle._QUEUE_STREAM_CLEANUP_EVERY_N_TICKS + 1

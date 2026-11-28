"""Tests for the queue-stream cache sweep running in the periodic maintenance
loop instead of inline on every snapshot request."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from support.object_store import an_unreachable_object_store
from support.web_app import make_app_context, make_fake_redis, make_test_app

import songmaker_cli.lifecycle as lifecycle
import songmaker_cli.queue_streams as queue_streams
from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import BACKGROUND_LOOP_FAILURE_THRESHOLD
from songmaker_cli.health_types import (
    BackgroundLoopName,
    BackgroundLoopStatus,
)


@pytest.fixture
def ctx(tmp_path: Path, pg_factory) -> AppContext:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    return make_app_context(
        db=pg_factory,
        audio_dir=audio_dir,
        data_dir=tmp_path / "data",
        redis=make_fake_redis(),
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
    loop = lifecycle.resource_event_cleanup_loop(app)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(loop)


def test_periodic_loop_runs_resource_event_cleanup_every_tick(ctx, monkeypatch) -> None:
    calls: list[AppContext] = []
    monkeypatch.setattr(lifecycle, "cleanup_expired_resource_events", calls.append)
    monkeypatch.setattr(queue_streams, "cleanup_expired_queue_streams", lambda _ctx: None)
    app = SimpleNamespace(
        state=SimpleNamespace(ctx=ctx),
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
        state=SimpleNamespace(ctx=ctx),
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
        state=SimpleNamespace(ctx=ctx),
    )

    _run_loop_for_n_ticks(
        monkeypatch, app, n=lifecycle._QUEUE_STREAM_CLEANUP_EVERY_N_TICKS + 1,
    )

    assert len(resource_event_calls) == lifecycle._QUEUE_STREAM_CLEANUP_EVERY_N_TICKS + 1


def test_periodic_loop_reads_failing_while_the_resource_event_sweep_keeps_raising(
    ctx, monkeypatch,
) -> None:
    def _broken_sweep(_ctx: AppContext) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(lifecycle, "cleanup_expired_resource_events", _broken_sweep)
    registry = ctx.background_loops
    app = SimpleNamespace(state=SimpleNamespace(ctx=ctx))

    _run_loop_for_n_ticks(monkeypatch, app, n=BACKGROUND_LOOP_FAILURE_THRESHOLD)

    health = registry.loop_health()[BackgroundLoopName.RESOURCE_EVENT_CLEANUP]
    assert health.status is BackgroundLoopStatus.FAILING


def test_the_web_starts_and_answers_while_the_object_store_cannot_be_reached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory,
) -> None:
    client, _ = make_test_app(
        tmp_path, factory=pg_factory, object_store=an_unreachable_object_store(monkeypatch),
    )

    with client:
        assert client.get("/health").status_code == 200
        assert client.get("/login/oidc", follow_redirects=False).status_code == 303

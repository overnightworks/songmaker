"""Tests for the background-loop health registry."""

from __future__ import annotations

import asyncio
import threading
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import make_test_app

import songmaker_cli.lifecycle as lifecycle
import songmaker_cli.server as server
from songmaker_cli.constants import BACKGROUND_LOOP_FAILURE_THRESHOLD
from songmaker_cli.lifecycle import (
    BackgroundLoopName,
    BackgroundLoopRegistry,
    BackgroundLoopStatus,
)


async def _failing_loop_tick(registry: BackgroundLoopRegistry) -> None:
    try:
        raise RuntimeError("redis unavailable")
    except RuntimeError as exc:
        registry.record_failure(BackgroundLoopName.SCORE_BACKFILL, exc)


def test_fake_loop_becomes_failing_after_the_named_failure_threshold() -> None:
    registry = BackgroundLoopRegistry()

    for _ in range(BACKGROUND_LOOP_FAILURE_THRESHOLD):
        asyncio.run(_failing_loop_tick(registry))

    health = registry.loop_health()[BackgroundLoopName.SCORE_BACKFILL]
    assert health.status is BackgroundLoopStatus.FAILING
    assert health.consecutive_failures == BACKGROUND_LOOP_FAILURE_THRESHOLD
    assert health.last_error == "RuntimeError"


def test_successful_fake_tick_resets_a_failing_loop() -> None:
    registry = BackgroundLoopRegistry()
    for _ in range(BACKGROUND_LOOP_FAILURE_THRESHOLD):
        asyncio.run(_failing_loop_tick(registry))

    registry.record_success(BackgroundLoopName.SCORE_BACKFILL)

    health = registry.loop_health()[BackgroundLoopName.SCORE_BACKFILL]
    assert health.status is BackgroundLoopStatus.OK
    assert health.consecutive_failures == 0
    assert health.last_error is None


def test_loop_error_detail_does_not_expose_its_message() -> None:
    registry = BackgroundLoopRegistry()

    registry.record_failure(
        BackgroundLoopName.SCORE_BACKFILL,
        RuntimeError("api_key=top-secret\\ntraceback"),
    )

    health = registry.loop_health()[BackgroundLoopName.SCORE_BACKFILL]
    assert health.last_error == "RuntimeError"
    assert "api_key" not in health.last_error

    registry.mark_dead(
        BackgroundLoopName.SESSION_SYNC,
        asyncio.CancelledError("token=top-secret"),
    )

    health = registry.loop_health()[BackgroundLoopName.SESSION_SYNC]
    assert health.last_error == "CancelledError"
    assert "token" not in health.last_error


def test_loop_health_returns_copies_of_the_registry_state() -> None:
    registry = BackgroundLoopRegistry()

    snapshot = registry.loop_health()
    snapshot[BackgroundLoopName.SCORE_BACKFILL].is_alive = False

    health = registry.loop_health()[BackgroundLoopName.SCORE_BACKFILL]
    assert health.is_alive is True


def test_score_backfill_generation_failure_marks_the_tick_failed(monkeypatch) -> None:
    registry = BackgroundLoopRegistry()
    app = SimpleNamespace(
        state=SimpleNamespace(
            background_loop_registry=registry,
            ctx=SimpleNamespace(
                db=lambda: nullcontext(),
                redis=SimpleNamespace(set=lambda *_args, **_kwargs: True),
            ),
        ),
    )
    tick_started = False

    async def fake_sleep(_seconds: float) -> None:
        nonlocal tick_started
        if tick_started:
            raise asyncio.CancelledError()
        tick_started = True

    failing_auto_score = AsyncMock(side_effect=RuntimeError("token=top-secret"))

    monkeypatch.setattr(lifecycle.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(lifecycle, "_clear_resolved_backfill_attempts", AsyncMock())
    monkeypatch.setattr(lifecycle, "_pick_unscored_generations", lambda *_args: [("g1", "s1")])
    monkeypatch.setattr(lifecycle, "_exhausted_backfill_ids", AsyncMock(return_value=set()))
    monkeypatch.setattr(lifecycle, "_record_backfill_attempt", AsyncMock())
    monkeypatch.setattr("songmaker_cli.arq_pool.get_arq_pool", lambda: object())
    monkeypatch.setattr("songmaker_cli.jobs._auto_score_generation", failing_auto_score)

    loop = lifecycle.score_backfill_loop(app)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(loop)

    health = registry.loop_health()[BackgroundLoopName.SCORE_BACKFILL]
    failing_auto_score.assert_awaited_once()
    assert health.consecutive_failures == 1
    assert health.last_error == "RuntimeError"


def test_finished_lifecycle_loop_is_dead_outside_shutdown(
    tmp_path, monkeypatch, mock_arq_pool, caplog,
) -> None:
    async def stopped_loop(_app) -> None:
        return None

    monkeypatch.setattr(server, "session_sync_loop", stopped_loop)
    client, _ = make_test_app(tmp_path)
    with client:
        response = client.get("/health")

    health = response.json()["background_loops"][BackgroundLoopName.SESSION_SYNC]
    assert health["state"] == BackgroundLoopStatus.DEAD
    assert health["last_error"] == "task ended"
    assert "Background loop session_sync ended" in caplog.text


def test_failed_lifecycle_loop_logs_its_exception(
    tmp_path, monkeypatch, mock_arq_pool, caplog,
) -> None:
    async def failed_loop(_app) -> None:
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(server, "session_sync_loop", failed_loop)
    client, _ = make_test_app(tmp_path)
    with client:
        response = client.get("/health")

    assert response.status_code == 200
    matching_records = [
        record for record in caplog.records
        if record.getMessage() == "Background loop session_sync ended"
    ]
    assert len(matching_records) == 1
    assert isinstance(matching_records[0].exc_info[1], RuntimeError)


def test_externally_cancelling_one_lifecycle_loop_marks_only_that_loop_dead(
    tmp_path, monkeypatch, mock_arq_pool,
) -> None:
    import songmaker_cli.arq_pool as arq_pool

    monkeypatch.setenv("COVER_EXECUTOR", "music")
    monkeypatch.setattr(arq_pool, "is_music_worker_healthy", AsyncMock(return_value=True))
    monkeypatch.setattr(arq_pool, "is_scoring_worker_healthy", AsyncMock(return_value=True))
    client, _ = make_test_app(tmp_path)
    with client:
        before_cancellation = client.get("/health")
        assert before_cancellation.status_code == 200
        assert before_cancellation.json()["status"] == "ok"

        tasks = client.app.state.background_loop_tasks
        task = tasks[BackgroundLoopName.SESSION_SYNC]

        async def cancel_and_wait_for_loop() -> None:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        client.portal.call(cancel_and_wait_for_loop)
        after_cancellation = client.get("/health")

    assert after_cancellation.status_code == 200
    assert after_cancellation.json()["status"] == "ok"
    loop_health = after_cancellation.json()["background_loops"]
    assert loop_health[BackgroundLoopName.SESSION_SYNC]["state"] == BackgroundLoopStatus.DEAD
    assert {
        name: health["state"]
        for name, health in loop_health.items()
        if name != BackgroundLoopName.SESSION_SYNC
    } == {
        BackgroundLoopName.RESOURCE_EVENT_CLEANUP: BackgroundLoopStatus.OK,
        BackgroundLoopName.SCORE_BACKFILL: BackgroundLoopStatus.OK,
        BackgroundLoopName.STALE_JOB_REAPER: BackgroundLoopStatus.OK,
        BackgroundLoopName.PROVIDER_STATUS_REFRESH: BackgroundLoopStatus.OK,
    }


def test_lifecycle_shutdown_does_not_mark_cancelled_loops_dead(
    tmp_path, mock_arq_pool,
) -> None:
    client, _ = make_test_app(tmp_path)
    with client:
        registry = client.app.state.background_loop_registry

    assert all(
        health.status is BackgroundLoopStatus.OK
        for health in registry.loop_health().values()
    )


def test_music_cover_executor_does_not_start_a_web_cover_runner(
    tmp_path, monkeypatch, mock_arq_pool,
) -> None:
    recovered = []
    monkeypatch.setenv("COVER_EXECUTOR", "music")
    monkeypatch.setattr(server, "recover_web_cover_jobs", lambda *_args: recovered.append(True))
    client, _ = make_test_app(tmp_path)

    with client:
        assert BackgroundLoopName.COVER_RUNNER not in client.app.state.background_loop_tasks
    assert recovered == []


def test_web_cover_runner_is_visible_in_lifecycle_health(
    tmp_path, monkeypatch, mock_arq_pool,
) -> None:
    started = threading.Event()
    recovered = []

    async def idle_cover_runner(app) -> None:
        lifecycle.background_loop_registry(app).record_success(BackgroundLoopName.COVER_RUNNER)
        started.set()
        await asyncio.Future()

    monkeypatch.setenv("COVER_EXECUTOR", "web")
    monkeypatch.setattr(server, "recover_web_cover_jobs", lambda *_args: recovered.append(True))
    monkeypatch.setattr(server, "cover_runner_loop", idle_cover_runner)
    client, _ = make_test_app(tmp_path)

    with client:
        assert started.wait(timeout=1)
        health = client.get("/health").json()["background_loops"]
        assert health[BackgroundLoopName.COVER_RUNNER]["state"] == BackgroundLoopStatus.OK
    assert recovered == [True]


def test_provider_status_loop_fills_snapshots_and_is_healthy(
    tmp_path, monkeypatch, mock_arq_pool,
) -> None:
    from songmaker_cli.constants import COWRITER_PROVIDERS
    from songmaker_cli.cowriter.catalog import (
        ConfiguredProvider,
        ProviderRoute,
        ProviderSetupMethod,
        provider_snapshot,
    )

    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.get_provider_configuration",
        lambda provider, _surface: ConfiguredProvider(
            provider, ProviderSetupMethod.API_KEY, f"{provider.upper()}_API_KEY",
        ),
    )
    refreshed = threading.Event()
    refreshed_routes: set[tuple[str, ProviderRoute]] = set()
    expected_routes = {
        (provider, route)
        for provider in COWRITER_PROVIDERS
        for route in ProviderRoute
    }

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog._cli_is_logged_in",
        lambda _provider: True,
    )
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog._anthropic_sdk_available",
        lambda: True,
    )

    def list_provider_models(provider: str, route: ProviderRoute) -> list[str]:
        refreshed_routes.add((provider, route))
        if refreshed_routes == expected_routes:
            refreshed.set()
        return [f"{provider}-model"]

    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.list_provider_models",
        list_provider_models,
    )
    monkeypatch.setattr(
        server, "provider_status_refresh_loop", lifecycle.provider_status_refresh_loop,
    )
    client, _ = make_test_app(tmp_path)

    with client:
        assert client.portal.call(asyncio.to_thread, refreshed.wait, 1)
        health = client.get("/health").json()["background_loops"]

    assert all(provider_snapshot(provider) is not None for provider in COWRITER_PROVIDERS)
    assert refreshed_routes == expected_routes
    assert health[BackgroundLoopName.PROVIDER_STATUS_REFRESH]["state"] == BackgroundLoopStatus.OK


def test_provider_status_loop_marks_the_sweep_failed_but_continues_refreshing(
    monkeypatch,
) -> None:
    from songmaker_cli.constants import COWRITER_PROVIDERS

    registry = BackgroundLoopRegistry()
    app = SimpleNamespace(state=SimpleNamespace(background_loop_registry=registry))
    refreshed: list[str] = []

    async def refresh(_function, provider: str) -> None:
        refreshed.append(provider)
        if provider == "grok":
            raise RuntimeError("grok unavailable")

    async def stop_after_sweep(_seconds: float) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(lifecycle.asyncio, "to_thread", refresh)
    monkeypatch.setattr(lifecycle.asyncio, "sleep", stop_after_sweep)

    loop = lifecycle.provider_status_refresh_loop(app)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(loop)

    health = registry.loop_health()[BackgroundLoopName.PROVIDER_STATUS_REFRESH]
    assert refreshed == list(COWRITER_PROVIDERS)
    assert health.consecutive_failures == 1
    assert health.last_error == "RuntimeError"

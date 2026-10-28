from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from acestep_engine.constants import MODEL_CONFIG_PATHS
from acestep_worker.__main__ import (
    _AcestepWorkerLogHandler,
    build_deps,
    configure_logging,
    declared_model_sizes,
    main,
)
from acestep_worker.gpu_util import GpuHealth
from acestep_worker.lm_failure import LM_FAILURE_EXIT_CODE
from acestep_worker.model_cache import CapacityError, LoadedModel, VramStats
from acestep_worker.settings import DEFAULT_CONTAINER_BIND_HOST, WorkerSettings


def test_worker_settings_default_to_container_network_bind_host() -> None:
    settings = WorkerSettings(
        worker_id="acestep-worker-0",
        redis_url="redis://fake",
        songmaker_internal_token="secret",
    )

    assert settings.worker_bind_host == DEFAULT_CONTAINER_BIND_HOST


def test_build_deps_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_ID", "acestep-worker-0")
    monkeypatch.setenv("REDIS_URL", "redis://fake")
    monkeypatch.delenv("CONTROL_PLANE_URL", raising=False)
    monkeypatch.setenv("SONGMAKER_INTERNAL_TOKEN", "secret")
    from acestep_worker.settings import get_worker_settings
    get_worker_settings.cache_clear()

    fake_redis = MagicMock()
    with (
        patch("acestep_worker.__main__.Redis.from_url", return_value=fake_redis),
        patch(
            "acestep_worker.__main__.make_acestep_runner",
            return_value=(MagicMock(), MagicMock()),
        ),
    ):
        deps = build_deps()

    assert deps.worker_id == "acestep-worker-0"
    assert deps.registry_client is None
    assert deps.registration is None
    assert deps.heartbeat is not None
    assert isinstance(deps.gpu_health_checker(), GpuHealth)


def test_build_deps_with_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_ID", "acestep-worker-0")
    monkeypatch.setenv("REDIS_URL", "redis://fake")
    monkeypatch.setenv("CONTROL_PLANE_URL", "http://web:8080")
    monkeypatch.setenv("SONGMAKER_INTERNAL_TOKEN", "secret")
    monkeypatch.setenv("GPU_ID", "1")
    monkeypatch.setenv("VRAM_BUDGET_GB", "16")
    from acestep_worker.settings import get_worker_settings
    get_worker_settings.cache_clear()

    with (
        patch("acestep_worker.__main__.Redis.from_url", return_value=MagicMock()),
        patch(
            "acestep_worker.__main__.make_acestep_runner",
            return_value=(MagicMock(), MagicMock()),
        ),
    ):
        deps = build_deps()

    assert deps.registry_client is not None
    assert deps.registration is not None
    assert deps.registration.gpu_id == 1
    assert deps.registration.vram_total_gb == 16.0


def test_main_runs_uvicorn(monkeypatch: pytest.MonkeyPatch, isolated_logging) -> None:
    monkeypatch.setenv("WORKER_ID", "acestep-worker-0")
    monkeypatch.setenv("REDIS_URL", "redis://fake")
    monkeypatch.setenv("WORKER_BIND_HOST", "127.0.0.1")
    monkeypatch.setenv("WORKER_PORT", "8765")
    monkeypatch.setenv("SONGMAKER_INTERNAL_TOKEN", "secret")
    from acestep_worker.settings import get_worker_settings

    get_worker_settings.cache_clear()

    with (
        patch("acestep_worker.__main__.Redis.from_url", return_value=MagicMock()),
        patch(
            "acestep_worker.__main__.make_acestep_runner",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("acestep_worker.__main__.uvicorn.run") as run_mock,
    ):
        main()

    run_mock.assert_called_once()
    _, kwargs = run_mock.call_args
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8765


def test_main_exits_with_the_code_the_worker_asked_for(
    monkeypatch: pytest.MonkeyPatch, isolated_logging
) -> None:
    monkeypatch.setenv("WORKER_ID", "acestep-worker-0")
    monkeypatch.setenv("REDIS_URL", "redis://fake")
    monkeypatch.setenv("SONGMAKER_INTERNAL_TOKEN", "secret")
    from acestep_worker.settings import get_worker_settings

    get_worker_settings.cache_clear()
    deps = build_deps_with_fake_redis()

    def serve_until_the_lm_fails(app, **_kwargs) -> None:
        app.state.deps.exit_code = LM_FAILURE_EXIT_CODE

    with (
        patch("acestep_worker.__main__.build_deps", return_value=deps),
        patch("acestep_worker.__main__.uvicorn.run", side_effect=serve_until_the_lm_fails),
        pytest.raises(SystemExit) as exit_info,
    ):
        main()

    assert exit_info.value.code == LM_FAILURE_EXIT_CODE


def build_deps_with_fake_redis():
    with (
        patch("acestep_worker.__main__.Redis.from_url", return_value=MagicMock()),
        patch(
            "acestep_worker.__main__.make_acestep_runner",
            return_value=(MagicMock(), MagicMock()),
        ),
    ):
        return build_deps()


def test_configure_logging_emits_common_json_fields(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    isolated_logging,
) -> None:
    configure_logging("INFO")
    configure_logging("INFO")

    logging.getLogger("acestep.worker").info("worker ready")

    root = logging.getLogger()
    assert caplog.handler in root.handlers
    assert sum(
        isinstance(handler, _AcestepWorkerLogHandler) for handler in root.handlers
    ) == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload == {
        "event": "worker ready",
        "level": "info",
        "logger": "acestep.worker",
        "timestamp": payload["timestamp"],
    }
    assert datetime.fromisoformat(payload["timestamp"])


def test_configure_logging_includes_exception_traceback(
    capsys: pytest.CaptureFixture[str],
    isolated_logging,
) -> None:
    configure_logging("INFO")

    try:
        raise ValueError("generation failed")
    except ValueError:
        logging.getLogger("acestep.worker").exception("generation failed")

    payload = json.loads(capsys.readouterr().err)
    assert "ValueError: generation failed" in payload["exception"]


def _settings(*, init_llm: bool = True, budget_gb: float = 24.0) -> WorkerSettings:
    return WorkerSettings(
        worker_id="acestep-worker-0",
        redis_url="redis://fake",
        songmaker_internal_token="secret",
        acestep_init_llm=init_llm,
        vram_budget_gb=budget_gb,
    )


def _cache_for(
    monkeypatch: pytest.MonkeyPatch, settings: WorkerSettings, measured_used_gb: float = 0.0,
):
    loaded: list[str] = []

    async def loader(mode: str) -> LoadedModel:
        loaded.append(mode)
        return LoadedModel(mode=mode, handle=mode, port=8101)

    async def unloader(model: LoadedModel) -> None:
        return None

    stats = VramStats(measured_used_gb, settings.vram_budget_gb)
    with (
        patch("acestep_worker.__main__.Redis.from_url", return_value=MagicMock()),
        patch("acestep_worker.__main__.make_acestep_runner", return_value=(loader, unloader)),
    ):
        cache = build_deps(settings).cache
    monkeypatch.setattr("acestep_worker.__main__.read_gpu_vram_stats", lambda gpu_id: stats)
    return cache, loaded


def test_declared_sizes_add_the_language_model_to_every_mode_when_it_is_on() -> None:
    with_lm = declared_model_sizes(_settings(init_llm=True))
    without_lm = declared_model_sizes(_settings(init_llm=False))

    assert set(with_lm) == set(MODEL_CONFIG_PATHS)
    lm_overhead_gb = {mode: with_lm[mode] - without_lm[mode] for mode in with_lm}
    assert lm_overhead_gb == dict.fromkeys(with_lm, 10.0)
    assert without_lm["xl-turbo"] == 12.0


@pytest.mark.parametrize("budget_gb", [24.0, 22.0])
def test_loading_another_mode_evicts_an_idle_xl_turbo_that_holds_the_card(
    budget_gb: float, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache, loaded = _cache_for(monkeypatch, _settings(budget_gb=budget_gb))
    asyncio.run(cache.load("xl-turbo"))

    result = asyncio.run(cache.load("sft"))

    assert result.evicted == ["xl-turbo"]
    assert loaded == ["xl-turbo", "sft"]


@pytest.mark.parametrize("hold", ["pin", "in-use"])
def test_loading_another_mode_is_refused_while_xl_turbo_is_pinned_or_in_use(
    hold: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache, loaded = _cache_for(monkeypatch, _settings())
    asyncio.run(cache.load("xl-turbo"))
    if hold == "pin":
        asyncio.run(cache.pin("xl-turbo"))
    else:
        asyncio.run(cache.acquire_for_use("xl-turbo"))
    refused_load = cache.load("sft")

    with pytest.raises(CapacityError):
        asyncio.run(refused_load)

    assert cache.loaded_modes() == ["xl-turbo"]
    assert loaded == ["xl-turbo"]


def test_xl_turbo_fits_an_empty_cache_on_an_idle_card_at_the_default_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache, loaded = _cache_for(monkeypatch, _settings(budget_gb=24.0), measured_used_gb=0.5)

    result = asyncio.run(cache.load("xl-turbo"))

    assert result.evicted == []
    assert loaded == ["xl-turbo"]

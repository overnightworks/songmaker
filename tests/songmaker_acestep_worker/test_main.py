from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from logline import RequestLineMiddleware
from logline.testing import configured
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from support.request_lines import request_lines
from support.wrapper_deps import make_deps

from songmaker_acestep_engine.constants import MODEL_CONFIG_PATHS
from songmaker_acestep_worker.__main__ import (
    SERVICE_NAME,
    build_app,
    build_deps,
    declared_model_sizes,
    main,
)
from songmaker_acestep_worker.gpu_util import GpuHealth
from songmaker_acestep_worker.lm_failure import LM_FAILURE_EXIT_CODE
from songmaker_acestep_worker.model_cache import CapacityError, LoadedModel, VramStats
from songmaker_acestep_worker.settings import DEFAULT_CONTAINER_BIND_HOST, WorkerSettings
from songmaker_cli.scheduler import worker_request_headers


@pytest.fixture(autouse=True)
def _local_output_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUDIO_OUTPUT_DIR", str(tmp_path / "worker-output"))


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
    from songmaker_acestep_worker.settings import get_worker_settings

    get_worker_settings.cache_clear()

    fake_redis = MagicMock()
    with (
        patch("songmaker_acestep_worker.__main__.Redis.from_url", return_value=fake_redis),
        patch(
            "songmaker_acestep_worker.__main__.make_acestep_runner",
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
    from songmaker_acestep_worker.settings import get_worker_settings

    get_worker_settings.cache_clear()

    with (
        patch("songmaker_acestep_worker.__main__.Redis.from_url", return_value=MagicMock()),
        patch(
            "songmaker_acestep_worker.__main__.make_acestep_runner",
            return_value=(MagicMock(), MagicMock()),
        ),
    ):
        deps = build_deps()

    assert deps.registry_client is not None
    assert deps.registration is not None
    assert deps.registration.gpu_id == 1
    assert deps.registration.vram_total_gb == 16.0


def test_main_serves_on_the_configured_host_and_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_ID", "acestep-worker-0")
    monkeypatch.setenv("REDIS_URL", "redis://fake")
    monkeypatch.setenv("WORKER_BIND_HOST", "127.0.0.1")
    monkeypatch.setenv("WORKER_PORT", "8765")
    monkeypatch.setenv("SONGMAKER_INTERNAL_TOKEN", "secret")
    from songmaker_acestep_worker.settings import get_worker_settings

    get_worker_settings.cache_clear()
    served: list[tuple[str, int]] = []

    with (
        configured("restored-after-the-test"),
        patch("songmaker_acestep_worker.__main__.Redis.from_url", return_value=MagicMock()),
        patch(
            "songmaker_acestep_worker.__main__.make_acestep_runner",
            return_value=(MagicMock(), MagicMock()),
        ),
    ):
        main(serve_deps=lambda deps, host, port: served.append((host, port)) or 0)

    assert served == [("127.0.0.1", 8765)]


def test_main_exits_with_the_code_serve_owes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_ID", "acestep-worker-0")
    monkeypatch.setenv("REDIS_URL", "redis://fake")
    monkeypatch.setenv("SONGMAKER_INTERNAL_TOKEN", "secret")
    from songmaker_acestep_worker.settings import get_worker_settings

    get_worker_settings.cache_clear()

    with configured("restored-after-the-test"), pytest.raises(SystemExit) as exit_info:
        main(serve_deps=lambda *_: LM_FAILURE_EXIT_CODE)

    assert exit_info.value.code == LM_FAILURE_EXIT_CODE


def test_main_writes_the_workers_lines_under_the_acestep_worker_service_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("WORKER_ID", "acestep-worker-0")
    monkeypatch.setenv("REDIS_URL", "redis://fake")
    monkeypatch.setenv("SONGMAKER_INTERNAL_TOKEN", "secret")
    from songmaker_acestep_worker.settings import get_worker_settings

    get_worker_settings.cache_clear()

    def serve_and_log(*_) -> int:
        logging.getLogger("songmaker_acestep_worker.probe").info("probe.ended")
        return 0

    with (
        configured("restored-after-the-test"),
        patch("songmaker_acestep_worker.__main__.Redis.from_url", return_value=MagicMock()),
        patch(
            "songmaker_acestep_worker.__main__.make_acestep_runner",
            return_value=(MagicMock(), MagicMock()),
        ),
    ):
        main(serve_deps=serve_and_log)

    (line,) = [json.loads(text) for text in capsys.readouterr().out.splitlines()]
    assert (line["service"], line["event"]) == ("songmaker-acestep-worker", "probe.ended")


_INCOMING_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
_INCOMING_TRACEPARENT = f"00-{_INCOMING_TRACE_ID}-00f067aa0ba902b7-01"


def _served_worker_client(tmp_path: Path) -> TestClient:
    deps, _ = make_deps(tmp_path)
    return TestClient(build_app(deps))


def _web_app_calling_the_worker(worker_app: Starlette) -> Starlette:
    async def call_the_worker(_: Request) -> JSONResponse:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=worker_app), base_url="http://worker",
        ) as client:
            response = await client.get("/health", headers=worker_request_headers())
        return JSONResponse({"status": response.status_code})

    app = Starlette(routes=[Route("/call", call_the_worker)])
    app.add_middleware(RequestLineMiddleware)
    return app


def test_a_request_to_the_worker_writes_its_request_line_in_the_callers_trace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    with configured(SERVICE_NAME):
        response = _served_worker_client(tmp_path).get(
            "/health", headers={"traceparent": _INCOMING_TRACEPARENT},
        )

    (request_line,) = request_lines(capsys.readouterr().out)
    assert request_line["service"] == SERVICE_NAME
    assert request_line["status"] == response.status_code
    assert request_line["duration_ms"] is not None
    assert request_line["trace_id"] == _INCOMING_TRACE_ID


def test_a_trace_the_web_process_started_continues_in_the_worker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    deps, _ = make_deps(tmp_path)

    with configured("songmaker-web"):
        web_response = TestClient(_web_app_calling_the_worker(build_app(deps))).get("/call")

    worker_line, web_line = request_lines(capsys.readouterr().out)
    assert worker_line["status"] == web_response.json()["status"]
    assert worker_line["trace_id"] == web_line["trace_id"]


def _settings(*, init_llm: bool = True, budget_gb: float = 24.0) -> WorkerSettings:
    return WorkerSettings(
        worker_id="acestep-worker-0",
        redis_url="redis://fake",
        songmaker_internal_token="secret",
        acestep_init_llm=init_llm,
        vram_budget_gb=budget_gb,
    )


def _cache_for(
    monkeypatch: pytest.MonkeyPatch,
    settings: WorkerSettings,
    measured_used_gb: float = 0.0,
):
    loaded: list[str] = []

    async def loader(mode: str) -> LoadedModel:
        loaded.append(mode)
        return LoadedModel(mode=mode, handle=mode, port=8101)

    async def unloader(model: LoadedModel) -> None:
        return None

    stats = VramStats(measured_used_gb, settings.vram_budget_gb)
    with (
        patch("songmaker_acestep_worker.__main__.Redis.from_url", return_value=MagicMock()),
        patch(
            "songmaker_acestep_worker.__main__.make_acestep_runner", return_value=(loader, unloader)
        ),
    ):
        cache = build_deps(settings).cache
    monkeypatch.setattr(
        "songmaker_acestep_worker.__main__.read_gpu_vram_stats", lambda gpu_id: stats
    )
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
    budget_gb: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache, loaded = _cache_for(monkeypatch, _settings(budget_gb=budget_gb))
    asyncio.run(cache.load("xl-turbo"))

    result = asyncio.run(cache.load("sft"))

    assert result.evicted == ["xl-turbo"]
    assert loaded == ["xl-turbo", "sft"]


@pytest.mark.parametrize("hold", ["pin", "in-use"])
def test_loading_another_mode_is_refused_while_xl_turbo_is_pinned_or_in_use(
    hold: str,
    monkeypatch: pytest.MonkeyPatch,
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

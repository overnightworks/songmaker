from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import fakeredis.aioredis
import httpx
import pytest
from acestep_http import acestep_http
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import BaseRoute

from acestep_engine.constants import MODE_NOT_LOADED_DETAIL
from acestep_engine.models import AceStepConfig
from acestep_engine.progress import AceStepPhase, AceStepProgress
from acestep_worker.clock import utcnow
from acestep_worker.gpu_util import GpuHealth, GpuHealthStatus
from acestep_worker.heartbeat import (
    DEFAULT_TTL_SECONDS,
    HeartbeatLoop,
    gpu_hold_key,
    queue_depth_key,
    reserve_gpu_hold,
)
from acestep_worker.model_cache import LoadedModel, ModelCache, VramReader, VramStats
from acestep_worker.models import (
    GenerateRequest,
    GenerationTaskResult,
    TrainLoraRequest,
    WorkerTaskEvent,
)
from acestep_worker.task_store import TaskStore
from acestep_worker.wrapper import (
    WorkerDeps,
    _create_gpu_hold_handover_task,
    _format_sse,
    _renew_gpu_hold_until_done,
    _run_train_lora_with_cleanup,
    _TrainLoraResources,
    build_router,
    build_state_payload,
    create_app,
    default_generate_runner,
    read_queue_depth,
)

_INTERNAL_TOKEN_HEADER = "X-Internal-Token"
_INTERNAL_TOKEN = "test-internal-token"
_INTERNAL_HEADERS = {_INTERNAL_TOKEN_HEADER: _INTERNAL_TOKEN}
_OPEN_OPERATION = ("GET", "/health")
_FRAMEWORK_PATHS = ["/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"]


def _run(coro):
    return asyncio.run(coro)


def _worker_client(app: FastAPI) -> TestClient:
    return TestClient(app, headers=_INTERNAL_HEADERS)


def _make_deps(
    tmp_path: Path,
    *,
    vram_reader: VramReader | None = None,
    model_sizes: dict[str, float] | None = None,
    model_loader: Callable[[str], Awaitable[LoadedModel]] | None = None,
) -> tuple[WorkerDeps, fakeredis.aioredis.FakeRedis]:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    loaded_log: list[str] = []

    async def loader(mode: str) -> LoadedModel:
        loaded_log.append(mode)
        return LoadedModel(mode=mode, handle=f"handle-{mode}", port=8101)

    async def unloader(_: LoadedModel) -> None:
        return None

    cache = ModelCache(
        vram_budget_gb=24.0,
        model_sizes=model_sizes if model_sizes is not None else {"sft": 6.0, "xl-sft": 12.0},
        loader=model_loader or loader,
        unloader=unloader,
        vram_reader=vram_reader,
    )
    task_store = TaskStore()

    async def fake_generate_runner(
        store: TaskStore,
        task_id: str,
        *,
        mode: str,
        config: AceStepConfig,
        port: int,
        audio_output_dir: Path,
    ) -> None:
        await store.mark_running(task_id)
        await store.complete(
            task_id,
            GenerationTaskResult(
                mode=mode,
                audio_path=f"/fake/{task_id}.wav",
                seed=42,
            ),
        )

    deps = WorkerDeps(
        worker_id="acestep-worker-0",
        cache=cache,
        task_store=task_store,
        heartbeat=None,  # type: ignore[arg-type]
        redis=redis,
        registry_client=None,
        registration=None,
        checkpoint_dir=tmp_path,
        audio_output_dir=tmp_path / "audio",
        internal_token=_INTERNAL_TOKEN,
        generate_runner=fake_generate_runner,
    )
    deps.heartbeat = HeartbeatLoop(
        redis=redis,
        worker_id="acestep-worker-0",
        state_provider=lambda: build_state_payload(deps),
    )
    return deps, redis


def _served_operations(routes: Iterable[BaseRoute]) -> list[tuple[str, str]]:
    operations: list[tuple[str, str]] = []
    for route in routes:
        included_router = getattr(route, "original_router", None)
        if included_router is not None:
            operations.extend(_served_operations(included_router.routes))
        else:
            operations.extend((method, route.path) for method in sorted(route.methods))
    return operations


_SERVED_OPERATIONS = _served_operations(create_app(_make_deps(Path("unused"))[0]).routes)
_PROTECTED_OPERATIONS = [
    operation for operation in _SERVED_OPERATIONS if operation != _OPEN_OPERATION
]
_OPERATION_IDS = [f"{method} {path}" for method, path in _PROTECTED_OPERATIONS]


@pytest.fixture
def recorded_process_kills(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int]]:
    kills: list[tuple[int, int]] = []
    monkeypatch.setattr("acestep_worker.lm_failure.os.kill", lambda p, s: kills.append((p, s)))
    return kills


@pytest.fixture
def headerless_client(
    tmp_path: Path,
    recorded_process_kills: list[tuple[int, int]],
) -> TestClient:
    deps, _ = _make_deps(tmp_path)
    return TestClient(create_app(deps))


def _call_operation(
    client: TestClient,
    method: str,
    path: str,
    token: bytes | None,
) -> httpx.Response:
    headers = [] if token is None else [(_INTERNAL_TOKEN_HEADER.encode(), token)]
    return client.request(method, re.sub(r"\{\w+\}", "ghost", path), json={}, headers=headers)


def _complains_about_missing_token(response: httpx.Response) -> bool:
    return response.status_code == 422 and any(
        error["loc"] == ["header", _INTERNAL_TOKEN_HEADER] for error in response.json()["detail"]
    )


def test_enumeration_reaches_operations_on_the_app_and_on_included_routers() -> None:
    assert {_OPEN_OPERATION, ("POST", "/generate")} <= set(_SERVED_OPERATIONS)


@pytest.mark.parametrize(("method", "path"), _PROTECTED_OPERATIONS, ids=_OPERATION_IDS)
def test_every_worker_operation_but_health_asks_for_the_internal_token(
    headerless_client: TestClient,
    method: str,
    path: str,
) -> None:
    response = _call_operation(headerless_client, method, path, token=None)

    assert _complains_about_missing_token(response)


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(b"wrong-token", id="wrong"),
        pytest.param(b"", id="empty"),
        pytest.param("t\u00f6ken".encode(), id="non-ascii"),
    ],
)
@pytest.mark.parametrize(("method", "path"), _PROTECTED_OPERATIONS, ids=_OPERATION_IDS)
def test_every_worker_operation_but_health_refuses_a_wrong_token(
    headerless_client: TestClient,
    method: str,
    path: str,
    token: bytes,
) -> None:
    response = _call_operation(headerless_client, method, path, token)

    assert response.status_code == 401


@pytest.mark.parametrize(("method", "path"), _PROTECTED_OPERATIONS, ids=_OPERATION_IDS)
def test_every_worker_operation_but_health_accepts_the_right_token(
    headerless_client: TestClient,
    method: str,
    path: str,
) -> None:
    response = _call_operation(headerless_client, method, path, _INTERNAL_TOKEN.encode())

    assert response.status_code != 401
    assert not _complains_about_missing_token(response)


@pytest.mark.parametrize("path", _FRAMEWORK_PATHS)
def test_worker_does_not_serve_the_framework_documentation_routes(
    headerless_client: TestClient,
    path: str,
) -> None:
    assert headerless_client.get(path).status_code == 404


def test_format_sse_payload() -> None:
    event = WorkerTaskEvent(type="progress", data={"progress": 0.5})
    raw = _format_sse(event)
    assert raw.startswith(b"event: progress\n")
    assert b"data: " in raw
    assert raw.endswith(b"\n\n")


def test_read_queue_depth_default(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    depth = _run(read_queue_depth(deps.redis, deps.worker_id))
    assert depth == 0


def test_read_queue_depth_set(tmp_path: Path) -> None:
    deps, redis = _make_deps(tmp_path)

    async def go():
        await redis.set(queue_depth_key(deps.worker_id), 5)
        return await read_queue_depth(deps.redis, deps.worker_id)

    assert _run(go()) == 5


def test_health_endpoint(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("path", "method", "error_statuses"),
    [
        pytest.param("/health", "get", {"503"}, id="health"),
        pytest.param("/load_model", "post", {"400", "409", "502"}, id="load-model"),
        pytest.param("/evict_model", "post", {"409"}, id="evict-model"),
        pytest.param("/pin_model", "post", {"409"}, id="pin-model"),
        pytest.param("/generate", "post", {"409"}, id="generate"),
        pytest.param("/gpu_hold/reserve", "post", {"409"}, id="reserve-gpu-hold"),
        pytest.param("/gpu_hold/renew", "post", {"409"}, id="renew-gpu-hold"),
        pytest.param("/gpu_hold/release", "post", {"409"}, id="release-gpu-hold"),
        pytest.param("/tasks/train_lora", "post", {"409", "422", "501"}, id="train-lora"),
        pytest.param("/tasks/{task_id}", "get", {"404"}, id="get-task"),
        pytest.param("/tasks/{task_id}/stream", "get", {"404"}, id="stream-task"),
    ],
)
def test_worker_api_documents_its_http_error_responses(
    tmp_path: Path,
    path: str,
    method: str,
    error_statuses: set[str],
) -> None:
    deps, _ = _make_deps(tmp_path)
    schema = create_app(deps).openapi()
    documented_responses = schema["paths"][path][method]["responses"]

    assert error_statuses.issubset(documented_responses)


def test_health_returns_503_when_gpu_is_unavailable(tmp_path: Path) -> None:
    """Issue #367: a worker whose NVML call fails (GPU vanished, driver
    mismatch) must fail its own healthcheck — never stay green while
    unable to generate. Simulated, not a lucky real GPU."""
    deps, _ = _make_deps(tmp_path)
    deps.gpu_health_checker = lambda: GpuHealth(
        GpuHealthStatus.UNAVAILABLE,
        detail="Driver/library version mismatch",
    )
    app = create_app(deps)
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 503
    assert "GPU unavailable" in resp.json()["detail"]
    assert "Driver/library version mismatch" in resp.json()["detail"]


def test_health_stays_200_when_pynvml_not_installed(tmp_path: Path) -> None:
    """A CI/test host with no NVIDIA driver is not a broken worker."""
    deps, _ = _make_deps(tmp_path)
    deps.gpu_health_checker = lambda: GpuHealth(GpuHealthStatus.NOT_INSTALLED)
    app = create_app(deps)
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_build_state_payload_carries_gpu_healthy_false_when_gpu_unavailable(
    tmp_path: Path,
) -> None:
    from acestep_worker.wrapper import build_state_payload

    deps, _ = _make_deps(tmp_path)
    deps.gpu_health_checker = lambda: GpuHealth(
        GpuHealthStatus.UNAVAILABLE,
        detail="Driver/library version mismatch",
    )
    payload = _run(build_state_payload(deps))
    assert payload["gpu_healthy"] is False
    assert payload["gpu_health_detail"] == "Driver/library version mismatch"


def test_build_state_payload_carries_gpu_healthy_true_by_default(
    tmp_path: Path,
) -> None:
    from acestep_worker.wrapper import build_state_payload

    deps, _ = _make_deps(tmp_path)
    payload = _run(build_state_payload(deps))
    assert payload["gpu_healthy"] is True
    assert payload["gpu_health_detail"] is None


def test_loaded_models_initial(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with _worker_client(app) as client:
        resp = client.get("/loaded_models")
    assert resp.status_code == 200
    body = resp.json()
    assert body["loaded"] == []
    assert body["target_loading"] is None
    assert body["queue_depth"] == 0
    assert body["vram_total_gb"] == 24.0
    assert body["vram_measured"] is False
    assert body["available_modes"] == []
    assert body["loading_last_log_line"] is None


def test_loaded_models_reports_vram_measured_true_with_a_reader(tmp_path: Path) -> None:
    deps, _ = _make_deps(
        tmp_path,
        vram_reader=lambda: VramStats(used_gb=15.3, total_gb=24.0),
    )
    app = create_app(deps)
    with _worker_client(app) as client:
        resp = client.get("/loaded_models")
    body = resp.json()
    assert body["vram_measured"] is True
    assert body["vram_used_gb"] == 15.3


def test_loaded_models_with_downloaded_mode(tmp_path: Path) -> None:
    sft_dir = tmp_path / "checkpoints" / "acestep-v15-sft"
    sft_dir.mkdir(parents=True)
    (sft_dir / "config.json").write_text("{}")
    (sft_dir / "model.safetensors").write_bytes(b"x")
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with _worker_client(app) as client:
        resp = client.get("/loaded_models")
    assert "sft" in resp.json()["available_modes"]


def test_load_model_success(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with _worker_client(app) as client:
        resp = client.post("/load_model", json={"mode": "sft"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["loaded"] == ["sft"]
    assert body["evicted"] == []


def test_load_model_unknown_mode(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with _worker_client(app) as client:
        resp = client.post("/load_model", json={"mode": "ghost"})
    assert resp.status_code == 400


@pytest.mark.parametrize("status", [409, 502])
def test_load_model_last_error_matches_response(tmp_path: Path, status: int) -> None:
    """S15-01: Load model last error matches response."""
    from acestep_worker.subprocess_runner import SubprocessStartError
    from songmaker_cli.acestep_state import read_worker_state

    async def failing_loader(mode: str) -> LoadedModel:
        raise SubprocessStartError("ACE-Step did not become healthy\nloading shard 2/4")

    deps, redis = _make_deps(
        tmp_path,
        model_sizes={"sft": 100.0 if status == 409 else 6.0},
        model_loader=failing_loader,
    )

    async def go():
        before = utcnow()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(deps)),
            base_url="http://worker", headers=_INTERNAL_HEADERS,
        ) as client:
            denied = await client.post(
                "/load_model", json={"mode": "sft"},
                headers={_INTERNAL_TOKEN_HEADER: "wrong-token"},
            )
            assert denied.status_code == 401
            assert (await build_state_payload(deps))["last_error"] is None
            response = await client.post("/load_model", json={"mode": "sft"})
        assert response.status_code == status
        if status == 502:
            assert response.json()["detail"] == "ACE-Step did not become healthy\nloading shard 2/4"
        await deps.heartbeat.publish_once()
        state = await read_worker_state(redis, deps.worker_id)
        assert state["last_error"] == response.json()["detail"]
        at = datetime.fromisoformat(state["last_error_at"])
        assert at.utcoffset() == timedelta(0)
        assert before <= at <= utcnow()

    _run(go())


@pytest.fixture
def last_error_worker(tmp_path: Path):
    from songmaker_cli.acestep_state import read_worker_state

    deps, redis = _make_deps(tmp_path)
    successful_runner = deps.generate_runner

    async def publish_pair():
        await deps.heartbeat.publish_once()
        state = await read_worker_state(redis, deps.worker_id)
        return state["last_error"], state["last_error_at"]

    async def generate_then_publish(client, failure: str | None):
        completed = asyncio.Event()

        async def runner(store, task_id, **kwargs):
            if failure is None:
                await successful_runner(store, task_id, **kwargs)
            else:
                await store.fail(task_id, failure)
            # Wake after the runner's completion edge has released its resources.
            asyncio.get_running_loop().call_soon(completed.set)

        deps.generate_runner = runner
        response = await client.post(
            "/generate", json={"mode": "sft", "config": {"prompt": "x", "lyrics": ""}},
        )
        assert response.status_code == 200
        await asyncio.wait_for(completed.wait(), timeout=5)
        task = await deps.task_store.get(response.json()["task_id"])
        assert task.state == ("done" if failure is None else "error")
        assert deps.cache.in_use_count("sft") == 0
        pair = await publish_pair()
        if failure is not None:
            assert pair == (task.error, task.updated_at.isoformat())
        assert await publish_pair() == pair
        return pair

    @asynccontextmanager
    async def worker():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(deps)),
            base_url="http://worker", headers=_INTERNAL_HEADERS,
        ) as client:
            assert (await client.post("/load_model", json={"mode": "sft"})).status_code == 200
            yield client, publish_pair, generate_then_publish

    return worker


def test_generate_last_error_matches_task_snapshot(last_error_worker) -> None:
    """S15-02: Generate last error matches task snapshot."""
    async def go():
        async with last_error_worker() as (client, _, generate_then_publish):
            await generate_then_publish(client, "ACE-Step failed\noriginal worker detail")

    _run(go())


@pytest.mark.parametrize("success", ["load", "generate"])
def test_last_error_survives_success_and_is_replaced(
    tmp_path: Path, success: str, last_error_worker,
) -> None:
    """S15-03: Last error survives success and is replaced."""
    async def go():
        async with last_error_worker() as (client, publish_pair, generate_then_publish):
            first = await generate_then_publish(client, "ACE-Step failed\noriginal worker detail")

            if success == "load":
                response = await client.post("/load_model", json={"mode": "xl-sft"})
                assert response.status_code == 200
                assert await publish_pair() == first
                assert await publish_pair() == first
            else:
                assert await generate_then_publish(client, None) == first

            later = await generate_then_publish(client, "RuntimeError: later failure")
            assert later != first

            other, _ = _make_deps(tmp_path)
            untouched = await build_state_payload(other)
            assert untouched["last_error"] is None
            assert untouched["last_error_at"] is None

    _run(go())


def test_evict_model(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with _worker_client(app) as client:
        client.post("/load_model", json={"mode": "sft"})
        resp = client.post("/evict_model", json={"mode": "sft"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["evicted"] == ["sft"]
    assert body["loaded"] == []


def test_generate_answers_an_unloaded_mode_the_way_the_scheduler_recognizes(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with _worker_client(app) as client:
        resp = client.post(
            "/generate",
            json={"mode": "sft", "config": {"prompt": "test", "lyrics": ""}},
        )
    assert resp.status_code == 409
    assert resp.json()["detail"] == MODE_NOT_LOADED_DETAIL.format(mode="sft")


def test_generate_acquisition_serializes_with_hold_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    deps, _ = _make_deps(tmp_path)
    generation_started = asyncio.Event()
    allow_generation_to_finish = asyncio.Event()
    spawned: list[object] = []

    async def scenario() -> None:
        await deps.cache.load("sft")

        async def blocking_runner(*_args, **_kwargs) -> None:
            generation_started.set()
            await allow_generation_to_finish.wait()

        deps.generate_runner = blocking_runner
        monkeypatch.setattr("acestep_worker.wrapper.spawn_background", spawned.append)
        router = build_router(deps)
        generate = next(route.endpoint for route in router.routes if route.path == "/generate")
        reserve = next(
            route.endpoint for route in router.routes if route.path == "/gpu_hold/reserve"
        )
        generated = await generate(
            GenerateRequest(mode="sft", config=AceStepConfig(prompt="test", lyrics=""))
        )
        assert generated.task_id
        running_generation = asyncio.create_task(spawned.pop())
        await generation_started.wait()
        reserve_task = asyncio.create_task(reserve())
        with pytest.raises(HTTPException, match="GPU is busy or held"):
            await reserve_task
        allow_generation_to_finish.set()
        await running_generation

        assert (await reserve()).token
        held_generation = generate(
            GenerateRequest(mode="sft", config=AceStepConfig(prompt="test", lyrics=""))
        )
        with pytest.raises(HTTPException, match="GPU is held for LoRA training"):
            await held_generation
        await deps.redis.delete(gpu_hold_key(deps.worker_id))

    _run(scenario())


def test_generate_rejects_a_worker_held_for_lora_training(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with _worker_client(app) as client:
        assert client.post("/load_model", json={"mode": "sft"}).status_code == 200
        reserve = client.post(
            "/gpu_hold/reserve",
        )
        assert reserve.status_code == 200
        resp = client.post(
            "/generate",
            json={"mode": "sft", "config": {"prompt": "test", "lyrics": ""}},
        )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "GPU is held for LoRA training"


def test_generate_returns_a_task_that_starts_loading_its_model(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with _worker_client(app) as client:
        client.post("/load_model", json={"mode": "sft"})
        resp = client.post(
            "/generate",
            json={"mode": "sft", "config": {"prompt": "test", "lyrics": ""}},
        )
        task = client.get(f"/tasks/{resp.json()['task_id']}")
    assert resp.status_code == 200
    assert resp.json()["task_id"].startswith("gen-")
    assert task.json()["phase"] == "loading_model"


def _full_ace_step_config_payload() -> dict[str, Any]:
    """A generation request shaped like the real scheduler payload — every
    AceStepConfig field present, several set away from their defaults."""
    return asdict(
        AceStepConfig(
            prompt="synthwave anthem",
            lyrics="verse one\nchorus",
            bpm=128,
            audio_duration=90,
            seed=42,
            inference_steps=12,
            guidance_scale=1.5,
            batch_size=2,
        )
    )


def test_generate_passes_the_full_config_through_losslessly(tmp_path: Path) -> None:
    """Issue #383 finding 1: an unrecognized config field must not silently
    fall back to a default — prove the honest path first: every field of a
    full, valid payload survives the HTTP boundary as a typed AceStepConfig."""
    deps, _ = _make_deps(tmp_path)
    received: list[AceStepConfig] = []

    async def capturing_runner(
        store: TaskStore,
        task_id: str,
        *,
        mode: str,
        config: AceStepConfig,
        port: int,
        audio_output_dir: Path,
    ) -> None:
        received.append(config)
        await store.mark_running(task_id)
        await store.complete(
            task_id,
            GenerationTaskResult(mode=mode, audio_path="/x", seed=0),
        )

    deps.generate_runner = capturing_runner
    app = create_app(deps)
    payload = _full_ace_step_config_payload()
    with _worker_client(app) as client:
        client.post("/load_model", json={"mode": "sft"})
        resp = client.post("/generate", json={"mode": "sft", "config": payload})

    assert resp.status_code == 200
    assert len(received) == 1
    assert isinstance(received[0], AceStepConfig)
    assert asdict(received[0]) == payload


def test_generate_rejects_an_unrecognized_config_field(tmp_path: Path) -> None:
    """A typo'd or renamed field (audio_duraton vs audio_duration) must 422,
    not silently vanish behind AceStepConfig's default for the real field."""
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    payload = {**_full_ace_step_config_payload(), "audio_duraton": 91}
    with _worker_client(app) as client:
        client.post("/load_model", json={"mode": "sft"})
        resp = client.post("/generate", json={"mode": "sft", "config": payload})
    assert resp.status_code == 422


def test_generate_rejects_a_missing_required_config_field(tmp_path: Path) -> None:
    """lyrics has no default on AceStepConfig — omitting it must 422, not
    construct a half-built config."""
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    payload = _full_ace_step_config_payload()
    del payload["lyrics"]
    with _worker_client(app) as client:
        client.post("/load_model", json={"mode": "sft"})
        resp = client.post("/generate", json={"mode": "sft", "config": payload})
    assert resp.status_code == 422


def test_download_model_returns_task_id(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)

    async def fake_download(repo_id: str, local_dir: Path) -> None:
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "config.json").write_text("{}")

    from acestep_worker import wrapper as wrapper_module

    original_start = wrapper_module.start_download

    async def fake_start(store, *, mode, checkpoint_dir):
        return await original_start(
            store,
            mode=mode,
            checkpoint_dir=checkpoint_dir,
            download_fn=fake_download,
        )

    wrapper_module.start_download = fake_start  # type: ignore[assignment]
    try:
        with _worker_client(app) as client:
            resp = client.post("/download_model", json={"mode": "sft"})
    finally:
        wrapper_module.start_download = original_start  # type: ignore[assignment]
    assert resp.status_code == 200
    assert resp.json()["task_id"].startswith("dow-")


def test_get_task_unknown(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with _worker_client(app) as client:
        resp = client.get("/tasks/ghost")
    assert resp.status_code == 404


def test_get_task_known(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with _worker_client(app) as client:
        client.post("/load_model", json={"mode": "sft"})
        gen = client.post(
            "/generate",
            json={"mode": "sft", "config": {"prompt": "x", "lyrics": ""}},
        )
        task_id = gen.json()["task_id"]
        for _ in range(20):
            resp = client.get(f"/tasks/{task_id}")
            if resp.json()["state"] == "done":
                break
    assert resp.json()["state"] == "done"
    assert resp.json()["result"]["seed"] == 42


def test_stream_task_unknown(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with _worker_client(app) as client:
        resp = client.get("/tasks/ghost/stream")
    assert resp.status_code == 404


def test_stream_task_yields_done(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with _worker_client(app) as client:
        client.post("/load_model", json={"mode": "sft"})
        gen = client.post(
            "/generate",
            json={"mode": "sft", "config": {"prompt": "x", "lyrics": ""}},
        )
        task_id = gen.json()["task_id"]
        for _ in range(20):
            snap = client.get(f"/tasks/{task_id}").json()
            if snap["state"] == "done":
                break
        with client.stream("GET", f"/tasks/{task_id}/stream") as resp:
            body = b"".join(resp.iter_bytes())
    assert b"event: done" in body
    assert b'"state": "done"' in body or b'"state":"done"' in body


def _patch_engine_modules(monkeypatch: pytest.MonkeyPatch, generate) -> None:
    """Point the runner's lazy engine-client import at a stub client."""
    import sys

    fake_client_cls = MagicMock()
    fake_client_cls.return_value.generate = generate
    monkeypatch.setitem(
        sys.modules,
        "acestep_engine.client",
        MagicMock(AceStepClient=fake_client_cls),
    )


def test_default_generate_runner_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_result = MagicMock(
        wav_bytes=b"WAV",
        seed=99,
        cot_caption="caption",
        cot_lyrics="lyrics",
        delivered_batch_size=None,
    )
    _patch_engine_modules(monkeypatch, MagicMock(return_value=fake_result))

    async def go():
        store = TaskStore()
        task_id = await store.create("generate")
        out_dir = tmp_path / "audio"
        await default_generate_runner(
            store,
            task_id,
            mode="sft",
            config=AceStepConfig(prompt="x", lyrics=""),
            port=8101,
            audio_output_dir=out_dir,
        )
        return await store.get(task_id)

    snap = _run(go())
    assert snap is not None
    assert snap.state == "done"
    assert snap.result is not None
    assert snap.result.seed == 99
    assert (tmp_path / "audio").exists()


def test_default_generate_runner_carries_delivered_batch_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A VRAM-guard batch reduction reported by the client reaches the task result.

    Issue #211: the ACE-Step server can silently shrink a requested batch;
    the fork now reports both numbers, and the worker must not drop the
    delivered one on the way to the task store.
    """
    fake_result = MagicMock(
        wav_bytes=b"WAV",
        seed=1,
        cot_caption="",
        cot_lyrics="",
        delivered_batch_size=1,
    )
    _patch_engine_modules(monkeypatch, MagicMock(return_value=fake_result))

    async def go():
        store = TaskStore()
        task_id = await store.create("generate")
        await default_generate_runner(
            store,
            task_id,
            mode="sft",
            config=AceStepConfig(prompt="x", lyrics=""),
            port=8101,
            audio_output_dir=tmp_path / "audio",
        )
        return await store.get(task_id)

    snap = _run(go())
    assert snap is not None
    assert snap.result is not None
    assert snap.result.delivered_batch_size == 1


def test_default_generate_runner_emits_the_engines_phase_and_fraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_result = MagicMock(
        wav_bytes=b"WAV",
        seed=1,
        cot_caption="",
        cot_lyrics="",
        delivered_batch_size=None,
    )

    def _fake_generate(ace_config, on_progress=None):
        on_progress(AceStepProgress(AceStepPhase.WRITING, 0.5))
        on_progress(AceStepProgress(AceStepPhase.RENDERING, 0.25))
        return fake_result

    _patch_engine_modules(monkeypatch, _fake_generate)

    async def go():
        store = TaskStore()
        task_id = await store.create("generate", phase=AceStepPhase.WRITING)
        events = store.subscribe(task_id)
        await anext(events)
        await default_generate_runner(
            store,
            task_id,
            mode="sft",
            config=AceStepConfig(prompt="x", lyrics=""),
            port=8101,
            audio_output_dir=tmp_path / "audio",
        )
        return [event async for event in events]

    events = _run(go())

    progress_events = [event.data for event in events if event.type == "progress"]
    assert [(data["phase"], data["progress"]) for data in progress_events] == [
        ("writing", 0.0),
        ("writing", 0.5),
        ("rendering", 0.25),
    ]
    assert events[-1].type == "done"


@pytest.fixture
def real_generate_worker(tmp_path: Path):
    """Use the public dependency seam while retaining the production runner."""
    with acestep_http() as boundary:
        async def loader(mode: str) -> LoadedModel:
            return LoadedModel(mode=mode, handle="test-model", port=boundary.port)

        deps, _ = _make_deps(tmp_path, model_loader=loader)
        completed = asyncio.Event()

        async def runner(store, task_id, **kwargs):
            try:
                await default_generate_runner(store, task_id, **kwargs)
            finally:
                # Observe the route's resource-release edge after the runner returns.
                asyncio.get_running_loop().call_soon(completed.set)

        deps.generate_runner = runner

        async def generate(client):
            completed.clear()
            response = await client.post(
                "/generate", json={"mode": "sft", "config": {"prompt": "x", "lyrics": ""}},
            )
            assert response.status_code == 200
            await asyncio.wait_for(completed.wait(), timeout=10)
            assert deps.cache.in_use_count("sft") == 0
            assert not deps.gpu_hold_generation_tasks
            snapshot = await client.get(f"/tasks/{response.json()['task_id']}")
            assert snapshot.status_code == 200
            return snapshot.json()

        @asynccontextmanager
        async def worker():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=create_app(deps)),
                base_url="http://worker", headers=_INTERNAL_HEADERS,
            ) as client:
                loaded = await client.post("/load_model", json={"mode": "sft"})
                assert loaded.status_code == 200
                yield client, deps, boundary, generate

        yield worker


@pytest.mark.parametrize("scenario, expected_kind, diagnostic", [
    ("gpu", "gpu_out_of_memory", "Generation stopped"),
    ("generic", None, "MemoryError: host allocation failed"),
    ("submission", None, "CUDA out of memory"),
    ("success", None, None),
    ("write-error", None, "FileExistsError:"),
])
def test_default_generate_runner_error_kind_over_get_and_stream(
    real_generate_worker, scenario: str, expected_kind: str | None, diagnostic: str | None,
) -> None:
    """S7-04/S7-05/S7-06: Real runner, GET and reconnecting SSE share classification."""
    async def go():
        async with real_generate_worker() as (client, deps, boundary, generate):
            if scenario == "submission":
                boundary.submission_status = "CUDA out of memory"
            elif scenario in {"success", "write-error"}:
                boundary.succeed()
                if scenario == "write-error":
                    deps.audio_output_dir.write_text("occupied")
            else:
                detail = (
                    "CUDA out of memory\nGeneration stopped"
                    if scenario == "gpu" else diagnostic
                )
                boundary.result = json.dumps([{"error": detail}])
            snapshot = await generate(client)
            assert snapshot["state"] == ("done" if scenario == "success" else "error")
            assert snapshot["error_kind"] == expected_kind
            if diagnostic is None:
                assert snapshot["error"] is None
                assert Path(snapshot["result"]["audio_path"]).read_bytes() == boundary.wav_bytes
            else:
                assert diagnostic in snapshot["error"]
                if scenario in {"gpu", "generic"}:
                    assert snapshot["error"] == diagnostic
                elif scenario == "submission":
                    assert snapshot["error"].startswith("ACE-Step returned no task_id:")
            for _ in range(2):
                response = await client.get(f"/tasks/{snapshot['task_id']}/stream")
                assert response.status_code == 200
                events = [line for line in response.text.splitlines() if line.startswith("event:")]
                assert events == [f"event: {snapshot['state']}"]
                data = [
                    line[6:] for line in response.text.splitlines() if line.startswith("data: ")
                ]
                assert [json.loads(item) for item in data] == [snapshot]

    _run(go())


def test_gpu_memory_last_error_survives_audio_success_and_is_replaced(real_generate_worker) -> None:
    """S7-08: Real failures retain heartbeat identity across a real WAV download."""
    from songmaker_cli.acestep_state import read_worker_state

    async def go():
        async with real_generate_worker() as (client, deps, boundary, generate):
            previous = None
            for failure in ("CUDA out of memory", None, "Invalid model"):
                if failure is None:
                    boundary.succeed()
                else:
                    boundary.status = 2
                    boundary.result = json.dumps([{"error": failure}])
                snapshot = await generate(client)
                if failure is None:
                    assert snapshot["state"] == "done"
                    assert snapshot["error_kind"] is None
                    assert Path(snapshot["result"]["audio_path"]).read_bytes() == boundary.wav_bytes
                else:
                    assert snapshot["state"] == "error"
                    assert snapshot["error"] == failure
                    assert snapshot["error_kind"] == (
                        "gpu_out_of_memory" if previous is None else None
                    )
                    current = (
                        snapshot["error"],
                        datetime.fromisoformat(snapshot["updated_at"]).isoformat(),
                    )
                    assert current != previous
                    previous = current
                for _ in range(2):
                    await deps.heartbeat.publish_once()
                    state = await read_worker_state(deps.redis, deps.worker_id)
                    assert (state["last_error"], state["last_error_at"]) == previous

    _run(go())


def test_build_state_payload(tmp_path: Path) -> None:
    """S15-04: Build state payload."""
    from acestep_worker.wrapper import build_state_payload

    deps, redis = _make_deps(tmp_path)

    async def go():
        await redis.set(queue_depth_key(deps.worker_id), 4)
        return await build_state_payload(deps)

    payload = _run(go())
    assert payload["last_error"] is None
    assert payload["last_error_at"] is None
    assert payload["loaded"] == []
    assert payload["queue_depth"] == 4
    assert payload["vram_total_gb"] == 24.0
    assert payload["vram_measured"] is False
    assert payload["target_loading"] is None
    assert payload["available_modes"] == []
    assert payload["pinned"] == []
    assert payload["loading_started_at"] is None
    assert payload["loading_last_log_line"] is None


def test_build_state_payload_projects_the_remaining_training_hold(tmp_path: Path) -> None:
    from acestep_worker.heartbeat import reserve_gpu_hold
    from acestep_worker.wrapper import build_state_payload

    deps, redis = _make_deps(tmp_path)

    async def go():
        assert await reserve_gpu_hold(redis, deps.worker_id, "hold-token", 15)
        return await build_state_payload(deps)

    payload = _run(go())
    assert payload["training_hold_seconds"] is not None
    assert 0 < payload["training_hold_seconds"] <= 15


def test_build_state_payload_after_load_uses_detail_shape(tmp_path: Path) -> None:
    from acestep_worker.wrapper import build_state_payload

    deps, _ = _make_deps(tmp_path)

    async def go():
        await deps.cache.load("sft")
        await deps.cache.pin("sft")
        return await build_state_payload(deps)

    payload = _run(go())
    assert payload["loaded"] == [{"mode": "sft", "size_gb": 6.0}]
    assert payload["pinned"] == ["sft"]
    assert payload["loading_started_at"] is None


def test_lifespan_calls_registry(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)

    register_calls = []

    class FakeRegistry:
        control_plane_url = "http://control-plane.test"

        async def register(self, registration):
            register_calls.append(registration)

    from acestep_worker.registry_client import WorkerRegistration

    deps.registry_client = FakeRegistry()  # type: ignore[assignment]
    deps.registration = WorkerRegistration(
        worker_id="acestep-worker-0",
        host="acestep-worker-0",
        port=8001,
        gpu_id=0,
        vram_total_gb=24.0,
    )
    app = create_app(deps)
    with TestClient(app):
        pass
    assert len(register_calls) == 1


def test_health_returns_503_until_registered_then_200(tmp_path: Path) -> None:
    import asyncio as _asyncio

    from acestep_worker.registry_client import WorkerRegistration
    from acestep_worker.wrapper import lifespan

    async def go():
        deps, _ = _make_deps(tmp_path)
        register_started = _asyncio.Event()
        register_release = _asyncio.Event()

        class SlowRegistry:
            control_plane_url = "http://control-plane.test"

            async def register(self, registration):
                register_started.set()
                await register_release.wait()

        deps.registry_client = SlowRegistry()  # type: ignore[assignment]
        deps.registration = WorkerRegistration(
            worker_id="acestep-worker-0",
            host="acestep-worker-0",
            port=8001,
            gpu_id=0,
            vram_total_gb=24.0,
        )

        app = create_app(deps)
        async with lifespan(app):
            await register_started.wait()
            assert deps.registered is False

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://test",
            ) as client:
                resp = await client.get("/health")
                assert resp.status_code == 503
                assert "awaiting control plane registration" in resp.json()["detail"]

                register_release.set()
                for _ in range(50):
                    if deps.registered:
                        break
                    await _asyncio.sleep(0.01)
                assert deps.registered is True

                resp = await client.get("/health")
                assert resp.status_code == 200
                assert resp.json() == {"status": "ok"}

    _run(go())


def test_lifespan_cancels_pending_registration_on_shutdown(tmp_path: Path) -> None:
    import asyncio as _asyncio

    deps, _ = _make_deps(tmp_path)
    cancelled = _asyncio.Event()

    class HangingRegistry:
        control_plane_url = "http://control-plane.test"

        async def register(self, registration):
            try:
                await _asyncio.sleep(60)
            except _asyncio.CancelledError:
                cancelled.set()
                raise

    from acestep_worker.registry_client import WorkerRegistration

    deps.registry_client = HangingRegistry()  # type: ignore[assignment]
    deps.registration = WorkerRegistration(
        worker_id="acestep-worker-0",
        host="acestep-worker-0",
        port=8001,
        gpu_id=0,
        vram_total_gb=24.0,
    )

    async def go():
        from acestep_worker.wrapper import lifespan

        app = create_app(deps)
        async with lifespan(app):
            await _asyncio.sleep(0.01)
            assert deps.registration_task is not None
            assert not deps.registration_task.done()
        assert cancelled.is_set()
        assert deps.registration_task is not None
        assert deps.registration_task.cancelled() or deps.registration_task.done()

    _run(go())


def test_lifespan_swallows_registration_exception_on_shutdown(tmp_path: Path) -> None:
    import asyncio as _asyncio

    deps, _ = _make_deps(tmp_path)

    class FailingRegistry:
        control_plane_url = "http://control-plane.test"

        async def register(self, registration):
            await _asyncio.sleep(60)
            raise RuntimeError("should not reach this")

    from acestep_worker.registry_client import WorkerRegistration

    deps.registry_client = FailingRegistry()  # type: ignore[assignment]
    deps.registration = WorkerRegistration(
        worker_id="acestep-worker-0",
        host="acestep-worker-0",
        port=8001,
        gpu_id=0,
        vram_total_gb=24.0,
    )

    async def go():
        from acestep_worker.wrapper import lifespan

        app = create_app(deps)
        async with lifespan(app):
            await _asyncio.sleep(0.01)

    _run(go())


# ── D5 wrapper: pin/unpin endpoints ──────────────────────────────


def test_pin_model_success(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with _worker_client(app) as client:
        client.post("/load_model", json={"mode": "sft"})
        resp = client.post("/pin_model", json={"mode": "sft"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "sft"
        assert body["pinned"] == ["sft"]
        assert deps.cache.is_pinned("sft")


def test_pin_model_not_loaded_returns_409(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with _worker_client(app) as client:
        resp = client.post("/pin_model", json={"mode": "sft"})
    assert resp.status_code == 409
    assert "Cannot pin" in resp.json()["detail"]


def test_unpin_model_success(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with _worker_client(app) as client:
        client.post("/load_model", json={"mode": "sft"})
        client.post("/pin_model", json={"mode": "sft"})
        resp = client.post("/unpin_model", json={"mode": "sft"})
        assert resp.status_code == 200
        assert resp.json()["pinned"] == []
        assert deps.cache.is_pinned("sft") is False


def test_unpin_unknown_mode_returns_200(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with _worker_client(app) as client:
        resp = client.post("/unpin_model", json={"mode": "sft"})
    assert resp.status_code == 200


# ── D4 wrapper: /restart endpoint ────────────────────────────────


def test_restart_endpoint_schedules_sigterm(
    tmp_path: Path,
    recorded_process_kills: list[tuple[int, int]],
) -> None:
    import os as _os

    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)

    with _worker_client(app) as client:
        resp = client.post("/restart")
        body = resp.json()
        assert resp.status_code == 200
        assert body["status"] == "restarting"
        assert body["pid"] == _os.getpid()
        for _ in range(20):
            if recorded_process_kills:
                break
            _run(_asyncio_sleep(0.05))

    assert len(recorded_process_kills) == 1
    assert recorded_process_kills[0][0] == _os.getpid()


async def _asyncio_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


# ── D6 wrapper: /generate refcount integration ───────────────────


def test_generate_acquires_and_releases_refcount(tmp_path: Path) -> None:
    from acestep_worker.wrapper import lifespan

    deps, _ = _make_deps(tmp_path)

    release_event = asyncio.Event()
    saw_in_use_one = False

    async def slow_runner(
        store: TaskStore,
        task_id: str,
        *,
        mode: str,
        config: AceStepConfig,
        port: int,
        audio_output_dir: Path,
    ) -> None:
        nonlocal saw_in_use_one
        await store.mark_running(task_id)
        if deps.cache.in_use_count(mode) == 1:
            saw_in_use_one = True
        await release_event.wait()
        await store.complete(
            task_id,
            GenerationTaskResult(mode=mode, audio_path="/x", seed=0),
        )

    deps.generate_runner = slow_runner

    app = create_app(deps)

    async def go():
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://test",
                headers=_INTERNAL_HEADERS,
            ) as client:
                await client.post("/load_model", json={"mode": "sft"})
                resp = await client.post(
                    "/generate",
                    json={"mode": "sft", "config": {"prompt": "x", "lyrics": ""}},
                )
                assert resp.status_code == 200
                for _ in range(50):
                    if deps.cache.in_use_count("sft") > 0:
                        break
                    await asyncio.sleep(0.01)
                assert deps.cache.in_use_count("sft") == 1
                release_event.set()
                for _ in range(50):
                    if deps.cache.in_use_count("sft") == 0:
                        break
                    await asyncio.sleep(0.01)
                assert deps.cache.in_use_count("sft") == 0
        assert saw_in_use_one

    _run(go())


def test_generate_releases_refcount_on_runner_exception(tmp_path: Path) -> None:
    from acestep_worker.wrapper import lifespan

    deps, _ = _make_deps(tmp_path)

    async def failing_runner(
        store: TaskStore,
        task_id: str,
        *,
        mode: str,
        config: AceStepConfig,
        port: int,
        audio_output_dir: Path,
    ) -> None:
        await store.mark_running(task_id)
        raise RuntimeError("kaboom")

    deps.generate_runner = failing_runner

    app = create_app(deps)

    async def go():
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://test",
                headers=_INTERNAL_HEADERS,
            ) as client:
                await client.post("/load_model", json={"mode": "sft"})
                resp = await client.post(
                    "/generate",
                    json={"mode": "sft", "config": {"prompt": "x", "lyrics": ""}},
                )
                assert resp.status_code == 200
                for _ in range(50):
                    if deps.cache.in_use_count("sft") == 0:
                        break
                    await asyncio.sleep(0.01)
                assert deps.cache.in_use_count("sft") == 0

    _run(go())


def test_evict_endpoint_409_when_in_use(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with _worker_client(app) as client:
        client.post("/load_model", json={"mode": "sft"})

        async def hold():
            await deps.cache.acquire_for_use("sft")

        _run(hold())
        resp = client.post("/evict_model", json={"mode": "sft"})
        assert resp.status_code == 409
        assert "in use" in resp.json()["detail"]


_TRAINING_HOLD_TOKEN = "training-hold-token"
_HANG_GUARD_SECONDS = 5


@dataclass
class _ChildStoppingUntilCancelledAgain:
    started: asyncio.Event = field(default_factory=asyncio.Event)
    stopping: asyncio.Event = field(default_factory=asyncio.Event)
    ended: asyncio.Event = field(default_factory=asyncio.Event)

    async def __call__(self, *_args: object, **_kwargs: object) -> None:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.stopping.set()
            await asyncio.Event().wait()
        finally:
            self.ended.set()


@dataclass
class _ChildIgnoringCancelsUntilReleased:
    started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    cancels: asyncio.Queue[None] = field(default_factory=asyncio.Queue)
    ended: asyncio.Event = field(default_factory=asyncio.Event)

    async def __call__(self, *_args: object, **_kwargs: object) -> None:
        self.started.set()
        try:
            while not self.release.is_set():
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    self.cancels.put_nowait(None)
        finally:
            self.ended.set()


async def _training_finished_at_once(*_args: object, **_kwargs: object) -> None:
    return None


async def _renewing_the_training_hold(deps: WorkerDeps) -> None:
    await _renew_gpu_hold_until_done(deps.redis, deps.worker_id, _TRAINING_HOLD_TOKEN)


@dataclass
class _TrainingOwner:
    deps: WorkerDeps
    renew_task: asyncio.Task[None]
    task: asyncio.Task[None]

    async def still_holds_everything(self) -> None:
        assert not self.task.done()
        assert await self.deps.redis.get(gpu_hold_key(self.deps.worker_id)) is not None
        assert self.deps.cache.in_use_count("sft") == 1
        assert _TRAINING_HOLD_TOKEN in self.deps.gpu_hold_handover_tokens
        assert not self.renew_task.done()

    async def ends_cancelled_with_everything_released(self) -> None:
        with pytest.raises(asyncio.CancelledError):
            await self.task
        assert self.task.cancelled()
        assert await self.deps.redis.get(gpu_hold_key(self.deps.worker_id)) is None
        assert self.deps.cache.in_use_count("sft") == 0
        assert _TRAINING_HOLD_TOKEN not in self.deps.gpu_hold_handover_tokens
        assert self.renew_task.done()


async def _start_training_owner(
    tmp_path: Path,
    runner: Callable[..., Awaitable[None]],
    renewal: Callable[[WorkerDeps], Awaitable[None]],
) -> _TrainingOwner:
    deps, redis = _make_deps(tmp_path)
    await deps.cache.load("sft")
    loaded = await deps.cache.acquire_for_use("sft")
    assert await reserve_gpu_hold(redis, deps.worker_id, _TRAINING_HOLD_TOKEN, DEFAULT_TTL_SECONDS)
    task_id = await _create_gpu_hold_handover_task(deps, _TRAINING_HOLD_TOKEN, train_epochs=1)
    assert task_id is not None
    renew_task = asyncio.create_task(renewal(deps))
    request = TrainLoraRequest.model_construct(mode="sft", hold_token=_TRAINING_HOLD_TOKEN)
    resources = _TrainLoraResources(loaded=loaded, renew_task=renew_task, task_id=task_id)
    owner = asyncio.create_task(
        _run_train_lora_with_cleanup(deps, request, request, runner, resources)
    )
    return _TrainingOwner(deps, renew_task, owner)


def test_training_owner_cancelled_again_while_training_stops_releases_everything(
    tmp_path: Path,
) -> None:
    """defect:#1509 -- a second cancel while training stopped skipped the release."""

    async def go() -> None:
        training = _ChildStoppingUntilCancelledAgain()
        owner = await _start_training_owner(tmp_path, training, _renewing_the_training_hold)
        await training.started.wait()
        owner.task.cancel()
        await training.stopping.wait()
        owner.task.cancel()
        await owner.ends_cancelled_with_everything_released()
        assert training.ended.is_set()

    _run(go())


@pytest.mark.parametrize("owner_cancels", [2, 3, 5])
def test_training_owner_cancelled_repeatedly_keeps_everything_until_training_has_ended(
    tmp_path: Path,
    owner_cancels: int,
) -> None:
    """defect:#1509 -- a third cancel released the hold and the cache while training still ran."""

    async def go() -> None:
        training = _ChildIgnoringCancelsUntilReleased()
        owner = await _start_training_owner(tmp_path, training, _renewing_the_training_hold)
        await training.started.wait()
        try:
            for _ in range(owner_cancels):
                owner.task.cancel()
                await training.cancels.get()
            await owner.still_holds_everything()
            assert not training.ended.is_set()
        finally:
            training.release.set()
        await owner.ends_cancelled_with_everything_released()
        assert training.ended.is_set()

    _run(asyncio.wait_for(go(), _HANG_GUARD_SECONDS))


def test_training_owner_cancelled_while_cleanup_waits_for_renewal_releases_everything(
    tmp_path: Path,
) -> None:
    """defect:#1509 -- a cancel while cleanup waited for the renewal skipped the release."""

    async def go() -> None:
        renewal = _ChildStoppingUntilCancelledAgain()
        owner = await _start_training_owner(tmp_path, _training_finished_at_once, renewal)
        await renewal.stopping.wait()
        owner.task.cancel()
        await owner.ends_cancelled_with_everything_released()
        assert renewal.ended.is_set()

    _run(go())

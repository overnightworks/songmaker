from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import fakeredis.aioredis
import httpx
import pytest
from fastapi.testclient import TestClient

from acestep_engine.models import AceStepConfig
from acestep_worker.gpu_util import GpuHealth, GpuHealthStatus
from acestep_worker.heartbeat import HeartbeatLoop, gpu_hold_key, queue_depth_key
from acestep_worker.model_cache import LoadedModel, ModelCache, VramReader, VramStats
from acestep_worker.models import GenerateRequest, GenerationTaskResult, WorkerTaskEvent
from acestep_worker.task_store import TaskStore
from acestep_worker.wrapper import (
    WorkerDeps,
    _format_sse,
    build_router,
    create_app,
    default_generate_runner,
    read_queue_depth,
)

_INTERNAL_HEADERS = {"X-Internal-Token": "test-internal-token"}


def _run(coro):
    return asyncio.run(coro)


def _make_deps(
    tmp_path: Path,
    *,
    vram_reader: VramReader | None = None,
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
        model_sizes={"sft": 6.0, "xl-sft": 12.0},
        loader=loader,
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
        internal_token="test-internal-token",
        generate_runner=fake_generate_runner,
    )
    deps.heartbeat = HeartbeatLoop(
        redis=redis,
        worker_id="acestep-worker-0",
        state_provider=lambda: _state_for_test(deps),
    )
    return deps, redis


async def _state_for_test(deps: WorkerDeps) -> dict[str, Any]:
    return {
        "loaded": deps.cache.loaded_modes(),
        "queue_depth": await read_queue_depth(deps.redis, deps.worker_id),
    }


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
    with TestClient(app) as client:
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
    with TestClient(app) as client:
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
    with TestClient(app) as client:
        resp = client.get("/loaded_models")
    assert "sft" in resp.json()["available_modes"]


def test_load_model_success(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with TestClient(app) as client:
        resp = client.post("/load_model", json={"mode": "sft"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["loaded"] == ["sft"]
    assert body["evicted"] == []


def test_load_model_unknown_mode(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with TestClient(app) as client:
        resp = client.post("/load_model", json={"mode": "ghost"})
    assert resp.status_code == 400


def test_load_model_capacity_error(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    deps.cache._sizes["huge"] = 100.0
    app = create_app(deps)
    with TestClient(app) as client:
        resp = client.post("/load_model", json={"mode": "huge"})
    assert resp.status_code == 409


def test_load_model_subprocess_start_error_returns_502(tmp_path: Path) -> None:
    from acestep_worker.model_cache import ModelCache
    from acestep_worker.subprocess_runner import SubprocessStartError

    async def failing_loader(mode: str) -> LoadedModel:
        raise SubprocessStartError(
            "ACE-Step did not become healthy within 900s\n"
            "--- last log lines ---\n"
            "vllm: loading shard 2/4",
        )

    async def unloader(_: LoadedModel) -> None:
        pass

    deps, _ = _make_deps(tmp_path)
    deps.cache = ModelCache(
        vram_budget_gb=24.0,
        model_sizes={"sft": 6.0},
        loader=failing_loader,
        unloader=unloader,
    )
    app = create_app(deps)
    with TestClient(app) as client:
        resp = client.post("/load_model", json={"mode": "sft"})
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "did not become healthy" in detail
    assert "loading shard 2/4" in detail


def test_evict_model(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with TestClient(app) as client:
        client.post("/load_model", json={"mode": "sft"})
        resp = client.post("/evict_model", json={"mode": "sft"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["evicted"] == ["sft"]
    assert body["loaded"] == []


def test_generate_requires_loaded(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with TestClient(app) as client:
        resp = client.post(
            "/generate",
            json={"mode": "sft", "config": {"prompt": "test", "lyrics": ""}},
            headers=_INTERNAL_HEADERS,
        )
    assert resp.status_code == 409


@pytest.mark.parametrize(
    ("headers", "status_code"),
    [
        pytest.param({}, 422, id="missing-token"),
        pytest.param({"X-Internal-Token": "wrong-token"}, 401, id="wrong-token"),
    ],
)
def test_generate_rejects_requests_without_the_internal_token(
    tmp_path: Path,
    headers: dict[str, str],
    status_code: int,
) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with TestClient(app) as client:
        response = client.post(
            "/generate",
            json={"mode": "sft", "config": {"prompt": "test", "lyrics": ""}},
            headers=headers,
        )
    assert response.status_code == status_code


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
        with pytest.raises(HTTPException, match="GPU is held for LoRA training"):
            await generate(
                GenerateRequest(mode="sft", config=AceStepConfig(prompt="test", lyrics=""))
            )
        await deps.redis.delete(gpu_hold_key(deps.worker_id))

    _run(scenario())


def test_generate_rejects_a_worker_held_for_lora_training(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with TestClient(app) as client:
        assert client.post("/load_model", json={"mode": "sft"}).status_code == 200
        reserve = client.post(
            "/gpu_hold/reserve",
            headers={"X-Internal-Token": "test-internal-token"},
        )
        assert reserve.status_code == 200
        resp = client.post(
            "/generate",
            json={"mode": "sft", "config": {"prompt": "test", "lyrics": ""}},
            headers=_INTERNAL_HEADERS,
        )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "GPU is held for LoRA training"


def test_generate_returns_task_id(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with TestClient(app) as client:
        client.post("/load_model", json={"mode": "sft"})
        resp = client.post(
            "/generate",
            json={"mode": "sft", "config": {"prompt": "test", "lyrics": ""}},
            headers=_INTERNAL_HEADERS,
        )
    assert resp.status_code == 200
    assert resp.json()["task_id"].startswith("gen-")


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
    with TestClient(app) as client:
        client.post("/load_model", json={"mode": "sft"})
        resp = client.post(
            "/generate", json={"mode": "sft", "config": payload}, headers=_INTERNAL_HEADERS
        )

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
    with TestClient(app) as client:
        client.post("/load_model", json={"mode": "sft"})
        resp = client.post(
            "/generate", json={"mode": "sft", "config": payload}, headers=_INTERNAL_HEADERS
        )
    assert resp.status_code == 422


def test_generate_rejects_a_missing_required_config_field(tmp_path: Path) -> None:
    """lyrics has no default on AceStepConfig — omitting it must 422, not
    construct a half-built config."""
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    payload = _full_ace_step_config_payload()
    del payload["lyrics"]
    with TestClient(app) as client:
        client.post("/load_model", json={"mode": "sft"})
        resp = client.post(
            "/generate", json={"mode": "sft", "config": payload}, headers=_INTERNAL_HEADERS
        )
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
        with TestClient(app) as client:
            resp = client.post("/download_model", json={"mode": "sft"})
    finally:
        wrapper_module.start_download = original_start  # type: ignore[assignment]
    assert resp.status_code == 200
    assert resp.json()["task_id"].startswith("dow-")


def test_get_task_unknown(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with TestClient(app) as client:
        resp = client.get("/tasks/ghost")
    assert resp.status_code == 404


def test_get_task_known(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with TestClient(app) as client:
        client.post("/load_model", json={"mode": "sft"})
        gen = client.post(
            "/generate",
            json={"mode": "sft", "config": {"prompt": "x", "lyrics": ""}},
            headers=_INTERNAL_HEADERS,
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
    with TestClient(app) as client:
        resp = client.get("/tasks/ghost/stream")
    assert resp.status_code == 404


def test_stream_task_yields_done(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with TestClient(app) as client:
        client.post("/load_model", json={"mode": "sft"})
        gen = client.post(
            "/generate",
            json={"mode": "sft", "config": {"prompt": "x", "lyrics": ""}},
            headers=_INTERNAL_HEADERS,
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


def test_default_generate_runner_emits_progress(
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

    captured_progress: list[float] = []

    def _fake_generate(ace_config, on_progress=None):
        if on_progress is not None:
            on_progress("8/50 [00:02<00:13]")
            on_progress("LM chunk 1/1")
            on_progress("25/50 [00:05<00:08]")
        return fake_result

    _patch_engine_modules(monkeypatch, _fake_generate)

    async def go():
        store = TaskStore()
        task_id = await store.create("generate")
        original_update = store.update_progress

        async def _capture(tid, fraction):
            captured_progress.append(fraction)
            await original_update(tid, fraction)

        store.update_progress = _capture  # type: ignore[method-assign]

        await default_generate_runner(
            store,
            task_id,
            mode="sft",
            config=AceStepConfig(prompt="x", lyrics=""),
            port=8101,
            audio_output_dir=tmp_path / "audio",
        )
        await asyncio.sleep(0.05)
        return await store.get(task_id)

    snap = _run(go())
    assert snap is not None
    assert snap.state == "done"
    assert captured_progress == [8 / 50, 25 / 50]


def test_default_generate_runner_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_engine_modules(monkeypatch, MagicMock(side_effect=RuntimeError("kaboom")))

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
    assert snap.state == "error"
    assert snap.error == "RuntimeError: kaboom"


def test_default_generate_runner_reports_acestep_cause_verbatim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from acestep_engine.errors import GenerationFailedError

    cause = "Music generation failed: Insufficient free VRAM: need ~2.0 GB, only 1.3 GB available"
    _patch_engine_modules(monkeypatch, MagicMock(side_effect=GenerationFailedError(cause)))

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
    assert snap.state == "error"
    assert snap.error == cause


def test_build_state_payload(tmp_path: Path) -> None:
    from acestep_worker.wrapper import build_state_payload

    deps, redis = _make_deps(tmp_path)

    async def go():
        await redis.set(queue_depth_key(deps.worker_id), 4)
        return await build_state_payload(deps)

    payload = _run(go())
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
    with TestClient(app) as client:
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
    with TestClient(app) as client:
        resp = client.post("/pin_model", json={"mode": "sft"})
    assert resp.status_code == 409
    assert "Cannot pin" in resp.json()["detail"]


def test_unpin_model_success(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with TestClient(app) as client:
        client.post("/load_model", json={"mode": "sft"})
        client.post("/pin_model", json={"mode": "sft"})
        resp = client.post("/unpin_model", json={"mode": "sft"})
        assert resp.status_code == 200
        assert resp.json()["pinned"] == []
        assert deps.cache.is_pinned("sft") is False


def test_unpin_unknown_mode_returns_200(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with TestClient(app) as client:
        resp = client.post("/unpin_model", json={"mode": "sft"})
    assert resp.status_code == 200


# ── D4 wrapper: /restart endpoint ────────────────────────────────


def test_restart_endpoint_schedules_sigterm(tmp_path: Path) -> None:
    import os as _os

    from acestep_worker import wrapper as wrapper_module

    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)

    kill_calls: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))

    original_kill = _os.kill
    wrapper_module.os.kill = fake_kill  # type: ignore[assignment]
    try:
        with TestClient(app) as client:
            resp = client.post("/restart")
            body = resp.json()
            assert resp.status_code == 200
            assert body["status"] == "restarting"
            assert body["pid"] == _os.getpid()
            for _ in range(20):
                if kill_calls:
                    break
                _run(_asyncio_sleep(0.05))
    finally:
        wrapper_module.os.kill = original_kill  # type: ignore[assignment]

    assert len(kill_calls) == 1
    assert kill_calls[0][0] == _os.getpid()


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
            ) as client:
                await client.post("/load_model", json={"mode": "sft"})
                resp = await client.post(
                    "/generate",
                    json={"mode": "sft", "config": {"prompt": "x", "lyrics": ""}},
                    headers=_INTERNAL_HEADERS,
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
            ) as client:
                await client.post("/load_model", json={"mode": "sft"})
                resp = await client.post(
                    "/generate",
                    json={"mode": "sft", "config": {"prompt": "x", "lyrics": ""}},
                    headers=_INTERNAL_HEADERS,
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
    with TestClient(app) as client:
        client.post("/load_model", json={"mode": "sft"})

        async def hold():
            await deps.cache.acquire_for_use("sft")

        _run(hold())
        resp = client.post("/evict_model", json={"mode": "sft"})
        assert resp.status_code == 409
        assert "in use" in resp.json()["detail"]

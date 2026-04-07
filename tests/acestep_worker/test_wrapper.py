from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import fakeredis.aioredis
import pytest
from fastapi.testclient import TestClient

from acestep_worker.heartbeat import HeartbeatLoop, queue_depth_key
from acestep_worker.model_cache import LoadedModel, ModelCache
from acestep_worker.models import WorkerTaskEvent
from acestep_worker.task_store import TaskStore
from acestep_worker.wrapper import (
    WorkerDeps,
    _format_sse,
    create_app,
    default_generate_runner,
    read_queue_depth,
)


def _run(coro):
    return asyncio.run(coro)


def _make_deps(tmp_path: Path) -> tuple[WorkerDeps, fakeredis.aioredis.FakeRedis]:
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
    )
    task_store = TaskStore()

    async def fake_generate_runner(
        store: TaskStore,
        task_id: str,
        *,
        mode: str,
        config: dict[str, Any],
        port: int,
        audio_output_dir: Path,
    ) -> None:
        await store.mark_running(task_id)
        await store.complete(
            task_id,
            {"mode": mode, "audio_path": f"/fake/{task_id}.wav", "seed": 42},
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
        "loaded_models": deps.cache.loaded_modes(),
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
    assert body["available_modes"] == []


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
        )
    assert resp.status_code == 409


def test_generate_returns_task_id(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)
    app = create_app(deps)
    with TestClient(app) as client:
        client.post("/load_model", json={"mode": "sft"})
        resp = client.post(
            "/generate",
            json={"mode": "sft", "config": {"prompt": "test", "lyrics": ""}},
        )
    assert resp.status_code == 200
    assert resp.json()["task_id"].startswith("gen-")


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
        )
        task_id = gen.json()["task_id"]
        for _ in range(20):
            resp = client.get(f"/tasks/{task_id}")
            if resp.json()["state"] == "done":
                break
    assert resp.json()["state"] == "done"


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


def test_default_generate_runner_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_result = MagicMock(wav_bytes=b"WAV", seed=99, cot_caption="caption", cot_lyrics="lyrics")

    fake_client_cls = MagicMock()
    fake_client_cls.return_value.generate = MagicMock(return_value=fake_result)

    fake_engine_client = MagicMock(AceStepClient=fake_client_cls)
    fake_engine_models = MagicMock(AceStepConfig=MagicMock(side_effect=lambda **kw: kw))

    import sys

    monkeypatch.setitem(sys.modules, "acestep_engine.client", fake_engine_client)
    monkeypatch.setitem(sys.modules, "acestep_engine.models", fake_engine_models)

    async def go():
        store = TaskStore()
        task_id = await store.create("generate")
        out_dir = tmp_path / "audio"
        await default_generate_runner(
            store,
            task_id,
            mode="sft",
            config={"prompt": "x", "lyrics": ""},
            port=8101,
            audio_output_dir=out_dir,
        )
        return await store.get(task_id)

    snap = _run(go())
    assert snap is not None
    assert snap.state == "done"
    assert snap.result is not None
    assert snap.result["seed"] == 99
    assert (tmp_path / "audio").exists()


def test_default_generate_runner_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client_cls = MagicMock()
    fake_client_cls.return_value.generate = MagicMock(side_effect=RuntimeError("kaboom"))
    fake_engine_client = MagicMock(AceStepClient=fake_client_cls)
    fake_engine_models = MagicMock(AceStepConfig=MagicMock(side_effect=lambda **kw: kw))

    import sys

    monkeypatch.setitem(sys.modules, "acestep_engine.client", fake_engine_client)
    monkeypatch.setitem(sys.modules, "acestep_engine.models", fake_engine_models)

    async def go():
        store = TaskStore()
        task_id = await store.create("generate")
        await default_generate_runner(
            store,
            task_id,
            mode="sft",
            config={"prompt": "x", "lyrics": ""},
            port=8101,
            audio_output_dir=tmp_path / "audio",
        )
        return await store.get(task_id)

    snap = _run(go())
    assert snap is not None
    assert snap.state == "error"
    assert "kaboom" in (snap.error or "")


def test_build_state_payload(tmp_path: Path) -> None:
    from acestep_worker.wrapper import build_state_payload

    deps, redis = _make_deps(tmp_path)

    async def go():
        await redis.set(queue_depth_key(deps.worker_id), 4)
        return await build_state_payload(deps)

    payload = _run(go())
    assert payload["loaded_models"] == []
    assert payload["queue_depth"] == 4
    assert payload["vram_total_gb"] == 24.0
    assert payload["target_loading"] is None
    assert payload["available_modes"] == []


def test_lifespan_calls_registry(tmp_path: Path) -> None:
    deps, _ = _make_deps(tmp_path)

    register_calls = []

    class FakeRegistry:
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

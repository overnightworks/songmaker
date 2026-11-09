"""Fixtures shared by the ACE-Step worker wrapper tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fakeredis.aioredis
import httpx
import pytest
from support.acestep_http import acestep_http
from support.wrapper_deps import INTERNAL_HEADERS, make_deps

from acestep_worker.heartbeat import HeartbeatLoop
from acestep_worker.model_cache import LoadedModel, ModelCache
from acestep_worker.models import TrainLoraRequest, TrainLoraTaskResult
from acestep_worker.task_store import TaskStore
from acestep_worker.wrapper import WorkerDeps, create_app, default_generate_runner


@pytest.fixture
def real_generate_worker(tmp_path: Path):
    """Use the public dependency seam while retaining the production runner."""
    with acestep_http() as boundary:

        async def loader(mode: str) -> LoadedModel:
            return LoadedModel(mode=mode, handle="test-model", port=boundary.port)

        deps, _ = make_deps(tmp_path, model_loader=loader)
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
                "/generate",
                json={"mode": "sft", "config": {"prompt": "x", "lyrics": ""}},
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
                base_url="http://worker",
                headers=INTERNAL_HEADERS,
            ) as client:
                loaded = await client.post("/load_model", json={"mode": "sft"})
                assert loaded.status_code == 200
                yield client, deps, boundary, generate

        yield worker


def _fake_train_runner(operation_events: list[str], train_events: list[str]):
    async def fake_train_runner(
        store: TaskStore,
        task_id: str,
        *,
        request: TrainLoraRequest,
        port: int,
        checkpoint_dir: Path,
        training_workspace_dirname: str,
    ) -> None:
        operation_events.append(f"train_lora:{request.mode}")
        train_events.append(f"start:{port}")
        await store.mark_running(task_id)
        await store.mark_training_started(task_id)
        await store.update_progress(task_id, 0.1, current_epoch=0)
        await store.update_progress(
            task_id,
            0.5,
            current_epoch=request.train_epochs // 2,
        )
        await store.complete(
            task_id,
            TrainLoraTaskResult(
                mode=request.mode,
                adapter_dir=str(Path(request.output_dir) / "final"),
                num_samples=3,
            ),
        )

    return fake_train_runner


def _build_train_lora_deps(tmp_path: Path, with_train_runner: bool = True) -> WorkerDeps:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    operation_events: list[str] = []

    async def loader(mode: str) -> LoadedModel:
        operation_events.append(f"load_model:{mode}")
        return LoadedModel(mode=mode, handle=f"handle-{mode}", port=8101)

    async def unloader(_: LoadedModel) -> None:
        return None

    cache = ModelCache(
        vram_budget_gb=24.0,
        model_sizes={"sft": 6.0},
        loader=loader,
        unloader=unloader,
    )
    task_store = TaskStore()

    async def fake_generate_runner(*args, **kwargs):
        await task_store.mark_running(kwargs.get("task_id") or args[1])

    train_events: list[str] = []
    fake_train_runner = _fake_train_runner(operation_events, train_events)

    deps = WorkerDeps(
        worker_id="w0",
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
        shared_audio_root=tmp_path / "shared",
        train_lora_runner=fake_train_runner if with_train_runner else None,
    )
    deps.shared_audio_root.mkdir()
    deps.heartbeat = HeartbeatLoop(
        redis=redis,
        worker_id="w0",
        state_provider=lambda: _heartbeat_state(deps),
    )
    deps._train_events = train_events  # type: ignore[attr-defined]
    deps._operation_events = operation_events  # type: ignore[attr-defined]
    return deps


async def _heartbeat_state(deps: WorkerDeps) -> dict[str, Any]:
    return {"loaded": deps.cache.loaded_modes(), "queue_depth": 0}


@pytest.fixture
def train_lora_deps() -> Callable[..., WorkerDeps]:
    return _build_train_lora_deps


def _train_body(**overrides: object) -> dict[str, object]:
    payload = {
        "lokr_linear_dim": 64,
        "lokr_linear_alpha": 128,
        "lokr_factor": -1,
        "lokr_decompose_both": False,
        "lokr_use_tucker": False,
        "lokr_use_scalar": False,
        "lokr_weight_decompose": True,
        "learning_rate": 0.03,
        "train_epochs": 500,
        "train_batch_size": 1,
        "gradient_accumulation": 4,
        "save_every_n_epochs": 5,
        "training_shift": 3.0,
        "training_seed": 42,
        "gradient_checkpointing": False,
        "poll_interval_seconds": 5.0,
    }
    return {**payload, **overrides}


@pytest.fixture
def train_body() -> Callable[..., dict[str, object]]:
    return _train_body


@dataclass
class TrainLoraWorker:
    """A worker with `sft` loaded behind its real routes; `spawned` holds its background runs."""

    client: httpx.AsyncClient
    deps: WorkerDeps
    spawned: list[Any]
    body: Callable[..., dict[str, object]]

    async def reserve_hold(self) -> str:
        response = await self.client.post("/gpu_hold/reserve")
        assert response.status_code == 200
        return response.json()["token"]

    async def train(self, hold_token: str, **overrides: object) -> httpx.Response:
        body = self.body(
            mode="sft",
            dataset_dir=str(self.deps.shared_audio_root / "dataset"),
            output_dir=str(self.deps.shared_audio_root / "out"),
            hold_token=hold_token,
        )
        return await self.client.post("/tasks/train_lora", json={**body, **overrides})


@pytest.fixture
def train_lora_worker(
    tmp_path: Path,
    train_lora_deps: Callable[..., WorkerDeps],
    train_body: Callable[..., dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[], Any]:
    @asynccontextmanager
    async def worker() -> AsyncIterator[TrainLoraWorker]:
        deps = train_lora_deps(tmp_path)
        (deps.shared_audio_root / "dataset").mkdir()
        spawned: list[Any] = []
        monkeypatch.setattr("acestep_worker.wrapper.spawn_background", spawned.append)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(deps)),
            base_url="http://worker",
            headers=INTERNAL_HEADERS,
        ) as client:
            loaded = await client.post("/load_model", json={"mode": "sft"})
            assert loaded.status_code == 200
            yield TrainLoraWorker(client, deps, spawned, train_body)

    return worker

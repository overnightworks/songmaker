"""Tests for the acestep_worker /tasks/train_lora endpoint + SSE progress.

The default_train_lora_runner is tested indirectly here; we install a
fake runner that emits a deterministic progress/done sequence so we can
assert event ordering."""

from __future__ import annotations

import asyncio
import shutil
import threading
from pathlib import Path
from typing import Any

import fakeredis.aioredis
import pytest
from fastapi.testclient import TestClient

from acestep_worker.heartbeat import HeartbeatLoop, gpu_hold_key, reserve_gpu_hold
from acestep_worker.model_cache import LoadedModel, ModelCache
from acestep_worker.models import GpuHoldTokenRequest, TrainLoraRequest, TrainLoraTaskResult
from acestep_worker.task_store import TaskStore
from acestep_worker.wrapper import (
    WorkerDeps,
    build_router,
    create_app,
    default_train_lora_runner,
)


def _run(coro):
    return asyncio.run(coro)


def _make_deps(tmp_path: Path, with_train_runner: bool = True) -> WorkerDeps:
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
        await store.update_progress(task_id, 0.1)
        await store.update_progress(task_id, 0.5)
        await store.complete(
            task_id,
            TrainLoraTaskResult(
                mode=request.mode,
                adapter_dir=str(Path(request.output_dir) / "final"),
                num_samples=3,
            ),
        )

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
        state_provider=lambda: _state(deps),
    )
    deps._train_events = train_events  # type: ignore[attr-defined]
    deps._operation_events = operation_events  # type: ignore[attr-defined]
    return deps


async def _state(deps: WorkerDeps) -> dict[str, Any]:
    return {"loaded": deps.cache.loaded_modes(), "queue_depth": 0}


def _auth_headers() -> dict[str, str]:
    from songmaker_cli.internal_api import INTERNAL_TOKEN_HEADER

    return {INTERNAL_TOKEN_HEADER: "test-internal-token"}


def _training_request_payload(**overrides: object) -> dict[str, object]:
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


def test_train_lora_rejects_missing_training_configuration(tmp_path: Path) -> None:
    deps = _make_deps(tmp_path)
    dataset_dir = deps.shared_audio_root / "dataset"
    dataset_dir.mkdir()
    app = create_app(deps)
    with TestClient(app) as client:
        response = client.post(
            "/tasks/train_lora",
            json={
                "mode": "sft",
                "dataset_dir": str(dataset_dir),
                "output_dir": str(deps.shared_audio_root / "output"),
                "hold_token": "test-token",
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 422


def test_train_lora_requires_loaded_mode(tmp_path: Path) -> None:
    deps = _make_deps(tmp_path)
    dataset_dir = deps.shared_audio_root / "dataset"
    dataset_dir.mkdir()
    app = create_app(deps)
    with TestClient(app) as client:
        resp = client.post(
            "/tasks/train_lora",
            json=_training_request_payload(
                mode="sft",
                dataset_dir=str(dataset_dir),
                output_dir=str(deps.shared_audio_root / "output"),
                hold_token="test-token",
            ),
            headers=_auth_headers(),
        )
    assert resp.status_code == 409


def test_gpu_hold_endpoints_require_the_internal_token(tmp_path: Path) -> None:
    deps = _make_deps(tmp_path)
    app = create_app(deps)
    with TestClient(app) as client:
        headers = {"X-Internal-Token": "wrong"}
        assert client.post("/gpu_hold/reserve", headers=headers).status_code == 401
        assert (
            client.post("/gpu_hold/renew", json={"token": "token"}, headers=headers).status_code
            == 401
        )
        assert (
            client.post("/gpu_hold/release", json={"token": "token"}, headers=headers).status_code
            == 401
        )
        payload = _training_request_payload(
            mode="sft",
            dataset_dir=str(deps.shared_audio_root),
            output_dir=str(deps.shared_audio_root / "output"),
            hold_token="token",
        )
        assert client.post("/tasks/train_lora", json=payload, headers=headers).status_code == 401
        assert client.post("/gpu_hold/reserve").status_code == 422
        assert client.post("/gpu_hold/renew", json={"token": "token"}).status_code == 422
        assert client.post("/gpu_hold/release", json={"token": "token"}).status_code == 422
        assert client.post("/tasks/train_lora", json=payload).status_code == 422
        empty_headers = {"X-Internal-Token": ""}
        assert client.post("/gpu_hold/reserve", headers=empty_headers).status_code == 401
        assert (
            client.post(
                "/gpu_hold/renew",
                json={"token": "token"},
                headers=empty_headers,
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/gpu_hold/release",
                json={"token": "token"},
                headers=empty_headers,
            ).status_code
            == 401
        )
        assert (
            client.post("/tasks/train_lora", json=payload, headers=empty_headers).status_code
            == 401
        )


def test_gpu_hold_endpoints_accept_only_the_current_token(tmp_path: Path) -> None:
    deps = _make_deps(tmp_path)
    app = create_app(deps)
    with TestClient(app) as client:
        first = client.post("/gpu_hold/reserve", headers=_auth_headers())
        assert first.status_code == 200
        first_token = first.json()["token"]
        assert (
            client.post(
                "/gpu_hold/renew",
                json={"token": "wrong-token"},
                headers=_auth_headers(),
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/gpu_hold/renew",
                json={"token": first_token},
                headers=_auth_headers(),
            ).status_code
            == 204
        )
        assert (
            client.post(
                "/gpu_hold/release",
                json={"token": first_token},
                headers=_auth_headers(),
            ).status_code
            == 204
        )
        second = client.post("/gpu_hold/reserve", headers=_auth_headers())
        assert second.status_code == 200
        second_token = second.json()["token"]
        assert second_token != first_token
        assert (
            client.post(
                "/gpu_hold/renew",
                json={"token": first_token},
                headers=_auth_headers(),
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/gpu_hold/release",
                json={"token": first_token},
                headers=_auth_headers(),
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/gpu_hold/release",
                json={"token": second_token},
                headers=_auth_headers(),
            ).status_code
            == 204
        )


def test_worker_settings_require_a_nonempty_internal_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic import ValidationError

    from acestep_worker.settings import WorkerSettings

    monkeypatch.delenv("SONGMAKER_INTERNAL_TOKEN", raising=False)
    with pytest.raises(ValidationError):
        WorkerSettings(worker_id="w0", redis_url="redis://localhost")
    with pytest.raises(ValidationError):
        WorkerSettings(
            worker_id="w0",
            redis_url="redis://localhost",
            songmaker_internal_token="",
        )
    settings = WorkerSettings(
        worker_id="w0",
        redis_url="redis://localhost",
        songmaker_internal_token="token",
    )
    assert settings.songmaker_internal_token.get_secret_value() == "token"


def test_train_lora_501_when_runner_missing(tmp_path: Path) -> None:
    deps = _make_deps(tmp_path, with_train_runner=False)
    dataset_dir = deps.shared_audio_root / "dataset"
    dataset_dir.mkdir()
    _run(deps.cache.load("sft"))
    app = create_app(deps)
    with TestClient(app) as client:
        resp = client.post(
            "/tasks/train_lora",
            json=_training_request_payload(
                mode="sft",
                dataset_dir=str(dataset_dir),
                output_dir=str(deps.shared_audio_root / "output"),
                hold_token="test-token",
            ),
            headers=_auth_headers(),
        )
    assert resp.status_code == 501


def test_train_lora_happy_path_emits_sse_events(tmp_path: Path) -> None:
    deps = _make_deps(tmp_path)
    dataset_dir = deps.shared_audio_root / "dataset"
    dataset_dir.mkdir()
    app = create_app(deps)
    with TestClient(app) as client:
        loaded = client.post(
            "/load_model",
            json={"mode": "sft"},
            headers=_auth_headers(),
        )
        assert loaded.status_code == 200
        hold = client.post("/gpu_hold/reserve", headers=_auth_headers())
        assert hold.status_code == 200
        resp = client.post(
            "/tasks/train_lora",
            json=_training_request_payload(
                mode="sft",
                dataset_dir=str(dataset_dir),
                output_dir=str(deps.shared_audio_root / "out"),
                hold_token=hold.json()["token"],
            ),
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]
        with client.stream(
            "GET",
            f"/tasks/{task_id}/stream",
            headers=_auth_headers(),
        ) as stream:
            events = []
            for chunk in stream.iter_text():
                events.append(chunk)
                if '"done"' in "".join(events) or "event: done" in "".join(events):
                    break
    joined = "".join(events)
    assert "event: done" in joined
    assert "adapter_dir" in joined
    assert deps._operation_events == [  # type: ignore[attr-defined]
        "load_model:sft",
        "train_lora:sft",
    ]


def test_train_lora_renews_before_creating_its_task_and_releases_after_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps = _make_deps(tmp_path)
    dataset_dir = deps.shared_audio_root / "dataset"
    dataset_dir.mkdir()
    spawned: list[object] = []
    renewal_task_created = asyncio.Event()

    async def renew_before_task(*args, **kwargs) -> bool:
        assert await deps.task_store.size() == 0
        renewal_task_created.set()
        return True

    async def scenario() -> None:
        await deps.cache.load("sft")
        assert await reserve_gpu_hold(deps.redis, deps.worker_id, "hold-token", 15)
        endpoint = next(
            route.endpoint
            for route in build_router(deps).routes
            if route.path == "/tasks/train_lora"
        )
        response = await endpoint(
            TrainLoraRequest(
                mode="sft",
                dataset_dir=str(dataset_dir),
                output_dir=str(deps.shared_audio_root / "output"),
                hold_token="hold-token",
                **_training_request_payload(),
            )
        )
        assert renewal_task_created.is_set()
        assert response.task_id
        assert await deps.task_store.size() == 1
        assert len(spawned) == 1
        await spawned[0]
        assert await deps.redis.get(gpu_hold_key(deps.worker_id)) is None
        assert not deps.gpu_hold_handover_tokens

    monkeypatch.setattr("acestep_worker.wrapper.renew_gpu_hold", renew_before_task)
    monkeypatch.setattr("acestep_worker.wrapper.spawn_background", spawned.append)
    _run(scenario())


def test_release_rejects_a_hold_claimed_by_a_training_task(tmp_path: Path) -> None:
    from fastapi import HTTPException

    deps = _make_deps(tmp_path)

    async def scenario() -> None:
        assert await reserve_gpu_hold(deps.redis, deps.worker_id, "hold-token", 15)
        async with deps.gpu_hold_handover_lock:
            deps.gpu_hold_handover_tokens.add("hold-token")
        endpoint = next(
            route.endpoint
            for route in build_router(deps).routes
            if route.path == "/gpu_hold/release"
        )
        with pytest.raises(HTTPException, match="owned by a training task") as exc_info:
            await endpoint(GpuHoldTokenRequest(token="hold-token"))
        assert exc_info.value.status_code == 409
        assert await deps.redis.get(gpu_hold_key(deps.worker_id)) == b"hold-token"

    _run(scenario())


def test_handover_claim_cannot_race_a_coordinator_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    from acestep_worker.heartbeat import release_gpu_hold
    from acestep_worker.wrapper import _create_gpu_hold_handover_task, _release_gpu_hold_handover

    deps = _make_deps(tmp_path)
    claim_entered = asyncio.Event()
    allow_claim = asyncio.Event()

    async def delayed_match(*_args, **_kwargs) -> bool:
        claim_entered.set()
        await allow_claim.wait()
        return True

    async def scenario() -> None:
        assert await reserve_gpu_hold(deps.redis, deps.worker_id, "hold-token", 15)
        release = next(
            route.endpoint
            for route in build_router(deps).routes
            if route.path == "/gpu_hold/release"
        )
        claim_task = asyncio.create_task(_create_gpu_hold_handover_task(deps, "hold-token"))
        await claim_entered.wait()
        release_task = asyncio.create_task(release(GpuHoldTokenRequest(token="hold-token")))
        await asyncio.sleep(0)
        assert not release_task.done()
        allow_claim.set()
        assert await claim_task is not None
        with pytest.raises(HTTPException, match="owned by a training task") as exc_info:
            await release_task
        assert exc_info.value.status_code == 409
        assert await deps.redis.get(gpu_hold_key(deps.worker_id)) == b"hold-token"
        await _release_gpu_hold_handover(deps, "hold-token")
        assert await release_gpu_hold(deps.redis, deps.worker_id, "hold-token")

    monkeypatch.setattr("acestep_worker.wrapper.gpu_hold_matches", delayed_match)
    _run(scenario())


def test_handover_does_not_report_a_claim_without_a_task(tmp_path: Path) -> None:
    deps = _make_deps(tmp_path)

    async def scenario() -> None:
        async with deps.gpu_hold_handover_lock:
            deps.gpu_hold_handover_tokens.add("hold-token")
        endpoint = next(
            route.endpoint
            for route in build_router(deps).routes
            if route.path == "/gpu_hold/handover"
        )
        response = await endpoint(GpuHoldTokenRequest(token="hold-token"))
        assert response.claimed is False
        assert response.task_id is None

    _run(scenario())


def test_train_lora_allows_only_one_concurrent_handover_for_a_hold_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    deps = _make_deps(tmp_path)
    dataset_dir = deps.shared_audio_root / "dataset"
    dataset_dir.mkdir()
    spawned: list[object] = []

    async def scenario() -> None:
        await deps.cache.load("sft")
        assert await reserve_gpu_hold(deps.redis, deps.worker_id, "hold-token", 15)
        endpoint = next(
            route.endpoint
            for route in build_router(deps).routes
            if route.path == "/tasks/train_lora"
        )
        request = TrainLoraRequest(
            mode="sft",
            dataset_dir=str(dataset_dir),
            output_dir=str(deps.shared_audio_root / "output"),
            hold_token="hold-token",
            **_training_request_payload(),
        )
        responses = await asyncio.gather(
            endpoint(request),
            endpoint(request),
            return_exceptions=True,
        )
        accepted = [response for response in responses if not isinstance(response, Exception)]
        rejected = [response for response in responses if isinstance(response, HTTPException)]
        assert len(accepted) == 1
        assert len(rejected) == 1
        assert rejected[0].status_code == 409
        assert await deps.task_store.size() == 1
        assert len(spawned) == 1
        await spawned[0]
        assert getattr(deps, "_train_events") == ["start:8101"]
        assert not deps.gpu_hold_handover_tokens

    monkeypatch.setattr("acestep_worker.wrapper.spawn_background", spawned.append)
    _run(scenario())


def test_train_lora_releases_handover_claim_after_setup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    deps = _make_deps(tmp_path)
    dataset_dir = deps.shared_audio_root / "dataset"
    dataset_dir.mkdir()
    spawned: list[object] = []

    async def scenario() -> None:
        await deps.cache.load("sft")
        assert await reserve_gpu_hold(deps.redis, deps.worker_id, "hold-token", 15)
        endpoint = next(
            route.endpoint
            for route in build_router(deps).routes
            if route.path == "/tasks/train_lora"
        )
        request = TrainLoraRequest(
            mode="sft",
            dataset_dir=str(dataset_dir),
            output_dir=str(deps.shared_audio_root / "output"),
            hold_token="hold-token",
            **_training_request_payload(),
        )
        original_create = deps.task_store.create

        async def failed_create(_: str) -> str:
            raise RuntimeError("task store unavailable")

        monkeypatch.setattr(deps.task_store, "create", failed_create)
        with pytest.raises(RuntimeError, match="task store unavailable"):
            await endpoint(request)
        assert not deps.gpu_hold_handover_tokens
        monkeypatch.setattr(deps.task_store, "create", original_create)
        response = await endpoint(request)
        assert response.task_id
        await spawned[0]
        assert not deps.gpu_hold_handover_tokens

        assert await reserve_gpu_hold(deps.redis, deps.worker_id, "renew-token", 15)
        renewal_attempts = 0

        async def fail_then_renew(*args, **kwargs) -> bool:
            nonlocal renewal_attempts
            renewal_attempts += 1
            return renewal_attempts > 1

        monkeypatch.setattr("acestep_worker.wrapper.renew_gpu_hold", fail_then_renew)
        failed_renewal_request = request.model_copy(update={"hold_token": "renew-token"})
        with pytest.raises(HTTPException) as exc_info:
            await endpoint(failed_renewal_request)
        assert exc_info.value.status_code == 409
        assert not deps.gpu_hold_handover_tokens
        response = await endpoint(failed_renewal_request)
        assert response.task_id
        await spawned[1]
        assert not deps.gpu_hold_handover_tokens

    monkeypatch.setattr("acestep_worker.wrapper.spawn_background", spawned.append)
    _run(scenario())


def test_train_lora_releases_handover_claim_after_connection_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps = _make_deps(tmp_path)
    dataset_dir = deps.shared_audio_root / "dataset"
    dataset_dir.mkdir()
    spawned: list[object] = []

    async def unavailable_renewal(*args, **kwargs) -> bool:
        raise ConnectionError("Redis unavailable")

    async def scenario() -> None:
        await deps.cache.load("sft")
        assert await reserve_gpu_hold(deps.redis, deps.worker_id, "hold-token", 15)
        endpoint = next(
            route.endpoint
            for route in build_router(deps).routes
            if route.path == "/tasks/train_lora"
        )
        request = TrainLoraRequest(
            mode="sft",
            dataset_dir=str(dataset_dir),
            output_dir=str(deps.shared_audio_root / "output"),
            hold_token="hold-token",
            **_training_request_payload(),
        )
        with pytest.raises(ConnectionError, match="Redis unavailable"):
            await endpoint(request)
        assert not deps.gpu_hold_handover_tokens
        assert deps.cache._in_use.get("sft", 0) == 0
        monkeypatch.undo()
        monkeypatch.setattr("acestep_worker.wrapper.spawn_background", spawned.append)
        response = await endpoint(request)
        assert response.task_id
        await spawned[0]

    monkeypatch.setattr("acestep_worker.wrapper.renew_gpu_hold", unavailable_renewal)
    _run(scenario())


def test_train_lora_releases_handover_claim_when_setup_is_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps = _make_deps(tmp_path)
    dataset_dir = deps.shared_audio_root / "dataset"
    dataset_dir.mkdir()
    spawned: list[object] = []
    renewal_started = asyncio.Event()
    wait_for_renewal = asyncio.Event()

    async def blocked_renewal(*args, **kwargs) -> bool:
        renewal_started.set()
        await wait_for_renewal.wait()
        return True

    async def scenario() -> None:
        await deps.cache.load("sft")
        assert await reserve_gpu_hold(deps.redis, deps.worker_id, "hold-token", 15)
        endpoint = next(
            route.endpoint
            for route in build_router(deps).routes
            if route.path == "/tasks/train_lora"
        )
        request = TrainLoraRequest(
            mode="sft",
            dataset_dir=str(dataset_dir),
            output_dir=str(deps.shared_audio_root / "output"),
            hold_token="hold-token",
            **_training_request_payload(),
        )
        handover = asyncio.create_task(endpoint(request))
        await renewal_started.wait()
        handover.cancel()
        with pytest.raises(asyncio.CancelledError):
            await handover
        assert not deps.gpu_hold_handover_tokens
        assert deps.cache._in_use.get("sft", 0) == 0
        monkeypatch.undo()
        monkeypatch.setattr("acestep_worker.wrapper.spawn_background", spawned.append)
        response = await endpoint(request)
        assert response.task_id
        await spawned[0]

    monkeypatch.setattr("acestep_worker.wrapper.renew_gpu_hold", blocked_renewal)
    _run(scenario())


def test_train_lora_releases_the_hold_when_the_runner_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps = _make_deps(tmp_path)
    dataset_dir = deps.shared_audio_root / "dataset"
    dataset_dir.mkdir()
    spawned: list[object] = []

    async def failing_runner(*args, **kwargs) -> None:
        raise RuntimeError("training failed")

    async def scenario() -> None:
        await deps.cache.load("sft")
        assert await reserve_gpu_hold(deps.redis, deps.worker_id, "hold-token", 15)
        deps.train_lora_runner = failing_runner
        endpoint = next(
            route.endpoint
            for route in build_router(deps).routes
            if route.path == "/tasks/train_lora"
        )
        await endpoint(
            TrainLoraRequest(
                mode="sft",
                dataset_dir=str(dataset_dir),
                output_dir=str(deps.shared_audio_root / "output"),
                hold_token="hold-token",
                **_training_request_payload(),
            )
        )
        with pytest.raises(RuntimeError, match="training failed"):
            await spawned[0]
        assert await deps.redis.get(gpu_hold_key(deps.worker_id)) is None
        assert not deps.gpu_hold_handover_tokens

    monkeypatch.setattr("acestep_worker.wrapper.spawn_background", spawned.append)
    _run(scenario())


def test_train_lora_releases_the_hold_when_the_runner_is_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps = _make_deps(tmp_path)
    dataset_dir = deps.shared_audio_root / "dataset"
    dataset_dir.mkdir()
    spawned: list[object] = []
    runner_started = asyncio.Event()
    release_runner = asyncio.Event()

    async def blocking_runner(*args, **kwargs) -> None:
        runner_started.set()
        await release_runner.wait()

    async def scenario() -> None:
        await deps.cache.load("sft")
        assert await reserve_gpu_hold(deps.redis, deps.worker_id, "hold-token", 15)
        deps.train_lora_runner = blocking_runner
        endpoint = next(
            route.endpoint
            for route in build_router(deps).routes
            if route.path == "/tasks/train_lora"
        )
        await endpoint(
            TrainLoraRequest(
                mode="sft",
                dataset_dir=str(dataset_dir),
                output_dir=str(deps.shared_audio_root / "output"),
                hold_token="hold-token",
                **_training_request_payload(),
            )
        )
        background_task = asyncio.create_task(spawned[0])
        await runner_started.wait()
        background_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await background_task
        assert await deps.redis.get(gpu_hold_key(deps.worker_id)) is None
        assert not deps.gpu_hold_handover_tokens

    monkeypatch.setattr("acestep_worker.wrapper.spawn_background", spawned.append)
    _run(scenario())


def test_worker_renewal_failure_releases_hold_and_cache_before_background_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps = _make_deps(tmp_path)
    dataset_dir = deps.shared_audio_root / "dataset"
    dataset_dir.mkdir()
    renewal_started = asyncio.Event()
    training_started = asyncio.Event()
    training_cancelled = asyncio.Event()
    spawned: list[object] = []

    async def failed_renewal(*args, **kwargs) -> None:
        renewal_started.set()
        raise RuntimeError("renewal failed")

    async def blocking_runner(
        store: TaskStore,
        task_id: str,
        **kwargs,
    ) -> None:
        training_started.set()
        await store.mark_running(task_id)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            training_cancelled.set()
            raise

    async def scenario() -> None:
        await deps.cache.load("sft")
        assert await reserve_gpu_hold(deps.redis, deps.worker_id, "hold-token", 15)
        deps.train_lora_runner = blocking_runner
        endpoint = next(
            route.endpoint
            for route in build_router(deps).routes
            if route.path == "/tasks/train_lora"
        )
        response = await endpoint(
            TrainLoraRequest(
                mode="sft",
                dataset_dir=str(dataset_dir),
                output_dir=str(deps.shared_audio_root / "output"),
                hold_token="hold-token",
                **_training_request_payload(),
            )
        )
        assert response.task_id
        assert len(spawned) == 1
        with pytest.raises(RuntimeError, match="renewal failed"):
            await spawned[0]
        assert renewal_started.is_set()
        assert training_started.is_set()
        assert training_cancelled.is_set()
        assert await deps.redis.get(gpu_hold_key(deps.worker_id)) is None
        assert deps.cache._in_use.get("sft", 0) == 0
        assert not deps.gpu_hold_handover_tokens
        assert not deps.gpu_hold_handover_tasks

    monkeypatch.setattr("acestep_worker.wrapper._renew_gpu_hold_until_done", failed_renewal)
    monkeypatch.setattr("acestep_worker.wrapper.spawn_background", spawned.append)
    _run(scenario())


def test_train_lora_rejects_an_expired_hold_before_returning_a_task_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    deps = _make_deps(tmp_path)
    dataset_dir = deps.shared_audio_root / "dataset"
    dataset_dir.mkdir()
    spawned: list[object] = []

    async def expired_renewal(*args, **kwargs) -> bool:
        return False

    async def scenario() -> None:
        await deps.cache.load("sft")
        assert await reserve_gpu_hold(deps.redis, deps.worker_id, "hold-token", 15)
        endpoint = next(
            route.endpoint
            for route in build_router(deps).routes
            if route.path == "/tasks/train_lora"
        )
        with pytest.raises(HTTPException) as exc_info:
            await endpoint(
                TrainLoraRequest(
                    mode="sft",
                    dataset_dir=str(dataset_dir),
                    output_dir=str(deps.shared_audio_root / "output"),
                    hold_token="hold-token",
                    **_training_request_payload(),
                )
            )
        assert exc_info.value.status_code == 409
        assert not spawned
        assert await deps.task_store.size() == 0
        assert deps.cache._in_use.get("sft", 0) == 0
        assert not deps.gpu_hold_handover_tokens

    monkeypatch.setattr("acestep_worker.wrapper.renew_gpu_hold", expired_renewal)
    monkeypatch.setattr("acestep_worker.wrapper.spawn_background", spawned.append)
    _run(scenario())


def test_train_lora_pins_mode_from_eviction(tmp_path: Path) -> None:
    """A training task in flight increments the cache's in-use count so
    the mode is protected from eviction."""
    deps = _make_deps(tmp_path)
    _run(deps.cache.load("sft"))

    release_event = asyncio.Event()

    async def blocking_runner(
        store: TaskStore,
        task_id: str,
        *,
        request: TrainLoraRequest,
        port: int,
        checkpoint_dir: Path,
        training_workspace_dirname: str,
    ) -> None:
        await store.mark_running(task_id)
        await release_event.wait()
        await store.complete(
            task_id,
            TrainLoraTaskResult(
                mode=request.mode,
                adapter_dir="/tmp/x",
                num_samples=0,
            ),
        )

    deps.train_lora_runner = blocking_runner

    async def scenario() -> None:
        from acestep_worker.wrapper import spawn_background

        task_id = await deps.task_store.create("train_lora")
        from acestep_worker.downloads import spawn_background as _sp  # noqa: F401

        loaded = await deps.cache.acquire_for_use("sft")
        spawn_background(
            blocking_runner(
                deps.task_store,
                task_id,
                request=TrainLoraRequest(
                    mode="sft",
                    dataset_dir="/x",
                    output_dir="/y",
                    hold_token="test-token",
                    **_training_request_payload(),
                ),
                port=loaded.port,
                checkpoint_dir=deps.checkpoint_dir,
                training_workspace_dirname=deps.training_workspace_dirname,
            ),
        )
        await asyncio.sleep(0)
        assert deps.cache._in_use.get("sft", 0) == 1
        release_event.set()
        await asyncio.sleep(0.05)
        await deps.cache.release("sft")

    _run(scenario())


def test_default_train_lora_runner_dispatches(tmp_path: Path) -> None:
    """Sanity test that the real default_train_lora_runner is wired to
    an AceStepTrainingClient; patch the client methods to avoid HTTP."""
    from unittest.mock import patch

    from acestep_engine.training_client import (
        ExportResult,
        PreprocessStatus,
        PreprocessTaskHandle,
        ScanDatasetResult,
        TrainingStartedHandle,
        TrainingStatus,
    )

    task_store = TaskStore()
    task_id = _run(task_store.create("train_lora"))

    output_dir = tmp_path / "shared" / "out"
    dataset_dir = tmp_path / "ds"
    dataset_dir.mkdir()
    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"audio")
    (dataset_dir / "sample.wav").symlink_to(sample)

    request = TrainLoraRequest(
        mode="sft",
        dataset_dir=str(dataset_dir),
        output_dir=str(output_dir),
        hold_token="test-token",
        **_training_request_payload(train_epochs=1, poll_interval_seconds=0.001),
    )

    preprocess_states = iter(
        [
            PreprocessStatus(
                task_id="pre",
                status="running",
                progress="1/2",
                current=1,
                total=2,
            ),
            PreprocessStatus(
                task_id="pre",
                status="completed",
                progress="done",
                current=2,
                total=2,
            ),
        ]
    )
    training_states = iter(
        [
            TrainingStatus(is_training=True, current_epoch=0, current_loss=0.5),
            TrainingStatus(is_training=False, current_epoch=1, current_loss=0.2),
        ]
    )

    calls: list[tuple[str, object]] = []

    def initialize_model(mode: str) -> None:
        calls.append(("initialize_model", mode))

    def scan_dataset(path: str) -> ScanDatasetResult:
        staged_sample = Path(path) / "sample.wav"
        assert staged_sample.read_bytes() == b"audio"
        assert not staged_sample.is_symlink()
        calls.append(("scan_dataset", path))
        return ScanDatasetResult(num_samples=3)

    def export_training(source: str, destination: str) -> ExportResult:
        calls.append(("export_training", (source, destination)))
        source_dir = Path(source) / "final"
        source_dir.mkdir(parents=True)
        (source_dir / "lokr_weights.safetensors").write_bytes(b"weights")
        shutil.copytree(source_dir, destination)
        return ExportResult(export_path=destination, source=str(source_dir))

    with (
        patch(
            "acestep_engine.training_client.AceStepTrainingClient.initialize_model",
            side_effect=initialize_model,
        ),
        patch(
            "acestep_engine.training_client.AceStepTrainingClient.scan_dataset",
            side_effect=scan_dataset,
        ),
        patch(
            "acestep_engine.training_client.AceStepTrainingClient.start_preprocess",
            return_value=PreprocessTaskHandle(task_id="pre", total=2),
        ),
        patch(
            "acestep_engine.training_client.AceStepTrainingClient.poll_preprocess",
            side_effect=lambda tid: next(preprocess_states),
        ),
        patch(
            "acestep_engine.training_client.AceStepTrainingClient.start_lokr",
            return_value=TrainingStartedHandle(
                tensor_dir="unused",
                output_dir="unused",
            ),
        ),
        patch(
            "acestep_engine.training_client.AceStepTrainingClient.poll_training",
            side_effect=lambda: next(training_states),
        ),
        patch(
            "acestep_engine.training_client.AceStepTrainingClient.export_training",
            side_effect=export_training,
        ),
    ):
        _run(
            default_train_lora_runner(
                task_store,
                task_id,
                request=request,
                port=8001,
                checkpoint_dir=tmp_path / "safe-root",
                training_workspace_dirname="training",
            ),
        )

    snap = _run(task_store.get(task_id))
    assert snap is not None
    assert snap.state == "done"
    assert snap.result is not None
    assert snap.result.adapter_dir == str(output_dir)
    assert (output_dir / "lokr_weights.safetensors").read_bytes() == b"weights"
    assert calls[0] == ("initialize_model", "sft")
    assert calls[1] == (
        "scan_dataset",
        str(tmp_path / "safe-root" / "training" / task_id / "dataset"),
    )
    source, destination = calls[-1][1]
    assert source == str(tmp_path / "safe-root" / "training" / task_id / "output")
    assert destination == str(tmp_path / "safe-root" / "training" / task_id / "export")
    assert source != destination
    assert not (tmp_path / "safe-root" / "training" / task_id).exists()


def test_default_train_lora_runner_fails_on_preprocess_error(tmp_path: Path) -> None:
    from unittest.mock import patch

    from acestep_engine.training_client import (
        PreprocessStatus,
        PreprocessTaskHandle,
        ScanDatasetResult,
    )

    task_store = TaskStore()
    task_id = _run(task_store.create("train_lora"))
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    request = TrainLoraRequest(
        mode="sft",
        dataset_dir=str(source_dir),
        output_dir=str(tmp_path / "out"),
        hold_token="test-token",
        **_training_request_payload(train_epochs=1, poll_interval_seconds=0.001),
    )
    with (
        patch(
            "acestep_engine.training_client.AceStepTrainingClient.initialize_model",
            return_value=None,
        ),
        patch(
            "acestep_engine.training_client.AceStepTrainingClient.scan_dataset",
            return_value=ScanDatasetResult(num_samples=3),
        ),
        patch(
            "acestep_engine.training_client.AceStepTrainingClient.start_preprocess",
            return_value=PreprocessTaskHandle(task_id="pre", total=2),
        ),
        patch(
            "acestep_engine.training_client.AceStepTrainingClient.poll_preprocess",
            return_value=PreprocessStatus(
                task_id="pre",
                status="failed",
                error="OOM",
                progress="",
                current=0,
                total=2,
            ),
        ),
        patch(
            "acestep_engine.training_client.AceStepTrainingClient.stop_training",
            return_value=None,
        ),
    ):
        _run(
            default_train_lora_runner(
                task_store,
                task_id,
                request=request,
                port=8001,
                checkpoint_dir=tmp_path / "safe-root",
                training_workspace_dirname="training",
            ),
        )
    snap = _run(task_store.get(task_id))
    assert snap.state == "error"
    assert "OOM" in (snap.error or "")
    assert not (tmp_path / "safe-root" / "training" / task_id).exists()


def test_default_train_lora_runner_fails_on_zero_samples(tmp_path: Path) -> None:
    from unittest.mock import patch

    from acestep_engine.training_client import ScanDatasetResult

    task_store = TaskStore()
    task_id = _run(task_store.create("train_lora"))
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    request = TrainLoraRequest(
        mode="sft",
        dataset_dir=str(source_dir),
        output_dir=str(tmp_path / "out"),
        hold_token="test-token",
        **_training_request_payload(train_epochs=1, poll_interval_seconds=0.001),
    )
    with (
        patch(
            "acestep_engine.training_client.AceStepTrainingClient.initialize_model",
            return_value=None,
        ),
        patch(
            "acestep_engine.training_client.AceStepTrainingClient.scan_dataset",
            return_value=ScanDatasetResult(num_samples=0),
        ),
        patch(
            "acestep_engine.training_client.AceStepTrainingClient.stop_training",
            return_value=None,
        ),
    ):
        _run(
            default_train_lora_runner(
                task_store,
                task_id,
                request=request,
                port=8001,
                checkpoint_dir=tmp_path / "safe-root",
                training_workspace_dirname="training",
            ),
        )
    snap = _run(task_store.get(task_id))
    assert snap.state == "error"


@pytest.mark.parametrize(
    "invalid_path",
    [
        "outside_dataset",
        "parent_escape",
        "absolute_output",
        "dataset_symlink",
        "output_symlink",
        "existing_output",
    ],
)
def test_train_lora_rejects_unsafe_shared_paths_before_creating_task(
    tmp_path: Path,
    invalid_path: str,
) -> None:
    deps = _make_deps(tmp_path)
    dataset_dir = deps.shared_audio_root / "dataset"
    dataset_dir.mkdir()
    outside_dataset = tmp_path / "outside-dataset"
    outside_dataset.mkdir()
    dataset_symlink = deps.shared_audio_root / "dataset-link"
    dataset_symlink.symlink_to(dataset_dir, target_is_directory=True)
    output_symlink = deps.shared_audio_root / "output-link"
    output_symlink.symlink_to(deps.shared_audio_root / "target")

    dataset_path = dataset_dir
    output_path = deps.shared_audio_root / "output"
    if invalid_path == "outside_dataset":
        dataset_path = outside_dataset
    elif invalid_path == "parent_escape":
        output_path = deps.shared_audio_root / "dataset" / ".." / ".." / "outside-output"
    elif invalid_path == "absolute_output":
        output_path = tmp_path / "outside-output"
    elif invalid_path == "dataset_symlink":
        dataset_path = dataset_symlink
    elif invalid_path == "existing_output":
        output_path.mkdir()
    else:
        output_path = output_symlink

    _run(deps.cache.load("sft"))
    app = create_app(deps)
    with TestClient(app) as client:
        response = client.post(
            "/tasks/train_lora",
            json=_training_request_payload(
                mode="sft",
                dataset_dir=str(dataset_path),
                output_dir=str(output_path),
                hold_token="test-token",
            ),
            headers=_auth_headers(),
        )

    assert response.status_code == 422
    assert _run(deps.task_store.size()) == 0
    assert getattr(deps, "_operation_events") == ["load_model:sft"]


def test_cancellation_waits_for_staging_copy_before_workspace_cleanup(
    tmp_path: Path,
) -> None:
    from unittest.mock import patch

    task_store = TaskStore()
    task_id = _run(task_store.create("train_lora"))
    shared_root = tmp_path / "shared"
    dataset_dir = shared_root / "dataset"
    dataset_dir.mkdir(parents=True)
    request = TrainLoraRequest(
        mode="sft",
        dataset_dir=str(dataset_dir),
        output_dir=str(shared_root / "training_tmp"),
        hold_token="test-token",
        **_training_request_payload(train_epochs=1, poll_interval_seconds=0.001),
    )
    copy_started = threading.Event()
    copy_release = threading.Event()
    workspace = tmp_path / "safe-root" / "training" / task_id

    def blocking_copytree(source, destination, *, symlinks):
        copy_started.set()
        copy_release.wait()
        return destination

    async def cancel_during_copy() -> None:
        runner = asyncio.create_task(
            default_train_lora_runner(
                task_store,
                task_id,
                request=request,
                port=8001,
                checkpoint_dir=tmp_path / "safe-root",
                training_workspace_dirname="training",
            )
        )
        await asyncio.to_thread(copy_started.wait)
        runner.cancel()
        await asyncio.sleep(0)
        assert workspace.exists()
        copy_release.set()
        with pytest.raises(asyncio.CancelledError):
            await runner

    with (
        patch(
            "acestep_worker.wrapper.shutil.copytree",
            side_effect=blocking_copytree,
        ),
        patch(
            "acestep_engine.training_client.AceStepTrainingClient.stop_training",
            return_value=None,
        ),
    ):
        _run(cancel_during_copy())

    assert not workspace.exists()

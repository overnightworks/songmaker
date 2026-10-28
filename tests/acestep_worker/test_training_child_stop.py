"""After a LoRA training the worker stops that mode's child before it releases the GPU hold."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

import fakeredis.aioredis
import httpx
import pytest

from acestep_engine.constants import MODE_NOT_LOADED_DETAIL
from acestep_worker.heartbeat import (
    DEFAULT_TTL_SECONDS,
    HeartbeatLoop,
    gpu_hold_key,
    reserve_gpu_hold,
)
from acestep_worker.model_cache import LoadedModel, ModelCache
from acestep_worker.models import GenerationTaskResult, TrainLoraRequest, TrainLoraTaskResult
from acestep_worker.subprocess_runner import SubprocessHandle, make_acestep_runner
from acestep_worker.task_store import TaskStore
from acestep_worker.wrapper import (
    WorkerDeps,
    _create_gpu_hold_handover_task,
    _renew_gpu_hold_until_done,
    _run_train_lora_with_cleanup,
    _TrainLoraResources,
    build_state_payload,
    create_app,
)

_TOKEN = "training-hold-token"
_HEADERS = {"X-Internal-Token": "test-internal-token"}
_GENERATE_BODY = {"mode": "sft", "config": {"prompt": "test", "lyrics": ""}}
_HANG_GUARD_SECONDS = 5
_HOLD_DETAIL = "GPU is held for LoRA training"

_T = TypeVar("_T")
Unloader = Callable[[LoadedModel], Awaitable[None]]
TrainingRunner = Callable[..., Awaitable[None]]


async def _training_succeeds(store: TaskStore, task_id: str, **_: object) -> None:
    await store.mark_running(task_id)
    await store.complete(task_id, TrainLoraTaskResult(mode="sft", adapter_dir="/adapter"))


async def _training_fails(store: TaskStore, task_id: str, **_: object) -> None:
    await store.mark_running(task_id)
    await store.fail(task_id, "training blew up")


async def _training_runs_until_cancelled(store: TaskStore, task_id: str, **_: object) -> None:
    await store.mark_running(task_id)
    await asyncio.Event().wait()


async def _generation_completes(store: TaskStore, task_id: str, **_: object) -> None:
    await store.mark_running(task_id)
    await store.complete(task_id, GenerationTaskResult(mode="sft", audio_path="/a.wav", seed=1))


@dataclass
class _Worker:
    deps: WorkerDeps
    children: list[SubprocessHandle] = field(default_factory=list)
    hold_existed_when_child_stopped: list[bool] = field(default_factory=list)
    task_id: str = ""

    @property
    def redis(self) -> fakeredis.aioredis.FakeRedis:
        return self.deps.redis  # type: ignore[return-value]

    async def hold_exists(self) -> bool:
        return bool(await self.redis.exists(gpu_hold_key(self.deps.worker_id)))

    def app_client(self) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=create_app(self.deps))
        return httpx.AsyncClient(transport=transport, base_url="http://worker", headers=_HEADERS)

    async def start_training(self, runner: TrainingRunner, mode: str = "sft") -> asyncio.Task[None]:
        deps = self.deps
        loaded = await deps.cache.acquire_for_use(mode)
        assert await reserve_gpu_hold(self.redis, deps.worker_id, _TOKEN, DEFAULT_TTL_SECONDS)
        task_id = await _create_gpu_hold_handover_task(deps, _TOKEN, train_epochs=1)
        assert task_id is not None
        renew_task = asyncio.create_task(
            _renew_gpu_hold_until_done(self.redis, deps.worker_id, _TOKEN)
        )
        request = TrainLoraRequest.model_construct(mode=mode, hold_token=_TOKEN)
        resources = _TrainLoraResources(loaded=loaded, renew_task=renew_task, task_id=task_id)
        self.task_id = task_id
        return asyncio.create_task(
            _run_train_lora_with_cleanup(deps, request, request, runner, resources)
        )

    async def train(self, runner: TrainingRunner, mode: str = "sft") -> None:
        await (await self.start_training(runner, mode))

    async def assert_everything_released(self, mode: str = "sft") -> None:
        assert not await self.hold_exists()
        assert self.deps.cache.in_use_count(mode) == 0
        assert _TOKEN not in self.deps.gpu_hold_handover_tokens
        assert mode not in self.deps.cache.loaded_modes()


@pytest.fixture
def make_worker(
    tmp_path: Path, fake_uv, free_port: Callable[[], int]
) -> Callable[..., _Worker]:
    def make(
        *,
        unloader_wrapper: Callable[[_Worker, Unloader], Unloader] | None = None,
        init_llm: bool = True,
    ) -> _Worker:
        redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
        _, production_unloader = make_acestep_runner(
            checkpoint_dir=tmp_path, base_port=free_port(), vram_budget_gb=24.0
        )
        body = fake_uv.health(llm_initialized=init_llm)
        children: list[SubprocessHandle] = []

        async def loader(mode: str) -> LoadedModel:
            handle = await asyncio.to_thread(fake_uv.start, body, mode=mode, init_llm=init_llm)
            children.append(handle)
            return LoadedModel(mode=mode, handle=handle, port=handle.port)

        cache = ModelCache(
            vram_budget_gb=24.0,
            model_sizes={"sft": 6.0, "turbo": 6.0},
            loader=loader,
            unloader=production_unloader,
        )
        deps = WorkerDeps(
            worker_id="acestep-worker-0",
            cache=cache,
            task_store=TaskStore(),
            heartbeat=None,  # type: ignore[arg-type]
            redis=redis,
            registry_client=None,
            registration=None,
            checkpoint_dir=tmp_path,
            audio_output_dir=tmp_path / "audio",
            internal_token="test-internal-token",
            generate_runner=_generation_completes,
        )
        deps.heartbeat = HeartbeatLoop(
            redis=redis,
            worker_id=deps.worker_id,
            state_provider=lambda: build_state_payload(deps),
        )
        worker = _Worker(deps=deps, children=children)

        async def observing(model: LoadedModel) -> None:
            worker.hold_existed_when_child_stopped.append(await worker.hold_exists())
            await production_unloader(model)

        cache._unloader = (
            unloader_wrapper(worker, observing) if unloader_wrapper is not None else observing
        )
        return worker

    return make


async def _within(awaitable: Awaitable[_T]) -> _T:
    return await asyncio.wait_for(awaitable, timeout=_HANG_GUARD_SECONDS)


def _alive(handle: SubprocessHandle) -> bool:
    return handle.process.poll() is None


@pytest.mark.parametrize(
    ("runner", "state"),
    [
        pytest.param(_training_succeeds, "done", id="success"),
        pytest.param(_training_fails, "error", id="failure"),
    ],
)
def test_training_stops_the_child_before_the_hold_is_released(
    make_worker, runner: TrainingRunner, state: str
) -> None:
    async def scenario() -> None:
        worker = make_worker()
        await worker.deps.cache.load("sft")
        await worker.train(runner)

        assert worker.hold_existed_when_child_stopped == [True]
        assert not _alive(worker.children[0])
        await worker.assert_everything_released()
        snapshot = await worker.deps.task_store.get(worker.task_id)
        assert snapshot is not None
        assert snapshot.state == state

    asyncio.run(scenario())


def test_cancelled_training_stops_the_child_before_the_hold_is_released(make_worker) -> None:
    async def scenario() -> None:
        worker = make_worker()
        await worker.deps.cache.load("sft")
        owner = await worker.start_training(_training_runs_until_cancelled)
        await asyncio.sleep(0)
        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner

        assert worker.hold_existed_when_child_stopped == [True]
        assert not _alive(worker.children[0])
        await worker.assert_everything_released()
        snapshot = await worker.deps.task_store.get(worker.task_id)
        assert snapshot is not None
        assert snapshot.state == "running"

    asyncio.run(scenario())


def test_next_take_after_a_training_reloads_a_fresh_child(make_worker) -> None:
    async def scenario() -> None:
        worker = make_worker()
        await worker.deps.cache.load("sft")
        await worker.train(_training_succeeds)

        async with worker.app_client() as client:
            refused = await client.post("/generate", json=_GENERATE_BODY)
            assert refused.status_code == 409
            assert refused.json()["detail"] == MODE_NOT_LOADED_DETAIL.format(mode="sft")
            assert (await client.post("/load_model", json={"mode": "sft"})).status_code == 200
            admitted = await client.post("/generate", json=_GENERATE_BODY)

        assert admitted.status_code == 200
        assert len(worker.children) == 2
        assert worker.children[0].process.pid != worker.children[1].process.pid
        assert _alive(worker.children[1])
        await worker.deps.cache.evict_all()

    asyncio.run(scenario())


def test_training_stops_the_child_the_same_way_with_the_lm_off(make_worker) -> None:
    async def scenario() -> None:
        worker = make_worker(init_llm=False)
        await worker.deps.cache.load("sft")
        await worker.train(_training_succeeds)

        assert worker.hold_existed_when_child_stopped == [True]
        assert not _alive(worker.children[0])
        await worker.assert_everything_released()

    asyncio.run(scenario())


def test_failing_stop_still_releases_everything_and_is_logged(
    make_worker, caplog: pytest.LogCaptureFixture
) -> None:

    def failing_wrapper(_worker: _Worker, observing: Unloader) -> Unloader:
        async def unloader(model: LoadedModel) -> None:
            await observing(model)
            raise RuntimeError("child would not stop")

        return unloader

    async def scenario() -> None:
        worker = make_worker(unloader_wrapper=failing_wrapper)
        await worker.deps.cache.load("sft")
        await worker.deps.cache.pin("sft")
        with pytest.raises(RuntimeError, match="child would not stop"):
            await worker.train(_training_succeeds)

        assert worker.hold_existed_when_child_stopped == [True]
        await worker.assert_everything_released()
        assert worker.deps.cache.is_pinned("sft")
        worker.children[0].process.kill()

    with caplog.at_level("ERROR"):
        asyncio.run(scenario())
    assert "child would not stop" in caplog.text


def test_training_cancelled_while_the_child_stops_still_releases_everything(make_worker) -> None:
    stopping = asyncio.Event
    holder: dict[str, asyncio.Event] = {}

    def blocking_wrapper(_worker: _Worker, observing: Unloader) -> Unloader:
        async def unloader(model: LoadedModel) -> None:
            await observing(model)
            holder["stopping"].set()
            await asyncio.Event().wait()

        return unloader

    async def scenario() -> None:
        holder["stopping"] = stopping()
        worker = make_worker(unloader_wrapper=blocking_wrapper)
        await worker.deps.cache.load("sft")
        owner = await worker.start_training(_training_succeeds)
        await _within(holder["stopping"].wait())
        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner

        await worker.assert_everything_released()
        worker.children[0].process.kill()

    asyncio.run(scenario())


def test_use_above_one_leaves_the_child_running_and_is_logged(
    make_worker, caplog: pytest.LogCaptureFixture
) -> None:
    async def scenario() -> None:
        worker = make_worker()
        await worker.deps.cache.load("sft")
        await worker.deps.cache.acquire_for_use("sft")
        await worker.train(_training_succeeds)

        assert worker.hold_existed_when_child_stopped == []
        assert _alive(worker.children[0])
        assert worker.deps.cache.in_use_count("sft") == 1
        assert not await worker.hold_exists()
        await worker.deps.cache.evict_all()

    with caplog.at_level("WARNING"):
        asyncio.run(scenario())
    assert "sft" in caplog.text


def test_training_leaves_another_loaded_mode_running(make_worker) -> None:
    async def scenario() -> None:
        worker = make_worker()
        await worker.deps.cache.load("sft")
        await worker.deps.cache.load("turbo")
        await worker.deps.cache.acquire_for_use("turbo")
        await worker.train(_training_succeeds)

        assert worker.deps.cache.loaded_modes() == ["turbo"]
        assert worker.deps.cache.in_use_count("turbo") == 1
        assert _alive(worker.children[1])
        await worker.deps.cache.evict_all()

    asyncio.run(scenario())


def test_pinned_mode_is_pinned_again_when_the_next_take_reloads_it(make_worker) -> None:
    async def scenario() -> None:
        worker = make_worker()
        await worker.deps.cache.load("sft")
        await worker.deps.cache.pin("sft")
        await worker.train(_training_succeeds)

        assert worker.deps.cache.loaded_modes() == []
        assert worker.deps.cache.snapshot().pinned == ("sft",)
        await worker.deps.cache.load("sft")
        assert worker.deps.cache.is_pinned("sft")
        await worker.deps.cache.evict_all()

    asyncio.run(scenario())


def test_cleanup_after_the_shutdown_evicted_everything_raises_nothing(make_worker) -> None:
    async def scenario() -> None:
        worker = make_worker()
        await worker.deps.cache.load("sft")
        owner = await worker.start_training(_training_runs_until_cancelled)
        await asyncio.sleep(0)
        await worker.deps.cache.evict_all()
        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner

        await worker.assert_everything_released()

    asyncio.run(scenario())


@pytest.mark.parametrize("hold_lapses", [False, True], ids=["hold-stands", "hold-lapsed"])
def test_take_during_the_stop_never_reaches_the_old_child(make_worker, hold_lapses: bool) -> None:
    holder: dict[str, asyncio.Event] = {}

    def gated_wrapper(worker: _Worker, observing: Unloader) -> Unloader:
        async def unloader(model: LoadedModel) -> None:
            await observing(model)
            if hold_lapses:
                await worker.redis.delete(gpu_hold_key(worker.deps.worker_id))
            holder["stopping"].set()
            await _within(holder["proceed"].wait())

        return unloader

    async def scenario() -> None:
        holder["stopping"], holder["proceed"] = asyncio.Event(), asyncio.Event()
        worker = make_worker(unloader_wrapper=gated_wrapper)
        await worker.deps.cache.load("sft")
        owner = await worker.start_training(_training_succeeds)
        await _within(holder["stopping"].wait())

        async with worker.app_client() as client:
            take = asyncio.create_task(client.post("/generate", json=_GENERATE_BODY))
            for _ in range(20):
                await asyncio.sleep(0)
            if hold_lapses:
                assert not take.done()
            holder["proceed"].set()
            response = await _within(take)
        await owner

        assert response.status_code == 409
        expected = _HOLD_DETAIL if not hold_lapses else MODE_NOT_LOADED_DETAIL.format(mode="sft")
        assert response.json()["detail"] == expected

    asyncio.run(scenario())

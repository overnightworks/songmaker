"""Fakes for the ACE-Step worker wrapper's dependencies and its internal-token headers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

import fakeredis
import fakeredis.aioredis
from tandem.testing import aged_epoch

from songmaker_acestep_engine.models import AceStepConfig
from songmaker_acestep_worker.heartbeat import HeartbeatLoop, gpu_hold_locks, reserve_gpu_hold
from songmaker_acestep_worker.model_cache import LoadedModel, ModelCache, VramReader
from songmaker_acestep_worker.models import GenerationTaskResult
from songmaker_acestep_worker.task_store import TaskStore
from songmaker_acestep_worker.wrapper import WorkerDeps, build_state_payload
from songmaker_cli.constants import REDIS_KEY_PREFIX

INTERNAL_TOKEN_HEADER = "X-Internal-Token"
INTERNAL_TOKEN = "test-internal-token"
INTERNAL_HEADERS = {INTERNAL_TOKEN_HEADER: INTERNAL_TOKEN}


def run(coro):
    return asyncio.run(coro)


def settled_fake_redis() -> fakeredis.aioredis.FakeRedis:
    """A worker's Redis that has run longer than a GPU hold lasts, as it finds it in operation."""
    server = fakeredis.FakeServer()
    sync_client = fakeredis.FakeRedis(server=server)
    sync_client.set(*aged_epoch(key_prefix=REDIS_KEY_PREFIX))
    return fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)


def make_deps(
    tmp_path: Path,
    *,
    vram_reader: VramReader | None = None,
    model_sizes: dict[str, float] | None = None,
    model_loader: Callable[[str], Awaitable[LoadedModel]] | None = None,
) -> tuple[WorkerDeps, fakeredis.aioredis.FakeRedis]:
    redis = settled_fake_redis()
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
        await store.complete(task_id, GenerationTaskResult(mode=mode, seed=42))

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
        internal_token=INTERNAL_TOKEN,
        generate_runner=fake_generate_runner,
    )
    deps.heartbeat = HeartbeatLoop(
        redis=redis,
        worker_id="acestep-worker-0",
        state_provider=lambda: build_state_payload(deps),
    )
    return deps, redis


async def gpu_hold_generation(redis: fakeredis.aioredis.FakeRedis, worker_id: str) -> str | None:
    """The generation of the worker's live GPU hold, or None when none is held."""
    return (await gpu_hold_locks(redis).state(worker_id)).generation


async def reserved_gpu_hold(redis: fakeredis.aioredis.FakeRedis, worker_id: str) -> str:
    """The generation of a new GPU hold on the worker; the reserve must have succeeded."""
    generation = await reserve_gpu_hold(redis, worker_id)
    assert generation
    return generation

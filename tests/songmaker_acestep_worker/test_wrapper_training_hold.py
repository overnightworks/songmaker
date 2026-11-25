"""The ACE-Step worker's LoRA training keeps its hold and refuses a hold it no longer has."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import fakeredis
import pytest
from fastapi.testclient import TestClient
from support.wrapper_deps import INTERNAL_HEADERS, make_deps
from tandem.testing import aged_epoch

from songmaker_acestep_worker.heartbeat import GPU_HOLD_LASTS, gpu_hold_locks
from songmaker_acestep_worker.wrapper import create_app
from songmaker_cli.constants import REDIS_KEY_PREFIX

_LOWERED_TTL_SECONDS = 3
_BOUND_SECONDS = 5


def test_a_training_renews_its_hold_after_each_interval(
    train_lora_worker: Callable[[], Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from songmaker_acestep_worker import wrapper

    monkeypatch.setattr("songmaker_acestep_worker.wrapper.DEFAULT_INTERVAL_SECONDS", 0)
    renew_gpu_hold = wrapper.renew_gpu_hold
    hold_lowered = False
    renewed_after_lowering = asyncio.Event()

    async def renew_and_signal(*args: Any) -> bool:
        started_after_lowering = hold_lowered
        renewed = await renew_gpu_hold(*args)
        if started_after_lowering:
            renewed_after_lowering.set()
        return renewed

    monkeypatch.setattr("songmaker_acestep_worker.wrapper.renew_gpu_hold", renew_and_signal)

    async def scenario() -> tuple[str, str | None, timedelta]:
        nonlocal hold_lowered
        async with train_lora_worker() as worker:
            token = await worker.reserve_hold()
            locks = gpu_hold_locks(worker.deps.redis)
            worker_id = worker.deps.worker_id
            observed: list[tuple[str | None, timedelta]] = []

            async def runner(store: Any, task_id: str, **_kwargs: Any) -> None:
                nonlocal hold_lowered
                lowered_expiry_ms = (time.time() + _LOWERED_TTL_SECONDS) * 1000
                await worker.deps.redis.zadd(locks.keys.expiry, {worker_id: lowered_expiry_ms})
                hold_lowered = True
                await asyncio.wait_for(renewed_after_lowering.wait(), _BOUND_SECONDS)
                state = await locks.state(worker_id)
                assert state.remaining is not None
                observed.append((state.generation, state.remaining))
                await store.fail(task_id, "stopped")

            worker.deps.train_lora_runner = runner
            response = await worker.train(token)
            assert response.status_code == 200
            await worker.spawned[0]
            return token, *observed[0]

    token, holder, remaining = asyncio.run(scenario())

    assert holder == token
    assert timedelta(seconds=_LOWERED_TTL_SECONDS) < remaining <= GPU_HOLD_LASTS


def test_a_training_whose_hold_is_lost_at_handover_is_refused_and_its_renewal_is_cancelled(
    train_lora_worker: Callable[[], Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from songmaker_acestep_worker import wrapper

    start_gpu_hold_renewal = wrapper._start_gpu_hold_renewal
    renewals: list[asyncio.Task[None]] = []
    created_task_ids: list[str] = []

    async def lose_the_hold_at_handover(*_args: Any) -> bool:
        return False

    async def record_renewal(*args: Any) -> asyncio.Task[None]:
        renewals.append(await start_gpu_hold_renewal(*args))
        return renewals[-1]

    monkeypatch.setattr(
        "songmaker_acestep_worker.wrapper.gpu_hold_matches", lose_the_hold_at_handover
    )
    monkeypatch.setattr("songmaker_acestep_worker.wrapper._start_gpu_hold_renewal", record_renewal)

    async def scenario() -> tuple[int, bool, list[Any], list[str]]:
        async with train_lora_worker() as worker:
            token = await worker.reserve_hold()
            task_store = worker.deps.task_store
            create_task = task_store.create

            async def record_created_task(*args: Any, **kwargs: Any) -> str:
                task_id = await create_task(*args, **kwargs)
                created_task_ids.append(task_id)
                return task_id

            monkeypatch.setattr(task_store, "create", record_created_task)
            refused = await worker.train(token)
            (renewal,) = renewals
            await asyncio.wait({renewal}, timeout=_BOUND_SECONDS)
            return (
                refused.status_code,
                renewal.cancelled(),
                worker.spawned,
                created_task_ids,
            )

    status_code, renewal_cancelled, spawned, created_ids = asyncio.run(scenario())

    assert status_code == 409
    assert renewal_cancelled
    assert spawned == []
    assert created_ids == []


def test_a_worker_answers_busy_until_a_redis_restart_is_settled_and_fails_nothing(
    tmp_path: Path,
) -> None:
    """After a restart a hold may have been lost: reserve and generate get the ordinary 409
    for one span, then the worker serves both again."""
    deps, redis = make_deps(tmp_path)
    server = redis.connection_pool.connection_kwargs["server"]
    restarted_redis = fakeredis.FakeRedis(server=server)
    app = create_app(deps)
    generation = {"mode": "sft", "config": {"prompt": "test", "lyrics": ""}}
    with TestClient(app, headers=INTERNAL_HEADERS) as client:
        assert client.post("/load_model", json={"mode": "sft"}).status_code == 200
        restarted_redis.flushall()

        reserved = client.post("/gpu_hold/reserve")
        generated = client.post("/generate", json=generation)
        restarted_redis.set(*aged_epoch(key_prefix=REDIS_KEY_PREFIX))
        reserved_when_settled = client.post("/gpu_hold/reserve")

    assert reserved.status_code == 409
    assert reserved.json()["detail"] == "GPU is busy or held"
    assert generated.status_code == 409
    assert generated.json()["detail"] == "GPU is held for LoRA training"
    assert reserved_when_settled.status_code == 200

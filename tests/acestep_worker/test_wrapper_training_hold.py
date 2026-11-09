"""The ACE-Step worker's LoRA training keeps its hold and refuses a hold it no longer has."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from acestep_worker.heartbeat import DEFAULT_TTL_SECONDS, gpu_hold_key

_LOWERED_TTL_SECONDS = 3
_BOUND_SECONDS = 5


def test_a_training_renews_its_hold_after_each_interval(
    train_lora_worker: Callable[[], Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from acestep_worker import wrapper

    monkeypatch.setattr("acestep_worker.wrapper.DEFAULT_INTERVAL_SECONDS", 0)
    renew_gpu_hold = wrapper.renew_gpu_hold
    hold_lowered = False
    renewed_after_lowering = asyncio.Event()

    async def renew_and_signal(*args: Any) -> bool:
        started_after_lowering = hold_lowered
        renewed = await renew_gpu_hold(*args)
        if started_after_lowering:
            renewed_after_lowering.set()
        return renewed

    monkeypatch.setattr("acestep_worker.wrapper.renew_gpu_hold", renew_and_signal)

    async def scenario() -> tuple[str, bytes | None, int]:
        nonlocal hold_lowered
        async with train_lora_worker() as worker:
            token = await worker.reserve_hold()
            key = gpu_hold_key(worker.deps.worker_id)
            observed: list[tuple[bytes | None, int]] = []

            async def runner(store: Any, task_id: str, **_kwargs: Any) -> None:
                nonlocal hold_lowered
                redis = worker.deps.redis
                await redis.expire(key, _LOWERED_TTL_SECONDS)
                hold_lowered = True
                await asyncio.wait_for(renewed_after_lowering.wait(), _BOUND_SECONDS)
                observed.append((await redis.get(key), await redis.ttl(key)))
                await store.fail(task_id, "stopped")

            worker.deps.train_lora_runner = runner
            response = await worker.train(token)
            assert response.status_code == 200
            await worker.spawned[0]
            return token, *observed[0]

    token, holder, ttl_seconds = asyncio.run(scenario())

    assert holder == token.encode()
    assert ttl_seconds == DEFAULT_TTL_SECONDS


def test_a_training_whose_hold_is_lost_at_handover_is_refused_and_its_renewal_is_cancelled(
    train_lora_worker: Callable[[], Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from acestep_worker import wrapper

    start_gpu_hold_renewal = wrapper._start_gpu_hold_renewal
    renewals: list[asyncio.Task[None]] = []
    created_task_ids: list[str] = []

    async def lose_the_hold_at_handover(*_args: Any) -> bool:
        return False

    async def record_renewal(*args: Any) -> asyncio.Task[None]:
        renewals.append(await start_gpu_hold_renewal(*args))
        return renewals[-1]

    monkeypatch.setattr("acestep_worker.wrapper.gpu_hold_matches", lose_the_hold_at_handover)
    monkeypatch.setattr("acestep_worker.wrapper._start_gpu_hold_renewal", record_renewal)

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

"""The ACE-Step worker's LoRA training keeps its hold and refuses a hold it no longer has."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from acestep_worker.heartbeat import DEFAULT_TTL_SECONDS, gpu_hold_key, reserve_gpu_hold

_LOWERED_TTL_SECONDS = 3
_TURNS_TO_WAIT = 100


def test_a_training_renews_its_hold_after_each_interval(
    train_lora_worker: Callable[[], Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("acestep_worker.wrapper.DEFAULT_INTERVAL_SECONDS", 0)

    async def scenario() -> tuple[str, bytes | None, int]:
        async with train_lora_worker() as worker:
            token = await worker.reserve_hold()
            key = gpu_hold_key(worker.deps.worker_id)
            observed: list[tuple[bytes | None, int]] = []

            async def runner(store: Any, task_id: str, **_kwargs: Any) -> None:
                redis = worker.deps.redis
                await redis.expire(key, _LOWERED_TTL_SECONDS)
                for _ in range(_TURNS_TO_WAIT):
                    await asyncio.sleep(0)
                    if await redis.ttl(key) > _LOWERED_TTL_SECONDS:
                        break
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


def test_a_training_whose_hold_is_lost_before_handover_is_refused_and_stops_renewing(
    train_lora_worker: Callable[[], Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from acestep_worker import wrapper

    monkeypatch.setattr("acestep_worker.wrapper.DEFAULT_INTERVAL_SECONDS", 0)
    renew_gpu_hold = wrapper.renew_gpu_hold

    async def renew_then_lose_the_hold(redis: Any, worker_id: str, *args: Any) -> bool:
        renewed = await renew_gpu_hold(redis, worker_id, *args)
        await redis.delete(gpu_hold_key(worker_id))
        return renewed

    async def scenario() -> tuple[int, dict[str, Any], int]:
        async with train_lora_worker() as worker:
            token = await worker.reserve_hold()
            key = gpu_hold_key(worker.deps.worker_id)
            monkeypatch.setattr("acestep_worker.wrapper.renew_gpu_hold", renew_then_lose_the_hold)
            refused = await worker.train(token)
            monkeypatch.setattr("acestep_worker.wrapper.renew_gpu_hold", renew_gpu_hold)
            handover = await worker.client.post("/gpu_hold/handover", json={"token": token})
            assert await reserve_gpu_hold(
                worker.deps.redis, worker.deps.worker_id, token, _LOWERED_TTL_SECONDS
            )
            for _ in range(_TURNS_TO_WAIT):
                await asyncio.sleep(0)
            return refused.status_code, handover.json(), await worker.deps.redis.ttl(key)

    status_code, handover, ttl_seconds = asyncio.run(scenario())

    assert status_code == 409
    assert handover == {"claimed": False, "task_id": None}
    assert ttl_seconds <= _LOWERED_TTL_SECONDS

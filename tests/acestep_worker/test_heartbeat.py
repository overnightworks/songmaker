from __future__ import annotations

import asyncio
import json

import fakeredis.aioredis
import pytest

from acestep_worker.heartbeat import (
    DEFAULT_TTL_SECONDS,
    HeartbeatLoop,
    gpu_hold_key,
    queue_depth_key,
    worker_state_key,
)


def _run(coro):
    return asyncio.run(coro)


def _make_loop(provider=None, interval=0.05, ttl=2):
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)

    async def default_provider() -> dict[str, object]:
        return {"loaded": ["sft"], "queue_depth": 3}

    return HeartbeatLoop(
        redis=redis,
        worker_id="acestep-worker-0",
        state_provider=provider or default_provider,
        interval_seconds=interval,
        ttl_seconds=ttl,
    ), redis


def test_keys_helper() -> None:
    assert worker_state_key("a") == "songmaker:acestep:worker:a"
    assert queue_depth_key("b") == "songmaker:acestep:queue:b"


def test_publish_once_writes_to_redis() -> None:
    async def go():
        loop, redis = _make_loop()
        await loop.publish_once()
        raw = await redis.get(worker_state_key("acestep-worker-0"))
        ttl = await redis.ttl(worker_state_key("acestep-worker-0"))
        return raw, ttl

    raw, ttl = _run(go())
    assert raw is not None
    payload = json.loads(raw)
    assert payload["loaded"] == ["sft"]
    assert "last_heartbeat_at" in payload
    assert 0 < ttl <= 2


def test_publish_once_does_not_renew_a_gpu_hold() -> None:
    async def go() -> tuple[bytes | None, int]:
        loop, redis = _make_loop()
        hold_key = gpu_hold_key("acestep-worker-0")
        await redis.set(hold_key, "hold-token", ex=DEFAULT_TTL_SECONDS)
        await loop.publish_once()
        return await redis.get(hold_key), await redis.ttl(hold_key)

    assert _run(go()) == (b"hold-token", DEFAULT_TTL_SECONDS)


def test_clear_orphaned_queue() -> None:
    async def go():
        loop, redis = _make_loop()
        await redis.set(queue_depth_key("acestep-worker-0"), 7)
        await redis.set(gpu_hold_key("acestep-worker-0"), "hold-token")
        await loop.clear_orphaned_queue()
        return (
            await redis.get(queue_depth_key("acestep-worker-0")),
            await redis.get(gpu_hold_key("acestep-worker-0")),
        )

    assert _run(go()) == (None, None)


def test_start_stop_cycles() -> None:
    async def go():
        loop, redis = _make_loop(interval=0.05)
        loop.start()
        await asyncio.sleep(0.12)
        running = loop.is_running
        await loop.stop()
        not_running = loop.is_running
        raw = await redis.get(worker_state_key("acestep-worker-0"))
        return running, not_running, raw

    running, not_running, raw = _run(go())
    assert running
    assert not not_running
    assert raw is not None


def test_start_idempotent() -> None:
    async def go():
        loop, _ = _make_loop()
        loop.start()
        first_task = loop._task
        loop.start()
        second_task = loop._task
        await loop.stop()
        return first_task, second_task

    first, second = _run(go())
    assert first is second


def test_shutdown_deletes_state_key() -> None:
    async def go():
        loop, redis = _make_loop()
        await loop.publish_once()
        await loop.shutdown()
        return await redis.get(worker_state_key("acestep-worker-0"))

    assert _run(go()) is None


def test_publish_failure_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    async def go():
        async def bad_provider() -> dict[str, object]:
            raise RuntimeError("provider died")

        loop, _ = _make_loop(provider=bad_provider, interval=0.05)
        loop.start()
        await asyncio.sleep(0.08)
        await loop.stop()

    _run(go())
    assert any("Heartbeat publish failed" in r.message for r in caplog.records)


def test_stop_without_start_is_safe() -> None:
    async def go():
        loop, _ = _make_loop()
        await loop.stop()

    _run(go())


def test_stop_handles_externally_cancelled_task() -> None:
    async def go():
        loop, _ = _make_loop()
        loop.start()
        await asyncio.sleep(0)
        assert loop._task is not None
        loop._task.cancel()
        await loop.stop()

    _run(go())

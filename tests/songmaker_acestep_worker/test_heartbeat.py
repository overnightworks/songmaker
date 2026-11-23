from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import fakeredis
import fakeredis.aioredis
import pytest
from support.wrapper_deps import settled_fake_redis
from tandem import Liveness
from tandem.testing import aged_epoch

from songmaker_acestep_worker.heartbeat import (
    GPU_HOLD_LASTS,
    HeartbeatLoop,
    gpu_hold_locks,
    queue_depth_key,
    reserve_gpu_hold,
    worker_state_key,
)
from songmaker_cli.constants import REDIS_KEY_PREFIX


def _run(coro):
    return asyncio.run(coro)


def _make_loop(provider=None, interval=0.05, ttl=2):
    redis = settled_fake_redis()

    async def default_provider() -> dict[str, object]:
        return {"loaded": [{"mode": "sft", "size_gb": 0}], "queue_depth": 3}

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
    assert payload["loaded"] == [{"mode": "sft", "size_gb": 0}]
    assert "last_heartbeat_at" in payload
    assert 0 < ttl <= 2


def test_publish_once_does_not_renew_a_gpu_hold() -> None:
    async def go() -> tuple[str | None, timedelta | None]:
        loop, redis = _make_loop()
        await reserve_gpu_hold(redis, "acestep-worker-0")
        before = await gpu_hold_locks(redis).state("acestep-worker-0")
        await loop.publish_once()
        after = await gpu_hold_locks(redis).state("acestep-worker-0")
        assert before.remaining is not None
        assert after.remaining is not None
        return after.generation, before.remaining - after.remaining

    generation, renewed_by = _run(go())

    assert generation is not None
    assert renewed_by >= timedelta(0)
    assert renewed_by < GPU_HOLD_LASTS


def test_clear_orphaned_queue_ends_the_hold_of_a_previous_process() -> None:
    async def go():
        loop, redis = _make_loop()
        await redis.set(queue_depth_key("acestep-worker-0"), 7)
        previous_hold = await gpu_hold_locks(redis).acquire("acestep-worker-0")
        await loop.clear_orphaned_queue()
        return (
            previous_hold,
            await redis.get(queue_depth_key("acestep-worker-0")),
            await gpu_hold_locks(redis).state("acestep-worker-0"),
        )

    previous_hold, depth, hold = _run(go())

    assert previous_hold is not None
    assert depth is None
    assert hold.liveness is Liveness.GONE


class _ReplacingTheHoldAfterTheFirstScript(fakeredis.aioredis.FakeRedis):
    """A client whose hold is taken by another process once its first script has answered."""

    def __init__(self, *, server, replace_hold) -> None:
        super().__init__(server=server, decode_responses=False)
        self._replace_hold = replace_hold
        self._replaced = False

    async def evalsha(self, *args, **kwargs):
        reply = await super().evalsha(*args, **kwargs)
        if not self._replaced:
            self._replaced = True
            await self._replace_hold()
        return reply


def test_clear_orphaned_queue_leaves_a_hold_taken_after_its_state_read() -> None:
    worker_id = "acestep-worker-0"

    async def go():
        server = fakeredis.FakeServer()
        fakeredis.FakeRedis(server=server).set(*aged_epoch(key_prefix=REDIS_KEY_PREFIX))
        other = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
        previous = await gpu_hold_locks(other).acquire(worker_id)
        assert previous is not None
        replacement: list[str] = []

        async def replace_hold() -> None:
            assert await gpu_hold_locks(other).release(worker_id, previous)
            acquired = await gpu_hold_locks(other).acquire(worker_id)
            assert acquired is not None
            replacement.append(acquired)

        loop = HeartbeatLoop(
            redis=_ReplacingTheHoldAfterTheFirstScript(server=server, replace_hold=replace_hold),
            worker_id=worker_id,
            state_provider=_no_state,
        )
        await loop.clear_orphaned_queue()
        return replacement, await gpu_hold_locks(other).state(worker_id)

    replacement, hold = _run(go())

    assert hold.liveness is Liveness.ALIVE
    assert hold.generation == replacement[0]


async def _no_state() -> dict[str, object]:
    return {}


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


def test_stop_ends_cancelled_when_cancelled_while_waiting_for_the_loop() -> None:
    """defect:#1509 -- cancelling stop() while it waited for the loop was swallowed."""

    async def go():
        publishing = asyncio.Event()
        finish_publishing = asyncio.Event()

        async def slow_provider() -> dict[str, object]:
            publishing.set()
            await finish_publishing.wait()
            return {}

        loop, _ = _make_loop(provider=slow_provider)
        loop.start()
        await publishing.wait()
        stopping = asyncio.create_task(loop.stop())
        await asyncio.sleep(0)
        stopping.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopping
        finish_publishing.set()
        await loop.stop()
        return loop.is_running

    assert not _run(go())

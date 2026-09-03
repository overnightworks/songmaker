from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

log = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 5.0
DEFAULT_TTL_SECONDS = 15

WORKER_KEY_PREFIX = "songmaker:acestep:worker"
QUEUE_KEY_PREFIX = "songmaker:acestep:queue"
GPU_HOLD_KEY_PREFIX = "songmaker:acestep:hold"

ADMIT_GENERATION_SCRIPT = """
if redis.call('EXISTS', KEYS[2]) == 1 then return 0 end
redis.call('INCR', KEYS[1])
return 1
"""

RENEW_GPU_HOLD_SCRIPT = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
return redis.call('EXPIRE', KEYS[1], ARGV[2])
"""
RELEASE_GPU_HOLD_SCRIPT = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
return redis.call('DEL', KEYS[1])
"""
RESERVE_GPU_HOLD_SCRIPT = """
if redis.call('EXISTS', KEYS[2]) == 1 then return 0 end
local depth = redis.call('GET', KEYS[1])
if depth and tonumber(depth) > 0 then return 0 end
return redis.call('SET', KEYS[2], ARGV[1], 'EX', ARGV[2], 'NX') and 1 or 0
"""


def worker_state_key(worker_id: str) -> str:
    return f"{WORKER_KEY_PREFIX}:{worker_id}"


def queue_depth_key(worker_id: str) -> str:
    return f"{QUEUE_KEY_PREFIX}:{worker_id}"


def gpu_hold_key(worker_id: str) -> str:
    return f"{GPU_HOLD_KEY_PREFIX}:{worker_id}"


async def gpu_hold_matches(redis: Redis, worker_id: str, token: str) -> bool:
    return await redis.get(gpu_hold_key(worker_id)) == token.encode()


async def reserve_gpu_hold(redis: Redis, worker_id: str, token: str, ttl_seconds: int) -> bool:
    result = await redis.eval(
        RESERVE_GPU_HOLD_SCRIPT,
        2,
        queue_depth_key(worker_id),
        gpu_hold_key(worker_id),
        token,
        ttl_seconds,
    )
    return bool(result)


async def renew_gpu_hold(redis: Redis, worker_id: str, token: str, ttl_seconds: int) -> bool:
    result = await redis.eval(RENEW_GPU_HOLD_SCRIPT, 1, gpu_hold_key(worker_id), token, ttl_seconds)
    return bool(result)


async def release_gpu_hold(redis: Redis, worker_id: str, token: str) -> bool:
    result = await redis.eval(RELEASE_GPU_HOLD_SCRIPT, 1, gpu_hold_key(worker_id), token)
    return bool(result)


StateProvider = Callable[[], Awaitable[dict[str, Any]]]


class HeartbeatLoop:
    def __init__(
        self,
        *,
        redis: Redis,
        worker_id: str,
        state_provider: StateProvider,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._redis = redis
        self._worker_id = worker_id
        self._state_provider = state_provider
        self._interval = interval_seconds
        self._ttl = ttl_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def publish_once(self) -> None:
        state = await self._state_provider()
        state["last_heartbeat_at"] = datetime.now(timezone.utc).isoformat()
        key = worker_state_key(self._worker_id)
        await self._redis.set(key, json.dumps(state), ex=self._ttl)

    async def clear_orphaned_queue(self) -> None:
        await self._redis.delete(queue_depth_key(self._worker_id), gpu_hold_key(self._worker_id))

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.publish_once()
            except Exception:
                log.warning("Heartbeat publish failed", exc_info=True)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                continue

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def shutdown(self) -> None:
        await self.stop()
        await self._redis.delete(worker_state_key(self._worker_id))

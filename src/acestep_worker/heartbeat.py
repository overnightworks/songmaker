from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from redis.asyncio import Redis
from tandem import Liveness, Locks

from acestep_worker.child_tasks import settle_child_task

log = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 5.0
DEFAULT_TTL_SECONDS = 15

WORKER_KEY_PREFIX = "songmaker:acestep:worker"
QUEUE_KEY_PREFIX = "songmaker:acestep:queue"

GPU_HOLD_OLD_KEY_PREFIX = "songmaker:acestep:hold"
LOCK_KEY_PREFIX = "songmaker"
GPU_HOLD_FAMILY = "gpu"
GPU_HOLD_LASTS = timedelta(seconds=DEFAULT_TTL_SECONDS)


def worker_state_key(worker_id: str) -> str:
    return f"{WORKER_KEY_PREFIX}:{worker_id}"


def queue_depth_key(worker_id: str) -> str:
    return f"{QUEUE_KEY_PREFIX}:{worker_id}"


# Deletes the old hold key only while it still carries the generation the caller released.
RELEASE_OLD_GPU_HOLD_SCRIPT = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
return redis.call('DEL', KEYS[1])
"""


def gpu_hold_old_key(worker_id: str) -> str:
    """The key the previous release holds for a worker's GPU hold, kept beside the lock.

    Web, music worker and ACE-Step worker are separate deployments that do not restart together,
    so a process of the previous release reads only this key. The worker writes it with the hold
    and every reader of this release treats it as a hold too. Deleting the key's writes and
    reads ends the stage.
    """
    return f"{GPU_HOLD_OLD_KEY_PREFIX}:{worker_id}"


def gpu_hold_locks(redis: Redis) -> Locks:
    """The GPU holds of the workers, one lock per worker id.

    The web and music side builds the same family in ``songmaker_cli.acestep_state``.
    """
    return Locks(redis, key_prefix=LOCK_KEY_PREFIX, family=GPU_HOLD_FAMILY, lasts=GPU_HOLD_LASTS)


async def read_queue_depth(redis: Redis, worker_id: str) -> int:
    raw = await redis.get(queue_depth_key(worker_id))
    return int(raw) if raw is not None else 0


async def gpu_hold_matches(redis: Redis, worker_id: str, generation: str) -> bool:
    state = await gpu_hold_locks(redis).state(worker_id)
    return state.liveness is Liveness.ALIVE and state.generation == generation


async def gpu_hold_blocks_generation(redis: Redis, worker_id: str) -> bool:
    """Whether a hold, or a Redis restart that may have lost one, keeps a generation off the GPU."""
    state = await gpu_hold_locks(redis).state(worker_id)
    if state.liveness is not Liveness.GONE:
        return True
    return bool(await redis.exists(gpu_hold_old_key(worker_id)))


async def gpu_hold_remaining_seconds(redis: Redis, worker_id: str) -> int | None:
    state = await gpu_hold_locks(redis).state(worker_id)
    if state.liveness is not Liveness.ALIVE or state.remaining is None:
        return None
    return math.ceil(state.remaining.total_seconds())


async def reserve_gpu_hold(redis: Redis, worker_id: str) -> str | None:
    """The generation of a new hold, or None while a generation is queued or a hold is live.

    The depth is read again after ``acquire``: an admission that read the lock free before it
    has raised the depth by then, and one that comes after it reads the lock held. The old key
    is written before that second read, so an admission of the previous release, which reads
    only the old key, either sees it or has raised the depth by then.
    """
    if await read_queue_depth(redis, worker_id) > 0:
        return None
    generation = await gpu_hold_locks(redis).acquire(worker_id)
    if generation is None:
        return None
    await _write_old_gpu_hold(redis, worker_id, generation)
    if await read_queue_depth(redis, worker_id) > 0:
        await release_gpu_hold(redis, worker_id, generation)
        return None
    return generation


async def _write_old_gpu_hold(redis: Redis, worker_id: str, generation: str) -> None:
    await redis.set(
        gpu_hold_old_key(worker_id), generation, ex=int(GPU_HOLD_LASTS.total_seconds()),
    )


async def renew_gpu_hold(redis: Redis, worker_id: str, generation: str) -> bool:
    renewed = await gpu_hold_locks(redis).extend(worker_id, generation)
    if renewed:
        await _write_old_gpu_hold(redis, worker_id, generation)
    return renewed


async def _delete_old_gpu_hold_carrying(redis: Redis, worker_id: str, generation: str | bytes) -> None:
    await redis.eval(RELEASE_OLD_GPU_HOLD_SCRIPT, 1, gpu_hold_old_key(worker_id), generation)


async def release_gpu_hold(redis: Redis, worker_id: str, generation: str) -> bool:
    released = await gpu_hold_locks(redis).release(worker_id, generation)
    await _delete_old_gpu_hold_carrying(redis, worker_id, generation)
    return released


async def release_orphaned_gpu_hold(redis: Redis, worker_id: str) -> None:
    """End the hold a previous process of this worker left, with the generation it holds.

    Neither layout of the hold is ended by a replacement taken after the read: the lock by the
    generation read, the old key by the value read.
    """
    observed_old_key = await redis.get(gpu_hold_old_key(worker_id))
    state = await gpu_hold_locks(redis).state(worker_id)
    if state.liveness is Liveness.ALIVE and state.generation is not None:
        await release_gpu_hold(redis, worker_id, state.generation)
    elif observed_old_key is not None:
        await _delete_old_gpu_hold_carrying(redis, worker_id, observed_old_key)


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
        await self._redis.delete(queue_depth_key(self._worker_id))
        await release_orphaned_gpu_hold(self._redis, self._worker_id)

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
            await settle_child_task(self._task)
            self._task = None

    async def shutdown(self) -> None:
        await self.stop()
        await self._redis.delete(worker_state_key(self._worker_id))

"""Redis read/write helpers for ACE-Step worker ephemeral state.

Workers publish their loaded models, queue depth, and VRAM usage to Redis
with a 15s TTL via ``acestep_worker.heartbeat``. The web container reads
that state through these helpers when assembling the admin Worker Pool view.

The key prefixes here MUST stay in sync with ``acestep_worker.heartbeat``;
see ``tests/test_acestep_state.py`` for the cross-package assertion.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from arq.connections import ArqRedis

WORKER_KEY_PREFIX = "songmaker:acestep:worker"
QUEUE_KEY_PREFIX = "songmaker:acestep:queue"
GPU_HOLD_KEY_PREFIX = "songmaker:acestep:hold"
DOWNLOAD_KEY_PREFIX = "songmaker:acestep:download"
DOWNLOAD_TTL_SECONDS = 1800

ADMIT_GENERATION_SCRIPT = """
if redis.call('EXISTS', KEYS[2]) == 1 then return 0 end
redis.call('INCR', KEYS[1])
return 1
"""
RESERVE_GPU_HOLD_SCRIPT = """
if redis.call('EXISTS', KEYS[2]) == 1 then return 0 end
local depth = redis.call('GET', KEYS[1])
if depth and tonumber(depth) > 0 then return 0 end
return redis.call('SET', KEYS[2], ARGV[1], 'EX', ARGV[2], 'NX') and 1 or 0
"""
RENEW_GPU_HOLD_SCRIPT = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
return redis.call('EXPIRE', KEYS[1], ARGV[2])
"""
RELEASE_GPU_HOLD_SCRIPT = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
return redis.call('DEL', KEYS[1])
"""


def worker_state_key(worker_id: str) -> str:
    return f"{WORKER_KEY_PREFIX}:{worker_id}"


def queue_depth_key(worker_id: str) -> str:
    return f"{QUEUE_KEY_PREFIX}:{worker_id}"


def gpu_hold_key(worker_id: str) -> str:
    return f"{GPU_HOLD_KEY_PREFIX}:{worker_id}"


def download_key(mode: str) -> str:
    return f"{DOWNLOAD_KEY_PREFIX}:{mode}"


def decode_redis_text(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode()
    return raw


async def read_worker_state(pool: ArqRedis, worker_id: str) -> dict[str, Any] | None:
    raw = await pool.get(worker_state_key(worker_id))
    text = decode_redis_text(raw)
    if text is None:
        return None
    return json.loads(text)


def worker_is_online(state: Mapping[str, Any] | None) -> bool:
    """The one place that answers "does this worker take jobs right now?"

    A worker whose GPU has gone away (NVML present but unreachable — a
    driver/GPU mismatch, a vanished device) keeps heartbeating fine, so
    heartbeat presence alone is not enough (issue #367); it must also report
    ``gpu_healthy: true``. Fail-closed on purpose: a heartbeat missing the
    ``gpu_healthy`` key entirely — an old or broken worker build that never
    learned to publish it — counts as not online, never as a silent "assume
    fine forever". This is a single-host deployment where every container is
    rebuilt in one `docker compose up --build`; the mixed-version window a
    lenient default would have covered is seconds on the first deploy after
    this change, not an ongoing state worth trusting indefinitely.

    Every caller that decides "is this worker available" (``/health``,
    ``/metrics``, the scheduler's own worker picker, the generate/repaint/
    cover preflight, the admin worker pool and model registry) must go
    through this function, not re-read the heartbeat dict itself, so the
    definition of "online" cannot drift between them.
    """
    return state is not None and state.get("gpu_healthy") is True


async def read_queue_depth(pool: ArqRedis, worker_id: str) -> int:
    raw = await pool.get(queue_depth_key(worker_id))
    text = decode_redis_text(raw)
    return int(text) if text is not None else 0


async def incr_queue_depth(pool: ArqRedis, worker_id: str) -> int:
    return await pool.incr(queue_depth_key(worker_id))


async def decr_queue_depth(pool: ArqRedis, worker_id: str) -> int:
    return await pool.decr(queue_depth_key(worker_id))


async def admit_generation(pool: ArqRedis, worker_id: str) -> bool:
    result = await pool.eval(
        ADMIT_GENERATION_SCRIPT,
        2,
        queue_depth_key(worker_id),
        gpu_hold_key(worker_id),
    )
    return bool(result)


async def reserve_gpu_hold(
    pool: ArqRedis,
    worker_id: str,
    token: str,
    ttl_seconds: int,
) -> bool:
    result = await pool.eval(
        RESERVE_GPU_HOLD_SCRIPT,
        2,
        queue_depth_key(worker_id),
        gpu_hold_key(worker_id),
        token,
        ttl_seconds,
    )
    return bool(result)


async def renew_gpu_hold(
    pool: ArqRedis,
    worker_id: str,
    token: str,
    ttl_seconds: int,
) -> bool:
    result = await pool.eval(
        RENEW_GPU_HOLD_SCRIPT,
        1,
        gpu_hold_key(worker_id),
        token,
        ttl_seconds,
    )
    return bool(result)


async def release_gpu_hold(pool: ArqRedis, worker_id: str, token: str) -> bool:
    result = await pool.eval(RELEASE_GPU_HOLD_SCRIPT, 1, gpu_hold_key(worker_id), token)
    return bool(result)


async def list_worker_states(
    pool: ArqRedis,
    worker_ids: list[str],
) -> dict[str, dict[str, Any] | None]:
    return {wid: await read_worker_state(pool, wid) for wid in worker_ids}


async def set_download_in_progress(pool: ArqRedis, mode: str, job_id: str) -> bool:
    result = await pool.set(
        download_key(mode),
        job_id,
        ex=DOWNLOAD_TTL_SECONDS,
        nx=True,
    )
    return bool(result)


async def clear_download_in_progress(pool: ArqRedis, mode: str) -> None:
    await pool.delete(download_key(mode))


async def read_download_in_progress(pool: ArqRedis, mode: str) -> str | None:
    raw = await pool.get(download_key(mode))
    return decode_redis_text(raw)

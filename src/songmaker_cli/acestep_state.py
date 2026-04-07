"""Redis read/write helpers for ACE-Step worker ephemeral state.

Workers publish their loaded models, queue depth, and VRAM usage to Redis
with a 15s TTL via ``acestep_worker.heartbeat``. The web container reads
that state through these helpers when assembling the admin Worker Pool view.

The key prefixes here MUST stay in sync with ``acestep_worker.heartbeat``;
see ``tests/test_acestep_state.py`` for the cross-package assertion.
"""

from __future__ import annotations

import json
from typing import Any

from arq.connections import ArqRedis

WORKER_KEY_PREFIX = "songmaker:acestep:worker"
QUEUE_KEY_PREFIX = "songmaker:acestep:queue"


def worker_state_key(worker_id: str) -> str:
    return f"{WORKER_KEY_PREFIX}:{worker_id}"


def queue_depth_key(worker_id: str) -> str:
    return f"{QUEUE_KEY_PREFIX}:{worker_id}"


def _decode(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode()
    return raw


async def read_worker_state(pool: ArqRedis, worker_id: str) -> dict[str, Any] | None:
    raw = await pool.get(worker_state_key(worker_id))
    text = _decode(raw)
    if text is None:
        return None
    return json.loads(text)


async def read_queue_depth(pool: ArqRedis, worker_id: str) -> int:
    raw = await pool.get(queue_depth_key(worker_id))
    text = _decode(raw)
    return int(text) if text is not None else 0


async def incr_queue_depth(pool: ArqRedis, worker_id: str) -> int:
    return await pool.incr(queue_depth_key(worker_id))


async def decr_queue_depth(pool: ArqRedis, worker_id: str) -> int:
    return await pool.decr(queue_depth_key(worker_id))


async def list_worker_states(
    pool: ArqRedis, worker_ids: list[str],
) -> dict[str, dict[str, Any] | None]:
    return {wid: await read_worker_state(pool, wid) for wid in worker_ids}

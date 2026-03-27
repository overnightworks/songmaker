"""arq connection pool — singleton for the API server side.

Provides a lazily-initialized ArqRedis pool for enqueuing jobs, plus
helper functions for reading worker health/metrics from Redis.
"""

from __future__ import annotations

import os

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from songmaker_cli.constants import (
    ACTIVE_MODEL_REDIS_KEY,
    ARQ_HEALTH_KEY_PATTERN,
    ARQ_QUEUE_KEY,
)

_pool: ArqRedis | None = None


async def get_arq_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(
            RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        )
    return _pool


async def close_arq_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def get_queue_depth() -> int:
    try:
        pool = await get_arq_pool()
        return await pool.zcard(ARQ_QUEUE_KEY)
    except Exception:
        return 0


async def is_worker_healthy() -> bool:
    try:
        pool = await get_arq_pool()
        keys = await pool.keys(ARQ_HEALTH_KEY_PATTERN)
        return len(keys) > 0
    except Exception:
        return False


async def get_active_model() -> str | None:
    try:
        pool = await get_arq_pool()
        value = await pool.get(ACTIVE_MODEL_REDIS_KEY)
        return value.decode() if value else None
    except Exception:
        return None

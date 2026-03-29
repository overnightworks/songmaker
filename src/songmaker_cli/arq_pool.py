"""arq connection pool — singleton for the API server side.

Initialized eagerly during app lifespan via ``init_arq_pool``.
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


async def init_arq_pool() -> ArqRedis:
    """Create the pool once during app startup. Not safe to call concurrently."""
    global _pool
    _pool = await create_pool(
        RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    )
    return _pool


def get_arq_pool() -> ArqRedis:
    """Return the pool created by ``init_arq_pool``. Raises if not initialized."""
    if _pool is None:
        raise RuntimeError("arq pool not initialized — call init_arq_pool() during startup")
    return _pool


async def close_arq_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def get_queue_depth() -> int:
    try:
        return await get_arq_pool().zcard(ARQ_QUEUE_KEY)
    except Exception:
        return 0


async def is_worker_healthy() -> bool:
    try:
        keys = await get_arq_pool().keys(ARQ_HEALTH_KEY_PATTERN)
        return len(keys) > 0
    except Exception:
        return False


async def get_active_model() -> str | None:
    try:
        value = await get_arq_pool().get(ACTIVE_MODEL_REDIS_KEY)
        return value.decode() if value else None
    except Exception:
        return None

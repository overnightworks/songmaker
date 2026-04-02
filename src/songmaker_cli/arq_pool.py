"""arq connection pool — singleton for the API server side.

Initialized eagerly during app lifespan via ``init_arq_pool``.
"""

from __future__ import annotations

import os
import threading

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from songmaker_cli.constants import (
    ACTIVE_MODEL_REDIS_KEY,
    ARQ_HEALTH_KEY,
    ARQ_MUSIC_HEALTH_KEY,
    ARQ_MUSIC_QUEUE_NAME,
    ARQ_QUEUE_KEY,
    ARQ_SCORING_HEALTH_KEY,
    ARQ_SCORING_QUEUE_NAME,
)

_pool: ArqRedis | None = None
_pool_lock = threading.Lock()


async def init_arq_pool() -> ArqRedis:
    global _pool
    pool = await create_pool(
        RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    )
    with _pool_lock:
        _pool = pool
    return pool


def get_arq_pool() -> ArqRedis:
    with _pool_lock:
        if _pool is None:
            raise RuntimeError("arq pool not initialized — call init_arq_pool() during startup")
        return _pool


async def close_arq_pool() -> None:
    global _pool
    with _pool_lock:
        pool = _pool
        _pool = None
    if pool is not None:
        await pool.aclose()


async def get_queue_depth() -> int:
    try:
        return await get_arq_pool().zcard(ARQ_QUEUE_KEY)
    except Exception:
        return 0


async def is_worker_healthy() -> bool:
    try:
        return await get_arq_pool().exists(ARQ_HEALTH_KEY) > 0
    except Exception:
        return False


async def is_music_worker_healthy() -> bool:
    try:
        return await get_arq_pool().exists(ARQ_MUSIC_HEALTH_KEY) > 0
    except Exception:
        return False


async def is_scoring_worker_healthy() -> bool:
    try:
        return await get_arq_pool().exists(ARQ_SCORING_HEALTH_KEY) > 0
    except Exception:
        return False


async def get_music_queue_depth() -> int:
    try:
        return await get_arq_pool().zcard(ARQ_MUSIC_QUEUE_NAME)
    except Exception:
        return 0


async def get_scoring_queue_depth() -> int:
    try:
        return await get_arq_pool().zcard(ARQ_SCORING_QUEUE_NAME)
    except Exception:
        return 0


async def get_active_model() -> str | None:
    try:
        value = await get_arq_pool().get(ACTIVE_MODEL_REDIS_KEY)
        return value.decode() if value else None
    except Exception:
        return None

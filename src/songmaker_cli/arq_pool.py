"""arq connection pool — singleton for the API server side.

Initialized eagerly during app lifespan via ``init_arq_pool``.
"""

from __future__ import annotations

import threading

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from songmaker_cli.constants import (
    ARQ_MUSIC_HEALTH_KEY,
    ARQ_MUSIC_QUEUE_NAME,
    ARQ_SCORING_HEALTH_KEY,
    ARQ_SCORING_QUEUE_NAME,
)
from songmaker_cli.settings import get_settings

_pool: ArqRedis | None = None
_pool_lock = threading.Lock()


async def init_arq_pool() -> ArqRedis:
    global _pool
    pool = await create_pool(
        RedisSettings.from_dsn(get_settings().redis_url)
    )
    with _pool_lock:
        _pool = pool
    return pool


def get_arq_pool() -> ArqRedis:
    with _pool_lock:
        if _pool is None:
            raise RuntimeError("arq pool not initialized — call init_arq_pool() during startup")
        return _pool


def get_arq_pool_dep() -> ArqRedis:
    return get_arq_pool()


async def close_arq_pool() -> None:
    global _pool
    with _pool_lock:
        pool = _pool
        _pool = None
    if pool is not None:
        await pool.aclose()


async def is_music_worker_healthy() -> bool:
    try:
        return await get_arq_pool().exists(ARQ_MUSIC_HEALTH_KEY) > 0
    except Exception:
        return False


async def is_scoring_worker_healthy(pool: ArqRedis | None = None) -> bool:
    """Check the scoring worker's heartbeat key.

    ``pool`` defaults to this process's own singleton (the web process,
    where every existing caller runs). A caller running outside that
    process — the music worker, dispatching an auto-score job right after a
    generation completes — has no singleton to fall back to and must pass
    its own arq redis connection explicitly.
    """
    try:
        redis = pool if pool is not None else get_arq_pool()
        return await redis.exists(ARQ_SCORING_HEALTH_KEY) > 0
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



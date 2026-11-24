"""arq connection pool — singleton for the API server side.

Initialized eagerly during app lifespan via ``init_arq_pool``.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from redis.asyncio import Redis

from songmaker_cli.arq_codec import deserialize_arq, serialize_arq
from songmaker_cli.job_types import WorkerLivenessSignal
from songmaker_cli.redis_client import build_arq_redis_settings
from songmaker_cli.settings import get_settings
from songmaker_cli.worker_liveness import worker_kind_leases

if TYPE_CHECKING:
    from arq.connections import ArqRedis

_pool: ArqRedis | None = None
_pool_lock = threading.Lock()


async def init_arq_pool() -> ArqRedis:
    from arq import create_pool

    global _pool
    pool = await create_pool(
        build_arq_redis_settings(get_settings().redis_url),
        job_serializer=serialize_arq,
        job_deserializer=deserialize_arq,
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


async def _kind_has_a_live_holder(kind: WorkerLivenessSignal, pool: Redis | None) -> bool:
    try:
        redis = pool if pool is not None else get_arq_pool()
        roster = await worker_kind_leases(redis, kind).live()
    except Exception:
        return False
    return bool(roster.holders)


async def is_music_worker_healthy() -> bool:
    """Whether a music worker holds a live lease of its kind; any failed read says no."""
    return await _kind_has_a_live_holder(WorkerLivenessSignal.MUSIC, None)


async def is_scoring_worker_healthy(pool: Redis | None = None) -> bool:
    """Whether a scoring worker holds a live lease of its kind; any failed read says no.

    ``pool`` defaults to this process's own singleton (the web process,
    where every existing caller runs). A caller running outside that
    process — the music worker, dispatching an auto-score job right after a
    generation completes — has no singleton to fall back to and must pass
    its own Redis client explicitly.
    """
    return await _kind_has_a_live_holder(WorkerLivenessSignal.SCORING, pool)

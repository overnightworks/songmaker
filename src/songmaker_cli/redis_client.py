"""Redis client utilities — connection, health, stream slots, and metrics."""

from __future__ import annotations

import asyncio
import logging
import math
import socket
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic_settings import BaseSettings, SettingsConfigDict

from songmaker_cli.constants import (
    REDIS_METRICS_DURATION_KEY,
    REDIS_METRICS_HTTP_KEY,
    REDIS_METRICS_TOTAL_KEY,
    REDIS_SOCKET_TIMEOUT_SECONDS,
    REDIS_STARTUP_ERROR,
    STORE_STARTUP_RETRY_DELAY_SECONDS,
    STORE_STARTUP_WAIT_SECONDS,
)

if TYPE_CHECKING:
    from arq.connections import RedisSettings
    from redis import Redis
    from redis.asyncio import Redis as AsyncRedis
    from tandem import Slots

log = logging.getLogger(__name__)

_ASYNC_REDIS_RETRY_ATTEMPTS = 3
# A half-open connection of the wake follower is dropped after about 30 + 3 * 10 seconds.
_WAKE_KEEPALIVE_OPTIONS = {
    socket.TCP_KEEPIDLE: 30,
    socket.TCP_KEEPINTVL: 10,
    socket.TCP_KEEPCNT: 3,
}
GLOBAL_SLOT_POOL = "global"


class RedisConnectionSettings(BaseSettings):
    """The one setting every Redis connection needs.

    Processes that must not require the app's other settings or secrets (the
    worker healthcheck) read the URL through this type; ``REDIS_URL`` has no
    default.
    """

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    redis_url: str


def create_redis(url: str) -> Redis:
    from redis import Redis as RedisClient

    return RedisClient.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
        socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
    )


def create_async_redis(url: str, *, follows_wakes: bool = False) -> AsyncRedis:
    """The asyncio client tandem needs.

    Its retry rides out a Redis restart and replays a command whose reply a lost
    connection took (redis-py 5.x retries only the errors named in ``retry_on_error``);
    its timeouts bound a silent one.

    ``follows_wakes`` makes a client that only follows the wake channel: its blocking read of
    the subscription has no ``socket_timeout``, which would end every quiet interval and make
    tandem subscribe again. TCP keepalive finds a dead connection instead.
    """
    from redis.asyncio import Redis as AsyncRedisClient
    from redis.asyncio.retry import Retry
    from redis.backoff import ExponentialBackoff
    from redis.exceptions import ConnectionError, TimeoutError

    return AsyncRedisClient.from_url(
        url,
        retry=Retry(ExponentialBackoff(), _ASYNC_REDIS_RETRY_ATTEMPTS),
        retry_on_error=[ConnectionError, TimeoutError],
        socket_connect_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
        socket_timeout=None if follows_wakes else REDIS_SOCKET_TIMEOUT_SECONDS,
        socket_keepalive=follows_wakes,
        socket_keepalive_options=_WAKE_KEEPALIVE_OPTIONS if follows_wakes else None,
    )


def build_arq_redis_settings(url: str) -> RedisSettings:
    """arq's pool-creation retry covers at least ``STORE_STARTUP_WAIT_SECONDS``."""
    from arq.connections import RedisSettings

    settings = RedisSettings.from_dsn(url)
    settings.conn_retry_delay = STORE_STARTUP_RETRY_DELAY_SECONDS
    settings.conn_retries = math.ceil(
        STORE_STARTUP_WAIT_SECONDS / STORE_STARTUP_RETRY_DELAY_SECONDS,
    )
    return settings


def redis_health(r: Redis) -> bool:
    try:
        return r.ping()
    except Exception:
        return False


def wait_for_redis(
    r: Redis,
    shown_url: str,
    *,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Block until Redis answers a ping; raise ``RuntimeError`` after the bound.

    ``shown_url`` is the credential-free address used in log and error text.
    """
    from redis.exceptions import AuthenticationError, ConnectionError, TimeoutError

    log.info("Waiting up to %ss for Redis at %s", STORE_STARTUP_WAIT_SECONDS, shown_url)
    deadline = now() + STORE_STARTUP_WAIT_SECONDS
    while True:
        try:
            r.ping()
        except AuthenticationError:
            raise
        except (ConnectionError, TimeoutError) as error:
            # Retried: refused, unresolved or timed-out connections. An authentication
            # error is a ConnectionError subclass but a wait cannot fix it.
            if now() >= deadline:
                raise RuntimeError(REDIS_STARTUP_ERROR.format(url=shown_url)) from error
            sleep(STORE_STARTUP_RETRY_DELAY_SECONDS)
        else:
            log.info("Redis answers at %s", shown_url)
            return


async def take_stream_slot(
    slots: Slots, user_id: str, per_person_cap: int, global_cap: int,
) -> str | None:
    """Hold one slot in the person's pool and in the global pool, or in neither.

    Returns the token for ``SlotReleases.release_in_background``, or None when a pool is at its cap.
    """
    return await slots.take({GLOBAL_SLOT_POOL: global_cap, f"person:{user_id}": per_person_cap})


async def _release_slot(slots: Slots, token: str, *, subject: str) -> None:
    try:
        released = await slots.release(token)
    except Exception:
        log.warning("%s hold release failed", subject)
        return
    if not released:
        log.warning("%s hold had already ended at its release", subject)


class SlotReleases:
    """The background slot releases of one application, awaited before its event loop closes."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    def release_in_background(self, slots: Slots, token: str, *, subject: str) -> None:
        task = asyncio.create_task(_release_slot(slots, token, subject=subject))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        while self._tasks:
            pending = tuple(self._tasks)
            await asyncio.gather(*pending)
            self._tasks.difference_update(pending)


class RedisHttpMetrics:
    """HTTP request metrics backed by Redis hashes."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def record(self, method: str, status_code: int, duration_ms: float) -> None:
        field = f"{method} {status_code}"
        pipe = self._redis.pipeline()
        pipe.hincrby(REDIS_METRICS_HTTP_KEY, field, 1)
        pipe.hincrbyfloat(REDIS_METRICS_DURATION_KEY, "duration_ms", duration_ms)
        pipe.hincrby(REDIS_METRICS_TOTAL_KEY, "total", 1)
        pipe.execute()

    def snapshot(self) -> dict:
        pipe = self._redis.pipeline()
        pipe.hgetall(REDIS_METRICS_HTTP_KEY)
        pipe.hget(REDIS_METRICS_DURATION_KEY, "duration_ms")
        pipe.hget(REDIS_METRICS_TOTAL_KEY, "total")
        counts_raw, duration_raw, total_raw = pipe.execute()

        counts = {k: int(v) for k, v in sorted(counts_raw.items())} if counts_raw else {}
        total = int(total_raw) if total_raw else 0
        duration = float(duration_raw) if duration_raw else 0.0

        return {
            "http_requests_total": counts,
            "http_requests_count": total,
            "http_request_duration_total_ms": round(duration, 1),
        }

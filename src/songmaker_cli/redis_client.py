"""Redis client utilities — connection, health, rate limiting, metrics, and session cache."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

from songmaker_cli.constants import (
    REDIS_METRICS_DURATION_KEY,
    REDIS_METRICS_HTTP_KEY,
    REDIS_METRICS_TOTAL_KEY,
    REDIS_SESSION_PREFIX,
    REDIS_SOCKET_TIMEOUT_SECONDS,
    REDIS_USER_SESSIONS_PREFIX,
)

if TYPE_CHECKING:
    from redis import Redis


def create_redis(url: str) -> Redis:
    from redis import Redis as RedisClient

    return RedisClient.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
        socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
    )


def redis_health(r: Redis) -> bool:
    try:
        return r.ping()
    except Exception:
        return False


class RedisRateLimiter:
    """Sliding-window rate limiter backed by Redis sorted sets."""

    def __init__(
        self, redis: Redis, prefix: str, max_requests: int, window_seconds: int,
    ) -> None:
        self._redis = redis
        self._prefix = prefix
        self._max = max_requests
        self._window = window_seconds

    _LUA_SLIDING_WINDOW = """
    local key = KEYS[1]
    local now = tonumber(ARGV[1])
    local window = tonumber(ARGV[2])
    local max_requests = tonumber(ARGV[3])
    local member = ARGV[4]
    redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
    local count = redis.call('ZCARD', key)
    if count >= max_requests then return count + 1 end
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, window)
    return count + 1
    """

    def is_allowed(self, ip: str) -> bool:
        now = time.time()
        key = f"{self._prefix}:{ip}"
        count = self._redis.eval(
            self._LUA_SLIDING_WINDOW,
            1,
            key,
            now,
            self._window,
            self._max,
            uuid.uuid4().hex,
        )
        return count <= self._max


class RedisConcurrentLeaseLimiter:
    """Atomic expiring per-scope and global concurrency leases."""

    _LUA_ACQUIRE = """
    local redis_time = redis.call('TIME')
    local now = tonumber(redis_time[1]) + (tonumber(redis_time[2]) / 1000000)
    local lease_seconds = tonumber(ARGV[1])
    local scope_max = tonumber(ARGV[2])
    local global_max = tonumber(ARGV[3])
    local token = ARGV[4]
    local expires_at = now + lease_seconds

    redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
    redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now)
    if redis.call('ZCARD', KEYS[1]) >= scope_max then return 0 end
    if redis.call('ZCARD', KEYS[2]) >= global_max then return 0 end

    redis.call('ZADD', KEYS[1], expires_at, token)
    redis.call('ZADD', KEYS[2], expires_at, token)
    redis.call('EXPIRE', KEYS[1], math.ceil(lease_seconds) + 1)
    redis.call('EXPIRE', KEYS[2], math.ceil(lease_seconds) + 1)
    return 1
    """

    _LUA_RELEASE = """
    redis.call('ZREM', KEYS[1], ARGV[1])
    redis.call('ZREM', KEYS[2], ARGV[1])
    return 1
    """

    def __init__(
        self,
        redis: Redis,
        *,
        scope_prefix: str,
        global_key: str,
        max_per_scope: int,
        max_global: int,
        lease_seconds: int,
    ) -> None:
        self._redis = redis
        self._scope_prefix = scope_prefix
        self._global_key = global_key
        self._max_per_scope = max_per_scope
        self._max_global = max_global
        self._lease_seconds = lease_seconds

    def _scope_key(self, scope_id: str) -> str:
        return f"{self._scope_prefix}:{scope_id}"

    def acquire(self, scope_id: str) -> str | None:
        token = uuid.uuid4().hex
        acquired = self._redis.eval(
            self._LUA_ACQUIRE,
            2,
            self._scope_key(scope_id),
            self._global_key,
            self._lease_seconds,
            self._max_per_scope,
            self._max_global,
            token,
        )
        return token if acquired == 1 else None

    def release(self, scope_id: str, token: str) -> None:
        self._redis.eval(
            self._LUA_RELEASE,
            2,
            self._scope_key(scope_id),
            self._global_key,
            token,
        )


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


class CachedSessionData(BaseModel):
    """Structured session payload stored in Redis."""

    user_id: str
    username: str
    role: str
    is_active: bool
    ip_address: str
    user_agent: str
    expires_at: datetime
    created_at: datetime


class SessionCache:
    """Redis-backed session cache — reduces per-request DB writes."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._failure_lock = threading.Lock()
        self._consecutive_failures: int = 0

    @property
    def consecutive_failures(self) -> int:
        with self._failure_lock:
            return self._consecutive_failures

    def _record_success(self) -> None:
        with self._failure_lock:
            self._consecutive_failures = 0

    def _record_failure(self) -> None:
        with self._failure_lock:
            self._consecutive_failures += 1

    def _session_key(self, session_id: str) -> str:
        return f"{REDIS_SESSION_PREFIX}:{session_id}"

    def _user_sessions_key(self, user_id: str) -> str:
        return f"{REDIS_USER_SESSIONS_PREFIX}:{user_id}"

    def store(
        self,
        session_id: str,
        user_id: str,
        username: str,
        role: str,
        is_active: bool,
        ip_address: str,
        user_agent: str,
        expires_at: datetime,
        created_at: datetime,
        max_age_seconds: int,
    ) -> None:
        data = CachedSessionData(
            user_id=user_id, username=username, role=role, is_active=is_active,
            ip_address=ip_address, user_agent=user_agent,
            expires_at=expires_at, created_at=created_at,
        )
        pipe = self._redis.pipeline()
        pipe.set(self._session_key(session_id), data.model_dump_json(), ex=max_age_seconds)
        pipe.sadd(self._user_sessions_key(user_id), session_id)
        pipe.execute()

    def get(self, session_id: str) -> CachedSessionData | None:
        try:
            raw = self._redis.get(self._session_key(session_id))
        except Exception:
            self._record_failure()
            raise
        self._record_success()
        if raw is None:
            return None
        return CachedSessionData.model_validate_json(raw)

    def refresh_ttl(self, session_id: str, max_age_seconds: int) -> None:
        self._redis.expire(self._session_key(session_id), max_age_seconds)

    _LUA_UPDATE_IP_UA = """
    local key = KEYS[1]
    local ip = ARGV[1]
    local ua = ARGV[2]
    local raw = redis.call('GET', key)
    if not raw then return 0 end
    local ttl = redis.call('TTL', key)
    if ttl <= 0 then return 0 end
    local data = cjson.decode(raw)
    data['ip_address'] = ip
    data['user_agent'] = ua
    redis.call('SET', key, cjson.encode(data), 'EX', ttl)
    return 1
    """

    def update_ip_ua(self, session_id: str, ip_address: str, user_agent: str) -> None:
        key = self._session_key(session_id)
        self._redis.eval(self._LUA_UPDATE_IP_UA, 1, key, ip_address, user_agent)

    def delete(self, session_id: str, user_id: str) -> None:
        pipe = self._redis.pipeline()
        pipe.delete(self._session_key(session_id))
        pipe.srem(self._user_sessions_key(user_id), session_id)
        pipe.execute()

    def delete_user_sessions(self, user_id: str) -> list[str]:
        user_key = self._user_sessions_key(user_id)
        session_ids = list(self._redis.smembers(user_key))
        if session_ids:
            pipe = self._redis.pipeline()
            for sid in session_ids:
                pipe.delete(self._session_key(sid))
            pipe.delete(user_key)
            pipe.execute()
        return session_ids

    def get_all_sessions(self) -> list[tuple[str, int]]:
        prefix = f"{REDIS_SESSION_PREFIX}:"
        all_keys: list[str] = []
        cursor = 0
        while True:
            cursor, keys = self._redis.scan(cursor, match=f"{prefix}*", count=100)
            all_keys.extend(keys)
            if cursor == 0:
                break
        if not all_keys:
            return []
        pipe = self._redis.pipeline()
        for key in all_keys:
            pipe.ttl(key)
        ttls = pipe.execute()
        result = []
        for key, ttl in zip(all_keys, ttls):
            if ttl > 0:
                session_id = key[len(prefix):]
                result.append((session_id, ttl))
        return result

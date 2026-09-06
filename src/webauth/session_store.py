"""The Redis session cache — Redis owns expiry, the database keeps a copy."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel

if TYPE_CHECKING:
    from redis import Redis
    from starlette.applications import Starlette

    from webauth.config import SessionKeyPrefixes

SESSION_CACHE_STATE_ATTRIBUTE: Final = "session_cache"


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

    def __init__(self, redis: Redis, prefixes: SessionKeyPrefixes) -> None:
        self._redis = redis
        self._prefixes = prefixes
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
        return f"{self._prefixes.session}:{session_id}"

    def _user_sessions_key(self, user_id: str) -> str:
        return f"{self._prefixes.user_sessions}:{user_id}"

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
        prefix = f"{self._prefixes.session}:"
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


def install_session_cache(app: Starlette, cache: SessionCache) -> None:
    """Publish ``cache`` on ``app`` so every request can reach it."""
    setattr(app.state, SESSION_CACHE_STATE_ATTRIBUTE, cache)


def installed_session_cache(app: Starlette) -> SessionCache | None:
    """The cache ``app`` was started with, or None when it runs without one.

    Absence is not an error: every reader falls back to the database, which
    stays authoritative for who a session belongs to.
    """
    return getattr(app.state, SESSION_CACHE_STATE_ATTRIBUTE, None)

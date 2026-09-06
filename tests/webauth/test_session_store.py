"""The Redis session cache: what it stores, refreshes, and forgets."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import fakeredis
import pytest

from webauth.config import SessionKeyPrefixes
from webauth.session_store import SessionCache

_PREFIXES = SessionKeyPrefixes(session="app:session", user_sessions="app:user_sessions")


@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


class TestSessionCache:
    def _make_cache(self, fake_redis) -> SessionCache:
        return SessionCache(fake_redis, _PREFIXES)

    def _store_sample(
        self, cache: SessionCache, session_id: str = "sess1",
        user_id: str = "user1", username: str = "alice",
    ) -> None:
        now = datetime.now(timezone.utc)
        cache.store(
            session_id, user_id, username, "user", True,
            "1.2.3.4", "TestBrowser/1.0",
            now + timedelta(days=30), now, 86400,
        )

    def test_store_and_get(self, fake_redis) -> None:
        cache = self._make_cache(fake_redis)
        self._store_sample(cache)
        data = cache.get("sess1")
        assert data is not None
        assert data.user_id == "user1"
        assert data.username == "alice"
        assert data.role == "user"
        assert data.is_active is True
        assert data.ip_address == "1.2.3.4"

    def test_get_missing_returns_none(self, fake_redis) -> None:
        cache = self._make_cache(fake_redis)
        assert cache.get("nonexistent") is None

    def test_store_adds_to_user_sessions_set(self, fake_redis) -> None:
        cache = self._make_cache(fake_redis)
        self._store_sample(cache)
        members = fake_redis.smembers(f"{_PREFIXES.user_sessions}:user1")
        assert "sess1" in members

    def test_store_sets_expiry(self, fake_redis) -> None:
        cache = self._make_cache(fake_redis)
        self._store_sample(cache)
        ttl = fake_redis.ttl(f"{_PREFIXES.session}:sess1")
        assert 0 < ttl <= 86400

    def test_refresh_ttl(self, fake_redis) -> None:
        cache = self._make_cache(fake_redis)
        self._store_sample(cache)
        cache.refresh_ttl("sess1", 999)
        ttl = fake_redis.ttl(f"{_PREFIXES.session}:sess1")
        assert 0 < ttl <= 999

    def test_update_ip_ua(self, fake_redis) -> None:
        cache = self._make_cache(fake_redis)
        self._store_sample(cache)
        cache.update_ip_ua("sess1", "5.6.7.8", "NewBrowser/2.0")
        data = cache.get("sess1")
        assert data.ip_address == "5.6.7.8"
        assert data.user_agent == "NewBrowser/2.0"

    def test_update_ip_ua_missing_session_noop(self, fake_redis) -> None:
        cache = self._make_cache(fake_redis)
        cache.update_ip_ua("nonexistent", "5.6.7.8", "NewBrowser/2.0")

    def test_delete(self, fake_redis) -> None:
        cache = self._make_cache(fake_redis)
        self._store_sample(cache)
        cache.delete("sess1", "user1")
        assert cache.get("sess1") is None
        members = fake_redis.smembers(f"{_PREFIXES.user_sessions}:user1")
        assert "sess1" not in members

    def test_delete_user_sessions(self, fake_redis) -> None:
        cache = self._make_cache(fake_redis)
        self._store_sample(cache, session_id="s1", user_id="u1")
        self._store_sample(cache, session_id="s2", user_id="u1")
        self._store_sample(cache, session_id="s3", user_id="u2")
        deleted = cache.delete_user_sessions("u1")
        assert set(deleted) == {"s1", "s2"}
        assert cache.get("s1") is None
        assert cache.get("s2") is None
        assert cache.get("s3") is not None

    def test_get_all_sessions(self, fake_redis) -> None:
        cache = self._make_cache(fake_redis)
        self._store_sample(cache, session_id="s1")
        self._store_sample(cache, session_id="s2")
        result = cache.get_all_sessions()
        session_ids = {sid for sid, _ in result}
        assert "s1" in session_ids
        assert "s2" in session_ids
        for _, ttl in result:
            assert ttl > 0

    def test_raises_on_redis_failure(self) -> None:
        broken = MagicMock()
        broken.get.side_effect = ConnectionError("down")
        cache = SessionCache(broken, _PREFIXES)
        with pytest.raises(ConnectionError):
            cache.get("sess1")

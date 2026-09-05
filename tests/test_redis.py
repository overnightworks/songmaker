"""Tests for Redis client, rate limiter, and metrics."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import fakeredis
import pytest
from conftest import TEST_SECRET
from fastapi.testclient import TestClient

from songmaker_cli.app_context import AppContext
from songmaker_cli.auth import hash_password
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import User
from songmaker_cli.redis_client import (
    RedisHttpMetrics,
    RedisRateLimiter,
    SessionCache,
    create_redis,
    redis_health,
)
from songmaker_cli.server import create_app


@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


# ── create_redis / redis_health ─────────────────────────────────


def test_redis_health_returns_true(fake_redis) -> None:
    assert redis_health(fake_redis) is True


def test_redis_health_returns_false_on_error() -> None:
    broken = MagicMock()
    broken.ping.side_effect = ConnectionError("down")
    assert redis_health(broken) is False


def test_create_redis_returns_client() -> None:
    r = create_redis("redis://localhost:6379/0")
    assert r is not None
    assert r.connection_pool.connection_kwargs["socket_connect_timeout"] == 2.0
    assert r.connection_pool.connection_kwargs["socket_timeout"] == 2.0


# ── RedisRateLimiter ─────────────────────────────────────────────


class TestRedisRateLimiter:
    def test_allows_within_limit(self, fake_redis) -> None:
        limiter = RedisRateLimiter(fake_redis, "rl:test", max_requests=3, window_seconds=60)
        assert limiter.is_allowed("10.0.0.1") is True
        assert limiter.is_allowed("10.0.0.1") is True
        assert limiter.is_allowed("10.0.0.1") is True

    def test_blocks_over_limit(self, fake_redis) -> None:
        limiter = RedisRateLimiter(fake_redis, "rl:test", max_requests=2, window_seconds=60)
        limiter.is_allowed("10.0.0.1")
        limiter.is_allowed("10.0.0.1")
        assert limiter.is_allowed("10.0.0.1") is False

    def test_counts_requests_with_identical_timestamps(self, fake_redis) -> None:
        limiter = RedisRateLimiter(fake_redis, "rl:test", max_requests=2, window_seconds=60)
        with patch("songmaker_cli.redis_client.time.time", return_value=1234.5):
            assert limiter.is_allowed("10.0.0.1") is True
            assert limiter.is_allowed("10.0.0.1") is True
            assert limiter.is_allowed("10.0.0.1") is False
            for _ in range(1_000):
                assert limiter.is_allowed("10.0.0.1") is False
            assert fake_redis.zcard("rl:test:10.0.0.1") == 2

    def test_different_ips_independent(self, fake_redis) -> None:
        limiter = RedisRateLimiter(fake_redis, "rl:test", max_requests=1, window_seconds=60)
        assert limiter.is_allowed("10.0.0.1") is True
        assert limiter.is_allowed("10.0.0.2") is True
        assert limiter.is_allowed("10.0.0.1") is False

    def test_different_prefixes_independent(self, fake_redis) -> None:
        limiter_a = RedisRateLimiter(fake_redis, "rl:a", max_requests=1, window_seconds=60)
        limiter_b = RedisRateLimiter(fake_redis, "rl:b", max_requests=1, window_seconds=60)
        assert limiter_a.is_allowed("10.0.0.1") is True
        assert limiter_b.is_allowed("10.0.0.1") is True
        assert limiter_a.is_allowed("10.0.0.1") is False
        assert limiter_b.is_allowed("10.0.0.1") is False

    def test_window_expiry(self, fake_redis) -> None:
        limiter = RedisRateLimiter(fake_redis, "rl:test", max_requests=1, window_seconds=1)
        assert limiter.is_allowed("10.0.0.1") is True
        assert limiter.is_allowed("10.0.0.1") is False
        with patch("songmaker_cli.redis_client.time") as mock_time:
            mock_time.time.return_value = time.time() + 2
            assert limiter.is_allowed("10.0.0.1") is True

    def test_raises_on_redis_failure(self) -> None:
        broken = MagicMock()
        broken.eval.side_effect = ConnectionError("down")
        limiter = RedisRateLimiter(broken, "rl:test", max_requests=10, window_seconds=60)
        with pytest.raises(ConnectionError):
            limiter.is_allowed("10.0.0.1")


# ── RedisHttpMetrics ─────────────────────────────────────────────


class TestRedisHttpMetrics:
    def test_empty_snapshot(self, fake_redis) -> None:
        m = RedisHttpMetrics(fake_redis)
        snap = m.snapshot()
        assert snap["http_requests_count"] == 0
        assert snap["http_request_duration_total_ms"] == 0.0
        assert snap["http_requests_total"] == {}

    def test_record_and_snapshot(self, fake_redis) -> None:
        m = RedisHttpMetrics(fake_redis)
        m.record("GET", 200, 10.0)
        m.record("GET", 200, 20.0)
        m.record("POST", 201, 30.0)
        snap = m.snapshot()
        assert snap["http_requests_count"] == 3
        assert snap["http_request_duration_total_ms"] == 60.0
        assert snap["http_requests_total"]["GET 200"] == 2
        assert snap["http_requests_total"]["POST 201"] == 1


# ── Server integration with Redis ────────────────────────────────


def _make_server_project(tmp_path: Path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")
    return audio_dir, data_dir, project_root


def _make_redis_ctx(tmp_path: Path, fake_redis) -> tuple[AppContext, Path, Path, Path]:
    audio_dir, data_dir, project_root = _make_server_project(tmp_path)
    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        session.add(User(
            username="admin", password_hash=hash_password("admin12345"), role="admin",
        ))
        session.commit()
    ctx = AppContext(
        db=factory, audio_dir=audio_dir, data_dir=data_dir,
        session_secret=TEST_SECRET, redis=fake_redis,
    )
    return ctx, audio_dir, data_dir, project_root


def test_health_reports_redis_ok(tmp_path: Path, fake_redis, mock_arq_pool) -> None:
    ctx, audio_dir, data_dir, project_root = _make_redis_ctx(tmp_path, fake_redis)
    app = create_app(audio_dir, data_dir, project_root, ctx=ctx)
    with (
        patch("songmaker_cli.arq_pool.is_music_worker_healthy", return_value=False),
        patch("songmaker_cli.arq_pool.is_scoring_worker_healthy", return_value=False),
        patch("songmaker_cli.arq_pool.get_music_queue_depth", return_value=0),
        patch("songmaker_cli.arq_pool.get_scoring_queue_depth", return_value=0),
        TestClient(app) as client,
    ):
        resp = client.get("/health")
    data = resp.json()
    assert data["redis"] == "ok"


def test_health_reports_redis_error(tmp_path: Path, fake_redis, mock_arq_pool) -> None:
    ctx, audio_dir, data_dir, project_root = _make_redis_ctx(tmp_path, fake_redis)
    app = create_app(audio_dir, data_dir, project_root, ctx=ctx)
    with TestClient(app) as client:
        with patch("songmaker_cli.redis_client.redis_health", return_value=False):
            resp = client.get("/health")
    data = resp.json()
    assert data["redis"] == "error"
    assert data["status"] == "degraded"



def test_ip_rate_limit_middleware_uses_redis(tmp_path: Path, fake_redis, mock_arq_pool) -> None:
    ctx, audio_dir, data_dir, project_root = _make_redis_ctx(tmp_path, fake_redis)
    app = create_app(audio_dir, data_dir, project_root, ctx=ctx)
    client = TestClient(app, cookies={})
    from conftest import login_and_csrf
    login_and_csrf(client, "admin", "admin12345")
    for _ in range(5):
        resp = client.get("/api/songs")
        assert resp.status_code == 200


def test_redis_rate_limit_fail_closed(tmp_path: Path, mock_arq_pool) -> None:
    broken_redis = MagicMock()
    broken_redis.ping.return_value = True
    pipe_mock = MagicMock()
    pipe_mock.execute.side_effect = ConnectionError("Redis down")
    broken_redis.pipeline.return_value = pipe_mock

    audio_dir, data_dir, project_root = _make_server_project(tmp_path)
    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        session.add(User(
            username="admin", password_hash=hash_password("admin12345"), role="admin",
        ))
        session.commit()
    ctx = AppContext(
        db=factory, audio_dir=audio_dir, data_dir=data_dir,
        session_secret=TEST_SECRET, redis=broken_redis,
    )
    app = create_app(audio_dir, data_dir, project_root, ctx=ctx)
    client = TestClient(app, cookies={}, raise_server_exceptions=False)
    resp = client.get("/api/songs")
    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "5"


def test_metrics_with_redis(tmp_path: Path, fake_redis, mock_arq_pool) -> None:
    ctx, audio_dir, data_dir, project_root = _make_redis_ctx(tmp_path, fake_redis)
    app = create_app(audio_dir, data_dir, project_root, ctx=ctx)
    with TestClient(app) as client:
        client.get("/health")
        resp = client.get("/metrics")
    body = resp.text
    assert "songmaker_http_requests_total" in body
    assert "songmaker_http_request_duration_milliseconds_total" in body
    assert 'method="GET"' in body


def test_ip_rate_limit_middleware_writes_to_redis(
    tmp_path: Path, fake_redis, mock_arq_pool,
) -> None:
    from songmaker_cli.constants import REDIS_RL_IP_PREFIX

    ctx, audio_dir, data_dir, project_root = _make_redis_ctx(tmp_path, fake_redis)
    app = create_app(audio_dir, data_dir, project_root, ctx=ctx)
    client = TestClient(app, cookies={})
    from conftest import login_and_csrf
    login_and_csrf(client, "admin", "admin12345")
    client.get("/api/songs")
    keys = [k for k in fake_redis.keys() if k.startswith(REDIS_RL_IP_PREFIX)]
    assert len(keys) > 0


# ── SessionCache ────────────────────────────────────────────────


class TestSessionCache:
    def _make_cache(self, fake_redis) -> SessionCache:
        return SessionCache(fake_redis)

    def _store_sample(
        self, cache: SessionCache, session_id: str = "sess1",
        user_id: str = "user1", username: str = "alice",
    ) -> None:
        from datetime import datetime, timedelta, timezone
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
        from songmaker_cli.constants import REDIS_USER_SESSIONS_PREFIX
        cache = self._make_cache(fake_redis)
        self._store_sample(cache)
        members = fake_redis.smembers(f"{REDIS_USER_SESSIONS_PREFIX}:user1")
        assert "sess1" in members

    def test_store_sets_expiry(self, fake_redis) -> None:
        from songmaker_cli.constants import REDIS_SESSION_PREFIX
        cache = self._make_cache(fake_redis)
        self._store_sample(cache)
        ttl = fake_redis.ttl(f"{REDIS_SESSION_PREFIX}:sess1")
        assert 0 < ttl <= 86400

    def test_refresh_ttl(self, fake_redis) -> None:
        from songmaker_cli.constants import REDIS_SESSION_PREFIX
        cache = self._make_cache(fake_redis)
        self._store_sample(cache)
        cache.refresh_ttl("sess1", 999)
        ttl = fake_redis.ttl(f"{REDIS_SESSION_PREFIX}:sess1")
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
        from songmaker_cli.constants import REDIS_USER_SESSIONS_PREFIX
        cache = self._make_cache(fake_redis)
        self._store_sample(cache)
        cache.delete("sess1", "user1")
        assert cache.get("sess1") is None
        members = fake_redis.smembers(f"{REDIS_USER_SESSIONS_PREFIX}:user1")
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
        cache = SessionCache(broken)
        with pytest.raises(ConnectionError):
            cache.get("sess1")

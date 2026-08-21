"""Tests for auth API endpoints — setup, login, logout, me, password change."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from conftest import make_fake_redis, make_test_app
from fastapi.testclient import TestClient

from songmaker_cli.app_context import AppContext
from songmaker_cli.auth import hash_password
from songmaker_cli.db.queries import create_user
from songmaker_cli.middleware import SESSION_COOKIE


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    client, _ = make_test_app(tmp_path)
    yield client


def _seed_admin(client: TestClient) -> None:
    factory = client.app.state.ctx.db
    with factory() as session:
        create_user(session, "admin", hash_password("admin12345"), role="admin")
        session.commit()


def _seed_user(client: TestClient, username: str = "alice", active: bool = True) -> None:
    factory = client.app.state.ctx.db
    with factory() as session:
        user = create_user(session, username, hash_password("t3stP@ssw0rd"), role="user")
        user.is_active = active
        session.flush()
        session.commit()


def _login(client: TestClient, username: str, password: str) -> TestClient:
    from conftest import login_and_csrf
    login_and_csrf(client, username, password)
    return client


# -- Setup --------------------------------------------------------------------


def test_setup_required_true(client: TestClient) -> None:
    resp = client.get("/api/auth/setup-required")
    assert resp.status_code == 200
    assert resp.json()["required"] is True


def test_setup_required_false(client: TestClient) -> None:
    _seed_admin(client)
    resp = client.get("/api/auth/setup-required")
    assert resp.status_code == 200
    assert resp.json()["required"] is False


def test_setup_creates_admin(client: TestClient) -> None:
    resp = client.post("/api/auth/setup", json={"username": "myadmin", "password": "secure1234"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "myadmin"
    assert data["role"] == "admin"
    assert SESSION_COOKIE in resp.cookies


def test_setup_rejected_when_admin_exists(client: TestClient) -> None:
    _seed_admin(client)
    resp = client.post("/api/auth/setup", json={"username": "hacker", "password": "t3stP@ssw0rd"})
    assert resp.status_code == 403
    assert "already completed" in resp.json()["detail"]


def test_setup_validates_short_username(client: TestClient) -> None:
    resp = client.post("/api/auth/setup", json={"username": "ab", "password": "t3stP@ssw0rd"})
    assert resp.status_code == 422


def test_setup_validates_short_password(client: TestClient) -> None:
    resp = client.post("/api/auth/setup", json={"username": "admin", "password": "short"})
    assert resp.status_code == 422


# -- Login --------------------------------------------------------------------


def test_login_success(client: TestClient) -> None:
    _seed_admin(client)
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin12345"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"
    assert SESSION_COOKIE in resp.cookies


def test_login_wrong_password(client: TestClient) -> None:
    _seed_admin(client)
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "wrong12345"})
    assert resp.status_code == 401
    assert "Invalid" in resp.json()["detail"]


def test_login_nonexistent_user(client: TestClient) -> None:
    resp = client.post("/api/auth/login", json={"username": "nobody", "password": "t3stP@ssw0rd"})
    assert resp.status_code == 401


def test_login_disabled_user(client: TestClient) -> None:
    _seed_user(client, "disabled_user", active=False)
    resp = client.post(
        "/api/auth/login", json={"username": "disabled_user", "password": "t3stP@ssw0rd"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid username or password"


def test_login_brute_force_lockout(client: TestClient) -> None:
    _seed_admin(client)
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "admin", "password": "wrong12345"})

    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin12345"})
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


def test_login_lockout_after_sustained_failures(client: TestClient) -> None:
    from songmaker_cli.db.queries import record_login_attempt
    from songmaker_cli.settings import get_settings
    _seed_admin(client)
    threshold = get_settings().login_lockout_threshold
    factory = client.app.state.ctx.db
    with factory() as session:
        for _ in range(threshold):
            record_login_attempt(session, "testclient", "admin", success=False)
        session.commit()

    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin12345"})
    assert resp.status_code == 429
    assert "temporarily locked" in resp.json()["detail"]
    assert "Retry-After" in resp.headers


def test_client_ip_trusted_proxy(client: TestClient) -> None:
    _seed_admin(client)
    client.app.state.ctx = dataclasses.replace(
        client.app.state.ctx, trusted_proxies=frozenset({"testclient", "10.0.0.1"}),
    )
    resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin12345"},
        headers={"x-forwarded-for": "203.0.113.1, 10.0.0.1"},
    )
    assert resp.status_code == 200

    factory = client.app.state.ctx.db
    with factory() as session:
        from songmaker_cli.db.models import LoginAttempt
        attempt = session.query(LoginAttempt).order_by(LoginAttempt.attempted_at.desc()).first()
        assert attempt.ip_address == "203.0.113.1"


# -- Logout -------------------------------------------------------------------


def test_logout(client: TestClient) -> None:
    _seed_admin(client)
    _login(client, "admin", "admin12345")
    resp = client.delete("/api/auth/session")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_logout_invalidates_session_in_db(client: TestClient) -> None:
    _seed_admin(client)
    _login(client, "admin", "admin12345")
    cookie = client.cookies.get(SESSION_COOKIE)
    resp = client.delete("/api/auth/session")
    assert resp.status_code == 200

    other = TestClient(client.app, cookies={})
    other.cookies.set(SESSION_COOKIE, cookie)
    resp = other.get("/api/auth/me")
    assert resp.status_code == 401


def test_logout_without_session(client: TestClient) -> None:
    resp = client.delete("/api/auth/session")
    assert resp.status_code in (401, 403)


# -- Me -----------------------------------------------------------------------


def test_me_authenticated(client: TestClient) -> None:
    _seed_admin(client)
    _login(client, "admin", "admin12345")
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "admin"
    assert data["role"] == "admin"


def test_me_unauthenticated(client: TestClient) -> None:
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


# -- Change password ----------------------------------------------------------


def test_change_password(client: TestClient) -> None:
    _seed_admin(client)
    _login(client, "admin", "admin12345")
    resp = client.put(
        "/api/auth/password",
        json={"current": "admin12345", "new_password": "newpassword1"},
    )
    assert resp.status_code == 200

    client.delete("/api/auth/session")
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "newpassword1"})
    assert resp.status_code == 200


def test_change_password_wrong_current(client: TestClient) -> None:
    _seed_admin(client)
    _login(client, "admin", "admin12345")
    resp = client.put(
        "/api/auth/password",
        json={"current": "wrongpass1", "new_password": "newpassword1"},
    )
    assert resp.status_code == 401
    assert "incorrect" in resp.json()["detail"]


def test_change_password_too_short(client: TestClient) -> None:
    _seed_admin(client)
    _login(client, "admin", "admin12345")
    resp = client.put(
        "/api/auth/password",
        json={"current": "admin12345", "new_password": "short"},
    )
    assert resp.status_code == 422


def test_change_password_brute_force_lockout(client: TestClient) -> None:
    _seed_admin(client)
    _login(client, "admin", "admin12345")
    for _ in range(5):
        client.put(
            "/api/auth/password",
            json={"current": "wrongpass1", "new_password": "newpassword1"},
        )
    resp = client.put(
        "/api/auth/password",
        json={"current": "admin12345", "new_password": "newpassword1"},
    )
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


def test_change_password_unauthenticated(client: TestClient) -> None:
    resp = client.put(
        "/api/auth/password",
        json={"current": "admin12345", "new_password": "newpassword1"},
    )
    assert resp.status_code in (401, 403)


# -- Setup race-condition and integrity error guards ---------------------------


def test_setup_race_condition_second_user_created(client: TestClient) -> None:
    """After flush, user_count > 1 means another request won the race — must 403."""
    from unittest.mock import patch

    call_count = 0

    def _user_count_side_effect(db):
        nonlocal call_count
        call_count += 1
        return 0 if call_count == 1 else 2

    with patch("songmaker_cli.auth_api.user_count", side_effect=_user_count_side_effect):
        resp = client.post(
            "/api/auth/setup", json={"username": "racing", "password": "t3stP@ssw0rd"},
        )

    assert resp.status_code == 403
    assert "already completed" in resp.json()["detail"]


def test_setup_integrity_error_returns_403(client: TestClient) -> None:
    """IntegrityError from create_user (duplicate username) must return 403."""
    from unittest.mock import patch

    from sqlalchemy.exc import IntegrityError

    with patch(
        "songmaker_cli.auth_api.create_user",
        side_effect=IntegrityError("duplicate", {}, Exception()),
    ):
        resp = client.post(
            "/api/auth/setup", json={"username": "admin", "password": "t3stP@ssw0rd"},
        )

    assert resp.status_code == 403
    assert "already completed" in resp.json()["detail"]


# -- _detect_secure ------------------------------------------------------------


def test_detect_secure_none_request() -> None:
    from songmaker_cli.auth_api import _detect_secure

    redis = make_fake_redis()
    ctx = AppContext(
        db=MagicMock(), audio_dir=Path("/tmp/audio"),
        data_dir=Path("/tmp/data"), session_secret=b"x" * 32, redis=redis,
    )
    assert _detect_secure(None, ctx) is False


# -- Redis session cache integration ------------------------------------------


def test_login_populates_redis(client: TestClient) -> None:
    from songmaker_cli.redis_client import SessionCache

    _seed_admin(client)
    session_cache: SessionCache = client.app.state.session_cache

    client.post("/api/auth/login", json={"username": "admin", "password": "admin12345"})

    from songmaker_cli.constants import REDIS_USER_SESSIONS_PREFIX
    redis = client.app.state.ctx.redis
    members = redis.smembers(f"{REDIS_USER_SESSIONS_PREFIX}:{_get_user_id(client, 'admin')}")
    assert len(members) == 1
    sid = list(members)[0]
    assert session_cache.get(sid) is not None


def test_second_login_keeps_existing_sessions(client: TestClient) -> None:
    from songmaker_cli.constants import REDIS_USER_SESSIONS_PREFIX
    from songmaker_cli.redis_client import SessionCache

    _seed_admin(client)
    session_cache: SessionCache = client.app.state.session_cache
    redis = client.app.state.ctx.redis
    user_id = _get_user_id(client, "admin")

    first = TestClient(client.app, cookies={})
    second = TestClient(client.app, cookies={})
    assert first.post(
        "/api/auth/login", json={"username": "admin", "password": "admin12345"},
    ).status_code == 200
    assert second.post(
        "/api/auth/login", json={"username": "admin", "password": "admin12345"},
    ).status_code == 200

    sids = redis.smembers(f"{REDIS_USER_SESSIONS_PREFIX}:{user_id}")
    assert len(sids) == 2
    for sid in sids:
        assert session_cache.get(sid) is not None
    assert first.get("/api/auth/me").status_code == 200
    assert second.get("/api/auth/me").status_code == 200


def test_login_prunes_oldest_session_over_cap(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from songmaker_cli.constants import REDIS_USER_SESSIONS_PREFIX
    from songmaker_cli.db.models import UserSession
    from songmaker_cli.settings import get_settings

    monkeypatch.setattr(get_settings(), "max_concurrent_sessions_per_user", 2)
    _seed_admin(client)
    redis = client.app.state.ctx.redis
    session_cache = client.app.state.session_cache
    user_id = _get_user_id(client, "admin")

    first = TestClient(client.app, cookies={})
    second = TestClient(client.app, cookies={})
    third = TestClient(client.app, cookies={})
    assert first.post(
        "/api/auth/login", json={"username": "admin", "password": "admin12345"},
    ).status_code == 200
    oldest_sids = redis.smembers(f"{REDIS_USER_SESSIONS_PREFIX}:{user_id}")
    assert len(oldest_sids) == 1
    oldest_sid = next(iter(oldest_sids))
    assert second.post(
        "/api/auth/login", json={"username": "admin", "password": "admin12345"},
    ).status_code == 200
    assert third.post(
        "/api/auth/login", json={"username": "admin", "password": "admin12345"},
    ).status_code == 200

    members = redis.smembers(f"{REDIS_USER_SESSIONS_PREFIX}:{user_id}")
    assert len(members) == 2
    assert oldest_sid not in members
    assert session_cache.get(oldest_sid) is None
    assert first.get("/api/auth/me").status_code == 401
    assert second.get("/api/auth/me").status_code == 200
    assert third.get("/api/auth/me").status_code == 200

    factory = client.app.state.ctx.db
    with factory() as session:
        remaining = session.query(UserSession).filter_by(user_id=user_id).all()
        remaining_ids = {row.id for row in remaining}
        assert len(remaining_ids) == 2
        assert oldest_sid not in remaining_ids


def test_login_redis_prune_failure_rolls_back(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from songmaker_cli.constants import REDIS_USER_SESSIONS_PREFIX
    from songmaker_cli.db.models import UserSession
    from songmaker_cli.settings import get_settings

    monkeypatch.setattr(get_settings(), "max_concurrent_sessions_per_user", 1)
    _seed_admin(client)
    redis = client.app.state.ctx.redis
    session_cache = client.app.state.session_cache
    user_id = _get_user_id(client, "admin")

    first = TestClient(client.app, cookies={})
    assert first.post(
        "/api/auth/login", json={"username": "admin", "password": "admin12345"},
    ).status_code == 200
    old_sids = redis.smembers(f"{REDIS_USER_SESSIONS_PREFIX}:{user_id}")
    assert len(old_sids) == 1
    old_sid = next(iter(old_sids))

    monkeypatch.setattr(
        session_cache, "delete", MagicMock(side_effect=RuntimeError("redis down")),
    )
    second = TestClient(client.app, cookies={})
    resp = second.post(
        "/api/auth/login", json={"username": "admin", "password": "admin12345"},
    )
    assert resp.status_code == 503
    assert "degraded" in resp.json()["detail"]

    assert first.get("/api/auth/me").status_code == 200
    factory = client.app.state.ctx.db
    with factory() as session:
        remaining = session.query(UserSession).filter_by(user_id=user_id).all()
        remaining_ids = {row.id for row in remaining}
        assert remaining_ids == {old_sid}
    assert redis.smembers(f"{REDIS_USER_SESSIONS_PREFIX}:{user_id}") == old_sids
    assert session_cache.get(old_sid) is not None


def test_login_commit_failure_does_not_leave_redis_session(client: TestClient) -> None:
    from unittest.mock import patch

    from songmaker_cli.constants import REDIS_USER_SESSIONS_PREFIX
    from songmaker_cli.db.models import UserSession
    from songmaker_cli.db.queries import create_session as real_create_session

    _seed_admin(client)
    user_id = _get_user_id(client, "admin")
    session_cache = client.app.state.session_cache
    redis = client.app.state.ctx.redis
    created_ids: list[str] = []
    cached_before_commit = {"present": False}

    def create_session_then_fail_commit(db, *args, **kwargs):
        user_session = real_create_session(db, *args, **kwargs)
        created_ids.append(user_session.id)

        def fail_commit() -> None:
            cached_before_commit["present"] = session_cache.get(user_session.id) is not None
            raise RuntimeError("commit failed")

        db.commit = fail_commit
        return user_session

    with patch(
        "songmaker_cli.auth_api.create_session",
        side_effect=create_session_then_fail_commit,
    ):
        with pytest.raises(RuntimeError, match="commit failed"):
            client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "admin12345"},
            )

    assert created_ids
    new_sid = created_ids[0]
    assert cached_before_commit["present"] is True
    assert session_cache.get(new_sid) is None
    assert new_sid not in redis.smembers(f"{REDIS_USER_SESSIONS_PREFIX}:{user_id}")

    factory = client.app.state.ctx.db
    with factory() as session:
        remaining = session.query(UserSession).filter_by(user_id=user_id).all()
        assert remaining == []


def test_logout_clears_redis(client: TestClient) -> None:
    from songmaker_cli.redis_client import SessionCache

    _seed_admin(client)
    _login(client, "admin", "admin12345")

    session_cache: SessionCache = client.app.state.session_cache
    from songmaker_cli.constants import REDIS_USER_SESSIONS_PREFIX
    redis = client.app.state.ctx.redis
    user_id = _get_user_id(client, "admin")
    sids_before = redis.smembers(f"{REDIS_USER_SESSIONS_PREFIX}:{user_id}")
    assert len(sids_before) >= 1
    sid = list(sids_before)[0]

    client.delete("/api/auth/session")

    assert session_cache.get(sid) is None


def test_password_change_clears_old_populates_new(client: TestClient) -> None:
    from songmaker_cli.redis_client import SessionCache

    _seed_admin(client)
    _login(client, "admin", "admin12345")

    session_cache: SessionCache = client.app.state.session_cache
    from songmaker_cli.constants import REDIS_USER_SESSIONS_PREFIX
    redis = client.app.state.ctx.redis
    user_id = _get_user_id(client, "admin")
    old_sids = redis.smembers(f"{REDIS_USER_SESSIONS_PREFIX}:{user_id}")
    old_sid = list(old_sids)[0]

    client.put(
        "/api/auth/password",
        json={"current": "admin12345", "new_password": "newpassword1"},
    )

    assert session_cache.get(old_sid) is None
    new_sids = redis.smembers(f"{REDIS_USER_SESSIONS_PREFIX}:{user_id}")
    assert len(new_sids) == 1
    new_sid = list(new_sids)[0]
    assert new_sid != old_sid
    assert session_cache.get(new_sid) is not None


def test_setup_populates_redis(client: TestClient) -> None:
    from songmaker_cli.redis_client import SessionCache

    session_cache: SessionCache = client.app.state.session_cache
    client.post("/api/auth/setup", json={"username": "myadmin", "password": "secure1234"})

    from songmaker_cli.constants import REDIS_USER_SESSIONS_PREFIX
    redis = client.app.state.ctx.redis
    user_id = _get_user_id(client, "myadmin")
    members = redis.smembers(f"{REDIS_USER_SESSIONS_PREFIX}:{user_id}")
    assert len(members) == 1
    sid = list(members)[0]
    assert session_cache.get(sid) is not None


def _get_user_id(client: TestClient, username: str) -> str:
    factory = client.app.state.ctx.db
    with factory() as session:
        from songmaker_cli.db.queries import get_user_by_username
        user = get_user_by_username(session, username)
        return user.id

"""Tests for session auth dependency and FastAPI integration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import make_fake_redis
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from songmaker_cli.auth import hash_password, sign_session_id
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.queries import create_session, create_user
from songmaker_cli.middleware import (
    SESSION_COOKIE,
    AuthenticatedUser,
    get_current_user,
    require_admin,
)

_TEST_SECRET = b"a" * 64


@pytest.fixture
def _db(tmp_path: Path):
    return init_db(tmp_path / "test.db")


def _build_auth_app(_db, redis=None):
    from songmaker_cli.app_context import AppContext, get_db_session
    from songmaker_cli.redis_client import SessionCache

    if redis is None:
        redis = make_fake_redis()
    ctx = AppContext(
        db=_db, audio_dir=Path("/tmp/audio"), data_dir=Path("/tmp/data"),
        session_secret=_TEST_SECRET, redis=redis,
    )
    app = FastAPI()
    app.state.ctx = ctx
    app.state.session_cache = SessionCache(redis)

    @app.get("/protected")
    def protected(
        request: Request,
        user: AuthenticatedUser = Depends(get_current_user),
        db: Session = Depends(get_db_session),
    ):
        db.commit()
        return {
            "username": user.username,
            "role": user.role,
            "session_id_set": hasattr(request.state, "session_id"),
        }

    @app.get("/admin-only")
    def admin_only(user: AuthenticatedUser = Depends(require_admin)):
        return {"username": user.username}

    @app.get("/public")
    def public():
        return {"status": "ok"}

    return app


@pytest.fixture
def auth_app(_db) -> TestClient:
    """Minimal FastAPI app with auth dependency — no middleware stack."""
    app = _build_auth_app(_db)
    return TestClient(app, cookies={})


def _make_user_and_session(
    factory,
    role: str = "user", active: bool = True, expired: bool = False,
    created_days_ago: int = 0,
) -> str:
    with factory() as session:
        user = create_user(
            session, f"test_{role}_{active}_{expired}_{created_days_ago}",
            hash_password("t3stP@ssw0rd"), role=role,
        )
        user.is_active = active
        session.flush()
        if expired:
            expires = datetime.now(timezone.utc) - timedelta(days=1)
        else:
            expires = datetime.now(timezone.utc) + timedelta(days=30)
        user_session = create_session(session, user.id, expires)
        if created_days_ago:
            user_session.created_at = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
        session.commit()
        return user_session.id


@pytest.fixture
def create_session_id(_db):
    from functools import partial
    return partial(_make_user_and_session, _db)


# -- No cookie / bad cookie ---------------------------------------------------


def test_no_cookie_returns_401(auth_app: TestClient) -> None:
    resp = auth_app.get("/protected")
    assert resp.status_code == 401


def test_unsigned_cookie_returns_401(auth_app: TestClient) -> None:
    auth_app.cookies.set(SESSION_COOKIE, "raw-no-hmac")
    resp = auth_app.get("/protected")
    assert resp.status_code == 401


def test_nonexistent_session_returns_401(auth_app: TestClient) -> None:
    auth_app.cookies.set(SESSION_COOKIE, sign_session_id("nonexistent", _TEST_SECRET))
    resp = auth_app.get("/protected")
    assert resp.status_code == 401


# -- Expiry -------------------------------------------------------------------


def test_expired_session_returns_401(auth_app: TestClient, create_session_id) -> None:
    sid = create_session_id(expired=True)
    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid, _TEST_SECRET))
    resp = auth_app.get("/protected")
    assert resp.status_code == 401


def test_absolute_max_age_expired(auth_app: TestClient, create_session_id) -> None:
    sid = create_session_id(created_days_ago=91)
    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid, _TEST_SECRET))
    resp = auth_app.get("/protected")
    assert resp.status_code == 401


# -- Disabled user ------------------------------------------------------------


def test_disabled_user_returns_403(auth_app: TestClient, create_session_id) -> None:
    sid = create_session_id(active=False)
    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid, _TEST_SECRET))
    resp = auth_app.get("/protected")
    assert resp.status_code == 403


# -- Valid session ------------------------------------------------------------


def test_valid_session_returns_200(auth_app: TestClient, create_session_id) -> None:
    sid = create_session_id()
    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid, _TEST_SECRET))
    resp = auth_app.get("/protected")
    assert resp.status_code == 200
    assert resp.json()["username"].startswith("test_user")


def test_session_id_set_on_request_state(auth_app: TestClient, create_session_id) -> None:
    sid = create_session_id()
    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid, _TEST_SECRET))
    resp = auth_app.get("/protected")
    assert resp.status_code == 200
    assert resp.json()["session_id_set"] is True


def test_sliding_window_renewal(auth_app: TestClient, create_session_id) -> None:
    from songmaker_cli.db.queries import get_session_with_user

    sid = create_session_id()
    factory = auth_app.app.state.ctx.db

    with factory() as db:
        old_expires = get_session_with_user(db, sid).expires_at

    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid, _TEST_SECRET))
    auth_app.get("/protected")

    with factory() as db:
        new_expires = get_session_with_user(db, sid).expires_at
        assert new_expires >= old_expires


def test_public_route_no_auth_needed(auth_app: TestClient) -> None:
    resp = auth_app.get("/public")
    assert resp.status_code == 200


# -- Admin dependency ---------------------------------------------------------


def test_require_admin_rejects_regular_user(auth_app: TestClient, create_session_id) -> None:
    sid = create_session_id(role="user")
    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid, _TEST_SECRET))
    resp = auth_app.get("/admin-only")
    assert resp.status_code == 403


def test_require_admin_allows_admin(auth_app: TestClient, create_session_id) -> None:
    sid = create_session_id(role="admin")
    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid, _TEST_SECRET))
    resp = auth_app.get("/admin-only")
    assert resp.status_code == 200


# -- IP/UA audit logging -----------------------------------------------------


def test_ip_change_creates_audit(auth_app: TestClient, create_session_id) -> None:
    from songmaker_cli.db.models import AuditLog

    sid = create_session_id()
    factory = auth_app.app.state.ctx.db

    with factory() as db:
        from songmaker_cli.db.queries import get_session_with_user
        sess = get_session_with_user(db, sid)
        sess.ip_address = "1.2.3.4"
        db.commit()

    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid, _TEST_SECRET))
    auth_app.get("/protected")

    with factory() as db:
        entry = db.query(AuditLog).filter(AuditLog.action == "session_ip_change").first()
        assert entry is not None
        assert "1.2.3.4" in entry.detail


def test_ua_change_creates_audit(auth_app: TestClient, create_session_id) -> None:
    from songmaker_cli.db.models import AuditLog

    sid = create_session_id()
    factory = auth_app.app.state.ctx.db

    with factory() as db:
        from songmaker_cli.db.queries import get_session_with_user
        sess = get_session_with_user(db, sid)
        sess.user_agent = "OldBrowser/1.0"
        db.commit()

    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid, _TEST_SECRET))
    auth_app.get("/protected", headers={"user-agent": "NewBrowser/2.0"})

    with factory() as db:
        entry = db.query(AuditLog).filter(AuditLog.action == "session_ua_change").first()
        assert entry is not None




# -- Redis session cache integration -----------------------------------------


def test_redis_cache_hit_skips_db_query(auth_app: TestClient, create_session_id) -> None:
    from unittest.mock import patch

    from songmaker_cli.redis_client import SessionCache

    sid = create_session_id()
    session_cache: SessionCache = auth_app.app.state.session_cache

    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid, _TEST_SECRET))
    auth_app.get("/protected")
    assert session_cache.get(sid) is not None

    with patch("songmaker_cli.middleware.auth.get_session_with_user") as mock_db:
        auth_app.get("/protected")
        mock_db.assert_not_called()


def test_redis_miss_falls_back_to_db_and_populates_cache(
    auth_app: TestClient, create_session_id,
) -> None:
    from songmaker_cli.redis_client import SessionCache

    sid = create_session_id()
    session_cache: SessionCache = auth_app.app.state.session_cache

    assert session_cache.get(sid) is None

    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid, _TEST_SECRET))
    resp = auth_app.get("/protected")
    assert resp.status_code == 200

    assert session_cache.get(sid) is not None


def test_redis_failure_falls_back_to_db(_db, create_session_id) -> None:
    from unittest.mock import MagicMock

    broken_redis = MagicMock()
    broken_redis.get.side_effect = ConnectionError("Redis down")

    app = _build_auth_app(_db, redis=broken_redis)
    client = TestClient(app, cookies={})

    sid = create_session_id()
    client.cookies.set(SESSION_COOKIE, sign_session_id(sid, _TEST_SECRET))
    resp = client.get("/protected")
    assert resp.status_code == 200


def test_redis_path_checks_absolute_max_age(auth_app: TestClient, create_session_id) -> None:
    import json

    from songmaker_cli.constants import REDIS_SESSION_PREFIX

    sid = create_session_id()

    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid, _TEST_SECRET))
    resp = auth_app.get("/protected")
    assert resp.status_code == 200

    key = f"{REDIS_SESSION_PREFIX}:{sid}"
    redis = auth_app.app.state.ctx.redis
    raw = json.loads(redis.get(key))
    raw["created_at"] = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()
    redis.set(key, json.dumps(raw), ex=86400)

    resp = auth_app.get("/protected")
    assert resp.status_code == 401


def test_redis_path_ip_change_writes_audit(auth_app: TestClient, create_session_id) -> None:
    from songmaker_cli.db.models import AuditLog

    sid = create_session_id()

    factory = auth_app.app.state.ctx.db
    with factory() as db:
        from songmaker_cli.db.queries import get_session_with_user
        sess = get_session_with_user(db, sid)
        sess.ip_address = "1.2.3.4"
        db.commit()

    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid, _TEST_SECRET))
    auth_app.get("/protected")

    import json

    from songmaker_cli.constants import REDIS_SESSION_PREFIX
    key = f"{REDIS_SESSION_PREFIX}:{sid}"
    raw = json.loads(auth_app.app.state.ctx.redis.get(key))
    raw["ip_address"] = "9.9.9.9"
    auth_app.app.state.ctx.redis.set(key, json.dumps(raw), ex=86400)

    auth_app.get("/protected")

    with factory() as db:
        entry = db.query(AuditLog).filter(AuditLog.action == "session_ip_change").all()
        ip_entries = [e for e in entry if "9.9.9.9" in (e.detail or "")]
        assert len(ip_entries) >= 1


def test_redis_path_refreshes_ttl(auth_app: TestClient, create_session_id) -> None:
    from songmaker_cli.constants import REDIS_SESSION_PREFIX

    sid = create_session_id()
    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid, _TEST_SECRET))
    auth_app.get("/protected")

    key = f"{REDIS_SESSION_PREFIX}:{sid}"
    redis = auth_app.app.state.ctx.redis
    redis.expire(key, 100)

    auth_app.get("/protected")
    ttl = redis.ttl(key)
    assert ttl > 100



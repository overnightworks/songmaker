"""Tests for admin API endpoints — user CRUD, sessions, login attempts."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_fake_redis
from fastapi.testclient import TestClient

from songmaker_cli.app_context import AppContext
from songmaker_cli.auth import hash_password
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.queries import create_user
from songmaker_cli.middleware import SESSION_COOKIE
from songmaker_cli.server import create_app

_TEST_SECRET = b"a" * 64


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Songmaker</html>")

    factory = init_db(data_dir / "songmaker.db")
    redis = make_fake_redis()
    ctx = AppContext(
        db=factory, audio_dir=audio_dir, data_dir=data_dir,
        session_secret=_TEST_SECRET, redis=redis,
    )
    app = create_app(audio_dir, data_dir, project_root, ctx=ctx)
    yield TestClient(app, cookies={})


def _login_as_admin(client: TestClient) -> None:
    from conftest import login_and_csrf
    factory = client.app.state.ctx.db
    with factory() as session:
        create_user(session, "admin", hash_password("admin12345"), role="admin")
        session.commit()
    login_and_csrf(client, "admin", "admin12345")


def _login_as_user(client: TestClient) -> None:
    from conftest import login_and_csrf
    factory = client.app.state.ctx.db
    with factory() as session:
        create_user(session, "regular", hash_password("user123456"), role="user")
        session.commit()
    login_and_csrf(client, "regular", "user123456")


# -- Access control -----------------------------------------------------------


def test_admin_endpoints_require_auth(client: TestClient) -> None:
    resp = client.get("/api/admin/users")
    assert resp.status_code == 401


def test_admin_endpoints_require_admin_role(client: TestClient) -> None:
    _login_as_user(client)
    resp = client.get("/api/admin/users")
    assert resp.status_code == 403


# -- List users ---------------------------------------------------------------


def test_list_users(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.get("/api/admin/users")
    assert resp.status_code == 200
    users = resp.json()
    assert len(users) == 1
    assert users[0]["username"] == "admin"
    assert "password_hash" not in users[0]


# -- Create user --------------------------------------------------------------


def test_create_user(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "newuser", "password": "t3stP@ssw0rd", "role": "user"},
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "newuser"
    assert resp.json()["role"] == "user"


def test_create_user_duplicate(client: TestClient) -> None:
    _login_as_admin(client)
    client.post(
        "/api/admin/users",
        json={"username": "dup", "password": "t3stP@ssw0rd"},
    )
    resp = client.post(
        "/api/admin/users",
        json={"username": "dup", "password": "t3stP@ssw0rd"},
    )
    assert resp.status_code == 409


def test_create_user_invalid_role(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "bob", "password": "t3stP@ssw0rd", "role": "superadmin"},
    )
    assert resp.status_code == 422


# -- Update user --------------------------------------------------------------


def test_update_user_role(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "bob", "password": "t3stP@ssw0rd"},
    )
    user_id = resp.json()["id"]

    resp = client.put(f"/api/admin/users/{user_id}", json={"role": "admin"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


def test_update_user_deactivate(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "bob", "password": "t3stP@ssw0rd"},
    )
    user_id = resp.json()["id"]

    resp = client.put(f"/api/admin/users/{user_id}", json={"is_active": False})
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_update_user_password(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "bob", "password": "t3stP@ssw0rd"},
    )
    user_id = resp.json()["id"]

    resp = client.put(f"/api/admin/users/{user_id}", json={"password": "newpass12345"})
    assert resp.status_code == 200


def test_update_user_not_found(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.put("/api/admin/users/nonexistent", json={"role": "admin"})
    assert resp.status_code == 404


def test_update_user_invalid_role(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "bob", "password": "t3stP@ssw0rd"},
    )
    user_id = resp.json()["id"]

    resp = client.put(f"/api/admin/users/{user_id}", json={"role": "superadmin"})
    assert resp.status_code == 422


def test_cannot_deactivate_self(client: TestClient) -> None:
    _login_as_admin(client)
    me = client.get("/api/auth/me").json()
    resp = client.put(f"/api/admin/users/{me['id']}", json={"is_active": False})
    assert resp.status_code == 400
    assert "own account" in resp.json()["detail"]


def test_cannot_demote_self(client: TestClient) -> None:
    _login_as_admin(client)
    me = client.get("/api/auth/me").json()
    resp = client.put(f"/api/admin/users/{me['id']}", json={"role": "user"})
    assert resp.status_code == 400
    assert "last active admin" in resp.json()["detail"]


def test_cannot_demote_last_admin_even_different_user(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "admin2", "password": "t3stP@ssw0rd", "role": "admin"},
    )
    admin2_id = resp.json()["id"]

    client.put(f"/api/admin/users/{admin2_id}", json={"is_active": False})

    me = client.get("/api/auth/me").json()
    resp = client.put(f"/api/admin/users/{me['id']}", json={"role": "user"})
    assert resp.status_code == 400
    assert "last active admin" in resp.json()["detail"]


def test_demote_admin_allowed_when_multiple(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "admin2", "password": "t3stP@ssw0rd", "role": "admin"},
    )
    admin2_id = resp.json()["id"]

    resp = client.put(f"/api/admin/users/{admin2_id}", json={"role": "user"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "user"


# -- Delete (deactivate) user -------------------------------------------------


def test_deactivate_user(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "bob", "password": "t3stP@ssw0rd"},
    )
    user_id = resp.json()["id"]

    resp = client.delete(f"/api/admin/users/{user_id}")
    assert resp.status_code == 200

    users = client.get("/api/admin/users").json()
    bob = next(u for u in users if u["username"] == "bob")
    assert bob["is_active"] is False


def test_deactivate_user_not_found(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.delete("/api/admin/users/nonexistent")
    assert resp.status_code == 404


def test_cannot_deactivate_self_via_delete(client: TestClient) -> None:
    _login_as_admin(client)
    me = client.get("/api/auth/me").json()
    resp = client.delete(f"/api/admin/users/{me['id']}")
    assert resp.status_code == 400


def test_deactivate_admin_via_delete_allowed_when_multiple(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "admin2", "password": "t3stP@ssw0rd", "role": "admin"},
    )
    admin2_id = resp.json()["id"]

    resp = client.delete(f"/api/admin/users/{admin2_id}")
    assert resp.status_code == 200

    factory = client.app.state.ctx.db
    with factory() as session:
        from songmaker_cli.db.queries import get_user
        admin2_user = get_user(session, admin2_id)
        assert admin2_user.is_active is False


def test_delete_inactive_admin_blocked_when_sole_active(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "admin2", "password": "t3stP@ssw0rd", "role": "admin"},
    )
    admin2_id = resp.json()["id"]
    client.put(f"/api/admin/users/{admin2_id}", json={"is_active": False})

    resp = client.delete(f"/api/admin/users/{admin2_id}")
    assert resp.status_code == 400
    assert "last active admin" in resp.json()["detail"]


def test_cannot_deactivate_sole_active_admin_via_delete(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "admin2", "password": "t3stP@ssw0rd", "role": "admin"},
    )
    admin2_id = resp.json()["id"]

    resp = client.delete(f"/api/admin/users/{admin2_id}")
    assert resp.status_code == 200

    resp = client.post(
        "/api/admin/users",
        json={"username": "admin3", "password": "t3stP@ssw0rd", "role": "admin"},
    )
    admin3_id = resp.json()["id"]

    client.put(f"/api/admin/users/{admin3_id}", json={"is_active": False})

    resp = client.post(
        "/api/admin/users",
        json={"username": "bob", "password": "t3stP@ssw0rd", "role": "user"},
    )
    bob_id = resp.json()["id"]

    resp = client.delete(f"/api/admin/users/{bob_id}")
    assert resp.status_code == 200


# -- Login attempts -----------------------------------------------------------


def test_list_login_attempts(client: TestClient) -> None:
    _login_as_admin(client)
    client.post("/api/auth/login", json={"username": "nobody", "password": "wrong12345"})
    resp = client.get("/api/admin/login-attempts")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) >= 1
    assert data["total"] >= 1


# -- Sessions -----------------------------------------------------------------


def test_list_sessions(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.get("/api/admin/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) >= 1
    assert data["items"][0]["username"] == "admin"


def test_force_logout(client: TestClient) -> None:
    _login_as_admin(client)

    factory = client.app.state.ctx.db
    with factory() as session:
        create_user(session, "victim", hash_password("t3stP@ssw0rd"))
        session.commit()

    other_client = TestClient(client.app, cookies={})
    other_client.post("/api/auth/login", json={"username": "victim", "password": "t3stP@ssw0rd"})
    victim_cookie = other_client.cookies.get(SESSION_COOKIE)

    sessions_resp = client.get("/api/admin/sessions")
    victim_sessions = [
        s for s in sessions_resp.json()["items"] if s["username"] == "victim"
    ]
    assert victim_sessions
    session_hash = victim_sessions[0]["id"]

    resp = client.delete(f"/api/admin/sessions/{session_hash}")
    assert resp.status_code == 200

    other_client.cookies.set(SESSION_COOKIE, victim_cookie)
    resp = other_client.get("/api/auth/me")
    assert resp.status_code == 401


def test_force_logout_not_found(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.delete("/api/admin/sessions/nonexistent_hash")
    assert resp.status_code == 404


# -- ACE-Step reinitialize ----------------------------------------------------


def test_reinitialize_acestep_success(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    _login_as_admin(client)

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(return_value=AsyncMock())

    with patch("songmaker_cli.arq_pool.get_arq_pool", return_value=mock_pool):
        resp = client.post("/api/admin/acestep/reinitialize")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    mock_pool.enqueue_job.assert_called_once_with("reinitialize_acestep")


def test_reinitialize_acestep_already_queued(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    _login_as_admin(client)

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(return_value=None)

    with patch("songmaker_cli.arq_pool.get_arq_pool", return_value=mock_pool):
        resp = client.post("/api/admin/acestep/reinitialize")

    assert resp.status_code == 409


# -- ACE-Step status ----------------------------------------------------------


def test_acestep_status_online(client: TestClient) -> None:
    import json
    from unittest.mock import AsyncMock, patch

    _login_as_admin(client)

    status = {
        "online": True,
        "model": "turbo",
        "lm_model": "small",
        "jobs": {"pending": 0, "running": 1},
    }
    mock_pool = AsyncMock()
    mock_pool.get = AsyncMock(return_value=json.dumps(status).encode())

    with patch("songmaker_cli.arq_pool.get_arq_pool", return_value=mock_pool):
        resp = client.get("/api/admin/acestep/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["online"] is True
    assert data["model"] == "turbo"
    assert data["lm_model"] == "small"
    assert data["jobs"] == {"pending": 0, "running": 1}


def test_acestep_status_offline(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    _login_as_admin(client)

    mock_pool = AsyncMock()
    mock_pool.get = AsyncMock(return_value=None)

    with patch("songmaker_cli.arq_pool.get_arq_pool", return_value=mock_pool):
        resp = client.get("/api/admin/acestep/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["online"] is False
    assert data["model"] is None
    assert data["lm_model"] is None
    assert data["jobs"] == {}


# -- Redis session cache integration ------------------------------------------


def _get_user_id(client: TestClient, username: str) -> str:
    factory = client.app.state.ctx.db
    with factory() as session:
        from songmaker_cli.db.queries import get_user_by_username
        user = get_user_by_username(session, username)
        return user.id


def test_deactivate_user_clears_redis_sessions(client: TestClient) -> None:
    from conftest import login_and_csrf

    from songmaker_cli.redis_client import SessionCache

    _login_as_admin(client)

    client.post(
        "/api/admin/users",
        json={"username": "victim", "password": "t3stP@ssw0rd"},
    )
    victim_id = _get_user_id(client, "victim")

    victim_client = TestClient(client.app, cookies={})
    login_and_csrf(victim_client, "victim", "t3stP@ssw0rd")

    session_cache: SessionCache = client.app.state.session_cache
    from songmaker_cli.constants import REDIS_USER_SESSIONS_PREFIX
    redis = client.app.state.ctx.redis
    sids = redis.smembers(f"{REDIS_USER_SESSIONS_PREFIX}:{victim_id}")
    assert len(sids) >= 1

    client.delete(f"/api/admin/users/{victim_id}")

    sids_after = redis.smembers(f"{REDIS_USER_SESSIONS_PREFIX}:{victim_id}")
    assert len(sids_after) == 0
    for sid in sids:
        assert session_cache.get(sid) is None


def test_force_logout_clears_redis(client: TestClient) -> None:
    from songmaker_cli.redis_client import SessionCache

    _login_as_admin(client)

    factory = client.app.state.ctx.db
    with factory() as session:
        create_user(session, "victim2", hash_password("t3stP@ssw0rd"))
        session.commit()

    victim_client = TestClient(client.app, cookies={})
    victim_client.post(
        "/api/auth/login",
        json={"username": "victim2", "password": "t3stP@ssw0rd"},
    )

    session_cache: SessionCache = client.app.state.session_cache
    victim_id = _get_user_id(client, "victim2")
    from songmaker_cli.constants import REDIS_USER_SESSIONS_PREFIX
    redis = client.app.state.ctx.redis
    sids = redis.smembers(f"{REDIS_USER_SESSIONS_PREFIX}:{victim_id}")
    assert len(sids) >= 1
    sid = list(sids)[0]

    sessions_resp = client.get("/api/admin/sessions")
    victim_sessions = [
        s for s in sessions_resp.json()["items"] if s["username"] == "victim2"
    ]
    session_hash = victim_sessions[0]["id"]

    client.delete(f"/api/admin/sessions/{session_hash}")

    assert session_cache.get(sid) is None


def test_update_user_role_clears_redis(client: TestClient) -> None:
    from conftest import login_and_csrf

    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "bob", "password": "t3stP@ssw0rd"},
    )
    bob_id = resp.json()["id"]

    bob_client = TestClient(client.app, cookies={})
    login_and_csrf(bob_client, "bob", "t3stP@ssw0rd")

    from songmaker_cli.constants import REDIS_USER_SESSIONS_PREFIX
    redis = client.app.state.ctx.redis
    sids = redis.smembers(f"{REDIS_USER_SESSIONS_PREFIX}:{bob_id}")
    assert len(sids) >= 1

    client.put(f"/api/admin/users/{bob_id}", json={"role": "admin"})

    sids_after = redis.smembers(f"{REDIS_USER_SESSIONS_PREFIX}:{bob_id}")
    assert len(sids_after) == 0

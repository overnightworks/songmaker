"""Tests for auth API endpoints — setup, login, logout, me, password change."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import MagicMock

import pytest
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
    output_dir = tmp_path / "_output"
    output_dir.mkdir()
    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Songmaker</html>")

    factory = init_db(output_dir / "songmaker.db")
    ctx = AppContext(db=factory, output_dir=output_dir, session_secret=_TEST_SECRET)
    app = create_app(output_dir, project_root, ctx=ctx)
    yield TestClient(app, cookies={})


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
    from songmaker_cli.auth import LOGIN_LOCKOUT_THRESHOLD
    from songmaker_cli.db.queries import record_login_attempt
    _seed_admin(client)
    factory = client.app.state.ctx.db
    with factory() as session:
        for _ in range(LOGIN_LOCKOUT_THRESHOLD):
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

    ctx = AppContext(db=MagicMock(), output_dir=Path("/tmp"), session_secret=b"x" * 32)
    assert _detect_secure(None, ctx) is False

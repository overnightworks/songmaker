"""Tests for admin API endpoints — user CRUD, sessions, login attempts."""

from __future__ import annotations

from pathlib import Path

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


def _make_urlopen_mock(payloads: list[bytes]):
    """Return a side_effect list of context-manager mocks, one per urlopen call."""
    from unittest.mock import MagicMock

    mocks = []
    for payload in payloads:
        cm = MagicMock()
        cm.__enter__ = lambda self, p=payload: _make_read_mock(p)
        cm.__exit__ = MagicMock(return_value=False)
        mocks.append(cm)
    return mocks


def _make_read_mock(payload: bytes):
    from unittest.mock import MagicMock

    m = MagicMock()
    m.read.return_value = payload
    return m


def test_reinitialize_acestep_success(client: TestClient) -> None:
    import json
    from unittest.mock import MagicMock, patch

    _login_as_admin(client)

    cm = MagicMock()
    cm.__enter__ = lambda self: _make_read_mock(json.dumps({"code": 200}).encode())
    cm.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=cm):
        resp = client.post("/api/admin/acestep/reinitialize")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_reinitialize_acestep_error_response(client: TestClient) -> None:
    import json
    from unittest.mock import MagicMock, patch

    _login_as_admin(client)

    cm = MagicMock()
    cm.__enter__ = lambda self: _make_read_mock(
        json.dumps({"code": 500, "error": "model not loaded"}).encode()
    )
    cm.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=cm):
        resp = client.post("/api/admin/acestep/reinitialize")

    assert resp.status_code == 502
    assert resp.json()["detail"] == "ACE-Step returned an error"


def test_reinitialize_acestep_connection_failure(client: TestClient) -> None:
    from unittest.mock import patch

    _login_as_admin(client)

    with patch(
        "urllib.request.urlopen",
        side_effect=OSError("connection refused"),
    ):
        resp = client.post("/api/admin/acestep/reinitialize")

    assert resp.status_code == 502
    assert "unreachable" in resp.json()["detail"]


# -- ACE-Step status ----------------------------------------------------------


def test_acestep_status_online(client: TestClient) -> None:
    import json
    from unittest.mock import MagicMock, patch

    _login_as_admin(client)

    health_payload = json.dumps(
        {"data": {"loaded_model": "turbo", "loaded_lm_model": "small"}}
    ).encode()
    stats_payload = json.dumps({"data": {"jobs": {"pending": 0, "running": 1}}}).encode()

    call_count = 0

    def fake_urlopen(req, timeout=None):
        nonlocal call_count
        payload = health_payload if call_count == 0 else stats_payload
        call_count += 1
        cm = MagicMock()
        cm.__enter__ = lambda self, p=payload: _make_read_mock(p)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        resp = client.get("/api/admin/acestep/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["online"] is True
    assert data["model"] == "turbo"
    assert data["lm_model"] == "small"
    assert data["jobs"] == {"pending": 0, "running": 1}


def test_acestep_status_offline(client: TestClient) -> None:
    from unittest.mock import patch

    _login_as_admin(client)

    with patch(
        "urllib.request.urlopen",
        side_effect=OSError("connection refused"),
    ):
        resp = client.get("/api/admin/acestep/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["online"] is False
    assert data["model"] is None
    assert data["lm_model"] is None
    assert data["jobs"] == {}

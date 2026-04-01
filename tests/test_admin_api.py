"""Tests for admin API endpoints — user CRUD, sessions, login attempts."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_test_app
from fastapi.testclient import TestClient

from songmaker_cli.auth import hash_password
from songmaker_cli.db.queries import create_user
from songmaker_cli.middleware import SESSION_COOKIE


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    client, _ = make_test_app(tmp_path)
    yield client


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
    from songmaker_cli.constants import ARQ_MUSIC_QUEUE_NAME
    mock_pool.enqueue_job.assert_called_once_with(
        "reinitialize_acestep", _queue_name=ARQ_MUSIC_QUEUE_NAME,
    )


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


# -- Hard delete user ---------------------------------------------------------


def _create_user_with_data(client: TestClient, username: str) -> str:
    """Create a user with an album, song, and generation. Returns user_id."""
    factory = client.app.state.ctx.db
    audio_dir = client.app.state.ctx.audio_dir

    with factory() as session:
        from songmaker_cli.db.queries import (
            create_album,
            create_generation,
            create_playlist,
            create_song,
        )

        user = create_user(session, username, hash_password("t3stP@ssw0rd"))
        album = create_album(session, f"{username}-album", "Test Album", created_by=user.id)
        song = create_song(session, "Test Song", album.id)
        mp3_rel = f"{user.id}/{song.id}.mp3"
        wav_rel = f"{user.id}/{song.id}.wav"
        create_generation(session, song.id, None, mp3_rel, wav_path=wav_rel)
        create_playlist(session, "User Playlist", user.id)
        session.commit()

        mp3_path = audio_dir / mp3_rel
        mp3_path.parent.mkdir(parents=True, exist_ok=True)
        mp3_path.write_bytes(b"fake-mp3")
        (audio_dir / wav_rel).write_bytes(b"fake-wav")

        return user.id


def test_hard_delete_user(client: TestClient) -> None:
    _login_as_admin(client)
    user_id = _create_user_with_data(client, "victim")
    audio_dir = client.app.state.ctx.audio_dir

    resp = client.delete(f"/api/admin/users/{user_id}/permanent")
    assert resp.status_code == 200

    users = client.get("/api/admin/users").json()
    assert not any(u["id"] == user_id for u in users)

    factory = client.app.state.ctx.db
    with factory() as session:
        from songmaker_cli.db.queries import get_user, list_albums

        assert get_user(session, user_id) is None
        user_albums = [a for a in list_albums(session) if a.created_by == user_id]
        assert len(user_albums) == 0
        from songmaker_cli.db.queries import list_playlists
        assert len(list_playlists(session, user_id)) == 0

    assert not (audio_dir / user_id).exists()


def test_hard_delete_user_no_data(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "empty", "password": "t3stP@ssw0rd"},
    )
    user_id = resp.json()["id"]

    resp = client.delete(f"/api/admin/users/{user_id}/permanent")
    assert resp.status_code == 200

    users = client.get("/api/admin/users").json()
    assert not any(u["id"] == user_id for u in users)


def test_hard_delete_preserves_audit_log(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "audited", "password": "t3stP@ssw0rd"},
    )
    user_id = resp.json()["id"]

    resp = client.delete(f"/api/admin/users/{user_id}/permanent")
    assert resp.status_code == 200

    audit = client.get("/api/admin/audit-log").json()
    delete_entries = [
        e for e in audit["items"]
        if e["action"] == "hard_delete" and e["resource_id"] == user_id
    ]
    assert len(delete_entries) == 1
    assert "username=audited" in delete_entries[0]["detail"]


def test_hard_delete_self_blocked(client: TestClient) -> None:
    _login_as_admin(client)
    me = client.get("/api/auth/me").json()
    resp = client.delete(f"/api/admin/users/{me['id']}/permanent")
    assert resp.status_code == 400


def test_hard_delete_last_admin_blocked(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "admin2", "password": "t3stP@ssw0rd", "role": "admin"},
    )
    admin2_id = resp.json()["id"]

    client.put(f"/api/admin/users/{admin2_id}", json={"is_active": False})

    resp = client.delete(f"/api/admin/users/{admin2_id}/permanent")
    assert resp.status_code == 400
    assert "last active admin" in resp.json()["detail"]


def test_hard_delete_non_last_admin_allowed(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "admin2", "password": "t3stP@ssw0rd", "role": "admin"},
    )
    admin2_id = resp.json()["id"]

    resp = client.delete(f"/api/admin/users/{admin2_id}/permanent")
    assert resp.status_code == 200

    users = client.get("/api/admin/users").json()
    assert not any(u["id"] == admin2_id for u in users)


def test_hard_delete_not_found(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.delete("/api/admin/users/nonexistent/permanent")
    assert resp.status_code == 404

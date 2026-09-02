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
        song = create_song(session, "Test Song", album.id, slug="test-song")
        mp3_rel = f"{user.id}/{song.id}.mp3"
        wav_rel = f"{user.id}/{song.id}.wav"
        create_generation(
            session, song.id, None, mp3_rel, model_mode="sft", wav_path=wav_rel,
        )
        create_playlist(session, "User Playlist", user.id, slug="user-playlist")
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


# -- Worker pool / registry ---------------------------------------------------


def _seed_worker(client: TestClient, worker_id: str, **kwargs) -> None:
    from songmaker_cli.db.queries import register_worker

    factory = client.app.state.ctx.db
    with factory() as session:
        register_worker(
            session,
            worker_id=worker_id,
            host=kwargs.get("host", worker_id),
            port=kwargs.get("port", 8001),
            gpu_id=kwargs.get("gpu_id", 0),
            vram_total_gb=kwargs.get("vram_total_gb", 24.0),
        )
        session.commit()


class _InMemoryAsyncRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value, ex: int | None = None) -> None:
        self._store[key] = value

    async def incr(self, key: str) -> int:
        cur = int(self._store.get(key, 0)) + 1
        self._store[key] = str(cur)
        return cur

    async def decr(self, key: str) -> int:
        cur = int(self._store.get(key, 0)) - 1
        self._store[key] = str(cur)
        return cur


def _override_pool(client: TestClient, pool) -> None:
    from songmaker_cli.arq_pool import get_arq_pool_dep
    client.app.dependency_overrides[get_arq_pool_dep] = lambda: pool


def _make_fake_pool() -> _InMemoryAsyncRedis:
    return _InMemoryAsyncRedis()


def test_list_workers_empty(client: TestClient) -> None:
    _login_as_admin(client)
    _override_pool(client, _make_fake_pool())
    resp = client.get("/api/admin/workers")
    assert resp.status_code == 200
    assert resp.json() == {"workers": []}


def test_list_workers_online(client: TestClient) -> None:
    import json

    from songmaker_cli.acestep_state import worker_state_key

    _login_as_admin(client)
    _seed_worker(client, "acestep-worker-0")
    pool = _make_fake_pool()
    state = {
        "loaded": [{"mode": "sft", "size_gb": 6.0}],
        "target_loading": None,
        "loading_started_at": None,
        "vram_used_gb": 12.4,
        "vram_total_gb": 24.0,
        "available_modes": ["sft", "turbo"],
        "pinned": [],
        "last_heartbeat_at": "2026-04-07T12:00:00+00:00",
        "gpu_healthy": True,
    }
    pool._store[worker_state_key("acestep-worker-0")] = json.dumps(state)
    _override_pool(client, pool)

    resp = client.get("/api/admin/workers")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["workers"]) == 1
    w = data["workers"][0]
    assert w["identity"]["id"] == "acestep-worker-0"
    assert w["status"] == "online"
    assert w["state"]["loaded"] == [{"mode": "sft", "size_gb": 6.0}]
    assert w["state"]["available_modes"] == ["sft", "turbo"]
    assert w["state"]["pinned"] == []
    assert w["state"]["loading_last_log_line"] is None


def test_list_workers_propagates_loading_last_log_line(client: TestClient) -> None:
    import json

    from songmaker_cli.acestep_state import worker_state_key

    _login_as_admin(client)
    _seed_worker(client, "w1")
    pool = _make_fake_pool()
    pool._store[worker_state_key("w1")] = json.dumps(
        {
            "loaded": [],
            "target_loading": "xl-turbo",
            "loading_last_log_line": "vllm: loading shard 3/4",
            "gpu_healthy": True,
        },
    )
    _override_pool(client, pool)

    resp = client.get("/api/admin/workers")
    state = resp.json()["workers"][0]["state"]
    assert state["loading_last_log_line"] == "vllm: loading shard 3/4"


def test_list_workers_loading(client: TestClient) -> None:
    import json

    from songmaker_cli.acestep_state import worker_state_key

    _login_as_admin(client)
    _seed_worker(client, "w1")
    pool = _make_fake_pool()
    pool._store[worker_state_key("w1")] = json.dumps(
        {"loaded": [], "target_loading": "xl-sft", "gpu_healthy": True},
    )
    _override_pool(client, pool)

    resp = client.get("/api/admin/workers")
    assert resp.json()["workers"][0]["status"] == "loading"


def test_list_workers_offline_when_redis_missing(client: TestClient) -> None:
    _login_as_admin(client)
    _seed_worker(client, "w1")
    _override_pool(client, _make_fake_pool())
    resp = client.get("/api/admin/workers")
    data = resp.json()
    assert data["workers"][0]["status"] == "offline"
    assert data["workers"][0]["state"] is None


def test_list_workers_offline_when_gpu_broken(client: TestClient) -> None:
    """Issue #367 finding 3: a worker whose GPU has gone away keeps
    heartbeating fine, so the worker pool must not show it as "online" on
    heartbeat presence alone — simulated NVML failure, not a lucky real
    GPU."""
    import json

    from songmaker_cli.acestep_state import worker_state_key

    _login_as_admin(client)
    _seed_worker(client, "w1")
    pool = _make_fake_pool()
    pool._store[worker_state_key("w1")] = json.dumps(
        {"loaded": ["sft"], "gpu_healthy": False},
    )
    _override_pool(client, pool)

    resp = client.get("/api/admin/workers")
    data = resp.json()
    assert data["workers"][0]["status"] == "offline"


def test_list_workers_includes_queue_depth(client: TestClient) -> None:
    import json

    from songmaker_cli.acestep_state import queue_depth_key, worker_state_key

    _login_as_admin(client)
    _seed_worker(client, "w1")
    pool = _make_fake_pool()
    pool._store[worker_state_key("w1")] = json.dumps({"loaded": ["sft"]})
    pool._store[queue_depth_key("w1")] = "3"
    _override_pool(client, pool)

    resp = client.get("/api/admin/workers")
    assert resp.json()["workers"][0]["state"]["queue_depth"] == 3


def test_registry_union_across_workers(client: TestClient) -> None:
    import json

    from songmaker_cli.acestep_state import worker_state_key

    _login_as_admin(client)
    _seed_worker(client, "w1")
    _seed_worker(client, "w2")
    pool = _make_fake_pool()
    pool._store[worker_state_key("w1")] = json.dumps(
        {
            "loaded": ["sft"], "target_loading": None, "available_modes": ["sft"],
            "gpu_healthy": True,
        },
    )
    pool._store[worker_state_key("w2")] = json.dumps(
        {
            "loaded": [], "target_loading": "turbo", "available_modes": ["turbo"],
            "gpu_healthy": True,
        },
    )
    _override_pool(client, pool)

    resp = client.get("/api/admin/registry")
    assert resp.status_code == 200
    by_mode = {m["mode"]: m for m in resp.json()["models"]}
    assert by_mode["sft"]["availability"] == "downloaded"
    assert by_mode["sft"]["loaded_on"] == ["w1"]
    assert by_mode["sft"]["loading_on"] == []
    assert by_mode["turbo"]["availability"] == "downloaded"
    assert by_mode["turbo"]["loaded_on"] == []
    assert by_mode["turbo"]["loading_on"] == ["w2"]
    assert by_mode["xl-sft"]["availability"] == "not_downloaded"


def test_registry_unknown_availability_when_only_worker_gpu_broken(
    client: TestClient,
) -> None:
    """Same as "no worker online" (issue #252) — a worker whose only
    heartbeat says gpu_healthy: false must not make the registry think a
    real worker is answering."""
    import json

    from songmaker_cli.acestep_state import worker_state_key

    _login_as_admin(client)
    _seed_worker(client, "w1")
    pool = _make_fake_pool()
    pool._store[worker_state_key("w1")] = json.dumps(
        {"loaded": ["sft"], "available_modes": ["sft"], "gpu_healthy": False},
    )
    _override_pool(client, pool)

    resp = client.get("/api/admin/registry")
    assert resp.status_code == 200
    availabilities = {m["availability"] for m in resp.json()["models"]}
    assert availabilities == {"unknown_no_worker"}


def test_registry_unknown_availability_when_no_worker_online(client: TestClient) -> None:
    # The GPU worker sat on "Created" for five days without ever starting
    # (issue #252's live incident): the registry saw zero online workers and
    # called every model "not downloaded", as if the files were missing
    # rather than nobody being around to report on them. A model's download
    # state must read as unknown, not as a false negative, when no worker is
    # online to answer the question.
    _login_as_admin(client)
    _seed_worker(client, "w1")
    _override_pool(client, _make_pool_with_state({"w1": None}))

    resp = client.get("/api/admin/registry")
    assert resp.status_code == 200
    availabilities = {m["availability"] for m in resp.json()["models"]}
    assert availabilities == {"unknown_no_worker"}


def test_load_model_on_worker_enqueues_job(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    _login_as_admin(client)
    _seed_worker(client, "w1")

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(return_value=AsyncMock())

    with patch("songmaker_cli.arq_pool.get_arq_pool", return_value=mock_pool):
        resp = client.post(
            "/api/admin/workers/w1/load_model", json={"mode": "sft"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "load_model_on_worker"
    assert data["status"] == "queued"
    from songmaker_cli.constants import ARQ_MUSIC_QUEUE_NAME
    mock_pool.enqueue_job.assert_called_once_with(
        "load_model_on_worker", data["id"], "w1", "sft",
        _queue_name=ARQ_MUSIC_QUEUE_NAME,
    )


def test_load_model_on_worker_unknown_worker(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/workers/missing/load_model", json={"mode": "sft"},
    )
    assert resp.status_code == 404


def test_load_model_on_worker_unknown_mode(client: TestClient) -> None:
    _login_as_admin(client)
    _seed_worker(client, "w1")
    resp = client.post(
        "/api/admin/workers/w1/load_model", json={"mode": "bogus"},
    )
    assert resp.status_code == 400


def test_load_model_on_worker_queue_unavailable(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    _login_as_admin(client)
    _seed_worker(client, "w1")

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(side_effect=ConnectionError("redis down"))

    with patch("songmaker_cli.arq_pool.get_arq_pool", return_value=mock_pool):
        resp = client.post(
            "/api/admin/workers/w1/load_model", json={"mode": "sft"},
        )
    assert resp.status_code == 503


def test_evict_model_proxies_to_worker(client: TestClient) -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    _login_as_admin(client)
    _seed_worker(client, "w1", host="example", port=8001)

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=fake_client):
        resp = client.post(
            "/api/admin/workers/w1/evict_model", json={"mode": "sft"},
        )

    assert resp.status_code == 200
    fake_client.post.assert_called_once()
    args, kwargs = fake_client.post.call_args
    assert args[0] == "http://example:8001/evict_model"
    assert kwargs["json"] == {"mode": "sft"}


def test_evict_model_unknown_worker(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/workers/missing/evict_model", json={"mode": "sft"},
    )
    assert resp.status_code == 404


def test_evict_model_unknown_mode(client: TestClient) -> None:
    _login_as_admin(client)
    _seed_worker(client, "w1")
    resp = client.post(
        "/api/admin/workers/w1/evict_model", json={"mode": "bogus"},
    )
    assert resp.status_code == 400


def test_evict_model_worker_unreachable(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    import httpx

    _login_as_admin(client)
    _seed_worker(client, "w1")

    fake_client = AsyncMock()
    fake_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=fake_client):
        resp = client.post(
            "/api/admin/workers/w1/evict_model", json={"mode": "sft"},
        )
    assert resp.status_code == 502


def test_evict_model_worker_returns_4xx(client: TestClient) -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    _login_as_admin(client)
    _seed_worker(client, "w1")

    fake_response = MagicMock()
    fake_response.status_code = 500
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=fake_client):
        resp = client.post(
            "/api/admin/workers/w1/evict_model", json={"mode": "sft"},
        )
    assert resp.status_code == 502


# ── pin_model_on_worker_endpoint ────────────────────────────────────


def test_pin_model_on_worker_success(client: TestClient) -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    _login_as_admin(client)
    _seed_worker(client, "w1")

    fake_response = MagicMock(status_code=200)
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=fake_client):
        resp = client.post(
            "/api/admin/workers/w1/pin_model", json={"mode": "sft"},
        )
    assert resp.status_code == 200
    args, kwargs = fake_client.post.call_args
    assert args[0].endswith("/pin_model")
    assert kwargs["json"] == {"mode": "sft"}


def test_pin_model_unknown_worker(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/workers/missing/pin_model", json={"mode": "sft"},
    )
    assert resp.status_code == 404


def test_pin_model_unknown_mode(client: TestClient) -> None:
    _login_as_admin(client)
    _seed_worker(client, "w1")
    resp = client.post(
        "/api/admin/workers/w1/pin_model", json={"mode": "bogus"},
    )
    assert resp.status_code == 400


def test_pin_model_worker_409_passes_through(client: TestClient) -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    _login_as_admin(client)
    _seed_worker(client, "w1")

    fake_response = MagicMock(status_code=409)
    fake_response.json = MagicMock(return_value={"detail": "Cannot pin sft: not loaded"})
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=fake_client):
        resp = client.post(
            "/api/admin/workers/w1/pin_model", json={"mode": "sft"},
        )
    assert resp.status_code == 409
    assert "not loaded" in resp.json()["detail"]


def test_pin_model_worker_unreachable(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    import httpx

    _login_as_admin(client)
    _seed_worker(client, "w1")

    fake_client = AsyncMock()
    fake_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=fake_client):
        resp = client.post(
            "/api/admin/workers/w1/pin_model", json={"mode": "sft"},
        )
    assert resp.status_code == 502


def test_pin_model_requires_admin(client: TestClient) -> None:
    resp = client.post("/api/admin/workers/w1/pin_model", json={"mode": "sft"})
    assert resp.status_code in (401, 403)


# ── unpin_model_on_worker_endpoint ──────────────────────────────────


def test_unpin_model_on_worker_success(client: TestClient) -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    _login_as_admin(client)
    _seed_worker(client, "w1")

    fake_response = MagicMock(status_code=200)
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=fake_client):
        resp = client.post(
            "/api/admin/workers/w1/unpin_model", json={"mode": "sft"},
        )
    assert resp.status_code == 200
    args, _ = fake_client.post.call_args
    assert args[0].endswith("/unpin_model")


def test_unpin_model_unknown_worker(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/workers/missing/unpin_model", json={"mode": "sft"},
    )
    assert resp.status_code == 404


def test_unpin_model_unknown_mode(client: TestClient) -> None:
    _login_as_admin(client)
    _seed_worker(client, "w1")
    resp = client.post(
        "/api/admin/workers/w1/unpin_model", json={"mode": "bogus"},
    )
    assert resp.status_code == 400


# ── restart_worker_endpoint ─────────────────────────────────────────


def test_restart_worker_success(client: TestClient) -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    _login_as_admin(client)
    _seed_worker(client, "w1")

    fake_response = MagicMock(status_code=200)
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=fake_client):
        resp = client.post("/api/admin/workers/w1/restart")
    assert resp.status_code == 200
    assert resp.json()["status"] == "restarting"
    args, _ = fake_client.post.call_args
    assert args[0].endswith("/restart")


def test_restart_worker_unknown_worker(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post("/api/admin/workers/missing/restart")
    assert resp.status_code == 404


def test_restart_worker_unreachable(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    import httpx

    _login_as_admin(client)
    _seed_worker(client, "w1")

    fake_client = AsyncMock()
    fake_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=fake_client):
        resp = client.post("/api/admin/workers/w1/restart")
    assert resp.status_code == 502
    # The restart button is the one thing someone reaches for on a dead
    # worker; it must say why it can't help instead of relaying a bare
    # connection error (issue #252).
    detail = resp.json()["detail"]
    assert "can't be asked to restart itself" in detail
    assert "restart the container directly" in detail.lower()


def test_restart_worker_requires_admin(client: TestClient) -> None:
    resp = client.post("/api/admin/workers/w1/restart")
    assert resp.status_code in (401, 403)


# ── download_model_endpoint ─────────────────────────────────────────


def _make_pool_with_state(
    states: dict[str, dict | None], *, gpu_healthy: bool = True,
) -> object:
    """Defaults every present worker's heartbeat to a healthy GPU so the
    many download-endpoint tests unrelated to issue #367 don't need to know
    about it. A state dict that already carries "gpu_healthy" (e.g. to
    simulate a broken worker) is never overridden."""
    import json

    from songmaker_cli.acestep_state import worker_state_key

    pool = _make_fake_pool()
    for wid, state in states.items():
        if state is not None:
            payload = dict(state)
            payload.setdefault("gpu_healthy", gpu_healthy)
            pool._store[worker_state_key(wid)] = json.dumps(payload)
    return pool


def test_download_endpoint_unknown_mode(client: TestClient) -> None:
    _login_as_admin(client)
    _seed_worker(client, "w1")
    _override_pool(client, _make_pool_with_state({"w1": {"available_modes": []}}))
    resp = client.post("/api/admin/registry/ghost/download")
    assert resp.status_code == 400


def test_download_endpoint_no_workers(client: TestClient) -> None:
    _login_as_admin(client)
    _seed_worker(client, "w1")
    _override_pool(client, _make_pool_with_state({"w1": None}))
    resp = client.post("/api/admin/registry/sft/download")
    assert resp.status_code == 503


def test_download_endpoint_no_workers_when_gpu_broken(client: TestClient) -> None:
    """Issue #367 finding 3: the download precheck must not treat a
    heartbeating-but-GPU-broken worker as available — it would otherwise
    fail asynchronously later with a generic "no workers", exactly the
    delayed-symptom pattern from issue #252."""
    _login_as_admin(client)
    _seed_worker(client, "w1")
    _override_pool(
        client,
        _make_pool_with_state({"w1": {"available_modes": [], "gpu_healthy": False}}),
    )
    resp = client.post("/api/admin/registry/sft/download")
    assert resp.status_code == 503
    assert "No online workers available to download" in resp.json()["detail"]


def test_download_endpoint_already_downloaded(client: TestClient) -> None:
    _login_as_admin(client)
    _seed_worker(client, "w1")
    _override_pool(
        client,
        _make_pool_with_state({"w1": {"available_modes": ["sft", "turbo"]}}),
    )
    resp = client.post("/api/admin/registry/sft/download")
    assert resp.status_code == 409
    assert "already downloaded" in resp.json()["detail"]


def test_download_endpoint_already_in_progress(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    from songmaker_cli.acestep_state import download_key

    _login_as_admin(client)
    _seed_worker(client, "w1")
    pool = _make_pool_with_state({"w1": {"available_modes": []}})
    pool._store[download_key("xl-base")] = "previous-job-id"
    _override_pool(client, pool)

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(return_value=AsyncMock())
    with patch("songmaker_cli.arq_pool.get_arq_pool", return_value=mock_pool):
        resp = client.post("/api/admin/registry/xl-base/download")

    assert resp.status_code == 409
    assert "already being downloaded" in resp.json()["detail"]
    mock_pool.enqueue_job.assert_not_called()


def test_download_endpoint_enqueues_job(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    _login_as_admin(client)
    _seed_worker(client, "w1")
    _override_pool(client, _make_pool_with_state({"w1": {"available_modes": []}}))

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(return_value=AsyncMock())
    with patch("songmaker_cli.arq_pool.get_arq_pool", return_value=mock_pool):
        resp = client.post("/api/admin/registry/xl-base/download")

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "download_model_on_worker"
    assert data["status"] == "queued"

    from songmaker_cli.constants import ARQ_MUSIC_QUEUE_NAME
    mock_pool.enqueue_job.assert_called_once_with(
        "download_model_on_worker", data["id"], "xl-base",
        _queue_name=ARQ_MUSIC_QUEUE_NAME,
    )


def test_download_endpoint_queue_unavailable(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    _login_as_admin(client)
    _seed_worker(client, "w1")
    _override_pool(client, _make_pool_with_state({"w1": {"available_modes": []}}))

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(side_effect=ConnectionError("redis down"))
    with patch("songmaker_cli.arq_pool.get_arq_pool", return_value=mock_pool):
        resp = client.post("/api/admin/registry/xl-base/download")

    assert resp.status_code == 503


def test_download_endpoint_requires_admin(client: TestClient) -> None:
    resp = client.post("/api/admin/registry/sft/download")
    assert resp.status_code in (401, 403)


# -- Generation retention -----------------------------------------------------


def _seed_album_with_gens(client: TestClient) -> None:
    from songmaker_cli.db.models import Album, Generation, Song, Version
    factory = client.app.state.ctx.db
    with factory() as session:
        session.add(Album(id="a1", title="A", artist="X"))
        session.add(Song(id="s1", title="S", album_id="a1", track_number=1))
        session.add(
            Version(id="v1", song_id="s1", version_number=1, lyrics="", prompt=""),
        )
        session.add(
            Generation(
                id="g1", song_id="s1", version_id="v1",
                generation_number=1, mp3_path="a1/1.mp3",
            ),
        )
        session.commit()


def test_retention_preview_requires_admin(client: TestClient) -> None:
    resp = client.get("/api/admin/generation-retention/preview")
    assert resp.status_code in (401, 403)


def test_retention_run_requires_admin(client: TestClient) -> None:
    resp = client.post("/api/admin/generation-retention/run")
    assert resp.status_code in (401, 403)


def test_retention_preview_returns_counts(client: TestClient) -> None:
    _login_as_admin(client)
    _seed_album_with_gens(client)

    resp = client.get("/api/admin/generation-retention/preview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert "archived_ids" in body
    assert "deleted_ids" in body
    assert body["retention_days"] >= 1
    assert body["hard_delete_days"] >= 1


def test_retention_run_executes(client: TestClient) -> None:
    from datetime import datetime, timedelta, timezone

    from songmaker_cli.db.models import Generation

    _login_as_admin(client)
    _seed_album_with_gens(client)
    factory = client.app.state.ctx.db
    with factory() as session:
        gen = session.get(Generation, "g1")
        gen.created_at = datetime.now(timezone.utc) - timedelta(days=365)
        session.commit()

    resp = client.post("/api/admin/generation-retention/run")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is False
    assert "g1" in body["archived_ids"]

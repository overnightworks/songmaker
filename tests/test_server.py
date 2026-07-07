"""Tests for the songmaker server."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from conftest import TEST_SECRET, login_and_csrf, make_fake_redis, make_test_app
from fastapi.testclient import TestClient

from songmaker_cli.app_context import AppContext
from songmaker_cli.auth import hash_password, sign_session_id
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import Album, Generation, Score, Song, User, Version
from songmaker_cli.server import create_app, parse_allowed_hosts, run_server

_ADMIN_ID = "admin-user-id"


def _seed_server_data(session) -> None:
    admin = User(
        id=_ADMIN_ID, username="admin",
        password_hash=hash_password("admin12345"), role="admin",
    )
    session.add(admin)
    session.add(Album(id="test_album", title="Test", artist="Test"))
    session.add(Song(id="s1", title="Song", album_id="test_album", track_number=1))
    session.add(Version(id="v1", song_id="s1", version_number=1, lyrics="Hello"))
    session.add(Generation(
        id="g1", song_id="s1", version_id="v1", generation_number=1,
        mp3_path=f"{_ADMIN_ID}/g1.mp3", seed=42,
    ))
    session.add(Score(id="sc1", generation_id="g1", scorer="batch", value={"dynamics": 48.9}))


@pytest.fixture()
def server_app(tmp_path: Path) -> TestClient:
    client, _ = make_test_app(tmp_path, seed_db=_seed_server_data)
    audio_dir = tmp_path / "audio"
    user_dir = audio_dir / _ADMIN_ID
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "g1.mp3").write_bytes(b"\xff\xfb\x90\x00" * 100)
    login_and_csrf(client, "admin", "admin12345")
    yield client


def test_get_player(server_app: TestClient) -> None:
    resp = server_app.get("/")
    assert resp.status_code == 200
    assert "Songmaker" in resp.text


def test_security_headers(server_app: TestClient) -> None:
    resp = server_app.get("/")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in resp.headers["Permissions-Policy"]


def test_get_audio(server_app: TestClient) -> None:
    resp = server_app.get("/audio/admin-user-id/g1.mp3")
    assert resp.status_code == 200


def test_get_audio_supports_range_requests(server_app: TestClient) -> None:
    resp = server_app.get(
        "/audio/admin-user-id/g1.mp3",
        headers={"Range": "bytes=0-3"},
    )
    assert resp.status_code == 206
    assert resp.headers["Accept-Ranges"] == "bytes"
    assert resp.headers["Content-Range"] == "bytes 0-3/400"
    assert resp.content == b"\xff\xfb\x90\x00"


def test_get_audio_not_found(server_app: TestClient) -> None:
    resp = server_app.get("/audio/admin-user-id/nonexistent.mp3")
    assert resp.status_code == 404


def test_api_songs(server_app: TestClient) -> None:
    resp = server_app.get("/api/songs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["total"] == 1


def test_create_app_mounts_sveltekit_app(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    project_root = tmp_path
    sk_dir = project_root / "frontend" / "build"
    sk_app_dir = sk_dir / "_app"
    sk_app_dir.mkdir(parents=True)
    (sk_app_dir / "dummy.js").write_text("// chunk")
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        session.commit()

    ctx = AppContext(
        db=factory,
        audio_dir=audio_dir,
        data_dir=data_dir,
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    app = create_app(audio_dir, data_dir, project_root, ctx=ctx)
    client = TestClient(app)
    resp = client.get("/_app/dummy.js")
    assert resp.status_code == 200


def test_get_audio_path_traversal_denied(server_app: TestClient) -> None:
    resp = server_app.get("/audio/admin-user-id/..%2F..%2Fetc%2Fpasswd")
    assert resp.status_code in (403, 404)


def test_get_audio_path_traversal_via_symlink(tmp_path: Path) -> None:
    import os

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    (secret_dir / "data.mp3").write_bytes(b"\xff\xfb\x90\x00" * 10)

    admin_id = "symlink-admin-id"
    symlink_dir = audio_dir / admin_id
    os.symlink(str(secret_dir), str(symlink_dir))

    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        admin = User(
            id=admin_id, username="admin6",
            password_hash=hash_password("admin12345"), role="admin",
        )
        session.add(admin)
        session.commit()

    ctx = AppContext(
        db=factory,
        audio_dir=audio_dir,
        data_dir=data_dir,
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    app = create_app(audio_dir, data_dir, project_root, ctx=ctx)
    client = TestClient(app, cookies={})
    from conftest import login_and_csrf
    login_and_csrf(client, "admin6", "admin12345")
    resp = client.get(f"/audio/{admin_id}/data.mp3")
    assert resp.status_code == 403


@pytest.fixture()
def auth_server_app(tmp_path: Path):
    from songmaker_cli.db.queries import create_album, create_session, create_user
    from songmaker_cli.middleware import SESSION_COOKIE

    audio_dir = tmp_path / "audio"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Songmaker</html>")

    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        owner = create_user(session, "owner", hash_password("pass1234"))
        other = create_user(session, "other_user", hash_password("pass1234"))
        session.flush()

        owner_dir = audio_dir / owner.id
        owner_dir.mkdir(parents=True)
        (owner_dir / "song.mp3").write_bytes(b"\xff\xfb\x90\x00" * 100)

        other_dir = audio_dir / other.id
        other_dir.mkdir(parents=True)
        (other_dir / "other.mp3").write_bytes(b"\xff\xfb\x90\x00" * 100)

        create_album(session, "owned_album", "Owned Album", created_by=owner.id)
        create_album(session, "other_album", "Other Album", created_by=other.id)
        session.flush()

        expires = datetime.now(timezone.utc) + timedelta(days=30)
        owner_session = create_session(session, owner.id, expires)
        other_session = create_session(session, other.id, expires)
        session.commit()
        owner_sid = owner_session.id
        other_sid = other_session.id
        owner_id = owner.id
        other_id = other.id

    ctx = AppContext(
        db=factory,
        audio_dir=audio_dir,
        data_dir=data_dir,
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    app = create_app(audio_dir, data_dir, project_root, ctx=ctx)
    client = TestClient(app, cookies={})
    yield client, owner_sid, other_sid, SESSION_COOKIE, owner_id, other_id


def test_get_audio_own_files_allowed(auth_server_app) -> None:
    client, owner_sid, _other_sid, cookie_name, owner_id, _other_id = auth_server_app
    client.cookies.set(cookie_name, sign_session_id(owner_sid, TEST_SECRET))
    resp = client.get(f"/audio/{owner_id}/song.mp3")
    assert resp.status_code == 200


def test_get_audio_other_users_files_denied(auth_server_app) -> None:
    client, owner_sid, _other_sid, cookie_name, _owner_id, other_id = auth_server_app
    client.cookies.set(cookie_name, sign_session_id(owner_sid, TEST_SECRET))
    resp = client.get(f"/audio/{other_id}/other.mp3")
    assert resp.status_code == 404


def test_startup_cleans_expired_sessions(tmp_path: Path, mock_arq_pool) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Songmaker</html>")

    from songmaker_cli.db.queries import create_session as create_db_session

    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        user = User(username="tester", password_hash=hash_password("pass1234"))
        session.add(user)
        session.flush()
        expired = datetime.now(timezone.utc) - timedelta(days=1)
        create_db_session(session, user.id, expired)
        session.commit()

    with factory() as session:
        from songmaker_cli.db.models import UserSession
        assert session.query(UserSession).count() == 1

    ctx = AppContext(
        db=factory,
        audio_dir=audio_dir,
        data_dir=data_dir,
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    app = create_app(audio_dir, data_dir, project_root, ctx=ctx)
    with TestClient(app):
        pass

    with factory() as session:
        from songmaker_cli.db.models import UserSession
        assert session.query(UserSession).count() == 0


# ── run_server ──────────────────────────────────────────────────────


def test_run_server_calls_uvicorn(tmp_path: Path) -> None:
    mock_app = MagicMock()

    with (
        patch("uvicorn.run") as mock_uvicorn,
        patch("songmaker_cli.server.create_app", return_value=mock_app),
    ):
        run_server(project_root=tmp_path, port=9999)

    mock_uvicorn.assert_called_once()
    call_kwargs = mock_uvicorn.call_args
    assert call_kwargs.kwargs.get("port") == 9999


def test_run_server_defaults_to_localhost(tmp_path: Path) -> None:
    mock_app = MagicMock()

    with (
        patch("uvicorn.run") as mock_uvicorn,
        patch("songmaker_cli.server.create_app", return_value=mock_app),
    ):
        run_server(project_root=tmp_path, port=8080)

    _, kwargs = mock_uvicorn.call_args
    assert kwargs.get("host") == "127.0.0.1"


def test_run_server_opens_browser(tmp_path: Path) -> None:
    mock_app = MagicMock()

    with (
        patch("uvicorn.run"),
        patch("songmaker_cli.server.create_app", return_value=mock_app),
        patch("webbrowser.open") as mock_browser,
    ):
        run_server(project_root=tmp_path, open_browser=True)

    mock_browser.assert_called_once()


def test_run_server_creates_dirs(tmp_path: Path) -> None:
    from songmaker_cli.settings import get_settings

    settings = get_settings()
    mock_app = MagicMock()

    with (
        patch("uvicorn.run"),
        patch("songmaker_cli.server.create_app", return_value=mock_app),
    ):
        run_server(project_root=tmp_path)

    assert (tmp_path / settings.audio_dir).exists()
    assert (tmp_path / settings.data_dir).exists()


def test_run_server_infers_dirs_from_project_root(tmp_path: Path) -> None:
    from songmaker_cli.settings import get_settings

    settings = get_settings()
    mock_app = MagicMock()

    with (
        patch("uvicorn.run"),
        patch("songmaker_cli.server.create_app", return_value=mock_app) as mock_create,
        patch("songmaker_cli.server.find_project_root", return_value=tmp_path),
    ):
        run_server(project_root=None)

    call_args = mock_create.call_args
    assert call_args[0][0] == tmp_path / settings.audio_dir
    assert call_args[0][1] == tmp_path / settings.data_dir


def test_csrf_origin_check_rejects_cross_origin(server_app: TestClient) -> None:
    resp = server_app.post(
        "/api/songs",
        json={"title": "X", "album_id": "test_album"},
        headers={"origin": "http://evil.example.com", "host": "localhost:8080"},
    )
    assert resp.status_code == 403
    assert "Cross-origin" in resp.json()["detail"]


def test_csrf_rejects_form_submit_without_origin(server_app: TestClient) -> None:
    resp = server_app.post(
        "/api/songs",
        content=b"title=X&album_id=test_album",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 403
    assert "Missing Origin" in resp.json()["detail"]


def test_csrf_allows_json_without_origin(server_app: TestClient) -> None:
    resp = server_app.post(
        "/api/songs",
        json={"title": "X", "album_id": "test_album"},
    )
    assert resp.status_code == 200


def test_csrf_origin_check_allows_same_origin(server_app: TestClient) -> None:
    resp = server_app.post(
        "/api/songs",
        json={"title": "New Song", "album_id": "test_album"},
        headers={"origin": "http://localhost:8080"},
    )
    assert resp.status_code == 200


def test_csrf_rejects_spoofed_host_with_matching_origin(server_app: TestClient) -> None:
    resp = server_app.post(
        "/api/songs",
        json={"title": "X", "album_id": "test_album"},
        headers={"origin": "http://evil.com", "host": "evil.com"},
    )
    assert resp.status_code == 403


def test_csrf_allows_configured_allowed_host(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        admin = User(username="admin2", password_hash=hash_password("admin12345"), role="admin")
        session.add(admin)
        album = Album(id="a1", title="A", artist="A")
        session.add(album)
        session.commit()

    with patch.dict("os.environ", {"ALLOWED_HOSTS": "myapp.example.com"}):
        exact, patterns = parse_allowed_hosts()
        ctx = AppContext(
            db=factory,
            audio_dir=audio_dir,
            data_dir=data_dir,
            session_secret=TEST_SECRET,
            allowed_hosts_exact=exact,
            allowed_hosts_patterns=patterns,
            redis=make_fake_redis(),
        )
        app = create_app(audio_dir, data_dir, project_root, ctx=ctx)
        client = TestClient(app, cookies={})
        from conftest import login_and_csrf
        login_and_csrf(client, "admin2", "admin12345")

        resp = client.post(
            "/api/songs",
            json={"title": "X", "album_id": "a1"},
            headers={"origin": "https://myapp.example.com"},
        )
        assert resp.status_code == 200

        resp = client.post(
            "/api/songs",
            json={"title": "Y", "album_id": "a1"},
            headers={"origin": "https://evil.com"},
        )
        assert resp.status_code == 403


def test_cache_control_on_api_responses(server_app: TestClient) -> None:
    resp = server_app.get("/api/songs")
    assert resp.headers.get("Cache-Control") == "no-store"


def test_no_cache_control_on_non_api(server_app: TestClient) -> None:
    resp = server_app.get("/")
    assert "no-store" not in resp.headers.get("Cache-Control", "")


def test_body_size_limit_rejects_large_content_length(server_app: TestClient) -> None:
    resp = server_app.post(
        "/api/songs",
        content=b"{}",
        headers={"content-type": "application/json", "content-length": "999999999"},
    )
    assert resp.status_code == 413


def test_hsts_header_on_https(server_app: TestClient) -> None:
    server_app.app.state.ctx.trusted_proxies = frozenset({"testclient"})
    try:
        resp = server_app.get("/", headers={"x-forwarded-proto": "https"})
    finally:
        server_app.app.state.ctx.trusted_proxies = frozenset()
    assert "Strict-Transport-Security" in resp.headers
    assert "max-age=31536000" in resp.headers["Strict-Transport-Security"]


def test_hsts_header_not_set_without_trusted_proxy(server_app: TestClient) -> None:
    resp = server_app.get("/", headers={"x-forwarded-proto": "https"})
    assert "Strict-Transport-Security" not in resp.headers


def test_run_server_infers_project_root(tmp_path: Path) -> None:
    mock_app = MagicMock()

    with (
        patch("uvicorn.run"),
        patch("songmaker_cli.server.create_app", return_value=mock_app),
        patch("songmaker_cli.server.find_project_root", return_value=None),
    ):
        run_server(project_root=None)


def test_lifespan_connects_arq_pool(tmp_path: Path) -> None:
    from unittest.mock import AsyncMock

    from songmaker_cli.server import _lifespan

    factory = init_db(tmp_path / "test.db")
    mock_app = MagicMock()
    mock_app.state.ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )

    async def _run():
        with patch(
            "songmaker_cli.arq_pool.init_arq_pool",
            new_callable=AsyncMock,
        ) as mock_get, patch(
            "songmaker_cli.arq_pool.close_arq_pool",
            new_callable=AsyncMock,
        ) as mock_close:
            async with _lifespan(mock_app):
                pass
        mock_get.assert_called_once()
        mock_close.assert_called_once()

    asyncio.run(_run())


def test_lifespan_fails_on_redis_unavailable(tmp_path: Path) -> None:
    from unittest.mock import AsyncMock

    from songmaker_cli.server import _lifespan

    factory = init_db(tmp_path / "test.db")
    mock_app = MagicMock()
    mock_app.state.ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )

    async def _run():
        with patch(
            "songmaker_cli.arq_pool.init_arq_pool",
            new_callable=AsyncMock,
            side_effect=ConnectionError("no redis"),
        ), patch(
            "songmaker_cli.arq_pool.close_arq_pool",
            new_callable=AsyncMock,
        ), pytest.raises(ConnectionError):
            async with _lifespan(mock_app):
                pass

    asyncio.run(_run())


# ── BodySizeLimitMiddleware edge cases ─────────────────────────────


def test_body_size_limit_invalid_content_length(server_app: TestClient) -> None:
    resp = server_app.post(
        "/api/songs",
        content=b'{"title":"X","album_id":"test_album"}',
        headers={"content-type": "application/json", "content-length": "not-a-number"},
    )
    assert resp.status_code != 413


def test_body_size_streaming_too_large(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "10")

    from songmaker_cli.middleware.body_size import BodySizeLimitMiddleware

    async def dummy_app(scope, receive, send):
        await receive()
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [[b"content-type", b"text/plain"]],
        })
        await send({"type": "http.response.body", "body": b"ok"})

    if True:
        middleware = BodySizeLimitMiddleware(dummy_app)

        async def run():
            response_started = False
            status_code = None
            body_parts = []

            async def receive():
                return {"type": "http.request", "body": b"x" * 100, "more_body": False}

            async def send(msg):
                nonlocal response_started, status_code
                if msg["type"] == "http.response.start":
                    status_code = msg["status"]
                elif msg["type"] == "http.response.body":
                    body_parts.append(msg.get("body", b""))

            scope = {
                "type": "http",
                "method": "POST",
                "path": "/api/test",
                "headers": [],
            }
            await middleware(scope, receive, send)
            return status_code

        result = asyncio.run(run())
        assert result == 413


# ── CORS wildcard validation ───────────────────────────────────────


def test_cors_wildcard_invalid_raises(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(data_dir / "songmaker.db")
    ctx = AppContext(
        db=factory,
        audio_dir=audio_dir,
        data_dir=data_dir,
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )

    with patch.dict("os.environ", {"CORS_ORIGIN": "*."}):
        with pytest.raises(ValueError, match="Invalid CORS_ORIGIN"):
            create_app(audio_dir, data_dir, tmp_path, ctx=ctx)


def test_cors_specific_origin(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        session.commit()

    ctx = AppContext(
        db=factory,
        audio_dir=audio_dir,
        data_dir=data_dir,
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    with patch.dict("os.environ", {"CORS_ORIGIN": "https://mysite.example.com"}):
        app = create_app(audio_dir, data_dir, tmp_path, ctx=ctx)
    client = TestClient(app)
    resp = client.options(
        "/api/songs",
        headers={
            "origin": "https://mysite.example.com",
            "access-control-request-method": "GET",
        },
    )
    assert resp.status_code == 200


# ── Wildcard ALLOWED_HOSTS pattern ─────────────────────────────────


def test_wildcard_allowed_host_pattern(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        admin = User(username="admin4", password_hash=hash_password("admin12345"), role="admin")
        session.add(admin)
        album = Album(id="a1", title="A", artist="A")
        session.add(album)
        session.commit()

    with patch.dict("os.environ", {"ALLOWED_HOSTS": "*.trycloudflare.com"}):
        exact, patterns = parse_allowed_hosts()
        ctx = AppContext(
            db=factory,
            audio_dir=audio_dir,
            data_dir=data_dir,
            session_secret=TEST_SECRET,
            allowed_hosts_exact=exact,
            allowed_hosts_patterns=patterns,
            redis=make_fake_redis(),
        )
        app = create_app(audio_dir, data_dir, tmp_path, ctx=ctx)
        client = TestClient(app, cookies={})
        from conftest import login_and_csrf
        login_and_csrf(client, "admin4", "admin12345")

        resp = client.post(
            "/api/songs",
            json={"title": "X", "album_id": "a1"},
            headers={"origin": "https://abc.trycloudflare.com"},
        )
        assert resp.status_code == 200

        resp = client.post(
            "/api/songs",
            json={"title": "Y", "album_id": "a1"},
            headers={"origin": "https://evil.com"},
        )
        assert resp.status_code == 403


# ── parse_allowed_hosts ─────────────────────────────────────────────


def test_parse_allowed_hosts() -> None:
    with patch.dict("os.environ", {"ALLOWED_HOSTS": "example.com"}):
        exact, patterns = parse_allowed_hosts()
        assert "example.com" in exact


# ── IpRateLimitMiddleware ──────────────────────────────────────────


def test_ip_rate_limit_429(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("IP_RATE_LIMIT", "2")

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        session.commit()

    ctx = AppContext(
        db=factory,
        audio_dir=audio_dir,
        data_dir=data_dir,
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    app = create_app(audio_dir, data_dir, tmp_path, ctx=ctx)
    client = TestClient(app)
    for _ in range(3):
        resp = client.get("/api/auth/check")
    assert resp.status_code == 429
    assert "Too many requests" in resp.json()["detail"]


def test_static_assets_bypass_rate_limit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("IP_RATE_LIMIT", "2")

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    app_dir = sk_dir / "_app" / "immutable"
    app_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")
    (app_dir / "test.js").write_text("console.log('ok')")

    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        session.commit()

    ctx = AppContext(
        db=factory,
        audio_dir=audio_dir,
        data_dir=data_dir,
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    app = create_app(audio_dir, data_dir, tmp_path, ctx=ctx)
    client = TestClient(app)
    for _ in range(5):
        resp = client.get("/_app/immutable/test.js")
    assert resp.status_code == 200


# ── Audio endpoint edge cases ──────────────────────────────────────


def test_get_audio_other_user_id_denied(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    other_user_dir = audio_dir / "other-user-id"
    other_user_dir.mkdir(parents=True)
    (other_user_dir / "song.mp3").write_bytes(b"\xff\xfb\x90\x00" * 100)

    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        admin = User(username="admin5", password_hash=hash_password("admin12345"))
        session.add(admin)
        session.commit()

    ctx = AppContext(
        db=factory,
        audio_dir=audio_dir,
        data_dir=data_dir,
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    app = create_app(audio_dir, data_dir, project_root, ctx=ctx)
    client = TestClient(app, cookies={})
    from conftest import login_and_csrf
    login_and_csrf(client, "admin5", "admin12345")
    resp = client.get("/audio/other-user-id/song.mp3")
    assert resp.status_code == 404


# ── SPA fallback for API and audio paths ───────────────────────────


def test_spa_fallback_not_for_api(server_app: TestClient) -> None:
    resp = server_app.get("/api/nonexistent")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Not Found"


def test_spa_fallback_not_for_audio(server_app: TestClient) -> None:
    resp = server_app.get("/audio/nonexistent/song.mp3")
    assert resp.status_code in (401, 404)


# ── lifespan pruned login attempts log ──────────────────────────────


def test_startup_prunes_login_attempts(tmp_path: Path, mock_arq_pool) -> None:
    from songmaker_cli.db.models import LoginAttempt

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        old_time = datetime.now(timezone.utc) - timedelta(days=100)
        attempt = LoginAttempt(
            username="test", ip_address="127.0.0.1", success=False,
            attempted_at=old_time,
        )
        session.add(attempt)
        session.commit()

    with factory() as session:
        assert session.query(LoginAttempt).count() == 1

    ctx = AppContext(
        db=factory,
        audio_dir=audio_dir,
        data_dir=data_dir,
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    app = create_app(audio_dir, data_dir, tmp_path, ctx=ctx)
    with TestClient(app):
        pass

    with factory() as session:
        assert session.query(LoginAttempt).count() == 0


# ── structured logging configuration ──────────────────────────────


class TestConfigureLogging:
    def test_text_mode_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LOG_FORMAT", raising=False)
        from songmaker_cli.logging_config import configure_logging
        configure_logging()
        import logging
        root = logging.getLogger()
        assert root.handlers
        import structlog
        formatter = root.handlers[0].formatter
        assert isinstance(formatter, structlog.stdlib.ProcessorFormatter)
        last_processor = formatter.processors[-1]
        assert isinstance(last_processor, structlog.dev.ConsoleRenderer)

    def test_json_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_FORMAT", "json")
        from songmaker_cli.logging_config import configure_logging
        configure_logging()
        import logging
        root = logging.getLogger()
        assert root.handlers
        import structlog
        formatter = root.handlers[0].formatter
        assert isinstance(formatter, structlog.stdlib.ProcessorFormatter)
        last_processor = formatter.processors[-1]
        assert isinstance(last_processor, structlog.processors.JSONRenderer)


# ── health endpoint ──────────────────────────────────────────────


def test_health_no_auth_required(tmp_path: Path, mock_arq_pool) -> None:
    from unittest.mock import AsyncMock

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        admin = User(username="admin6", password_hash=hash_password("admin12345"), role="admin")
        session.add(admin)
        session.commit()

    redis = make_fake_redis()
    ctx = AppContext(
        db=factory, audio_dir=audio_dir, data_dir=data_dir, session_secret=TEST_SECRET, redis=redis,
    )
    app = create_app(audio_dir, data_dir, tmp_path, ctx=ctx)
    client = TestClient(app)

    with (
        client,
        patch("songmaker_cli.arq_pool.is_worker_healthy", AsyncMock(return_value=False)),
        patch("songmaker_cli.arq_pool.is_music_worker_healthy", AsyncMock(return_value=False)),
        patch("songmaker_cli.arq_pool.is_scoring_worker_healthy", AsyncMock(return_value=False)),
        patch("songmaker_cli.arq_pool.get_queue_depth", AsyncMock(return_value=0)),
        patch("songmaker_cli.arq_pool.get_music_queue_depth", AsyncMock(return_value=0)),
        patch("songmaker_cli.arq_pool.get_scoring_queue_depth", AsyncMock(return_value=0)),
    ):
        resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["db"] == "ok"
    assert data["worker"] == "stopped"
    assert data["music_worker"] == "stopped"
    assert data["scoring_worker"] == "stopped"
    assert data["queue_depth"] == 0
    assert data["acestep"] == "unknown"
    assert data["acestep_workers_total"] == 0
    assert data["acestep_workers_online"] == 0
    assert data["queue_depth_cap_reached"] is False
    assert isinstance(data["uptime_seconds"], int)


def test_health_with_worker_running(tmp_path: Path, mock_arq_pool) -> None:
    from unittest.mock import AsyncMock

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        admin = User(username="admin7", password_hash=hash_password("admin12345"), role="admin")
        session.add(admin)
        session.commit()

    redis = make_fake_redis()
    ctx = AppContext(
        db=factory, audio_dir=audio_dir, data_dir=data_dir, session_secret=TEST_SECRET, redis=redis,
    )
    app = create_app(audio_dir, data_dir, tmp_path, ctx=ctx)
    client = TestClient(app)

    with (
        client,
        patch("songmaker_cli.arq_pool.is_worker_healthy", AsyncMock(return_value=True)),
        patch("songmaker_cli.arq_pool.is_music_worker_healthy", AsyncMock(return_value=True)),
        patch("songmaker_cli.arq_pool.is_scoring_worker_healthy", AsyncMock(return_value=True)),
        patch("songmaker_cli.arq_pool.get_queue_depth", AsyncMock(return_value=3)),
        patch("songmaker_cli.arq_pool.get_music_queue_depth", AsyncMock(return_value=2)),
        patch("songmaker_cli.arq_pool.get_scoring_queue_depth", AsyncMock(return_value=1)),
    ):
        resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["worker"] == "running"
    assert data["music_worker"] == "running"
    assert data["scoring_worker"] == "running"
    assert data["queue_depth"] == 3
    assert data["acestep"] == "unknown"
    assert data["acestep_workers_total"] == 0


def test_health_degraded_when_worker_stopped(tmp_path: Path, mock_arq_pool) -> None:
    from unittest.mock import AsyncMock

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        admin = User(username="admin8", password_hash=hash_password("admin12345"), role="admin")
        session.add(admin)
        session.commit()

    redis = make_fake_redis()
    ctx = AppContext(
        db=factory, audio_dir=audio_dir, data_dir=data_dir, session_secret=TEST_SECRET, redis=redis,
    )
    app = create_app(audio_dir, data_dir, tmp_path, ctx=ctx)
    client = TestClient(app)

    with (
        client,
        patch("songmaker_cli.arq_pool.is_worker_healthy", AsyncMock(return_value=False)),
        patch("songmaker_cli.arq_pool.is_music_worker_healthy", AsyncMock(return_value=False)),
        patch("songmaker_cli.arq_pool.is_scoring_worker_healthy", AsyncMock(return_value=False)),
        patch("songmaker_cli.arq_pool.get_queue_depth", AsyncMock(return_value=0)),
        patch("songmaker_cli.arq_pool.get_music_queue_depth", AsyncMock(return_value=0)),
        patch("songmaker_cli.arq_pool.get_scoring_queue_depth", AsyncMock(return_value=0)),
    ):
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"


def test_health_queue_depth_cap_reached(tmp_path: Path, mock_arq_pool) -> None:
    from unittest.mock import AsyncMock

    from songmaker_cli.db.models import Job

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        admin = User(
            username="admincap", password_hash=hash_password("admin12345"), role="admin",
        )
        session.add(admin)
        for _ in range(3):
            session.add(Job(type="generate", status="queued"))
        session.commit()

    redis = make_fake_redis()
    ctx = AppContext(
        db=factory, audio_dir=audio_dir, data_dir=data_dir,
        session_secret=TEST_SECRET, redis=redis,
    )
    app = create_app(audio_dir, data_dir, tmp_path, ctx=ctx)
    client = TestClient(app)

    with (
        client,
        patch("songmaker_cli.arq_pool.is_worker_healthy", AsyncMock(return_value=True)),
        patch("songmaker_cli.arq_pool.is_music_worker_healthy", AsyncMock(return_value=True)),
        patch("songmaker_cli.arq_pool.is_scoring_worker_healthy", AsyncMock(return_value=True)),
        patch("songmaker_cli.arq_pool.get_queue_depth", AsyncMock(return_value=3)),
        patch("songmaker_cli.arq_pool.get_music_queue_depth", AsyncMock(return_value=3)),
        patch("songmaker_cli.arq_pool.get_scoring_queue_depth", AsyncMock(return_value=0)),
        patch("songmaker_cli.settings.get_settings") as mock_settings,
    ):
        mock_settings.return_value.max_queue_depth = 2
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["queue_depth_cap_reached"] is True


# ── /metrics endpoint ────────────────────────────────────────────


def _make_metrics_client(tmp_path: Path, mock_arq_pool=None) -> TestClient:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        admin = User(
            username="metrics_admin", password_hash=hash_password("admin12345"), role="admin",
        )
        session.add(admin)
        session.commit()

    redis = make_fake_redis()
    ctx = AppContext(
        db=factory, audio_dir=audio_dir, data_dir=data_dir, session_secret=TEST_SECRET, redis=redis,
    )
    return TestClient(create_app(audio_dir, data_dir, tmp_path, ctx=ctx))


def test_metrics_no_auth_required(tmp_path: Path, mock_arq_pool) -> None:
    from songmaker_cli.constants import PROM_CONTENT_TYPE
    client = _make_metrics_client(tmp_path)
    with client:
        resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == PROM_CONTENT_TYPE
    body = resp.text
    assert "songmaker_http_requests_total" in body
    assert "songmaker_http_request_duration_milliseconds_total" in body
    assert "songmaker_active_sessions" in body
    assert "songmaker_jobs_total" in body
    assert "songmaker_queue_depth" in body


def test_metrics_reflects_http_traffic(tmp_path: Path, mock_arq_pool) -> None:
    client = _make_metrics_client(tmp_path)
    with client:
        client.get("/health")
        client.get("/health")
        resp = client.get("/metrics")
    body = resp.text
    assert 'songmaker_http_requests_total{method="GET",status="200"}' in body


def test_metrics_with_jobs(tmp_path: Path, mock_arq_pool) -> None:
    from songmaker_cli.db.models import Job

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(data_dir / "songmaker.db")
    now = datetime.now(timezone.utc)
    with factory() as session:
        admin = User(
            username="metrics_admin2", password_hash=hash_password("admin12345"), role="admin",
        )
        session.add(admin)
        job = Job(type="generate", status="completed", started_at=now, completed_at=now)
        session.add(job)
        session.commit()

    redis = make_fake_redis()
    ctx = AppContext(
        db=factory, audio_dir=audio_dir, data_dir=data_dir, session_secret=TEST_SECRET, redis=redis,
    )
    app = create_app(audio_dir, data_dir, tmp_path, ctx=ctx)
    client = TestClient(app)

    with client:
        resp = client.get("/metrics")
    body = resp.text
    assert 'songmaker_jobs_total{type="generate",status="completed"} 1' in body
    assert "songmaker_job_duration_seconds" in body


def test_metrics_format_prometheus_all_sections() -> None:
    from songmaker_cli.health_api import _format_prometheus

    http_snapshot = {
        "http_requests_total": {"GET 200": 10, "POST 201": 3},
        "http_requests_count": 13,
        "http_request_duration_total_ms": 456.7,
    }
    jobs_by_type = {
        "generate": {"completed": 5, "failed": 1},
        "score": {"queued": 2},
    }
    body = _format_prometheus(
        http_snapshot=http_snapshot,
        jobs_by_type=jobs_by_type,
        duration_avg=12.3,
        duration_min=1.0,
        duration_max=45.6,
        queue_depth=7,
        gpu_vram_mb=1024.5,
        active_sessions=3,
        acestep_workers_online=0,
        acestep_workers_loading=0,
        acestep_workers_offline=0,
        acestep_worker_loaded_counts={},
        acestep_worker_queue_depths={},
    )
    assert '# TYPE songmaker_http_requests_total counter' in body
    assert 'songmaker_http_requests_total{method="GET",status="200"} 10' in body
    assert 'songmaker_http_requests_total{method="POST",status="201"} 3' in body
    assert "songmaker_http_request_duration_milliseconds_total 456.7" in body
    assert "songmaker_active_sessions 3" in body
    assert 'songmaker_jobs_total{type="generate",status="completed"} 5' in body
    assert 'songmaker_jobs_total{type="generate",status="failed"} 1' in body
    assert 'songmaker_jobs_total{type="score",status="queued"} 2' in body
    assert 'songmaker_job_duration_seconds{quantile="avg"} 12.3' in body
    assert 'songmaker_job_duration_seconds{quantile="min"} 1.0' in body
    assert 'songmaker_job_duration_seconds{quantile="max"} 45.6' in body
    assert "songmaker_queue_depth 7" in body
    assert "songmaker_gpu_vram_megabytes 1024.5" in body


def test_metrics_format_prometheus_no_gpu_no_duration() -> None:
    from songmaker_cli.health_api import _format_prometheus

    body = _format_prometheus(
        http_snapshot={
            "http_requests_total": {},
            "http_requests_count": 0,
            "http_request_duration_total_ms": 0.0,
        },
        jobs_by_type={},
        duration_avg=None,
        duration_min=None,
        duration_max=None,
        queue_depth=0,
        gpu_vram_mb=None,
        active_sessions=0,
        acestep_workers_online=0,
        acestep_workers_loading=0,
        acestep_workers_offline=0,
        acestep_worker_loaded_counts={},
        acestep_worker_queue_depths={},
    )
    assert "songmaker_gpu_vram_megabytes" not in body
    assert "songmaker_job_duration_seconds{" not in body
    assert "songmaker_active_sessions 0" in body
    assert "songmaker_queue_depth 0" in body


def test_metrics_format_prometheus_acestep_worker_gauges() -> None:
    from songmaker_cli.health_api import _format_prometheus

    body = _format_prometheus(
        http_snapshot={
            "http_requests_total": {},
            "http_requests_count": 0,
            "http_request_duration_total_ms": 0.0,
        },
        jobs_by_type={},
        duration_avg=None,
        duration_min=None,
        duration_max=None,
        queue_depth=0,
        gpu_vram_mb=None,
        active_sessions=0,
        acestep_workers_online=2,
        acestep_workers_loading=1,
        acestep_workers_offline=0,
        acestep_worker_loaded_counts={
            "acestep-worker-0": 2,
            "acestep-worker-1": 0,
            "acestep-worker-2": 1,
        },
        acestep_worker_queue_depths={
            "acestep-worker-0": 3,
            "acestep-worker-1": 0,
            "acestep-worker-2": 0,
        },
    )
    assert '# TYPE songmaker_acestep_workers_total gauge' in body
    assert 'songmaker_acestep_workers_total{status="online"} 2' in body
    assert 'songmaker_acestep_workers_total{status="loading"} 1' in body
    assert 'songmaker_acestep_workers_total{status="offline"} 0' in body
    assert '# TYPE songmaker_acestep_worker_loaded_models gauge' in body
    assert 'songmaker_acestep_worker_loaded_models{worker_id="acestep-worker-0"} 2' in body
    assert 'songmaker_acestep_worker_loaded_models{worker_id="acestep-worker-1"} 0' in body
    assert 'songmaker_acestep_worker_loaded_models{worker_id="acestep-worker-2"} 1' in body
    assert '# TYPE songmaker_acestep_worker_queue_depth gauge' in body
    assert 'songmaker_acestep_worker_queue_depth{worker_id="acestep-worker-0"} 3' in body


def test_metrics_format_prometheus_acestep_no_workers() -> None:
    from songmaker_cli.health_api import _format_prometheus

    body = _format_prometheus(
        http_snapshot={
            "http_requests_total": {},
            "http_requests_count": 0,
            "http_request_duration_total_ms": 0.0,
        },
        jobs_by_type={},
        duration_avg=None,
        duration_min=None,
        duration_max=None,
        queue_depth=0,
        gpu_vram_mb=None,
        active_sessions=0,
        acestep_workers_online=0,
        acestep_workers_loading=0,
        acestep_workers_offline=0,
        acestep_worker_loaded_counts={},
        acestep_worker_queue_depths={},
    )
    assert 'songmaker_acestep_workers_total{status="online"} 0' in body
    assert 'songmaker_acestep_workers_total{status="loading"} 0' in body
    assert 'songmaker_acestep_workers_total{status="offline"} 0' in body
    assert "# TYPE songmaker_acestep_worker_loaded_models gauge" in body
    assert "# TYPE songmaker_acestep_worker_queue_depth gauge" in body


def _override_arq_pool(pool_obj) -> object:
    import songmaker_cli.arq_pool as arq_mod
    saved = arq_mod._pool
    arq_mod._pool = pool_obj
    return saved


def _restore_arq_pool(saved) -> None:
    import songmaker_cli.arq_pool as arq_mod
    arq_mod._pool = saved


def test_metrics_endpoint_includes_acestep_gauges_with_seeded_worker(
    tmp_path: Path, mock_arq_pool,
) -> None:
    import json

    import fakeredis
    import fakeredis.aioredis

    from songmaker_cli.acestep_state import (
        queue_depth_key,
        worker_state_key,
    )
    from songmaker_cli.db.queries import register_worker

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        register_worker(
            session,
            worker_id="acestep-worker-0",
            host="acestep-worker-0",
            port=8001,
            gpu_id=0,
            vram_total_gb=24.0,
        )
        session.commit()

    server = fakeredis.FakeServer()
    sync_redis = fakeredis.FakeRedis(server=server, decode_responses=True)
    async_pool = fakeredis.aioredis.FakeRedis(server=server)

    sync_redis.set(
        worker_state_key("acestep-worker-0"),
        json.dumps({
            "loaded": ["sft", "xl-sft"],
            "target_loading": None,
            "queue_depth": 0,
            "vram_used_gb": 18.0,
            "vram_total_gb": 24.0,
            "available_modes": ["sft", "xl-sft"],
        }),
    )
    sync_redis.set(queue_depth_key("acestep-worker-0"), "0")

    ctx = AppContext(
        db=factory, audio_dir=audio_dir, data_dir=data_dir,
        session_secret=TEST_SECRET, redis=sync_redis,
    )
    client = TestClient(create_app(audio_dir, data_dir, tmp_path, ctx=ctx))

    with client:
        saved = _override_arq_pool(async_pool)
        try:
            resp = client.get("/metrics")
        finally:
            _restore_arq_pool(saved)

    body = resp.text
    assert resp.status_code == 200
    assert 'songmaker_acestep_workers_total{status="online"} 1' in body
    assert 'songmaker_acestep_workers_total{status="loading"} 0' in body
    assert 'songmaker_acestep_workers_total{status="offline"} 0' in body
    assert (
        'songmaker_acestep_worker_loaded_models{worker_id="acestep-worker-0"} 2'
        in body
    )


def test_metrics_endpoint_offline_worker(
    tmp_path: Path, mock_arq_pool,
) -> None:
    import fakeredis.aioredis

    from songmaker_cli.db.queries import register_worker

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        register_worker(
            session,
            worker_id="acestep-worker-0",
            host="acestep-worker-0",
            port=8001,
            gpu_id=0,
            vram_total_gb=24.0,
        )
        session.commit()

    redis = make_fake_redis()
    async_pool = fakeredis.aioredis.FakeRedis()

    ctx = AppContext(
        db=factory, audio_dir=audio_dir, data_dir=data_dir,
        session_secret=TEST_SECRET, redis=redis,
    )
    client = TestClient(create_app(audio_dir, data_dir, tmp_path, ctx=ctx))

    with client:
        saved = _override_arq_pool(async_pool)
        try:
            resp = client.get("/metrics")
        finally:
            _restore_arq_pool(saved)

    body = resp.text
    assert 'songmaker_acestep_workers_total{status="online"} 0' in body
    assert 'songmaker_acestep_workers_total{status="offline"} 1' in body
    assert (
        'songmaker_acestep_worker_loaded_models{worker_id="acestep-worker-0"} 0'
        in body
    )


# ── Auto-setup admin ──────────────────────────────────────────────


def test_auto_setup_admin_creates_user(tmp_path: Path) -> None:
    from songmaker_cli.db.queries import get_user_by_username
    from songmaker_cli.lifecycle import auto_setup_admin as _auto_setup_admin

    factory = init_db(tmp_path / "test.db")
    ctx = AppContext(
        db=factory, audio_dir=tmp_path / "audio", data_dir=tmp_path / "data",
        session_secret=TEST_SECRET, redis=make_fake_redis(),
    )
    with patch.dict("os.environ", {"ADMIN_USERNAME": "boss", "ADMIN_PASSWORD": "Str0ng!Pass99"}):
        _auto_setup_admin(ctx)

    with factory() as session:
        user = get_user_by_username(session, "boss")
        assert user is not None
        assert user.role == "admin"


def test_auto_setup_admin_skips_when_users_exist(tmp_path: Path) -> None:
    from songmaker_cli.auth import hash_password
    from songmaker_cli.db.queries import create_user, get_user_by_username
    from songmaker_cli.lifecycle import auto_setup_admin as _auto_setup_admin

    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        create_user(session, "existing", hash_password("Test1234!"), role="admin")
        session.commit()

    ctx = AppContext(
        db=factory, audio_dir=tmp_path / "audio", data_dir=tmp_path / "data",
        session_secret=TEST_SECRET, redis=make_fake_redis(),
    )
    with patch.dict("os.environ", {"ADMIN_USERNAME": "boss", "ADMIN_PASSWORD": "Str0ng!Pass99"}):
        _auto_setup_admin(ctx)

    with factory() as session:
        assert get_user_by_username(session, "boss") is None


def test_auto_setup_admin_skips_without_env_vars(
    tmp_path: Path, monkeypatch,
) -> None:
    from songmaker_cli.lifecycle import auto_setup_admin as _auto_setup_admin

    factory = init_db(tmp_path / "test.db")
    ctx = AppContext(
        db=factory, audio_dir=tmp_path / "audio", data_dir=tmp_path / "data",
        session_secret=TEST_SECRET, redis=make_fake_redis(),
    )
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    _auto_setup_admin(ctx)


def test_auto_setup_admin_rejects_weak_password(tmp_path: Path) -> None:
    from songmaker_cli.db.queries import user_count
    from songmaker_cli.lifecycle import auto_setup_admin as _auto_setup_admin

    factory = init_db(tmp_path / "test.db")
    ctx = AppContext(
        db=factory, audio_dir=tmp_path / "audio", data_dir=tmp_path / "data",
        session_secret=TEST_SECRET, redis=make_fake_redis(),
    )
    with patch.dict("os.environ", {"ADMIN_USERNAME": "boss", "ADMIN_PASSWORD": "aaa"}):
        _auto_setup_admin(ctx)

    with factory() as session:
        assert user_count(session) == 0


# ── PWA static routes ────────────────────────────────────────────────


def _pwa_test_app(tmp_path: Path, *, create_files: bool) -> TestClient:
    """Build a test app with or without PWA static files present."""
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Songmaker</html>")

    if create_files:
        (sk_dir / "service-worker.js").write_text("self.addEventListener('install', () => {})")
        (sk_dir / "manifest.webmanifest").write_text('{"name":"Songmaker"}')
        (sk_dir / "icon-192.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (sk_dir / "icon-512.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    factory = init_db(data_dir / "songmaker.db")
    ctx = AppContext(
        db=factory,
        audio_dir=audio_dir,
        data_dir=data_dir,
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    app = create_app(audio_dir, data_dir, tmp_path, ctx=ctx)
    return TestClient(app)


def test_service_worker_served_with_correct_mime_and_sw_allowed_header(
    tmp_path: Path,
) -> None:
    client = _pwa_test_app(tmp_path, create_files=True)
    resp = client.get("/service-worker.js")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/javascript")
    assert resp.headers["Service-Worker-Allowed"] == "/"


@pytest.mark.parametrize("path,expected_mime", [
    ("/manifest.webmanifest", "application/manifest+json"),
    ("/icon-192.png", "image/png"),
    ("/icon-512.png", "image/png"),
])
def test_pwa_static_served_with_correct_mime(
    tmp_path: Path, path: str, expected_mime: str,
) -> None:
    client = _pwa_test_app(tmp_path, create_files=True)
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(expected_mime)


@pytest.mark.parametrize("path", [
    "/service-worker.js",
    "/manifest.webmanifest",
    "/icon-192.png",
    "/icon-512.png",
])
def test_pwa_route_honest_404_when_file_missing(tmp_path: Path, path: str) -> None:
    client = _pwa_test_app(tmp_path, create_files=False)
    resp = client.get(path)
    assert resp.status_code == 404
    assert resp.headers.get("content-type", "").startswith("application/json")
    assert b"<html" not in resp.content


def test_csp_includes_manifest_src_self(server_app: TestClient) -> None:
    resp = server_app.get("/")
    assert "manifest-src 'self'" in resp.headers["Content-Security-Policy"]

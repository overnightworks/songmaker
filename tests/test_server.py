"""Tests for the songmaker server."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from conftest import TEST_SECRET
from fastapi.testclient import TestClient

from songmaker_cli.app_context import AppContext
from songmaker_cli.auth import hash_password, sign_session_id
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import Album, Generation, Score, Song, User, Version
from songmaker_cli.server import create_app, parse_allowed_hosts, run_server


@pytest.fixture()
def server_app(tmp_path: Path) -> TestClient:
    output_dir = tmp_path / "_output"
    album_dir = output_dir / "test_album"
    album_dir.mkdir(parents=True)

    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Songmaker</html>")

    mp3 = album_dir / "01_song_v1.mp3"
    mp3.write_bytes(b"\xff\xfb\x90\x00" * 100)

    factory = init_db(output_dir / "songmaker.db")
    with factory() as session:
        album = Album(id="test_album", title="Test", artist="Test")
        session.add(album)
        song = Song(id="s1", title="Song", album_id="test_album", track_number=1)
        session.add(song)
        ver = Version(id="v1", song_id="s1", version_number=1, lyrics="Hello")
        session.add(ver)
        gen = Generation(
            id="g1", song_id="s1", version_id="v1", generation_number=1,
            mp3_path="test_album/01_song_v1.mp3", seed=42,
        )
        session.add(gen)
        score = Score(id="sc1", generation_id="g1", scorer="batch", value={"dynamics": 48.9})
        session.add(score)
        admin = User(username="admin", password_hash=hash_password("admin12345"), role="admin")
        session.add(admin)
        session.commit()

    ctx = AppContext(
        db=factory,
        output_dir=output_dir,
        session_secret=TEST_SECRET,
    )
    app = create_app(output_dir, project_root, ctx=ctx)
    client = TestClient(app, cookies={})
    from conftest import login_and_csrf
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
    resp = server_app.get("/audio/test_album/01_song_v1.mp3")
    assert resp.status_code == 200


def test_get_audio_not_found(server_app: TestClient) -> None:
    resp = server_app.get("/audio/test_album/nonexistent.mp3")
    assert resp.status_code == 404


def test_api_songs(server_app: TestClient) -> None:
    resp = server_app.get("/api/songs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["total"] == 1


def test_api_rate(server_app: TestClient) -> None:
    resp = server_app.post(
        "/api/rate/test_album/01_song_v1",
        json={"rating": 72.5, "notes": "great groove"},
    )
    assert resp.status_code == 200


def test_create_app_mounts_sveltekit_app(tmp_path: Path) -> None:
    output_dir = tmp_path / "_output"
    output_dir.mkdir(parents=True)

    project_root = tmp_path
    sk_dir = project_root / "frontend" / "build"
    sk_app_dir = sk_dir / "_app"
    sk_app_dir.mkdir(parents=True)
    (sk_app_dir / "dummy.js").write_text("// chunk")
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(output_dir / "songmaker.db")
    with factory() as session:
        session.commit()

    ctx = AppContext(
        db=factory,
        output_dir=output_dir,
        session_secret=TEST_SECRET,
    )
    app = create_app(output_dir, project_root, ctx=ctx)
    client = TestClient(app)
    resp = client.get("/_app/dummy.js")
    assert resp.status_code == 200


def test_api_rate_not_found(server_app: TestClient) -> None:
    resp = server_app.post(
        "/api/rate/test_album/nonexistent",
        json={"rating": 3},
    )
    assert resp.status_code == 404


def test_get_audio_path_traversal_denied(server_app: TestClient) -> None:
    resp = server_app.get("/audio/..%2F..%2Fetc/passwd")
    assert resp.status_code in (403, 404)


def test_get_audio_path_traversal_via_symlink(tmp_path: Path) -> None:
    import os

    output_dir = tmp_path / "_output"
    output_dir.mkdir(parents=True)

    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    (secret_dir / "data.mp3").write_bytes(b"\xff\xfb\x90\x00" * 10)

    symlink_dir = output_dir / "escaped"
    os.symlink(str(secret_dir), str(symlink_dir))

    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(output_dir / "songmaker.db")
    with factory() as session:
        admin = User(username="admin6", password_hash=hash_password("admin12345"), role="admin")
        session.add(admin)
        session.commit()

    ctx = AppContext(
        db=factory,
        output_dir=output_dir,
        session_secret=TEST_SECRET,
    )
    app = create_app(output_dir, project_root, ctx=ctx)
    client = TestClient(app, cookies={})
    from conftest import login_and_csrf
    login_and_csrf(client, "admin6", "admin12345")
    resp = client.get("/audio/escaped/data.mp3")
    assert resp.status_code == 403


@pytest.fixture()
def auth_server_app(tmp_path: Path):
    from songmaker_cli.db.queries import create_album, create_session, create_user
    from songmaker_cli.middleware import SESSION_COOKIE

    output_dir = tmp_path / "_output"
    album_dir = output_dir / "owned_album"
    album_dir.mkdir(parents=True)
    (album_dir / "song.mp3").write_bytes(b"\xff\xfb\x90\x00" * 100)

    other_album_dir = output_dir / "other_album"
    other_album_dir.mkdir(parents=True)
    (other_album_dir / "other.mp3").write_bytes(b"\xff\xfb\x90\x00" * 100)

    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Songmaker</html>")

    factory = init_db(output_dir / "songmaker.db")
    with factory() as session:
        owner = create_user(session, "owner", hash_password("pass1234"))
        other = create_user(session, "other_user", hash_password("pass1234"))
        session.flush()

        create_album(session, "owned_album", "Owned Album", created_by=owner.id)
        create_album(session, "other_album", "Other Album", created_by=other.id)
        session.flush()

        expires = datetime.now(timezone.utc) + timedelta(days=30)
        owner_session = create_session(session, owner.id, expires)
        other_session = create_session(session, other.id, expires)
        session.commit()
        owner_sid = owner_session.id
        other_sid = other_session.id

    ctx = AppContext(
        db=factory,
        output_dir=output_dir,
        session_secret=TEST_SECRET,
    )
    app = create_app(output_dir, project_root, ctx=ctx)
    client = TestClient(app, cookies={})
    yield client, owner_sid, other_sid, SESSION_COOKIE


def test_get_audio_owned_album_allowed(auth_server_app) -> None:
    client, owner_sid, _other_sid, cookie_name = auth_server_app
    client.cookies.set(cookie_name, sign_session_id(owner_sid, TEST_SECRET))
    resp = client.get("/audio/owned_album/song.mp3")
    assert resp.status_code == 200


def test_get_audio_other_users_album_denied(auth_server_app) -> None:
    client, owner_sid, _other_sid, cookie_name = auth_server_app
    client.cookies.set(cookie_name, sign_session_id(owner_sid, TEST_SECRET))
    resp = client.get("/audio/other_album/other.mp3")
    assert resp.status_code == 404


def test_startup_cleans_expired_sessions(tmp_path: Path) -> None:
    output_dir = tmp_path / "_output"
    output_dir.mkdir(parents=True)
    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Songmaker</html>")

    from songmaker_cli.db.queries import create_session as create_db_session

    factory = init_db(output_dir / "songmaker.db")
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
        output_dir=output_dir,
        session_secret=TEST_SECRET,
    )
    app = create_app(output_dir, project_root, ctx=ctx)
    with TestClient(app):
        pass

    with factory() as session:
        from songmaker_cli.db.models import UserSession
        assert session.query(UserSession).count() == 0


# ── run_server ──────────────────────────────────────────────────────


def test_run_server_calls_uvicorn(tmp_path: Path) -> None:
    output_dir = tmp_path / "_output"
    mock_app = MagicMock()

    with (
        patch("uvicorn.run") as mock_uvicorn,
        patch("songmaker_cli.server.create_app", return_value=mock_app),
    ):
        run_server(output_dir=output_dir, project_root=tmp_path, port=9999)

    mock_uvicorn.assert_called_once()
    call_kwargs = mock_uvicorn.call_args
    assert call_kwargs.kwargs.get("port") == 9999


def test_run_server_defaults_to_localhost(tmp_path: Path) -> None:
    output_dir = tmp_path / "_output"
    mock_app = MagicMock()

    with (
        patch("uvicorn.run") as mock_uvicorn,
        patch("songmaker_cli.server.create_app", return_value=mock_app),
    ):
        run_server(output_dir=output_dir, project_root=tmp_path, port=8080)

    _, kwargs = mock_uvicorn.call_args
    assert kwargs.get("host") == "127.0.0.1"


def test_run_server_opens_browser(tmp_path: Path) -> None:
    output_dir = tmp_path / "_output"
    mock_app = MagicMock()

    with (
        patch("uvicorn.run"),
        patch("songmaker_cli.server.create_app", return_value=mock_app),
        patch("webbrowser.open") as mock_browser,
    ):
        run_server(output_dir=output_dir, project_root=tmp_path, open_browser=True)

    mock_browser.assert_called_once()


def test_run_server_creates_output_dir(tmp_path: Path) -> None:
    output_dir = tmp_path / "_output" / "nested"
    mock_app = MagicMock()

    with (
        patch("uvicorn.run"),
        patch("songmaker_cli.server.create_app", return_value=mock_app),
    ):
        run_server(output_dir=output_dir, project_root=tmp_path)

    assert output_dir.exists()


def test_run_server_infers_output_dir_from_project_root(tmp_path: Path) -> None:
    mock_app = MagicMock()

    with (
        patch("uvicorn.run"),
        patch("songmaker_cli.server.create_app", return_value=mock_app),
        patch("songmaker_cli.server.find_project_root", return_value=tmp_path),
    ):
        run_server(output_dir=None, project_root=None)


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
    output_dir = tmp_path / "_output"
    output_dir.mkdir(parents=True)
    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(output_dir / "songmaker.db")
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
            output_dir=output_dir,
            session_secret=TEST_SECRET,
            allowed_hosts_exact=exact,
            allowed_hosts_patterns=patterns,
        )
        app = create_app(output_dir, project_root, ctx=ctx)
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
    output_dir = tmp_path / "_output"
    mock_app = MagicMock()

    with (
        patch("uvicorn.run"),
        patch("songmaker_cli.server.create_app", return_value=mock_app),
        patch("songmaker_cli.server.find_project_root", return_value=None),
    ):
        run_server(output_dir=output_dir, project_root=None)


def test_run_server_rejects_multi_worker(tmp_path: Path) -> None:
    mock_app = MagicMock()

    with (
        patch.dict("os.environ", {"UVICORN_WORKERS": "2"}),
        patch("songmaker_cli.server.create_app", return_value=mock_app),
    ):
        with pytest.raises(ValueError, match="UVICORN_WORKERS=2 requires"):
            run_server(output_dir=tmp_path / "_output", project_root=tmp_path)


def test_lifespan_shutdown_calls_gpu_queue_shutdown(tmp_path: Path) -> None:
    from songmaker_cli.server import _lifespan

    factory = init_db(tmp_path / "test.db")
    mock_queue = MagicMock()
    mock_app = MagicMock()
    mock_app.state.ctx = AppContext(
        db=factory,
        output_dir=tmp_path,
        session_secret=TEST_SECRET,
        gpu_queue=mock_queue,
    )

    async def _run():
        async with _lifespan(mock_app):
            pass

    import asyncio
    asyncio.run(_run())
    mock_queue.shutdown.assert_called_once()


def test_lifespan_shutdown_handles_no_gpu_queue(tmp_path: Path) -> None:
    from songmaker_cli.server import _lifespan

    factory = init_db(tmp_path / "test.db")
    mock_app = MagicMock()
    mock_app.state.ctx = AppContext(
        db=factory,
        output_dir=tmp_path,
        session_secret=TEST_SECRET,
        gpu_queue=None,
    )

    async def _run():
        async with _lifespan(mock_app):
            pass

    import asyncio
    asyncio.run(_run())


# ── BodySizeLimitMiddleware edge cases ─────────────────────────────


def test_body_size_limit_invalid_content_length(server_app: TestClient) -> None:
    resp = server_app.post(
        "/api/songs",
        content=b'{"title":"X","album_id":"test_album"}',
        headers={"content-type": "application/json", "content-length": "not-a-number"},
    )
    assert resp.status_code != 413


def test_body_size_streaming_too_large(tmp_path: Path) -> None:
    import asyncio

    import songmaker_cli.server as srv
    from songmaker_cli.server import BodySizeLimitMiddleware

    async def dummy_app(scope, receive, send):
        await receive()
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [[b"content-type", b"text/plain"]],
        })
        await send({"type": "http.response.body", "body": b"ok"})

    old_limit = srv.MAX_REQUEST_BODY_BYTES
    srv.MAX_REQUEST_BODY_BYTES = 10
    try:
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
    finally:
        srv.MAX_REQUEST_BODY_BYTES = old_limit


# ── CORS wildcard validation ───────────────────────────────────────


def test_cors_wildcard_invalid_raises(tmp_path: Path) -> None:
    output_dir = tmp_path / "_output"
    output_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(output_dir / "songmaker.db")
    ctx = AppContext(
        db=factory,
        output_dir=output_dir,
        session_secret=TEST_SECRET,
    )

    with patch.dict("os.environ", {"CORS_ORIGIN": "*."}):
        with pytest.raises(ValueError, match="Invalid CORS_ORIGIN"):
            create_app(output_dir, tmp_path, ctx=ctx)


def test_cors_specific_origin(tmp_path: Path) -> None:
    output_dir = tmp_path / "_output"
    output_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(output_dir / "songmaker.db")
    with factory() as session:
        session.commit()

    ctx = AppContext(
        db=factory,
        output_dir=output_dir,
        session_secret=TEST_SECRET,
    )
    with patch.dict("os.environ", {"CORS_ORIGIN": "https://mysite.example.com"}):
        app = create_app(output_dir, tmp_path, ctx=ctx)
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
    output_dir = tmp_path / "_output"
    output_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(output_dir / "songmaker.db")
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
            output_dir=output_dir,
            session_secret=TEST_SECRET,
            allowed_hosts_exact=exact,
            allowed_hosts_patterns=patterns,
        )
        app = create_app(output_dir, tmp_path, ctx=ctx)
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


def test_ip_rate_limit_429(tmp_path: Path) -> None:
    import songmaker_cli.server as srv

    output_dir = tmp_path / "_output"
    output_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(output_dir / "songmaker.db")
    with factory() as session:
        session.commit()

    ctx = AppContext(
        db=factory,
        output_dir=output_dir,
        session_secret=TEST_SECRET,
    )
    old_limit = srv.IP_RATE_LIMIT
    srv.IP_RATE_LIMIT = 2
    try:
        app = create_app(output_dir, tmp_path, ctx=ctx)
        client = TestClient(app)
        for _ in range(3):
            resp = client.get("/api/auth/check")
        assert resp.status_code == 429
        assert "Too many requests" in resp.json()["detail"]
    finally:
        srv.IP_RATE_LIMIT = old_limit


def test_static_assets_bypass_rate_limit(tmp_path: Path) -> None:
    import songmaker_cli.server as srv

    output_dir = tmp_path / "_output"
    output_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    app_dir = sk_dir / "_app" / "immutable"
    app_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")
    (app_dir / "test.js").write_text("console.log('ok')")

    factory = init_db(output_dir / "songmaker.db")
    with factory() as session:
        session.commit()

    ctx = AppContext(
        db=factory,
        output_dir=output_dir,
        session_secret=TEST_SECRET,
    )
    old_limit = srv.IP_RATE_LIMIT
    srv.IP_RATE_LIMIT = 2
    try:
        app = create_app(output_dir, tmp_path, ctx=ctx)
        client = TestClient(app)
        for _ in range(5):
            resp = client.get("/_app/immutable/test.js")
        assert resp.status_code == 200
    finally:
        srv.IP_RATE_LIMIT = old_limit


# ── Audio endpoint edge cases ──────────────────────────────────────


def test_get_audio_album_not_in_db(tmp_path: Path) -> None:
    output_dir = tmp_path / "_output"
    orphan_dir = output_dir / "orphan_album"
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "song.mp3").write_bytes(b"\xff\xfb\x90\x00" * 100)

    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(output_dir / "songmaker.db")
    with factory() as session:
        admin = User(username="admin5", password_hash=hash_password("admin12345"), role="admin")
        session.add(admin)
        session.commit()

    ctx = AppContext(
        db=factory,
        output_dir=output_dir,
        session_secret=TEST_SECRET,
    )
    app = create_app(output_dir, project_root, ctx=ctx)
    client = TestClient(app, cookies={})
    from conftest import login_and_csrf
    login_and_csrf(client, "admin5", "admin12345")
    resp = client.get("/audio/orphan_album/song.mp3")
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


def test_startup_prunes_login_attempts(tmp_path: Path) -> None:
    from songmaker_cli.db.models import LoginAttempt

    output_dir = tmp_path / "_output"
    output_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(output_dir / "songmaker.db")
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
        output_dir=output_dir,
        session_secret=TEST_SECRET,
    )
    app = create_app(output_dir, tmp_path, ctx=ctx)
    with TestClient(app):
        pass

    with factory() as session:
        assert session.query(LoginAttempt).count() == 0


# ── run_server loads env file ───────────────────────────────────────


def test_run_server_loads_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".server.env"
    env_file.write_text("SOME_VAR=test\n")
    mock_app = MagicMock()

    with (
        patch("uvicorn.run"),
        patch("songmaker_cli.server.create_app", return_value=mock_app),
        patch("dotenv.load_dotenv") as mock_load,
    ):
        run_server(output_dir=tmp_path / "_output", project_root=tmp_path)

    mock_load.assert_called_once()


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


def test_health_no_auth_required(tmp_path: Path) -> None:
    output_dir = tmp_path / "_output"
    output_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(output_dir / "songmaker.db")
    with factory() as session:
        admin = User(username="admin6", password_hash=hash_password("admin12345"), role="admin")
        session.add(admin)
        session.commit()

    ctx = AppContext(db=factory, output_dir=output_dir, session_secret=TEST_SECRET)
    app = create_app(output_dir, tmp_path, ctx=ctx)
    client = TestClient(app)

    with client:
        resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["db"] == "ok"
    assert data["gpu_queue"] == "stopped"
    assert data["queue_depth"] == 0
    assert data["acestep"] == "unknown"
    assert data["acestep_model"] is None
    assert isinstance(data["uptime_seconds"], int)


def test_health_with_gpu_queue(tmp_path: Path) -> None:
    output_dir = tmp_path / "_output"
    output_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(output_dir / "songmaker.db")
    with factory() as session:
        admin = User(username="admin7", password_hash=hash_password("admin12345"), role="admin")
        session.add(admin)
        session.commit()

    gpu_queue = MagicMock()
    gpu_queue.is_running = True
    gpu_queue.queue_depth = 3
    gpu_queue.active_model = "sft"

    ctx = AppContext(
        db=factory, output_dir=output_dir, session_secret=TEST_SECRET,
        gpu_queue=gpu_queue,
    )
    app = create_app(output_dir, tmp_path, ctx=ctx)
    client = TestClient(app)

    with client:
        resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["gpu_queue"] == "running"
    assert data["queue_depth"] == 3
    assert data["acestep"] == "healthy"
    assert data["acestep_model"] == "sft"


def test_health_degraded_when_queue_stopped(tmp_path: Path) -> None:
    output_dir = tmp_path / "_output"
    output_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(output_dir / "songmaker.db")
    with factory() as session:
        admin = User(username="admin8", password_hash=hash_password("admin12345"), role="admin")
        session.add(admin)
        session.commit()

    gpu_queue = MagicMock()
    gpu_queue.is_running = False
    gpu_queue.queue_depth = 0
    gpu_queue.acestep_healthy = False
    gpu_queue.active_model = None

    ctx = AppContext(
        db=factory, output_dir=output_dir, session_secret=TEST_SECRET,
        gpu_queue=gpu_queue,
    )
    app = create_app(output_dir, tmp_path, ctx=ctx)
    client = TestClient(app)

    with client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"


# ── HttpMetrics ──────────────────────────────────────────────────


class TestHttpMetrics:
    def test_empty_snapshot(self) -> None:
        from songmaker_cli.server import HttpMetrics
        m = HttpMetrics()
        snap = m.snapshot()
        assert snap["http_requests_count"] == 0
        assert snap["http_request_duration_total_ms"] == 0.0
        assert snap["http_requests_total"] == {}

    def test_record_and_snapshot(self) -> None:
        from songmaker_cli.server import HttpMetrics
        m = HttpMetrics()
        m.record("GET", 200, 10.0)
        m.record("GET", 200, 20.0)
        m.record("POST", 201, 30.0)
        snap = m.snapshot()
        assert snap["http_requests_count"] == 3
        assert snap["http_request_duration_total_ms"] == 60.0
        assert snap["http_requests_total"]["GET 200"] == 2
        assert snap["http_requests_total"]["POST 201"] == 1


# ── /metrics endpoint ────────────────────────────────────────────


def _make_metrics_client(tmp_path: Path) -> TestClient:
    output_dir = tmp_path / "_output"
    output_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(output_dir / "songmaker.db")
    with factory() as session:
        admin = User(
            username="metrics_admin", password_hash=hash_password("admin12345"), role="admin",
        )
        session.add(admin)
        session.commit()

    ctx = AppContext(db=factory, output_dir=output_dir, session_secret=TEST_SECRET)
    return TestClient(create_app(output_dir, tmp_path, ctx=ctx))


def test_metrics_no_auth_required(tmp_path: Path) -> None:
    client = _make_metrics_client(tmp_path)
    with client:
        resp = client.get("/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "jobs_total" in data
    assert "jobs_active" in data
    assert "job_duration_seconds" in data
    assert "queue_depth" in data
    assert "gpu_vram_mb" in data
    assert "http_requests_total" in data
    assert "http_requests_count" in data
    assert "http_request_duration_total_ms" in data


def test_metrics_reflects_http_traffic(tmp_path: Path) -> None:
    client = _make_metrics_client(tmp_path)
    with client:
        client.get("/health")
        client.get("/health")
        resp = client.get("/metrics")
    data = resp.json()
    assert data["http_requests_count"] >= 2


def test_metrics_with_jobs(tmp_path: Path) -> None:
    from songmaker_cli.db.models import Job

    output_dir = tmp_path / "_output"
    output_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = tmp_path / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")

    factory = init_db(output_dir / "songmaker.db")
    now = datetime.now(timezone.utc)
    with factory() as session:
        admin = User(
            username="metrics_admin2", password_hash=hash_password("admin12345"), role="admin",
        )
        session.add(admin)
        job = Job(type="generate", status="completed", started_at=now, completed_at=now)
        session.add(job)
        session.commit()

    ctx = AppContext(db=factory, output_dir=output_dir, session_secret=TEST_SECRET)
    app = create_app(output_dir, tmp_path, ctx=ctx)
    client = TestClient(app)

    with client:
        resp = client.get("/metrics")
    data = resp.json()
    assert data["jobs_total"]["generate"]["completed"] == 1
    assert data["jobs_active"] == 0
    assert data["job_duration_seconds"]["avg"] is not None

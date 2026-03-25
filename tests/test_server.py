"""Tests for the songmaker server."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from songmaker_cli.auth import hash_password
from songmaker_cli.db.engine import init_db, reset_engine
from songmaker_cli.db.models import Album, Generation, Score, Song, User, Version
from songmaker_cli.server import create_app, run_server


@pytest.fixture()
def server_app(tmp_path: Path) -> TestClient:
    reset_engine()
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

    app = create_app(output_dir, project_root)
    client = TestClient(app, cookies={})
    from conftest import login_and_csrf
    login_and_csrf(client, "admin", "admin12345")
    yield client
    reset_engine()


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
    assert len(resp.json()) == 1


def test_api_rate(server_app: TestClient) -> None:
    resp = server_app.post(
        "/api/rate/test_album/01_song_v1",
        json={"rating": 72.5, "notes": "great groove"},
    )
    assert resp.status_code == 200


def test_create_app_mounts_sveltekit_app(tmp_path: Path) -> None:
    reset_engine()
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

    app = create_app(output_dir, project_root)
    client = TestClient(app)
    resp = client.get("/_app/dummy.js")
    assert resp.status_code == 200
    reset_engine()


def test_api_rate_not_found(server_app: TestClient) -> None:
    resp = server_app.post(
        "/api/rate/test_album/nonexistent",
        json={"rating": 3},
    )
    assert resp.status_code == 404


def test_get_audio_path_traversal_denied(server_app: TestClient) -> None:
    """Path traversal guard fires when album param escapes output_dir."""
    resp = server_app.get("/audio/..%2F..%2Fetc/passwd")
    assert resp.status_code in (403, 404)


@pytest.fixture()
def auth_server_app(tmp_path: Path):
    from datetime import datetime, timedelta, timezone

    from songmaker_cli.db.queries import create_album, create_session, create_user
    from songmaker_cli.middleware import SESSION_COOKIE

    reset_engine()
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

    from songmaker_cli.auth import hash_password

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

    app = create_app(output_dir, project_root)
    client = TestClient(app, cookies={})
    yield client, owner_sid, other_sid, SESSION_COOKIE
    reset_engine()


def test_get_audio_owned_album_allowed(auth_server_app) -> None:
    from songmaker_cli.auth import sign_session_id
    client, owner_sid, _other_sid, cookie_name = auth_server_app
    client.cookies.set(cookie_name, sign_session_id(owner_sid))
    resp = client.get("/audio/owned_album/song.mp3")
    assert resp.status_code == 200


def test_get_audio_other_users_album_denied(auth_server_app) -> None:
    from songmaker_cli.auth import sign_session_id
    client, owner_sid, _other_sid, cookie_name = auth_server_app
    client.cookies.set(cookie_name, sign_session_id(owner_sid))
    resp = client.get("/audio/other_album/other.mp3")
    assert resp.status_code == 404


def test_startup_cleans_expired_sessions(tmp_path: Path) -> None:
    reset_engine()
    output_dir = tmp_path / "_output"
    output_dir.mkdir(parents=True)
    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Songmaker</html>")

    from songmaker_cli.auth import hash_password
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

    app = create_app(output_dir, project_root)
    with TestClient(app):
        pass

    with factory() as session:
        from songmaker_cli.db.models import UserSession
        assert session.query(UserSession).count() == 0
    reset_engine()


# ── run_server ──────────────────────────────────────────────────────


def test_run_server_calls_uvicorn(tmp_path: Path) -> None:
    output_dir = tmp_path / "_output"

    with (
        patch("uvicorn.run") as mock_uvicorn,
        patch("songmaker_cli.db.engine.init_db"),
        patch("songmaker_cli.config.set_output_dir"),
        patch("songmaker_cli.auth.ensure_session_secret"),

    ):
        run_server(output_dir=output_dir, project_root=tmp_path, port=9999)

    mock_uvicorn.assert_called_once()
    call_kwargs = mock_uvicorn.call_args
    assert call_kwargs.kwargs.get("port") == 9999


def test_run_server_defaults_to_localhost(tmp_path: Path) -> None:
    output_dir = tmp_path / "_output"

    with (
        patch("uvicorn.run") as mock_uvicorn,
        patch("songmaker_cli.db.engine.init_db"),
        patch("songmaker_cli.config.set_output_dir"),
        patch("songmaker_cli.auth.ensure_session_secret"),
    ):
        run_server(output_dir=output_dir, project_root=tmp_path, port=8080)

    _, kwargs = mock_uvicorn.call_args
    assert kwargs.get("host") == "127.0.0.1"


def test_run_server_opens_browser(tmp_path: Path) -> None:
    output_dir = tmp_path / "_output"

    with (
        patch("uvicorn.run"),
        patch("songmaker_cli.db.engine.init_db"),
        patch("songmaker_cli.config.set_output_dir"),
        patch("songmaker_cli.auth.ensure_session_secret"),
        patch("webbrowser.open") as mock_browser,

    ):
        run_server(output_dir=output_dir, project_root=tmp_path, open_browser=True)

    mock_browser.assert_called_once()


def test_run_server_creates_output_dir(tmp_path: Path) -> None:
    output_dir = tmp_path / "_output" / "nested"

    with (
        patch("uvicorn.run"),
        patch("songmaker_cli.db.engine.init_db"),
        patch("songmaker_cli.config.set_output_dir"),
        patch("songmaker_cli.auth.ensure_session_secret"),

    ):
        run_server(output_dir=output_dir, project_root=tmp_path)

    assert output_dir.exists()


def test_run_server_infers_output_dir_from_project_root(tmp_path: Path) -> None:
    with (
        patch("uvicorn.run"),
        patch("songmaker_cli.db.engine.init_db"),
        patch("songmaker_cli.config.set_output_dir"),
        patch("songmaker_cli.auth.ensure_session_secret"),
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
    reset_engine()
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
        import songmaker_cli.server as srv
        srv._allowed_hosts_cache = None
        try:
            app = create_app(output_dir, project_root)
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
        finally:
            srv._allowed_hosts_cache = None
    reset_engine()


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
    import songmaker_cli.auth as auth_mod
    original = auth_mod.TRUSTED_PROXIES
    auth_mod.TRUSTED_PROXIES = frozenset({"testclient"})
    try:
        resp = server_app.get("/", headers={"x-forwarded-proto": "https"})
    finally:
        auth_mod.TRUSTED_PROXIES = original
    assert "Strict-Transport-Security" in resp.headers
    assert "max-age=31536000" in resp.headers["Strict-Transport-Security"]


def test_hsts_header_not_set_without_trusted_proxy(server_app: TestClient) -> None:
    resp = server_app.get("/", headers={"x-forwarded-proto": "https"})
    assert "Strict-Transport-Security" not in resp.headers


def test_run_server_infers_project_root(tmp_path: Path) -> None:
    output_dir = tmp_path / "_output"

    with (
        patch("uvicorn.run"),
        patch("songmaker_cli.db.engine.init_db"),
        patch("songmaker_cli.config.set_output_dir"),
        patch("songmaker_cli.auth.ensure_session_secret"),
        patch("songmaker_cli.server.find_project_root", return_value=None),

    ):
        run_server(output_dir=output_dir, project_root=None)

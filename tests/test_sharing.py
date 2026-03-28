"""Tests for album sharing feature."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import TEST_SECRET, login_and_csrf, make_fake_redis
from fastapi.testclient import TestClient

from songmaker_cli.app_context import AppContext
from songmaker_cli.auth import hash_password, sign_session_id
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import Album, Generation, Song, User, Version


def _make_sharing_app(tmp_path: Path) -> tuple[TestClient, Path]:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Songmaker</html>")

    user_dir = audio_dir / "admin_user"
    user_dir.mkdir(parents=True)
    mp3 = user_dir / "g1.mp3"
    mp3.write_bytes(b"\xff\xfb\x90\x00" * 100)

    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        admin = User(username="admin", password_hash=hash_password("admin12345"), role="admin")
        session.add(admin)
        album = Album(id="test_album", title="Test Album", artist="Test Artist")
        session.add(album)
        song = Song(id="s1", title="Song One", album_id="test_album", track_number=1)
        session.add(song)
        ver = Version(id="v1", song_id="s1", version_number=1, lyrics="Hello")
        session.add(ver)
        gen = Generation(
            id="g1", song_id="s1", version_id="v1", generation_number=1,
            mp3_path="admin_user/g1.mp3", seed=42, is_picked=True,
        )
        session.add(gen)
        session.commit()

    ctx = AppContext(
        db=factory,
        audio_dir=audio_dir,
        data_dir=data_dir,
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.server import create_app
    app = create_app(audio_dir, data_dir, project_root, ctx=ctx)
    return TestClient(app, cookies={}), audio_dir


@pytest.fixture()
def sharing_app(tmp_path: Path) -> TestClient:
    client, _ = _make_sharing_app(tmp_path)
    login_and_csrf(client, "admin", "admin12345")
    return client


# ── Share / Unshare endpoints ──────────────────────────────────────


def test_share_album(sharing_app: TestClient) -> None:
    resp = sharing_app.post("/api/albums/test_album/share")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["share_slug"]
    assert "/share/" in data["share_url"]


def test_share_album_idempotent(sharing_app: TestClient) -> None:
    resp1 = sharing_app.post("/api/albums/test_album/share")
    slug1 = resp1.json()["share_slug"]
    resp2 = sharing_app.post("/api/albums/test_album/share")
    slug2 = resp2.json()["share_slug"]
    assert slug1 == slug2


def test_unshare_album(sharing_app: TestClient) -> None:
    sharing_app.post("/api/albums/test_album/share")
    resp = sharing_app.delete("/api/albums/test_album/share")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_share_nonexistent_album(sharing_app: TestClient) -> None:
    resp = sharing_app.post("/api/albums/nonexistent/share")
    assert resp.status_code == 404


def test_album_response_includes_sharing_fields(sharing_app: TestClient) -> None:
    resp = sharing_app.get("/api/albums/test_album")
    data = resp.json()
    assert data["is_shared"] is False
    assert data["share_slug"] is None

    sharing_app.post("/api/albums/test_album/share")
    resp = sharing_app.get("/api/albums/test_album")
    data = resp.json()
    assert data["is_shared"] is True
    assert data["share_slug"] is not None


# ── Shared view endpoints ──────────────────────────────────────────


def test_shared_album_view(sharing_app: TestClient) -> None:
    resp = sharing_app.post("/api/albums/test_album/share")
    slug = resp.json()["share_slug"]

    unauthed = TestClient(sharing_app.app, cookies={})
    resp = unauthed.get(f"/shared/{slug}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Test Album"
    assert data["artist"] == "Test Artist"
    assert len(data["songs"]) == 1
    assert data["songs"][0]["title"] == "Song One"
    assert data["songs"][0]["audio_url"] is not None


def test_shared_album_not_found(sharing_app: TestClient) -> None:
    unauthed = TestClient(sharing_app.app, cookies={})
    resp = unauthed.get("/shared/nonexistent-slug")
    assert resp.status_code == 404


def test_shared_album_after_revoke(sharing_app: TestClient) -> None:
    resp = sharing_app.post("/api/albums/test_album/share")
    slug = resp.json()["share_slug"]
    sharing_app.delete("/api/albums/test_album/share")

    unauthed = TestClient(sharing_app.app, cookies={})
    resp = unauthed.get(f"/shared/{slug}")
    assert resp.status_code == 404


# ── Shared audio endpoint ──────────────────────────────────────────


def test_shared_audio(sharing_app: TestClient) -> None:
    resp = sharing_app.post("/api/albums/test_album/share")
    slug = resp.json()["share_slug"]

    unauthed = TestClient(sharing_app.app, cookies={})
    resp = unauthed.get(f"/shared/{slug}/audio/admin_user/g1.mp3")
    assert resp.status_code == 200


def test_shared_album_song_without_picked_generation(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Songmaker</html>")

    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        admin = User(username="admin", password_hash=hash_password("admin12345"), role="admin")
        session.add(admin)
        album = Album(id="test_album", title="Test Album", artist="Test Artist")
        session.add(album)
        song = Song(id="s1", title="No Pick", album_id="test_album", track_number=1)
        session.add(song)
        gen = Generation(
            id="g1", song_id="s1", generation_number=1,
            mp3_path="admin_user/g1.mp3", seed=42, is_picked=False,
        )
        session.add(gen)
        session.commit()

    redis = make_fake_redis()
    ctx = AppContext(
        db=factory, audio_dir=audio_dir, data_dir=data_dir, session_secret=TEST_SECRET, redis=redis,
    )
    from songmaker_cli.server import create_app
    app = create_app(audio_dir, data_dir, project_root, ctx=ctx)
    client = TestClient(app, cookies={})
    login_and_csrf(client, "admin", "admin12345")
    resp = client.post("/api/albums/test_album/share")
    slug = resp.json()["share_slug"]

    unauthed = TestClient(app, cookies={})
    resp = unauthed.get(f"/shared/{slug}")
    data = resp.json()
    assert data["songs"][0]["audio_url"] is None


def test_shared_audio_not_found_wrong_file(sharing_app: TestClient) -> None:
    resp = sharing_app.post("/api/albums/test_album/share")
    slug = resp.json()["share_slug"]

    unauthed = TestClient(sharing_app.app, cookies={})
    resp = unauthed.get(f"/shared/{slug}/audio/nonexistent.mp3")
    assert resp.status_code == 404


def test_shared_audio_not_found_bad_slug(sharing_app: TestClient) -> None:
    unauthed = TestClient(sharing_app.app, cookies={})
    resp = unauthed.get("/shared/bad-slug/audio/admin_user/g1.mp3")
    assert resp.status_code == 404


# ── Rate limiting ──────────────────────────────────────────────────


def test_shared_rate_limit(tmp_path: Path) -> None:
    import songmaker_cli.constants as consts

    client, _ = _make_sharing_app(tmp_path)
    login_and_csrf(client, "admin", "admin12345")

    resp = client.post("/api/albums/test_album/share")
    slug = resp.json()["share_slug"]

    old_limit = consts.SHARED_RATE_LIMIT
    consts.SHARED_RATE_LIMIT = 2
    try:
        from songmaker_cli.server import create_app
        audio_dir = client.app.state.ctx.audio_dir
        data_dir = client.app.state.ctx.data_dir

        ctx = AppContext(
            db=client.app.state.ctx.db,
            audio_dir=audio_dir,
            data_dir=data_dir,
            session_secret=TEST_SECRET,
            redis=make_fake_redis(),
        )
        app = create_app(audio_dir, data_dir, tmp_path, ctx=ctx)
        unauthed = TestClient(app, cookies={})

        for _ in range(3):
            resp = unauthed.get(f"/shared/{slug}")
        assert resp.status_code == 429
    finally:
        consts.SHARED_RATE_LIMIT = old_limit


# ── Ownership checks ──────────────────────────────────────────────


def test_share_album_ownership_enforced(tmp_path: Path) -> None:
    from songmaker_cli.db.queries import create_album, create_session, create_user
    from songmaker_cli.middleware import SESSION_COOKIE

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
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
        create_album(session, "owners_album", "Owners Album", created_by=owner.id)
        expires = datetime.now(timezone.utc) + timedelta(days=30)
        other_session = create_session(session, other.id, expires)
        session.commit()
        other_sid = other_session.id

    ctx = AppContext(
        db=factory,
        audio_dir=audio_dir,
        data_dir=data_dir,
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.server import create_app
    app = create_app(audio_dir, data_dir, project_root, ctx=ctx)
    client = TestClient(app, cookies={})
    client.cookies.set(SESSION_COOKIE, sign_session_id(other_sid, TEST_SECRET))

    from conftest import apply_csrf_header
    resp = client.post("/api/auth/login", json={"username": "other_user", "password": "pass1234"})
    apply_csrf_header(client)

    resp = client.post("/api/albums/owners_album/share")
    assert resp.status_code == 404


# ── DB query functions ─────────────────────────────────────────────


def test_enable_disable_sharing(tmp_path: Path) -> None:
    from songmaker_cli.db.queries import (
        create_album,
        disable_album_sharing,
        enable_album_sharing,
        get_album_by_slug,
    )

    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        create_album(session, "a1", "Album")
        session.commit()

    with factory() as session:
        album = enable_album_sharing(session, "a1")
        slug = album.share_slug
        assert slug is not None
        assert album.is_shared is True
        session.commit()

    with factory() as session:
        found = get_album_by_slug(session, slug)
        assert found is not None
        assert found.id == "a1"

    with factory() as session:
        album = disable_album_sharing(session, "a1")
        assert album.share_slug is None
        assert album.is_shared is False
        session.commit()

    with factory() as session:
        found = get_album_by_slug(session, slug)
        assert found is None


def test_enable_sharing_not_found(tmp_path: Path) -> None:
    from songmaker_cli.db.queries import enable_album_sharing

    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        with pytest.raises(ValueError, match="Album not found"):
            enable_album_sharing(session, "nonexistent")


def test_disable_sharing_not_found(tmp_path: Path) -> None:
    from songmaker_cli.db.queries import disable_album_sharing

    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        with pytest.raises(ValueError, match="Album not found"):
            disable_album_sharing(session, "nonexistent")

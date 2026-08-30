"""Tests for album sharing feature."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import TEST_SECRET, login_and_csrf, make_fake_redis, make_test_app
from fastapi.testclient import TestClient
from sqlalchemy import event

from songmaker_cli.app_context import AppContext
from songmaker_cli.auth import hash_password, sign_session_id
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import Album, Generation, Playlist, PlaylistEntry, Song, User, Version


def _seed_sharing_data(session) -> None:
    admin = User(username="admin", password_hash=hash_password("admin12345"), role="admin")
    session.add(admin)
    session.add(Album(id="test_album", title="Test Album", artist="Test Artist"))
    session.add(
        Song(id="s1", title="Song One", album_id="test_album", track_number=1, slug="song-one"),
    )
    session.add(Version(id="v1", song_id="s1", version_number=1, lyrics="Hello"))
    session.add(Generation(
        id="g1", song_id="s1", version_id="v1", generation_number=1,
        mp3_path="admin_user/g1.mp3", seed=42, is_picked=True,
    ))


def _make_sharing_app(tmp_path: Path) -> tuple[TestClient, Path]:
    client, _ = make_test_app(tmp_path, seed_db=_seed_sharing_data)
    audio_dir = tmp_path / "audio"
    user_dir = audio_dir / "admin_user"
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "g1.mp3").write_bytes(b"\xff\xfb\x90\x00" * 100)
    return client, audio_dir


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
    assert data["songs_without_playable_take"] == []


def _seed_mixed_playability_album(session) -> None:
    admin = User(username="admin", password_hash=hash_password("admin12345"), role="admin")
    session.add(admin)
    session.add(Album(id="test_album", title="Test Album", artist="Test Artist"))
    session.add(
        Song(
            id="s_playable", title="Has A Take", album_id="test_album", track_number=1,
            slug="has-a-take",
        ),
    )
    session.add(Generation(
        id="g_playable", song_id="s_playable", generation_number=1,
        mp3_path="admin_user/g_playable.mp3", seed=1, is_picked=True,
    ))
    session.add(Song(
        id="s_no_gen", title="No Generation At All", album_id="test_album", track_number=2,
        slug="no-generation-at-all",
    ))
    session.add(Song(
        id="s_archived_only", title="Only Archived Take", album_id="test_album", track_number=3,
        slug="only-archived-take",
    ))
    session.add(Generation(
        id="g_archived", song_id="s_archived_only", generation_number=1,
        mp3_path="admin_user/g_archived.mp3", seed=1, is_archived=True,
    ))
    session.add(Song(
        id="s_unpicked_take", title="Unpicked But Playable", album_id="test_album", track_number=4,
        slug="unpicked-but-playable",
    ))
    session.add(Generation(
        id="g_unpicked", song_id="s_unpicked_take", generation_number=1,
        mp3_path="admin_user/g_unpicked.mp3", seed=1, is_picked=False,
    ))
    session.add(Song(
        id="s_empty_mp3", title="Picked Take With Empty File",
        album_id="test_album", track_number=5, slug="picked-take-with-empty-file",
    ))
    session.add(Generation(
        id="g_empty_mp3", song_id="s_empty_mp3", generation_number=1,
        mp3_path="", seed=1, is_picked=True,
    ))


def test_share_album_response_lists_songs_without_playable_take(tmp_path: Path) -> None:
    client, _ = make_test_app(tmp_path, seed_db=_seed_mixed_playability_album)
    login_and_csrf(client, "admin", "admin12345")

    resp = client.post("/api/albums/test_album/share")

    assert resp.status_code == 200
    missing = resp.json()["songs_without_playable_take"]
    assert {(item["id"], item["title"]) for item in missing} == {
        ("s_no_gen", "No Generation At All"),
        ("s_archived_only", "Only Archived Take"),
        ("s_empty_mp3", "Picked Take With Empty File"),
    }


def test_share_warning_agrees_with_what_the_share_page_actually_plays(tmp_path: Path) -> None:
    """The owner-facing warning list and the public share page must use the
    same playability rule -- a song can't vanish from one without showing up
    in the other (#147)."""
    client, _ = make_test_app(tmp_path, seed_db=_seed_mixed_playability_album)
    login_and_csrf(client, "admin", "admin12345")

    share_resp = client.post("/api/albums/test_album/share")
    slug = share_resp.json()["share_slug"]
    warned_ids = {item["id"] for item in share_resp.json()["songs_without_playable_take"]}

    unauthed = TestClient(client.app, cookies={})
    shared_songs = unauthed.get(f"/shared/{slug}").json()["songs"]

    for song in shared_songs:
        has_audio = song["audio_url"] is not None
        assert has_audio == (song["id"] not in warned_ids)


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
    assert data["cover"] is None


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
        song = Song(
            id="s1", title="No Pick", album_id="test_album", track_number=1, slug="no-pick",
        )
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
    assert data["songs"][0]["audio_url"] is not None
    assert "g1.mp3" in data["songs"][0]["audio_url"]


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


# ── Share payload media fields (#128) ───────────────────────────────


def _count_queries(engine, statement_contains: str) -> tuple[list[str], Callable]:
    """Register a query-count probe; caller removes it via the returned handle."""
    queries: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany) -> None:
        if statement_contains.lower() in statement.lower():
            queries.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    return queries, _record


def _seed_multi_track_album(session) -> None:
    admin = User(username="admin", password_hash=hash_password("admin12345"), role="admin")
    session.add(admin)
    session.add(Album(id="test_album", title="Test Album", artist="Test Artist"))
    for i in range(4):
        song_id = f"s{i}"
        session.add(Song(
            id=song_id, title=f"Song {i}", album_id="test_album", track_number=i,
            slug=f"song-{i}",
        ))
        session.add(Version(
            id=f"v{i}", song_id=song_id, version_number=1,
            lyrics=f"Lyrics {i}", audio_duration=100 + i,
        ))
        session.add(Generation(
            id=f"g{i}", song_id=song_id, version_id=f"v{i}", generation_number=1,
            mp3_path=f"admin_user/g{i}.mp3", seed=1, is_picked=True,
            audio_duration_sec=100 + i,
        ))
    session.add(
        Song(
            id="s_no_pick", title="No Pick", album_id="test_album", track_number=4,
            slug="no-pick",
        ),
    )


def test_shared_album_view_includes_pick_media(tmp_path: Path) -> None:
    client, _ = make_test_app(tmp_path, seed_db=_seed_multi_track_album)
    login_and_csrf(client, "admin", "admin12345")
    resp = client.post("/api/albums/test_album/share")
    slug = resp.json()["share_slug"]

    unauthed = TestClient(client.app, cookies={})
    data = unauthed.get(f"/shared/{slug}").json()

    songs_by_id = {song["id"]: song for song in data["songs"]}
    for i in range(4):
        song = songs_by_id[f"s{i}"]
        assert song["generation_id"] == f"g{i}"
        assert song["audio_duration"] == 100 + i
        assert song["lyrics"] == f"Lyrics {i}"

    no_pick = songs_by_id["s_no_pick"]
    assert no_pick["audio_url"] is None
    assert no_pick["generation_id"] is None
    assert no_pick["audio_duration"] is None
    assert no_pick["lyrics"] is None


def test_shared_album_view_warms_versions_in_one_query(tmp_path: Path) -> None:
    client, factory = make_test_app(tmp_path, seed_db=_seed_multi_track_album)
    login_and_csrf(client, "admin", "admin12345")
    resp = client.post("/api/albums/test_album/share")
    slug = resp.json()["share_slug"]

    with factory() as probe_session:
        engine = probe_session.get_bind()

    queries, handle = _count_queries(engine, "versions")
    try:
        unauthed = TestClient(client.app, cookies={})
        resp = unauthed.get(f"/shared/{slug}")
    finally:
        event.remove(engine, "before_cursor_execute", handle)

    assert resp.status_code == 200
    assert len(resp.json()["songs"]) == 5
    assert len(queries) == 1, (
        f"expected one warm-up query for all four picks' versions, got {len(queries)}: {queries}"
    )


def _seed_song_with_pick(session) -> None:
    admin = User(username="admin", password_hash=hash_password("admin12345"), role="admin")
    session.add(admin)
    session.add(Album(id="test_album", title="Test Album", artist="Test Artist"))
    session.add(
        Song(id="s1", title="Song One", album_id="test_album", track_number=1, slug="song-one"),
    )
    session.add(Version(
        id="v1", song_id="s1", version_number=1, lyrics="Hello", audio_duration=180,
    ))
    session.add(Generation(
        id="g1", song_id="s1", version_id="v1", generation_number=1,
        mp3_path="admin_user/g1.mp3", seed=42, is_picked=True,
        audio_duration_sec=180.0,
    ))


def test_shared_song_view_includes_pick_media(tmp_path: Path) -> None:
    client, _ = make_test_app(tmp_path, seed_db=_seed_song_with_pick)
    login_and_csrf(client, "admin", "admin12345")
    resp = client.post("/api/songs/s1/share")
    slug = resp.json()["share_slug"]

    unauthed = TestClient(client.app, cookies={})
    data = unauthed.get(f"/shared/song/{slug}").json()

    assert data["generation_id"] == "g1"
    assert data["audio_duration"] == 180
    assert data["lyrics"] == "Hello"


def test_shared_song_view_without_pick_returns_null_media(tmp_path: Path) -> None:
    def _seed(session) -> None:
        admin = User(username="admin", password_hash=hash_password("admin12345"), role="admin")
        session.add(admin)
        session.add(Album(id="test_album", title="Test Album", artist="Test Artist"))
        session.add(
            Song(id="s1", title="No Pick", album_id="test_album", track_number=1, slug="no-pick"),
        )

    client, _ = make_test_app(tmp_path, seed_db=_seed)
    login_and_csrf(client, "admin", "admin12345")
    resp = client.post("/api/songs/s1/share")
    slug = resp.json()["share_slug"]

    unauthed = TestClient(client.app, cookies={})
    data = unauthed.get(f"/shared/song/{slug}").json()

    assert data["audio_url"] is None
    assert data["generation_id"] is None
    assert data["audio_duration"] is None
    assert data["lyrics"] is None


def test_shared_generation_view_includes_pick_media(sharing_app: TestClient) -> None:
    resp = sharing_app.post("/api/generations/g1/share")
    slug = resp.json()["share_slug"]

    unauthed = TestClient(sharing_app.app, cookies={})
    data = unauthed.get(f"/shared/gen/{slug}").json()

    assert data["generation_id"] == "g1"
    # audio_duration is the take's own measured length (#258), never the
    # requested parameter -- unmeasured is None here, not 0.
    assert data["audio_duration"] is None
    assert data["lyrics"] == "Hello"


def test_shared_generation_reports_the_takes_measured_duration(
    sharing_app: TestClient,
) -> None:
    factory = sharing_app.app.state.ctx.db
    with factory() as session:
        gen = session.query(Generation).filter_by(id="g1").one()
        gen.audio_duration_sec = 188.0
        session.commit()

    resp = sharing_app.post("/api/generations/g1/share")
    slug = resp.json()["share_slug"]

    unauthed = TestClient(sharing_app.app, cookies={})
    data = unauthed.get(f"/shared/gen/{slug}").json()

    assert data["audio_duration"] == 188.0


def _seed_playlist_with_entries(session) -> None:
    admin = User(username="admin", password_hash=hash_password("admin12345"), role="admin")
    session.add(admin)
    session.add(Album(id="test_album", title="Test Album", artist="Test Artist"))
    session.add(Playlist(id="pl1", title="My Playlist"))
    for i in range(3):
        song_id = f"s{i}"
        session.add(Song(
            id=song_id, title=f"Song {i}", album_id="test_album", track_number=i,
            slug=f"song-{i}",
        ))
        session.add(Version(
            id=f"v{i}", song_id=song_id, version_number=1,
            lyrics=f"Lyrics {i}", audio_duration=100 + i,
        ))
        session.add(Generation(
            id=f"g{i}", song_id=song_id, version_id=f"v{i}", generation_number=1,
            mp3_path=f"admin_user/g{i}.mp3", seed=1,
            audio_duration_sec=100 + i,
        ))
        session.add(PlaylistEntry(id=f"e{i}", playlist_id="pl1", generation_id=f"g{i}", position=i))


def test_shared_playlist_view_includes_pick_media(tmp_path: Path) -> None:
    client, _ = make_test_app(tmp_path, seed_db=_seed_playlist_with_entries)
    login_and_csrf(client, "admin", "admin12345")
    resp = client.post("/api/playlists/pl1/share")
    slug = resp.json()["share_slug"]

    unauthed = TestClient(client.app, cookies={})
    data = unauthed.get(f"/shared/playlist/{slug}").json()

    entries_by_id = {e["entry_id"]: e for e in data["entries"]}
    for i in range(3):
        entry = entries_by_id[f"e{i}"]
        assert entry["generation_id"] == f"g{i}"
        assert entry["audio_duration"] == 100 + i
        assert entry["lyrics"] == f"Lyrics {i}"


def test_shared_playlist_view_warms_versions_in_one_query(tmp_path: Path) -> None:
    client, factory = make_test_app(tmp_path, seed_db=_seed_playlist_with_entries)
    login_and_csrf(client, "admin", "admin12345")
    resp = client.post("/api/playlists/pl1/share")
    slug = resp.json()["share_slug"]

    with factory() as probe_session:
        engine = probe_session.get_bind()

    queries, handle = _count_queries(engine, "versions")
    try:
        unauthed = TestClient(client.app, cookies={})
        resp = unauthed.get(f"/shared/playlist/{slug}")
    finally:
        event.remove(engine, "before_cursor_execute", handle)

    assert resp.status_code == 200
    assert len(resp.json()["entries"]) == 3
    assert len(queries) == 1, (
        f"expected one warm-up query for all three entries' versions, got {len(queries)}: {queries}"
    )


# ── Rate limiting ──────────────────────────────────────────────────


def test_shared_rate_limit_fails_open_when_limiter_backend_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public share page is LimiterFailurePolicy.FAIL_OPEN: a broken
    limiter (Redis down) must let real listeners through rather than 503."""
    client, _ = _make_sharing_app(tmp_path)
    login_and_csrf(client, "admin", "admin12345")
    resp = client.post("/api/albums/test_album/share")
    slug = resp.json()["share_slug"]

    class _BrokenLimiter:
        def is_allowed(self, _ip: str) -> bool:
            raise RuntimeError("redis down")

    monkeypatch.setattr(
        "songmaker_cli.sharing_api._get_shared_limiter",
        lambda _request: _BrokenLimiter(),
    )

    unauthed = TestClient(client.app, cookies={})
    resp = unauthed.get(f"/shared/{slug}")
    assert resp.status_code == 200


def test_shared_rate_limit(tmp_path: Path) -> None:
    import songmaker_cli.constants as consts

    client, _ = _make_sharing_app(tmp_path)
    login_and_csrf(client, "admin", "admin12345")

    resp = client.post("/api/albums/test_album/share")
    slug = resp.json()["share_slug"]

    old_limit = consts.SHARING_RATE_LIMIT
    consts.SHARING_RATE_LIMIT = 2
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
        consts.SHARING_RATE_LIMIT = old_limit


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


# ── Share inventory ────────────────────────────────────────────────


USER_A = "user-a"
USER_B = "user-b"
ADMIN_ID = "user-admin"


def _ts(offset_seconds: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)


def _inventory_factory(tmp_path: Path):
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(id=USER_A, username="alice", password_hash="unused", role="user"))
        session.add(User(id=USER_B, username="bob", password_hash="unused", role="user"))
        session.add(User(id=ADMIN_ID, username="admin", password_hash="unused", role="admin"))
        session.flush()
        _seed_inventory(session)
        session.commit()
    return factory


def _seed_inventory(session) -> None:
    session.add(Album(
        id="alice-album", title="Alice Album", artist="Artist",
        created_by=USER_A, created_at=_ts(40),
        is_shared=True, share_slug="slug-album",
    ))
    session.add(Song(
        id="alice-song", title="Alice Song", album_id="alice-album", slug="alice-song",
        created_at=_ts(30), is_shared=True, share_slug="slug-song",
    ))
    session.add(Version(id="alice-v1", song_id="alice-song", version_number=1, lyrics="Hi"))
    session.add(Generation(
        id="alice-gen", song_id="alice-song", version_id="alice-v1",
        generation_number=1, mp3_path="alice/g1.mp3", seed=1,
        created_at=_ts(20), is_shared=True, share_slug="slug-gen",
    ))
    session.add(Playlist(
        id="alice-pl", title="Alice Playlist", created_by=USER_A,
        created_at=_ts(10), is_shared=True, share_slug="slug-pl",
    ))
    session.add(Album(
        id="bob-album", title="Bob Album", artist="Artist",
        created_by=USER_B, created_at=_ts(100),
        is_shared=True, share_slug="slug-bob",
    ))
    session.add(Album(
        id="admin-album", title="Admin Album", artist="Artist",
        created_by=ADMIN_ID, created_at=_ts(5),
        is_shared=True, share_slug="slug-admin",
    ))


def _inventory_client(tmp_path: Path, user_id: str, role: str = "user"):
    from fastapi import FastAPI

    from songmaker_cli.api import router
    from songmaker_cli.app_context import AppContext
    from songmaker_cli.middleware import AuthenticatedUser, get_current_user

    factory = _inventory_factory(tmp_path)
    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = (
        lambda: AuthenticatedUser(id=user_id, username=f"test-{user_id}", role=role, is_active=True)
    )
    app.include_router(router)
    return TestClient(app), factory


def test_share_inventory_lists_four_types_for_owner(tmp_path: Path) -> None:
    from songmaker_cli.db.models import Album, Generation, Playlist, Song
    from songmaker_cli.db.queries import list_shared_inventory

    factory = _inventory_factory(tmp_path)
    with factory() as session:
        page = list_shared_inventory(session, USER_A, offset=0, limit=50)
    assert page.total == 4
    assert page.filtered_total == 4
    assert [(type(item), item.id) for item in page.items] == [
        (Album, "alice-album"),
        (Song, "alice-song"),
        (Generation, "alice-gen"),
        (Playlist, "alice-pl"),
    ]
    assert {item.share_slug for item in page.items} == {
        "slug-album", "slug-song", "slug-gen", "slug-pl",
    }


def test_share_inventory_isolates_by_user_id(tmp_path: Path) -> None:
    from songmaker_cli.db.queries import list_shared_inventory

    factory = _inventory_factory(tmp_path)
    with factory() as session:
        alice = list_shared_inventory(session, USER_A, offset=0, limit=50)
        bob = list_shared_inventory(session, USER_B, offset=0, limit=50)
        admin = list_shared_inventory(session, ADMIN_ID, offset=0, limit=50)
    assert {item.id for item in alice.items} == {
        "alice-album", "alice-song", "alice-gen", "alice-pl",
    }
    assert {item.id for item in bob.items} == {"bob-album"}
    assert {item.id for item in admin.items} == {"admin-album"}
    assert admin.total == 1


def test_share_inventory_excludes_soft_deleted(tmp_path: Path) -> None:
    from songmaker_cli.db.queries import list_shared_inventory, soft_delete_album, soft_delete_song

    factory = _inventory_factory(tmp_path)
    with factory() as session:
        soft_delete_song(session, "alice-song")
        session.commit()
    with factory() as session:
        page = list_shared_inventory(session, USER_A, offset=0, limit=50)
    assert {item.id for item in page.items} == {"alice-album", "alice-pl"}
    assert page.total == 2

    with factory() as session:
        soft_delete_album(session, "alice-album")
        session.commit()
    with factory() as session:
        page = list_shared_inventory(session, USER_A, offset=0, limit=50)
    assert {item.id for item in page.items} == {"alice-pl"}
    assert page.total == 1


def test_share_inventory_includes_archived_take(tmp_path: Path) -> None:
    from songmaker_cli.db.queries import archive_generation, list_shared_inventory

    factory = _inventory_factory(tmp_path)
    with factory() as session:
        archive_generation(session, "alice-gen")
        session.commit()
    with factory() as session:
        page = list_shared_inventory(session, USER_A, offset=0, limit=50)
    gens = [item for item in page.items if item.id == "alice-gen"]
    assert len(gens) == 1
    assert gens[0].is_archived is True
    assert page.total == 4


def test_share_inventory_pagination_total_is_unfiltered(tmp_path: Path) -> None:
    from songmaker_cli.constants import LIBRARY_ITEM_ALBUM
    from songmaker_cli.db.queries import list_shared_inventory

    factory = _inventory_factory(tmp_path)
    with factory() as session:
        first = list_shared_inventory(session, USER_A, offset=0, limit=2)
        second = list_shared_inventory(session, USER_A, offset=2, limit=2)
        albums = list_shared_inventory(
            session, USER_A, item_type=LIBRARY_ITEM_ALBUM, offset=0, limit=50,
        )
    assert first.total == 4
    assert first.filtered_total == 4
    assert len(first.items) == 2
    assert [item.id for item in first.items] == ["alice-album", "alice-song"]
    assert second.total == 4
    assert [item.id for item in second.items] == ["alice-gen", "alice-pl"]
    assert albums.total == 4
    assert albums.filtered_total == 1
    assert [item.id for item in albums.items] == ["alice-album"]


def test_share_inventory_requires_public_slug_reachability(tmp_path: Path) -> None:
    from songmaker_cli.db.queries import list_shared_inventory

    factory = _inventory_factory(tmp_path)
    with factory() as session:
        session.query(Album).filter_by(id="alice-album").update({
            "is_shared": False,
        })
        session.query(Song).filter_by(id="alice-song").update({
            "share_slug": None,
        })
        session.commit()
    with factory() as session:
        page = list_shared_inventory(session, USER_A, offset=0, limit=50)
    assert {item.id for item in page.items} == {"alice-gen", "alice-pl"}
    assert page.total == 2


def test_api_library_shares_uses_user_id_not_owner_filter(tmp_path: Path) -> None:
    admin, _ = _inventory_client(tmp_path, ADMIN_ID, role="admin")
    resp = admin.get("/api/library/shares")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert [item["id"] for item in data["items"]] == ["admin-album"]
    assert data["items"][0]["type"] == "album"
    assert data["items"][0]["public_path"] == "/share/slug-admin"


def test_api_library_shares_type_filter_does_not_change_n(tmp_path: Path) -> None:
    alice, _ = _inventory_client(tmp_path, USER_A)
    all_items = alice.get("/api/library/shares").json()
    albums = alice.get("/api/library/shares", params={"type": "album"}).json()
    takes = alice.get("/api/library/shares", params={"type": "generation"}).json()
    assert all_items["total"] == 4
    assert albums["total"] == 4
    assert takes["total"] == 4
    assert [item["type"] for item in albums["items"]] == ["album"]
    assert takes["items"][0]["type"] == "generation"
    assert takes["items"][0]["is_archived"] is False
    assert takes["items"][0]["generation_number"] == 1
    assert takes["items"][0]["public_path"] == "/share/gen/slug-gen"
    assert albums["has_more"] is False


def test_api_library_shares_paginates(tmp_path: Path) -> None:
    alice, _ = _inventory_client(tmp_path, USER_A)
    first = alice.get("/api/library/shares", params={"offset": 0, "limit": 3}).json()
    second = alice.get("/api/library/shares", params={"offset": 3, "limit": 3}).json()
    assert first["total"] == 4
    assert first["has_more"] is True
    assert len(first["items"]) == 3
    assert second["total"] == 4
    assert second["has_more"] is False
    assert [item["id"] for item in second["items"]] == ["alice-pl"]


def test_api_library_shares_rejects_unknown_type(tmp_path: Path) -> None:
    alice, _ = _inventory_client(tmp_path, USER_A)
    resp = alice.get("/api/library/shares", params={"type": "voice"})
    assert resp.status_code == 422


def test_api_library_shares_requires_auth(sharing_app: TestClient) -> None:
    unauthed = TestClient(sharing_app.app, cookies={})
    resp = unauthed.get("/api/library/shares")
    assert resp.status_code == 401


# ── Share payload cues (#138) ───────────────────────────────────────

_SUNG_CUES = [
    {
        "start": 0.0,
        "end": 3.0,
        "text": "the lantern hums",
        "words": [
            {"start": 0.0, "end": 1.0, "text": "the"},
            {"start": 1.0, "end": 2.0, "text": "lantern"},
            {"start": 2.0, "end": 3.0, "text": "hums"},
        ],
    },
]
_OTHER_TAKE_CUES = [{"start": 0.0, "end": 2.0, "text": "a different rendition"}]
# A take scored before word timestamps stores no words; the payload says so
# explicitly rather than dropping the key.
_OTHER_TAKE_CUES_PAYLOAD = [{**_OTHER_TAKE_CUES[0], "words": None}]

_SHARED_ALBUM_KEYS = {"title", "artist", "subtitle", "year", "songs", "cover"}
_SHARED_ALBUM_SONG_KEYS = {
    "id", "title", "track_number", "audio_url",
    "generation_id", "audio_duration", "lyrics", "whisper_cues",
}
_SHARED_SONG_KEYS = {
    "title", "artist", "album_title", "audio_url", "cover",
    "generation_id", "audio_duration", "lyrics", "whisper_cues",
}
_SHARED_GENERATION_KEYS = {
    "title", "artist", "album_title", "generation_number", "seed", "audio_url",
    "generation_id", "audio_duration", "lyrics", "whisper_cues",
}
_SHARED_PLAYLIST_ENTRY_KEYS = {
    "entry_id", "song_title", "artist", "generation_number", "audio_url",
    "generation_id", "audio_duration", "lyrics", "whisper_cues",
}


def _seed_song_with_two_takes(session) -> None:
    admin = User(username="admin", password_hash=hash_password("admin12345"), role="admin")
    session.add(admin)
    session.add(Album(id="test_album", title="Test Album", artist="Test Artist"))
    session.add(
        Song(id="s1", title="Song One", album_id="test_album", track_number=1, slug="song-one"),
    )
    session.add(Version(
        id="v1", song_id="s1", version_number=1, lyrics="the lantern hums", audio_duration=187,
    ))
    session.add(Playlist(id="pl1", title="My Playlist"))
    session.add(Generation(
        id="g1", song_id="s1", version_id="v1", generation_number=1,
        mp3_path="admin_user/g1.mp3", seed=1, is_picked=True,
        whisper_text="the lantern hums", whisper_cues=_SUNG_CUES,
    ))
    session.add(Generation(
        id="g2", song_id="s1", version_id="v1", generation_number=2,
        mp3_path="admin_user/g2.mp3", seed=2,
        whisper_text="a different rendition", whisper_cues=_OTHER_TAKE_CUES,
    ))
    session.add(PlaylistEntry(id="e1", playlist_id="pl1", generation_id="g1", position=0))


@pytest.fixture()
def two_take_app(tmp_path: Path) -> TestClient:
    client, _ = make_test_app(tmp_path, seed_db=_seed_song_with_two_takes)
    login_and_csrf(client, "admin", "admin12345")
    return client


def _share_slug(client: TestClient, path: str) -> str:
    return client.post(path).json()["share_slug"]


@pytest.mark.parametrize(
    ("share_path", "shared_path_template", "expected_cues"),
    [
        ("/api/songs/s1/share", "/shared/song/{slug}", _SUNG_CUES),
        ("/api/generations/g1/share", "/shared/gen/{slug}", _SUNG_CUES),
        ("/api/generations/g2/share", "/shared/gen/{slug}", _OTHER_TAKE_CUES_PAYLOAD),
    ],
)
def test_share_payload_carries_only_the_shared_takes_cues(
    two_take_app: TestClient,
    share_path: str,
    shared_path_template: str,
    expected_cues: list[dict],
) -> None:
    slug = _share_slug(two_take_app, share_path)

    unauthed = TestClient(two_take_app.app, cookies={})
    data = unauthed.get(shared_path_template.format(slug=slug)).json()

    assert data["whisper_cues"] == expected_cues


def test_shared_album_view_carries_the_picked_takes_cues(two_take_app: TestClient) -> None:
    slug = _share_slug(two_take_app, "/api/albums/test_album/share")

    unauthed = TestClient(two_take_app.app, cookies={})
    data = unauthed.get(f"/shared/{slug}").json()

    assert data["songs"][0]["whisper_cues"] == _SUNG_CUES


def test_shared_playlist_view_carries_the_entry_takes_cues(two_take_app: TestClient) -> None:
    slug = _share_slug(two_take_app, "/api/playlists/pl1/share")

    unauthed = TestClient(two_take_app.app, cookies={})
    data = unauthed.get(f"/shared/playlist/{slug}").json()

    assert data["entries"][0]["whisper_cues"] == _SUNG_CUES


def test_share_payloads_expose_only_the_contract_fields(two_take_app: TestClient) -> None:
    """A public listener gets the shared take's playback data and nothing else —
    no transcript, no scores, no sibling takes, no owner."""
    album_slug = _share_slug(two_take_app, "/api/albums/test_album/share")
    song_slug = _share_slug(two_take_app, "/api/songs/s1/share")
    gen_slug = _share_slug(two_take_app, "/api/generations/g1/share")
    playlist_slug = _share_slug(two_take_app, "/api/playlists/pl1/share")

    unauthed = TestClient(two_take_app.app, cookies={})
    album = unauthed.get(f"/shared/{album_slug}").json()
    song = unauthed.get(f"/shared/song/{song_slug}").json()
    generation = unauthed.get(f"/shared/gen/{gen_slug}").json()
    playlist = unauthed.get(f"/shared/playlist/{playlist_slug}").json()

    assert set(album) == _SHARED_ALBUM_KEYS
    assert set(album["songs"][0]) == _SHARED_ALBUM_SONG_KEYS
    assert set(song) == _SHARED_SONG_KEYS
    assert set(generation) == _SHARED_GENERATION_KEYS
    assert set(playlist) == {"title", "entries"}
    assert set(playlist["entries"][0]) == _SHARED_PLAYLIST_ENTRY_KEYS

"""Tests for soft delete + restore on Albums and Songs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import TEST_SECRET, make_fake_redis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from songmaker_cli.app_context import AppContext
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import (
    Album,
    AuditLog,
    AvailableModel,
    ChatMessage,
    Generation,
    Song,
    User,
    Version,
)
from songmaker_cli.db.queries import (
    RestoreWindowExpiredError,
    add_song_to_playlist,
    create_playlist,
    create_song,
    delete_album,
    delete_song,
    enable_album_sharing,
    enable_song_sharing,
    get_album,
    get_album_by_slug,
    get_playlist,
    get_song,
    get_song_by_slug,
    hard_delete_user,
    list_albums,
    move_song,
    pick_generation,
    restore_album,
    restore_song,
    soft_delete_album,
    soft_delete_song,
)
from songmaker_cli.db.queries.albums import list_expired_albums
from songmaker_cli.db.queries.songs import list_expired_songs
from songmaker_cli.middleware import AuthenticatedUser, get_current_user
from songmaker_cli.settings import get_settings

RESTORE_WINDOW = timedelta(days=get_settings().soft_delete_retention_days)

_DEFAULT_USER_ID = "u-test"
_OTHER_USER_ID = "u-other"


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    factory = init_db(tmp_path / "test.db")
    session = factory()
    yield session
    session.close()


def _seed(session: Session, owner: str | None = None) -> None:
    session.add(Album(id="rock", title="Rock", artist="A", created_by=owner))
    session.add(
        Song(id="s1", title="Song1", album_id="rock", track_number=1, slug="song1"),
    )
    session.add(
        Song(id="s2", title="Song2", album_id="rock", track_number=2, slug="song2"),
    )
    session.add(Version(id="v1", song_id="s1", version_number=1))
    session.add(Version(id="v2", song_id="s2", version_number=1))
    session.add(Generation(
        id="g1", song_id="s1", version_id="v1", generation_number=1,
        mp3_path="u-test/g1.mp3", is_picked=True,
    ))
    session.add(Generation(
        id="g2", song_id="s2", version_id="v2", generation_number=1,
        mp3_path="u-test/g2.mp3", is_picked=True,
    ))
    session.commit()


@pytest.fixture()
def seeded(db_session: Session) -> Session:
    _seed(db_session)
    return db_session


# ── Query-layer tests ────────────────────────────────────────────────


def test_soft_delete_album_hides_from_list(seeded: Session) -> None:
    soft_delete_album(seeded, "rock")
    seeded.commit()
    assert list_albums(seeded) == []
    assert get_album(seeded, "rock") is None


def test_soft_delete_album_cascades_to_live_songs(seeded: Session) -> None:
    soft_delete_album(seeded, "rock")
    seeded.commit()
    assert get_song(seeded, "s1") is None
    assert get_song(seeded, "s2") is None


def test_soft_delete_song_hides_single_song(seeded: Session) -> None:
    soft_delete_song(seeded, "s1")
    seeded.commit()
    assert get_song(seeded, "s1") is None
    assert get_song(seeded, "s2") is not None


def test_get_song_by_slug_404s_on_soft_deleted(seeded: Session) -> None:
    enable_song_sharing(seeded, "s1")
    seeded.commit()
    slug = get_song(seeded, "s1").share_slug
    assert get_song_by_slug(seeded, slug) is not None
    soft_delete_song(seeded, "s1")
    seeded.commit()
    assert get_song_by_slug(seeded, slug) is None


def test_get_album_by_slug_404s_on_soft_deleted(seeded: Session) -> None:
    enable_album_sharing(seeded, "rock")
    seeded.commit()
    slug = get_album(seeded, "rock").share_slug
    assert get_album_by_slug(seeded, slug) is not None
    soft_delete_album(seeded, "rock")
    seeded.commit()
    assert get_album_by_slug(seeded, slug) is None


def test_restore_album_within_window(seeded: Session) -> None:
    soft_delete_album(seeded, "rock")
    seeded.commit()
    restored = restore_album(seeded, "rock")
    seeded.commit()
    assert restored.deleted_at is None
    assert get_album(seeded, "rock") is not None
    assert get_song(seeded, "s1") is not None
    assert get_song(seeded, "s2") is not None


def test_restore_album_does_not_revive_individually_deleted_songs(seeded: Session) -> None:
    """The cascade-timestamp rule: a song killed *before* the album stays dead."""
    soft_delete_song(seeded, "s1")
    seeded.commit()
    soft_delete_album(seeded, "rock")
    seeded.commit()
    restore_album(seeded, "rock")
    seeded.commit()
    assert get_album(seeded, "rock") is not None
    assert get_song(seeded, "s1") is None
    assert get_song(seeded, "s2") is not None


def test_restore_album_410_after_window(seeded: Session) -> None:
    soft_delete_album(seeded, "rock")
    album = (
        seeded.query(Album)
        .execution_options(include_deleted=True)
        .filter_by(id="rock")
        .first()
    )
    album.deleted_at = datetime.now(timezone.utc) - RESTORE_WINDOW - timedelta(seconds=1)
    seeded.commit()
    with pytest.raises(RestoreWindowExpiredError):
        restore_album(seeded, "rock")


def test_restore_song_410_after_window(seeded: Session) -> None:
    soft_delete_song(seeded, "s1")
    song = (
        seeded.query(Song)
        .execution_options(include_deleted=True)
        .filter_by(id="s1")
        .first()
    )
    song.deleted_at = datetime.now(timezone.utc) - RESTORE_WINDOW - timedelta(seconds=1)
    seeded.commit()
    with pytest.raises(RestoreWindowExpiredError):
        restore_song(seeded, "s1")


def test_restore_song_rejects_deleted_album(seeded: Session) -> None:
    soft_delete_album(seeded, "rock")
    seeded.commit()
    with pytest.raises(ValueError, match="parent album is deleted"):
        restore_song(seeded, "s1")


def test_restore_album_idempotent_on_live(seeded: Session) -> None:
    restored = restore_album(seeded, "rock")
    assert restored.deleted_at is None


def test_create_song_after_soft_delete_no_track_collision(seeded: Session) -> None:
    soft_delete_song(seeded, "s2")
    seeded.commit()
    new_song = create_song(seeded, title="Song3", album_id="rock", slug="song3")
    seeded.commit()
    assert new_song.track_number == 3


def test_move_song_target_filtered_when_album_soft_deleted(seeded: Session) -> None:
    seeded.add(Album(id="other", title="Other", artist="A"))
    seeded.commit()
    soft_delete_album(seeded, "other")
    seeded.commit()
    with pytest.raises(ValueError, match="Album not found"):
        move_song(seeded, "s1", "other", slug="song1")


def test_move_song_source_filtered_when_song_soft_deleted(seeded: Session) -> None:
    soft_delete_song(seeded, "s1")
    seeded.commit()
    with pytest.raises(ValueError, match="Song not found"):
        move_song(seeded, "s1", "rock", slug="song1")


def test_list_expired_finds_only_past_cutoff(seeded: Session) -> None:
    soft_delete_album(seeded, "rock")
    seeded.commit()
    cutoff = datetime.now(timezone.utc) + timedelta(seconds=10)
    expired = list_expired_albums(seeded, cutoff)
    assert len(expired) == 1
    cutoff_old = datetime.now(timezone.utc) - timedelta(days=365)
    assert list_expired_albums(seeded, cutoff_old) == []


def test_list_expired_songs_excludes_album_ids(seeded: Session) -> None:
    soft_delete_song(seeded, "s1")
    soft_delete_song(seeded, "s2")
    seeded.commit()
    cutoff = datetime.now(timezone.utc) + timedelta(seconds=10)
    songs = list_expired_songs(seeded, cutoff, exclude_album_ids=["rock"])
    assert songs == []
    songs = list_expired_songs(seeded, cutoff, exclude_album_ids=[])
    assert {s.id for s in songs} == {"s1", "s2"}


def test_hard_delete_album_sees_soft_deleted(seeded: Session) -> None:
    soft_delete_album(seeded, "rock")
    seeded.commit()
    paths = delete_album(seeded, "rock")
    seeded.commit()
    assert "u-test/g1.mp3" in paths
    album = (
        seeded.query(Album)
        .execution_options(include_deleted=True)
        .filter_by(id="rock")
        .first()
    )
    assert album is None


def test_hard_delete_song_sees_soft_deleted(seeded: Session) -> None:
    soft_delete_song(seeded, "s1")
    seeded.commit()
    paths = delete_song(seeded, "s1")
    seeded.commit()
    assert "u-test/g1.mp3" in paths


def test_hard_delete_user_includes_soft_deleted_albums(db_session: Session) -> None:
    db_session.add(User(id=_OTHER_USER_ID, username="u2", password_hash="x", role="user"))
    db_session.flush()
    _seed(db_session, owner=_OTHER_USER_ID)
    soft_delete_album(db_session, "rock")
    db_session.commit()
    paths, album_ids = hard_delete_user(db_session, _OTHER_USER_ID)
    db_session.commit()
    assert "u-test/g1.mp3" in paths
    assert "rock" in album_ids
    assert db_session.query(Album).execution_options(
        include_deleted=True,
    ).count() == 0


def test_chat_messages_survive_soft_delete_and_restore(seeded: Session) -> None:
    seeded.add(ChatMessage(id="m1", song_id="s1", role="user", content="hi"))
    seeded.commit()
    soft_delete_album(seeded, "rock")
    seeded.commit()
    assert seeded.query(ChatMessage).filter_by(song_id="s1").count() == 1
    restore_album(seeded, "rock")
    seeded.commit()
    assert seeded.query(ChatMessage).filter_by(song_id="s1").count() == 1


def test_playlist_entries_filtered_when_song_soft_deleted(seeded: Session) -> None:
    seeded.add(User(id="owner", username="o", password_hash="x", role="user"))
    seeded.commit()
    pl = create_playlist(seeded, "Mix", "owner")
    pick_generation(seeded, "g1")
    pick_generation(seeded, "g2")
    add_song_to_playlist(seeded, pl.id, "s1")
    add_song_to_playlist(seeded, pl.id, "s2")
    seeded.commit()
    soft_delete_song(seeded, "s1")
    seeded.commit()

    from songmaker_cli.api_models.playlists import PlaylistDetailResponse
    loaded = get_playlist(seeded, pl.id)
    resp = PlaylistDetailResponse.from_orm(loaded)
    assert resp.entry_count == 1
    assert len(resp.entries) == 1
    assert resp.entries[0].song_title == "Song2"


# ── API-layer tests ──────────────────────────────────────────────────


def _fake_user(user_id: str, role: str):
    user = AuthenticatedUser(
        id=user_id, username=f"u_{role}", role=role, is_active=True,
    )
    return lambda: user


def _make_client(tmp_path: Path, role: str = "user") -> TestClient:
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(
            id=_DEFAULT_USER_ID, username="u_user",
            password_hash="x", role=role,
        ))
        session.flush()
        session.add(Album(
            id="rock", title="Rock", artist="A", created_by=_DEFAULT_USER_ID,
        ))
        session.add(Song(id="s1", title="Song1", album_id="rock", track_number=1))
        session.add(Version(id="v1", song_id="s1", version_number=1))
        session.add(Generation(
            id="g1", song_id="s1", version_id="v1", generation_number=1,
            mp3_path="u-test/g1.mp3",
        ))
        session.query(AvailableModel).update({"is_active": True})
        session.commit()

    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router

    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user(_DEFAULT_USER_ID, role)
    app.include_router(router)
    return TestClient(app)


def test_api_delete_album_soft_deletes(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    r = client.delete("/api/albums/rock")
    assert r.status_code == 200
    assert client.get("/api/albums").json()["total"] == 0


def test_api_restore_album_round_trip(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.delete("/api/albums/rock")
    r = client.post("/api/albums/rock/restore")
    assert r.status_code == 200
    assert client.get("/api/albums").json()["total"] == 1


def test_api_restore_album_410_after_window(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.delete("/api/albums/rock")
    factory = client.app.state.ctx.db
    with factory() as session:
        album = (
            session.query(Album)
            .execution_options(include_deleted=True)
            .filter_by(id="rock")
            .first()
        )
        album.deleted_at = datetime.now(timezone.utc) - RESTORE_WINDOW - timedelta(hours=1)
        session.commit()
    r = client.post("/api/albums/rock/restore")
    assert r.status_code == 410


def test_api_restore_song_round_trip(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.delete("/api/songs/s1")
    assert client.get("/api/songs").json()["total"] == 0
    r = client.post("/api/songs/s1/restore")
    assert r.status_code == 200
    assert client.get("/api/songs").json()["total"] == 1


def test_api_restore_other_users_album_404(tmp_path: Path) -> None:
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(id="u1", username="u1", password_hash="x", role="user"))
        session.add(User(id="u2", username="u2", password_hash="x", role="user"))
        session.flush()
        session.add(Album(id="rock", title="R", artist="A", created_by="u1"))
        session.commit()

    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router

    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user("u1", "user")
    app.include_router(router)
    c1 = TestClient(app)
    c1.delete("/api/albums/rock")

    app.dependency_overrides[get_current_user] = _fake_user("u2", "user")
    c2 = TestClient(app)
    r = c2.post("/api/albums/rock/restore")
    assert r.status_code == 404


def test_api_audit_records_delete_and_restore(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.delete("/api/albums/rock")
    client.post("/api/albums/rock/restore")
    factory = client.app.state.ctx.db
    with factory() as session:
        actions = [a.action for a in session.query(AuditLog).all()]
    assert "delete" in actions
    assert "restore" in actions


def test_api_unique_album_id_skips_soft_deleted(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.delete("/api/albums/rock")
    r = client.post("/api/albums", json={"title": "Rock"})
    assert r.status_code == 200
    new_id = r.json()["id"]
    assert new_id != "rock"

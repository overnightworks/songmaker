"""Tests for soft delete + restore on Albums and Songs."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.auth_dependencies import get_current_user
from songmaker_cli.cleanup import run_cleanup_expired
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
from songmaker_cli.db.queries.albums import (
    archive_album,
    delete_album,
    enable_album_sharing,
    get_album,
    get_album_by_slug,
    list_albums,
    list_expired_albums,
    restore_album,
    set_album_cover_key,
    soft_delete_album,
    unarchive_album,
    update_album,
)
from songmaker_cli.db.queries.generations import pick_generation
from songmaker_cli.db.queries.playlists import add_song_to_playlist, create_playlist, get_playlist
from songmaker_cli.db.queries.songs import (
    create_song,
    delete_song,
    enable_song_sharing,
    get_song,
    get_song_by_slug,
    list_expired_songs,
    move_song,
    restore_song,
    set_song_cover_key,
    soft_delete_song,
)
from songmaker_cli.db.soft_delete import RestoreWindowExpiredError
from songmaker_cli.settings import get_settings

RESTORE_WINDOW = timedelta(days=get_settings().final_deletion_days)

_DEFAULT_USER_ID = "u-test"
_OTHER_USER_ID = "u-other"


@pytest.fixture
def db_session(pg_factory) -> Session:
    session = pg_factory()
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


@pytest.fixture
def seeded(db_session: Session) -> Session:
    _seed(db_session)
    return db_session


# ── Query-layer tests ────────────────────────────────────────────────


_ALBUM_MUTATIONS = {
    "update": lambda s, album_id: update_album(s, album_id, title="New"),
    "cover": lambda s, album_id: set_album_cover_key(s, album_id, "k"),
    "delete": soft_delete_album,
    "restore": restore_album,
    "archive": archive_album,
    "unarchive": unarchive_album,
}


@pytest.mark.parametrize(
    ("mutation", "trashed"),
    [
        pytest.param(name, trashed, id=f"{name}-{'in-trash' if trashed else 'gone'}")
        for name in _ALBUM_MUTATIONS
        for trashed in (True, False)
        if not (name == "restore" and trashed)
    ],
)
def test_album_mutation_of_a_missing_album_raises_not_found(
    seeded: Session, mutation: str, trashed: bool
) -> None:
    if trashed:
        soft_delete_album(seeded, "rock")
        seeded.commit()
        album_id = "rock"
    else:
        album_id = "never-existed"

    with pytest.raises(ValueError, match="Album not found"):
        _ALBUM_MUTATIONS[mutation](seeded, album_id)


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


@dataclass(frozen=True)
class _Deletable:
    id: str
    soft_delete: Callable[..., object]
    get: Callable[..., object]
    restore: Callable[..., object]


_ALBUM = _Deletable("rock", soft_delete_album, get_album, restore_album)
_SONG = _Deletable("s1", soft_delete_song, get_song, restore_song)
_KINDS = [pytest.param(_ALBUM, id="album"), pytest.param(_SONG, id="song")]


@pytest.mark.parametrize("kind", _KINDS)
def test_restore_410_after_window(seeded: Session, kind: _Deletable) -> None:
    kind.soft_delete(seeded, kind.id)
    row = kind.get(seeded, kind.id, include_deleted_rows=True)
    row.deleted_at = datetime.now(timezone.utc) - RESTORE_WINDOW - timedelta(seconds=1)
    seeded.commit()
    with pytest.raises(RestoreWindowExpiredError):
        kind.restore(seeded, kind.id)


@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize(
    ("age_days", "attempt", "still_deleted"),
    [
        pytest.param(6, nullcontext, False, id="inside"),
        pytest.param(8, lambda: pytest.raises(RestoreWindowExpiredError), True, id="expired"),
    ],
)
def test_restore_window_follows_the_final_deletion_setting(
    seeded: Session, monkeypatch: pytest.MonkeyPatch, fresh_settings, kind: _Deletable,
    age_days: int, attempt: Callable[[], AbstractContextManager], still_deleted: bool,
) -> None:
    monkeypatch.setenv("FINAL_DELETION_DAYS", "7")
    kind.soft_delete(seeded, kind.id)
    row = kind.get(seeded, kind.id, include_deleted_rows=True)
    row.deleted_at = datetime.now(timezone.utc) - timedelta(days=age_days)
    seeded.commit()

    with attempt():
        kind.restore(seeded, kind.id)

    row = kind.get(seeded, kind.id, include_deleted_rows=True)
    assert (row.deleted_at is not None) is still_deleted


def test_restore_song_rejects_deleted_album(seeded: Session) -> None:
    soft_delete_album(seeded, "rock")
    seeded.commit()
    with pytest.raises(ValueError, match="parent album is deleted"):
        restore_song(seeded, "s1")


@pytest.mark.parametrize(
    ("query", "make_unavailable"),
    [
        pytest.param(
            lambda session: set_song_cover_key(session, "s1", "cover.png"),
            lambda session: soft_delete_song(session, "s1"),
            id="cover-of-trashed-song",
        ),
        pytest.param(
            lambda session: set_song_cover_key(session, "s1", "cover.png"),
            lambda session: delete_song(session, "s1"),
            id="cover-of-purged-song",
        ),
        pytest.param(
            lambda session: soft_delete_song(session, "s1"),
            lambda session: soft_delete_song(session, "s1"),
            id="second-delete-of-trashed-song",
        ),
        pytest.param(
            lambda session: soft_delete_song(session, "s1"),
            lambda session: delete_song(session, "s1"),
            id="delete-of-purged-song",
        ),
        pytest.param(
            lambda session: restore_song(session, "s1"),
            lambda session: delete_song(session, "s1"),
            id="restore-of-purged-song",
        ),
    ],
)
def test_song_query_refuses_a_song_that_vanished_after_the_access_check(
    seeded: Session,
    query: Callable[[Session], object],
    make_unavailable: Callable[[Session], object],
) -> None:
    make_unavailable(seeded)
    seeded.commit()

    with pytest.raises(ValueError, match="Song not found: s1"):
        query(seeded)


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
    seeded.add(User(id="owner", username="o", role="user"))
    seeded.commit()
    pl = create_playlist(seeded, "Mix", "owner", slug="mix")
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


def _make_client(tmp_path: Path, pg_factory, role: str = "user") -> TestClient:
    with pg_factory() as session:
        session.add(User(
            id=_DEFAULT_USER_ID, username="u_user", role=role,
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

    app = make_router_app(
        make_router_ctx(tmp_path, db=pg_factory),
        user=make_authenticated_user(_DEFAULT_USER_ID, role=role, username=f"u_{role}"),
    )
    return web_client(app)


def test_api_delete_album_soft_deletes(tmp_path: Path, pg_factory) -> None:
    client = _make_client(tmp_path, pg_factory)
    r = client.delete("/api/albums/rock")
    assert r.status_code == 200
    assert client.get("/api/albums").json()["total"] == 0


def test_api_restore_album_round_trip(tmp_path: Path, pg_factory) -> None:
    client = _make_client(tmp_path, pg_factory)
    client.delete("/api/albums/rock")
    r = client.post("/api/albums/rock/restore")
    assert r.status_code == 200
    assert client.get("/api/albums").json()["total"] == 1


@pytest.mark.parametrize(
    ("entity", "model", "row_id"),
    [
        pytest.param("albums", Album, "rock", id="album"),
        pytest.param("songs", Song, "s1", id="song"),
    ],
)
def test_api_restore_410_after_window(
    tmp_path: Path, pg_factory, entity: str, model: type, row_id: str,
) -> None:
    client = _make_client(tmp_path, pg_factory)
    client.delete(f"/api/{entity}/{row_id}")
    factory = client.app.state.ctx.db

    def query(session: Session):
        return session.query(model).execution_options(include_deleted=True).filter_by(id=row_id)

    with factory() as session:
        query(session).one().deleted_at = (
            datetime.now(timezone.utc) - RESTORE_WINDOW - timedelta(hours=1)
        )
        session.commit()
    r = client.post(f"/api/{entity}/{row_id}/restore")
    assert r.status_code == 410
    assert f"{row_id} was deleted" in r.json()["detail"]
    assert "restore window" in r.json()["detail"]
    with factory() as session:
        assert query(session).one().deleted_at is not None


def test_api_restore_song_round_trip(tmp_path: Path, pg_factory) -> None:
    client = _make_client(tmp_path, pg_factory)
    client.delete("/api/songs/s1")
    assert client.get("/api/songs").json()["total"] == 0
    r = client.post("/api/songs/s1/restore")
    assert r.status_code == 200
    assert client.get("/api/songs").json()["total"] == 1


def test_api_restore_other_users_album_404(tmp_path: Path, pg_factory) -> None:
    with pg_factory() as session:
        session.add(User(id="u1", username="u1", role="user"))
        session.add(User(id="u2", username="u2", role="user"))
        session.flush()
        session.add(Album(id="rock", title="R", artist="A", created_by="u1"))
        session.commit()

    app = make_router_app(
        make_router_ctx(tmp_path, db=pg_factory),
        user=make_authenticated_user("u1", username="u_user"),
    )
    c1 = web_client(app)
    c1.delete("/api/albums/rock")

    app.dependency_overrides[get_current_user] = lambda: make_authenticated_user(
        "u2", username="u_user"
    )
    c2 = web_client(app)
    r = c2.post("/api/albums/rock/restore")
    assert r.status_code == 404


def test_api_audit_records_delete_and_restore(tmp_path: Path, pg_factory) -> None:
    client = _make_client(tmp_path, pg_factory)
    client.delete("/api/albums/rock")
    client.post("/api/albums/rock/restore")
    factory = client.app.state.ctx.db
    with factory() as session:
        actions = [a.action for a in session.query(AuditLog).all()]
    assert "delete" in actions
    assert "restore" in actions


def test_api_unique_album_id_skips_soft_deleted(tmp_path: Path, pg_factory) -> None:
    client = _make_client(tmp_path, pg_factory)
    client.delete("/api/albums/rock")
    r = client.post("/api/albums", json={"title": "Rock"})
    assert r.status_code == 200
    new_id = r.json()["id"]
    assert new_id != "rock"


@pytest.mark.parametrize("final_deletion_days", [30, 7])
@pytest.mark.parametrize(
    ("past_period_end", "is_purged"),
    [
        (-timedelta(days=1), False),
        (timedelta(0), False),
        (timedelta(microseconds=1), True),
        (timedelta(days=1), True),
    ],
)
def test_trashed_song_is_purged_only_past_the_end_of_the_final_deletion_period(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fresh_settings,
    final_deletion_days: int, past_period_end: timedelta, is_purged: bool,
) -> None:
    monkeypatch.setenv("FINAL_DELETION_DAYS", str(final_deletion_days))
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    _seed(db_session)
    soft_delete_song(db_session, "s1")
    song = get_song(db_session, "s1", include_deleted_rows=True)
    song.deleted_at = now - timedelta(days=final_deletion_days) - past_period_end
    db_session.commit()

    _, song_count = run_cleanup_expired(lambda: db_session, tmp_path / "audio", now=now)

    assert song_count == (1 if is_purged else 0)

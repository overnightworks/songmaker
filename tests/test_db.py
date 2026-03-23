"""Tests for the database layer — models, engine, queries, and migration."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from songmaker_cli.db.engine import init_db, reset_engine
from songmaker_cli.db.models import Album, Rating, Score, Song, SongRevision, Version
from songmaker_cli.db.queries import (
    album_to_dict,
    get_album,
    get_version,
    get_version_by_path,
    list_albums,
    list_library,
    list_versions,
    save_rating,
    version_to_dict,
)


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    """Create a fresh in-memory-like SQLite DB and return a session."""
    reset_engine()
    factory = init_db(tmp_path / "test.db")
    session = factory()
    yield session
    session.close()
    reset_engine()


@pytest.fixture()
def seeded_session(db_session: Session) -> Session:
    """Session with sample data: 1 album, 2 songs, 3 versions, 1 score, 1 rating."""
    album = Album(id="test_album", title="Test Album", artist="TestArtist")
    db_session.add(album)

    song1 = Song(id="song1", title="Song One", album_id="test_album", track_number=1)
    song2 = Song(id="song2", title="Song Two", album_id="test_album", track_number=2)
    db_session.add_all([song1, song2])

    rev = SongRevision(id="rev1", song_id="song1", lyrics="verse one", prompt="rock", bpm=120)
    db_session.add(rev)

    v1 = Version(
        id="v1", song_id="song1", revision_id="rev1", version_number=1,
        mp3_path="test_album/01_song_one_v1.mp3", seed=42,
        generation_params={"bpm": 120, "key": "Am"},
    )
    v2 = Version(
        id="v2", song_id="song1", revision_id="rev1", version_number=2,
        mp3_path="test_album/01_song_one_v2.mp3", seed=99,
    )
    v3 = Version(
        id="v3", song_id="song2", version_number=1,
        mp3_path="test_album/02_song_two_v1.mp3",
    )
    db_session.add_all([v1, v2, v3])

    score = Score(id="s1", version_id="v1", scorer="batch", value={"dynamics": 55.0, "lyrical_coherence": 7})
    db_session.add(score)

    rating = Rating(id="r1", version_id="v1", rating=82.5, notes="great groove")
    db_session.add(rating)

    db_session.commit()
    return db_session


# ── Model tests ──────────────────────────────────────────────────────


def test_album_songs_relationship(seeded_session: Session) -> None:
    album = seeded_session.query(Album).filter_by(id="test_album").one()
    assert len(album.songs) == 2


def test_song_latest_revision(seeded_session: Session) -> None:
    song = seeded_session.query(Song).filter_by(id="song1").one()
    assert song.latest_revision is not None
    assert song.latest_revision.lyrics == "verse one"


def test_version_scores_relationship(seeded_session: Session) -> None:
    version = seeded_session.query(Version).filter_by(id="v1").one()
    assert len(version.scores) == 1
    assert version.scores[0].value["dynamics"] == 55.0


def test_version_rating_relationship(seeded_session: Session) -> None:
    version = seeded_session.query(Version).filter_by(id="v1").one()
    assert version.rating is not None
    assert version.rating.rating == 82.5


# ── Query tests ──────────────────────────────────────────────────────


def test_list_albums(seeded_session: Session) -> None:
    albums = list_albums(seeded_session)
    assert len(albums) == 1
    assert albums[0].id == "test_album"


def test_get_album(seeded_session: Session) -> None:
    album = get_album(seeded_session, "test_album")
    assert album is not None
    assert album.title == "Test Album"


def test_get_album_not_found(seeded_session: Session) -> None:
    assert get_album(seeded_session, "nonexistent") is None


def test_list_versions(seeded_session: Session) -> None:
    versions = list_versions(seeded_session, "song1")
    assert len(versions) == 2
    assert versions[0].version_number == 2  # desc order


def test_get_version(seeded_session: Session) -> None:
    version = get_version(seeded_session, "v1")
    assert version is not None
    assert version.seed == 42


def test_get_version_by_path(seeded_session: Session) -> None:
    version = get_version_by_path(seeded_session, "test_album/01_song_one_v1.mp3")
    assert version is not None
    assert version.id == "v1"


def test_get_version_by_path_not_found(seeded_session: Session) -> None:
    assert get_version_by_path(seeded_session, "nonexistent.mp3") is None


def test_list_library(seeded_session: Session) -> None:
    versions, total = list_library(seeded_session)
    assert total == 3
    assert len(versions) == 3


def test_list_library_filtered_by_album(seeded_session: Session) -> None:
    versions, total = list_library(seeded_session, album_id="test_album")
    assert total == 3


def test_list_library_pagination(seeded_session: Session) -> None:
    versions, total = list_library(seeded_session, limit=2, offset=0)
    assert len(versions) == 2
    assert total == 3


def test_save_rating_create(seeded_session: Session) -> None:
    rating = save_rating(seeded_session, "v2", 75.0, "decent")
    seeded_session.commit()
    assert rating.rating == 75.0
    assert rating.notes == "decent"


def test_save_rating_update(seeded_session: Session) -> None:
    save_rating(seeded_session, "v1", 90.0, "updated")
    seeded_session.commit()
    version = get_version(seeded_session, "v1")
    assert version.rating.rating == 90.0
    assert version.rating.notes == "updated"


# ── Serialization tests ──────────────────────────────────────────────


def test_version_to_dict(seeded_session: Session) -> None:
    version = get_version(seeded_session, "v1")
    d = version_to_dict(version)
    assert d["id"] == "v1"
    assert d["title"] == "Song One"
    assert d["album_id"] == "test_album"
    assert d["scores"]["dynamics"] == 55.0
    assert d["scores"]["user_rating"] == 82.5
    assert d["generation"]["bpm"] == 120


def test_album_to_dict(seeded_session: Session) -> None:
    album = get_album(seeded_session, "test_album")
    d = album_to_dict(album)
    assert d["id"] == "test_album"
    assert d["song_count"] == 2

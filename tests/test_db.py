"""Tests for the database layer — models, engine, queries."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from songmaker_cli.db.engine import init_db, reset_engine
from songmaker_cli.db.models import Album, Generation, Rating, Score, Song, Version
from songmaker_cli.db.queries import (
    album_to_dict,
    create_song,
    generation_to_dict,
    get_album,
    get_generation,
    get_generation_by_path,
    get_song,
    list_albums,
    list_songs,
    save_rating,
    song_to_dict,
    update_song,
)


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    reset_engine()
    factory = init_db(tmp_path / "test.db")
    session = factory()
    yield session
    session.close()
    reset_engine()


@pytest.fixture()
def seeded_session(db_session: Session) -> Session:
    album = Album(id="test", title="Test Album", artist="TestArtist")
    db_session.add(album)

    song = Song(id="s1", title="Song One", album_id="test", track_number=1)
    db_session.add(song)

    ver = Version(id="v1", song_id="s1", version_number=1, lyrics="verse one", prompt="rock")
    db_session.add(ver)

    gen1 = Generation(
        id="g1", song_id="s1", version_id="v1", generation_number=1,
        mp3_path="test/01_song_one_v1.mp3", seed=42,
        generation_params={"bpm": 120, "key": "Am"},
    )
    gen2 = Generation(
        id="g2", song_id="s1", version_id="v1", generation_number=2,
        mp3_path="test/01_song_one_v2.mp3", seed=99,
    )
    db_session.add_all([gen1, gen2])

    score = Score(id="sc1", generation_id="g1", scorer="batch", value={"dynamics": 55.0})
    db_session.add(score)

    rating = Rating(id="r1", generation_id="g1", rating=82.5, notes="great groove")
    db_session.add(rating)

    db_session.commit()
    return db_session


def test_song_latest_version(seeded_session: Session) -> None:
    song = seeded_session.query(Song).filter_by(id="s1").one()
    assert song.latest_version is not None
    assert song.latest_version.lyrics == "verse one"


def test_generation_scores(seeded_session: Session) -> None:
    gen = get_generation(seeded_session, "g1")
    assert gen is not None
    assert len(gen.scores) == 1
    assert gen.scores[0].value["dynamics"] == 55.0


def test_generation_rating(seeded_session: Session) -> None:
    gen = get_generation(seeded_session, "g1")
    assert gen is not None
    assert gen.rating is not None
    assert gen.rating.rating == 82.5


def test_list_albums(seeded_session: Session) -> None:
    assert len(list_albums(seeded_session)) == 1


def test_list_songs(seeded_session: Session) -> None:
    songs = list_songs(seeded_session)
    assert len(songs) == 1
    assert songs[0].title == "Song One"


def test_get_song(seeded_session: Session) -> None:
    song = get_song(seeded_session, "s1")
    assert song is not None
    assert len(song.generations) == 2


def test_get_generation_by_path(seeded_session: Session) -> None:
    gen = get_generation_by_path(seeded_session, "test/01_song_one_v1.mp3")
    assert gen is not None
    assert gen.id == "g1"


def test_save_rating_create(seeded_session: Session) -> None:
    save_rating(seeded_session, "g2", 75.0, "decent")
    seeded_session.commit()
    gen = get_generation(seeded_session, "g2")
    assert gen.rating.rating == 75.0


def test_save_rating_update(seeded_session: Session) -> None:
    save_rating(seeded_session, "g1", 90.0, "updated")
    seeded_session.commit()
    gen = get_generation(seeded_session, "g1")
    assert gen.rating.rating == 90.0


def test_create_song(seeded_session: Session) -> None:
    song = create_song(seeded_session, "Song Two", "test", lyrics="hello", bpm=140)
    seeded_session.commit()
    assert song.track_number == 2
    assert song.latest_version.lyrics == "hello"


def test_update_song(seeded_session: Session) -> None:
    ver = update_song(seeded_session, "s1", lyrics="new lyrics")
    seeded_session.commit()
    assert ver.version_number == 2
    assert ver.lyrics == "new lyrics"


def test_generation_to_dict(seeded_session: Session) -> None:
    gen = get_generation(seeded_session, "g1")
    d = generation_to_dict(gen)
    assert d["seed"] == 42
    assert d["scores"]["dynamics"] == 55.0
    assert d["scores"]["user_rating"] == 82.5


def test_song_to_dict(seeded_session: Session) -> None:
    song = get_song(seeded_session, "s1")
    d = song_to_dict(song)
    assert d["title"] == "Song One"
    assert d["generation_count"] == 2
    assert d["best_rating"] == 82.5
    assert len(d["generations"]) == 2


def test_album_to_dict(seeded_session: Session) -> None:
    album = get_album(seeded_session, "test")
    d = album_to_dict(album)
    assert d["song_count"] == 1

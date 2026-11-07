"""Deleting takes one by one, in bulk or with their version removes their scores and rating."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from songmaker_cli.db.models import Album, Generation, Rating, Score, Song, Version
from songmaker_cli.db.queries.generations import bulk_delete_generations, delete_generation
from songmaker_cli.db.queries.versions import delete_version


@pytest.fixture
def session(pg_factory) -> Iterator[Session]:
    with pg_factory() as db_session:
        db_session.add(Album(id="album", title="A", artist="A"))
        db_session.add(Song(id="song", title="S", album_id="album", track_number=1))
        db_session.add(
            Version(id="version", song_id="song", version_number=1, lyrics="", prompt=""),
        )
        db_session.add_all(
            Generation(
                id=name, song_id="song", version_id="version", generation_number=number,
                mp3_path=f"album/{name}.mp3", wav_path=f"album/{name}.wav" if name == "a" else None,
            )
            for number, name in enumerate(("a", "b", "c"), start=1)
        )
        db_session.flush()
        db_session.add(Score(generation_id="a", scorer="batch", value={}))
        db_session.add(Rating(generation_id="a", rating=80.0))
        db_session.commit()
        yield db_session


def _remaining(session: Session) -> dict[str, int]:
    return {
        "takes": session.query(Generation).count(),
        "scores": session.query(Score).count(),
        "ratings": session.query(Rating).count(),
    }


def test_a_bulk_delete_answers_the_takes_that_still_exist_with_their_files(
    session: Session,
) -> None:
    requested = session.query(Generation).filter(Generation.id.in_(["a", "b", "c"])).all()
    session.query(Generation).filter_by(id="b").delete()
    session.commit()

    deletion = bulk_delete_generations(session, requested)
    session.commit()

    assert deletion.deleted_ids == ["a", "c"]
    assert deletion.paths == ["album/a.mp3", "album/a.wav", "album/c.mp3"]
    assert _remaining(session) == {"takes": 0, "scores": 0, "ratings": 0}


def test_a_single_delete_removes_the_scored_and_rated_take_and_returns_its_files_once(
    session: Session,
) -> None:
    paths = delete_generation(session, "a")
    session.commit()

    assert paths == ["album/a.mp3", "album/a.wav"]
    assert _remaining(session) == {"takes": 2, "scores": 0, "ratings": 0}


def test_a_version_delete_with_its_takes_returns_their_files_and_removes_all_of_them(
    session: Session,
) -> None:
    paths = delete_version(session, "version", delete_generations=True)
    session.commit()

    assert paths == ["album/a.mp3", "album/a.wav", "album/b.mp3", "album/c.mp3"]
    assert _remaining(session) == {"takes": 0, "scores": 0, "ratings": 0}

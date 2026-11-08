"""A moved song becomes the last track of its new album and keeps everything else."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from songmaker_cli.db.models import Album, Generation, Song, Version
from songmaker_cli.db.queries.songs import move_song


@pytest.fixture
def session(pg_factory) -> Session:
    with pg_factory() as opened:
        opened.add(Album(id="source", title="Source", artist="Band"))
        opened.add(Album(id="target", title="Target", artist="Band"))
        opened.add(
            Song(id="moving", title="Moving", album_id="source", track_number=2, slug="moving")
        )
        for number in (1, 2, 3):
            opened.add(
                Song(
                    id=f"t{number}",
                    title=f"Track {number}",
                    album_id="target",
                    track_number=number,
                    slug=f"track-{number}",
                ),
            )
        opened.commit()
        yield opened


def _track_of(session: Session, song_id: str) -> int:
    return session.get(Song, song_id).track_number


def test_a_moved_song_becomes_the_last_track_of_the_target(session: Session) -> None:
    move_song(session, "moving", "target", slug="moving")

    assert _track_of(session, "moving") == 4


def test_a_trashed_song_in_the_target_still_counts(session: Session) -> None:
    session.get(Song, "t3").deleted_at = datetime.now(timezone.utc)
    session.flush()

    move_song(session, "moving", "target", slug="moving")

    assert _track_of(session, "moving") == 4


def test_a_same_album_move_keeps_its_number(session: Session) -> None:
    move_song(session, "moving", "source", slug="moving")

    assert _track_of(session, "moving") == 2


def test_a_move_leaves_the_pick_takes_and_versions_unchanged(session: Session) -> None:
    session.add(Version(id="v1", song_id="moving", version_number=1))
    session.add(
        Generation(
            id="g1",
            song_id="moving",
            version_id="v1",
            generation_number=1,
            mp3_path="u/g1.mp3",
            is_picked=True,
        ),
    )
    session.commit()

    move_song(session, "moving", "target", slug="moving")
    session.commit()

    take = session.get(Generation, "g1")
    assert (take.song_id, take.is_picked, session.get(Version, "v1").song_id) == (
        "moving",
        True,
        "moving",
    )

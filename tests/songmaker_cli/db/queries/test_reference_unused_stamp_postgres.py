"""A detach stamp and an attach to the same reference serialize on its row."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from support.postgres_lock_harness import CommitPause, race, wrote_to_tables
from support.web_app import make_test_app, seed_session

from songmaker_cli.constants import REFERENCE_AUDIO_DIR
from songmaker_cli.db.models import Album, Generation, ReferenceRecording, Song, User, Version
from songmaker_cli.db.queries.reference_recordings import (
    lock_and_mark_reference_used,
    mark_newly_unused,
)

OWNER = "u1"
REFERENCE_ID = "reference-1"


def _seed_stamp_race(session) -> None:
    session.add(User(id=OWNER, username="owner"))
    session.flush()
    session.add(Album(id="album-a", title="A", artist="A", created_by=OWNER))
    session.flush()
    session.add(Song(id="song-a", title="S", album_id="album-a", track_number=1))
    session.add(ReferenceRecording(
        id=REFERENCE_ID, user_id=OWNER, storage_path=f"{OWNER}/{REFERENCE_AUDIO_DIR}/F.wav",
        original_filename="F.wav", size_bytes=4,
    ))
    session.flush()
    session.add(
        Version(id="version-a", song_id="song-a", version_number=1, lyrics="la", prompt="p"),
    )


class _World:
    def __init__(self, pg_factory, tmp_path: Path) -> None:
        self.pg_factory = pg_factory
        self.client, _ = make_test_app(tmp_path, factory=pg_factory, seed_db=_seed_stamp_race)
        seed_session(self.client, "owner")

    def attach(self) -> int:
        """V9a's lock-and-clear, then a take that links the row, in one transaction."""
        with self.pg_factory() as session:
            lock_and_mark_reference_used(session, OWNER, REFERENCE_ID)
            session.add(Generation(
                id="take-a", song_id="song-a", version_id="version-a", mp3_path="u1/take-a.mp3",
                reference_recording_id=REFERENCE_ID,
            ))
            session.commit()
        return 1

    def stamp(self) -> int:
        with self.pg_factory() as session:
            stamped = mark_newly_unused(session, {REFERENCE_ID})
            session.commit()
        return stamped

    def unused_since(self) -> datetime | None:
        with self.pg_factory() as session:
            return session.get(ReferenceRecording, REFERENCE_ID).unused_since


def test_a_stamp_after_an_attach_that_commits_first_finds_the_link_and_leaves_no_stamp(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)
    attach_pause = CommitPause(lambda session: wrote_to_tables(session, "generations"))

    answers = race(pg_factory, world.attach, world.stamp, attach_pause)

    assert answers["second"] == 0
    assert world.unused_since() is None


def test_an_attach_after_a_stamp_that_commits_first_clears_the_stamp(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)
    stamp_pause = CommitPause(lambda session: wrote_to_tables(session, "reference_recordings"))

    answers = race(pg_factory, world.stamp, world.attach, stamp_pause)

    assert answers["first"] == 1
    assert world.unused_since() is None

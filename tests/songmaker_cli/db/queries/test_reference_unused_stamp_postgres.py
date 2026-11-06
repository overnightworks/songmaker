"""A detach stamp and an attach to the same reference serialize on its row."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from support.postgres_lock_harness import CommitPause, race, wrote_to_tables
from support.web_app import make_test_app, seed_session

from songmaker_cli.constants import REFERENCE_AUDIO_DIR
from songmaker_cli.db.models import Album, Generation, ReferenceRecording, Song, User, Version
from songmaker_cli.db.queries.reference_recordings import (
    clear_stamps_on_used_or_kept,
    lock_and_mark_reference_used,
    mark_newly_unused,
)
from songmaker_cli.reference_audio import commit_unused_stamps, reconcile_unused_stamps

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

    def reconcile(self) -> int:
        return reconcile_unused_stamps(self.pg_factory).stamped

    def link_with_stale_stamp(self) -> None:
        """The version links the row, which still carries a stamp the clear half must remove."""
        with self.pg_factory() as session:
            session.get(Version, "version-a").reference_recording_id = REFERENCE_ID
            session.get(ReferenceRecording, REFERENCE_ID).unused_since = datetime.now(timezone.utc)
            session.commit()

    def clear_stale_stamp(self) -> int:
        with self.pg_factory() as session:
            cleared = clear_stamps_on_used_or_kept(session)
            session.commit()
        return cleared

    def detach_and_stamp(self) -> int:
        """Delete the linking version, commit, then stamp in a transaction of its own."""
        with self.pg_factory() as session:
            session.delete(session.get(Version, "version-a"))
            session.commit()
        with self.pg_factory() as session:
            commit_unused_stamps(session, {REFERENCE_ID})
        return 1

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


def test_a_reconciliation_stamp_half_that_waits_for_an_attach_finds_the_link_and_leaves_no_stamp(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)
    attach_pause = CommitPause(lambda session: wrote_to_tables(session, "generations"))

    answers = race(pg_factory, world.attach, world.reconcile, attach_pause)

    assert answers["second"] == 0
    assert world.unused_since() is None


def test_a_detach_stamp_that_runs_after_the_clear_half_commits_still_stamps_the_row(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)
    world.link_with_stale_stamp()

    cleared = world.clear_stale_stamp()
    world.detach_and_stamp()

    assert cleared == 1
    assert world.unused_since() is not None

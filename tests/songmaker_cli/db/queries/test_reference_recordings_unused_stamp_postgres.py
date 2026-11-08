"""A detach stamp, an attach, a keep and a delete of the same reference serialize on its row."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from httpx import Response
from support.postgres_lock_harness import (
    WAIT_SECONDS,
    CommitPause,
    in_thread,
    race,
    stop_workers,
    wrote_to_tables,
)
from support.reference_rows import a_reference
from support.web_app import make_test_app, seed_session

from songmaker_cli.db.models import Album, Generation, ReferenceRecording, Song, User, Version
from songmaker_cli.db.queries.reference_recordings import (
    clear_stamps_on_used_or_kept,
    keep_reference,
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
    a_reference(session, OWNER, name="F.wav", reference_id=REFERENCE_ID)
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

    def clear_stale_stamp_held_before_commit(self, pause: CommitPause) -> int:
        """The clear half, held after it counted the link and before it commits."""
        with self.pg_factory() as session:
            cleared = clear_stamps_on_used_or_kept(session)
            pause.hold(session)
            session.commit()
        return cleared

    def delete_linking_version(self) -> None:
        with self.pg_factory() as session:
            session.delete(session.get(Version, "version-a"))
            session.commit()

    def stamp_after_detach(self) -> None:
        with self.pg_factory() as session:
            commit_unused_stamps(session, {REFERENCE_ID})

    def keep(self) -> bool:
        with self.pg_factory() as session:
            kept = keep_reference(session, OWNER, REFERENCE_ID) is not None
            session.commit()
        return kept

    def delete_over_http(self) -> Response:
        return self.client.delete(f"/api/references/{REFERENCE_ID}")

    def keep_over_http(self) -> Response:
        return self.client.post(f"/api/references/{REFERENCE_ID}/keep")

    def is_kept(self) -> bool:
        with self.pg_factory() as session:
            return session.get(ReferenceRecording, REFERENCE_ID).is_kept

    def exists(self) -> bool:
        with self.pg_factory() as session:
            return session.get(ReferenceRecording, REFERENCE_ID) is not None

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


def test_a_detach_that_commits_while_the_clear_half_is_held_is_stamped_after_the_clear_commits(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)
    world.link_with_stale_stamp()
    pause = CommitPause()
    answers: dict[str, int] = {}
    clearing = in_thread(
        answers, "cleared", lambda: world.clear_stale_stamp_held_before_commit(pause),
    )
    clearing.start()
    try:
        assert pause.reached.wait(WAIT_SECONDS), "The clear half never reached its pause"
        world.delete_linking_version()
        detached_at = datetime.now(timezone.utc).replace(tzinfo=None)
    finally:
        pause.release.set()
        stuck = stop_workers(pg_factory, (clearing,), (pause.backend_pid,))
    assert not stuck
    assert answers["cleared"] == 1

    world.stamp_after_detach()

    assert world.unused_since().replace(tzinfo=None) >= detached_at


def test_a_keep_that_waits_for_a_stamping_that_commits_first_clears_the_stamp(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)
    stamp_pause = CommitPause(lambda session: wrote_to_tables(session, "reference_recordings"))

    answers = race(pg_factory, world.stamp, world.keep, stamp_pause)

    assert answers == {"first": 1, "second": True}
    assert world.is_kept()
    assert world.unused_since() is None


def test_a_detach_stamping_that_waits_for_a_keep_that_commits_first_leaves_the_row_unstamped(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)
    keep_pause = CommitPause(lambda session: wrote_to_tables(session, "reference_recordings"))

    answers = race(pg_factory, world.keep, world.stamp, keep_pause)

    assert answers == {"first": True, "second": 0}
    assert world.is_kept()
    assert world.unused_since() is None


def test_a_keep_request_that_waits_for_a_delete_that_commits_first_answers_not_found(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)
    delete_pause = CommitPause(lambda session: wrote_to_tables(session, "reference_recordings"))

    answers = race(pg_factory, world.delete_over_http, world.keep_over_http, delete_pause)

    assert answers["first"].status_code == 204
    assert answers["second"].status_code == 404
    assert answers["second"].json() == {"detail": "Not Found"}
    assert not world.exists()

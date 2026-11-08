"""The announced deletion against attach, keep, unkeep, the remnant run, the purge and retention."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from support.postgres_lock_harness import (
    WAIT_SECONDS,
    CommitPause,
    StatementPause,
    in_thread,
    race,
    stop_workers,
    wrote_to_tables,
)
from support.reference_countdown import publish_countdown, stored_file
from support.reference_rows import a_reference
from support.web_app import make_test_app, seed_session

from acestep_engine.models import AceStepConfig
from songmaker_cli.cleanup import run_cleanup_expired, run_generation_retention
from songmaker_cli.db.models import Album, Generation, Job, ReferenceRecording, Song, User, Version
from songmaker_cli.jobs import _persist_generation_row
from songmaker_cli.jobs._runtime import (
    JOB_ERROR_REFERENCE_DELETED_DURING_TAKE,
    ReferenceDeletedDuringTake,
)
from songmaker_cli.jobs.generation import GenerationContext
from songmaker_cli.parser import AlbumMeta, SongMeta
from songmaker_cli.reference_audio import (
    AnnouncedDeletionReport,
    delete_announced_references,
    reconcile_reference_remnants,
)

OWNER = "u1"
REFERENCE_ID = "reference-1"
STORED_NAME = "F.wav"
DAYS = 30
HOUR = 3
STAMPED = datetime(2026, 1, 1, tzinfo=timezone.utc)
PUBLISHED = datetime(2026, 1, 5, tzinfo=timezone.utc)
NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)
LONG_AGO = timedelta(days=400)
NOT_FOUND = {"detail": "Not Found"}


def _seed_stamped_row(session) -> None:
    session.add(User(id=OWNER, username="owner"))
    session.flush()
    session.add(Album(id="album-a", title="A", artist="A", created_by=OWNER))
    session.flush()
    session.add(Song(id="song-a", title="S", album_id="album-a", track_number=1, slug="s"))
    session.flush()
    session.add_all([
        Version(id="version-a", song_id="song-a", version_number=1, lyrics="la", prompt="p"),
        Job(id="job-a", type="generate", status="running", user_id=OWNER),
    ])
    a_reference(
        session, OWNER, name=STORED_NAME, reference_id=REFERENCE_ID, unused_since=STAMPED,
    )


def _listing_statement(sql: str) -> bool:
    return "FROM reference_recordings" in sql and "FOR UPDATE" not in sql


class _World:
    def __init__(self, pg_factory, tmp_path: Path) -> None:
        self.pg_factory = pg_factory
        self.client, _ = make_test_app(
            tmp_path, factory=pg_factory, seed_db=_seed_stamped_row,
        )
        seed_session(self.client, "owner")
        publish_countdown(pg_factory, PUBLISHED)
        self.audio_dir = self.client.app.state.ctx.audio_dir
        self.stored_file = stored_file(self.audio_dir, OWNER, STORED_NAME)
        self.stored_file.write_bytes(b"RIFF")

    def delete_announced(self) -> AnnouncedDeletionReport:
        return delete_announced_references(
            self.pg_factory, self.audio_dir, days=DAYS, hour=HOUR, now=NOW,
        )

    def hold_deletion_after_listing(self, between: Callable[[], None]) -> AnnouncedDeletionReport:
        """Run ``between`` after the run listed its candidates and before it locks the first."""
        pause = StatementPause(_listing_statement)
        answers: dict[str, AnnouncedDeletionReport] = {}
        deletion = in_thread(answers, "run", self.delete_announced)
        pause.install(self.pg_factory)
        try:
            deletion.start()
            assert pause.reached.wait(WAIT_SECONDS), "The run never listed its candidates"
            between()
        finally:
            pause.release.set()
            stuck = stop_workers(self.pg_factory, (deletion,), (pause.backend_pid,))
            pause.remove(self.pg_factory)
        assert not stuck
        if isinstance(answers["run"], BaseException):
            raise answers["run"]
        return answers["run"]

    def attach_take(self) -> int:
        with self.pg_factory() as session:
            from songmaker_cli.db.queries.reference_recordings import lock_and_mark_reference_used

            lock_and_mark_reference_used(session, OWNER, REFERENCE_ID)
            session.add(Generation(
                id="take-a", song_id="song-a", version_id="version-a", mp3_path="u1/take-a.mp3",
                reference_recording_id=REFERENCE_ID,
            ))
            session.commit()
        return 1

    def persist_take(self):
        """The take's persistence; the message that ends the job is its answer."""
        context = GenerationContext(
            song_id="song-a", version_id="version-a",
            meta=SongMeta(title="S", lyrics="la", prompt="p"),
            album_meta=AlbumMeta(title="A", artist="A"),
            ace_config=AceStepConfig(prompt="p", lyrics="la", audio_duration=0),
            audio_dir=self.audio_dir, user_id=OWNER, reference_recording_id=REFERENCE_ID,
            model_name="turbo",
        )
        try:
            return _persist_generation_row(
                db_factory=self.pg_factory, ctx=context, generation_id="take-a", seed=1,
                cot_caption="", cot_lyrics="", delivered_batch_size=None, job_id="job-a",
            )
        except ReferenceDeletedDuringTake as failure:
            return str(failure)

    def link_with_stale_stamp(self, *, via_take: bool = False) -> None:
        """A link on the stamped row, which no flow creates; the re-check must still see it."""
        with self.pg_factory() as session:
            if via_take:
                session.add(Generation(
                    id="take-a", song_id="song-a", version_id="version-a",
                    mp3_path="u1/take-a.mp3", reference_recording_id=REFERENCE_ID,
                    is_archived=True, archived_at=datetime.now(timezone.utc) - LONG_AGO,
                ))
            else:
                session.get(Version, "version-a").reference_recording_id = REFERENCE_ID
            session.commit()

    def keep(self):
        return self.client.post(f"/api/references/{REFERENCE_ID}/keep")

    def unkeep(self):
        return self.client.post(f"/api/references/{REFERENCE_ID}/unkeep")

    def save_song_with_changed_lyrics(self):
        return self.client.put("/api/songs/song-a", json={"lyrics": "changed", "new_version": True})

    def save_song_with_reference(self):
        return self.client.put(
            "/api/songs/song-a", json={"reference_recording_id": REFERENCE_ID},
        )

    def reference_rows(self) -> int:
        with self.pg_factory() as session:
            return session.query(ReferenceRecording).count()

    def is_kept(self) -> bool:
        with self.pg_factory() as session:
            return session.get(ReferenceRecording, REFERENCE_ID).is_kept

    def take_rows(self) -> int:
        with self.pg_factory() as session:
            return session.query(Generation).count()


@pytest.fixture
def world(pg_factory, tmp_path) -> _World:
    return _World(pg_factory, tmp_path)


def _held_at_delete_commit() -> CommitPause:
    return CommitPause(lambda session: wrote_to_tables(session, "reference_recordings"))


def test_an_attach_that_commits_first_makes_the_run_skip_the_row_and_keep_the_file(world) -> None:
    attach_pause = CommitPause(lambda session: wrote_to_tables(session, "generations"))

    answers = race(world.pg_factory, world.attach_take, world.delete_announced, attach_pause)

    assert answers["second"] == AnnouncedDeletionReport(skipped=1)
    assert world.reference_rows() == 1
    assert world.stored_file.exists()


def test_a_take_waiting_for_the_run_fails_with_the_deleted_message(world) -> None:
    answers = race(
        world.pg_factory, world.delete_announced, world.persist_take, _held_at_delete_commit(),
    )

    assert answers["first"] == AnnouncedDeletionReport(deleted=1)
    assert answers["second"] == JOB_ERROR_REFERENCE_DELETED_DURING_TAKE
    assert world.reference_rows() == 0
    assert world.take_rows() == 0
    assert not world.stored_file.exists()


def test_a_save_waiting_for_the_run_answers_not_found(world) -> None:
    answers = race(
        world.pg_factory, world.delete_announced, world.save_song_with_reference,
        _held_at_delete_commit(),
    )

    assert answers["first"] == AnnouncedDeletionReport(deleted=1)
    assert answers["second"].status_code == 404
    assert answers["second"].json() == NOT_FOUND


@pytest.mark.parametrize("toggle", ["keep", "unkeep"])
def test_a_keep_or_unkeep_waiting_for_the_run_answers_not_found(world, toggle) -> None:
    answers = race(
        world.pg_factory, world.delete_announced, getattr(world, toggle),
        _held_at_delete_commit(),
    )

    assert answers["first"] == AnnouncedDeletionReport(deleted=1)
    assert answers["second"].status_code == 404
    assert not world.stored_file.exists()


def _keep_leaving_the_stamp(world: _World) -> None:
    with world.pg_factory() as session:
        session.get(ReferenceRecording, REFERENCE_ID).is_kept = True
        session.commit()


def _clear_the_stamp(world: _World) -> None:
    with world.pg_factory() as session:
        session.get(ReferenceRecording, REFERENCE_ID).unused_since = None
        session.commit()


@pytest.mark.parametrize("change", [
    lambda world: world.keep(),
    lambda world: world.attach_take(),
    _keep_leaving_the_stamp,
    _clear_the_stamp,
    lambda world: publish_countdown(world.pg_factory, PUBLISHED + timedelta(days=1)),
], ids=["keep", "attach", "kept with a stamp", "stamp cleared", "publication moved"])
def test_a_row_that_changes_after_the_listing_is_skipped_and_keeps_its_file(
    world, change,
) -> None:
    report = world.hold_deletion_after_listing(lambda: change(world))

    assert report == AnnouncedDeletionReport(skipped=1)
    assert world.reference_rows() == 1
    assert world.stored_file.exists()


def test_a_keep_and_unkeep_after_the_listing_start_a_fresh_countdown_the_run_respects(
    world,
) -> None:
    def keep_then_unkeep() -> None:
        assert world.keep().status_code == 200
        assert world.unkeep().status_code == 200

    report = world.hold_deletion_after_listing(keep_then_unkeep)

    assert report == AnnouncedDeletionReport(skipped=1)
    assert world.reference_rows() == 1
    assert world.stored_file.exists()


def test_a_save_that_carries_the_link_holds_the_row_until_the_run_counts_it(world) -> None:
    world.link_with_stale_stamp()
    save_pause = CommitPause(lambda session: wrote_to_tables(session, "versions"))

    answers = race(
        world.pg_factory, world.save_song_with_changed_lyrics, world.delete_announced,
        save_pause,
    )

    assert answers["first"].status_code == 200
    assert answers["second"] == AnnouncedDeletionReport(skipped=1)
    assert world.reference_rows() == 1
    assert world.stored_file.exists()


def test_a_remnant_run_beside_the_deletion_leaves_the_file_to_the_deletions_one_unlink(
    world,
) -> None:
    pause = _held_at_delete_commit()
    answers: dict = {}
    deletion = in_thread(answers, "run", world.delete_announced)
    pause.install(world.pg_factory)
    try:
        deletion.start()
        assert pause.reached.wait(WAIT_SECONDS), "The run never reached its commit"
        remnants = reconcile_reference_remnants(world.pg_factory, world.audio_dir)
    finally:
        pause.release.set()
        stuck = stop_workers(world.pg_factory, (deletion,), (pause.backend_pid,))
        pause.remove(world.pg_factory)
    assert not stuck

    assert remnants.removed == 0
    assert answers["run"] == AnnouncedDeletionReport(deleted=1)
    assert not world.stored_file.exists()


def _trash_the_song_and_album(world: _World) -> None:
    with world.pg_factory() as session:
        session.get(Album, "album-a").deleted_at = datetime.now(timezone.utc) - LONG_AGO
        session.get(Song, "song-a").deleted_at = datetime.now(timezone.utc) - LONG_AGO
        session.commit()


def _purge(world: _World) -> None:
    run_cleanup_expired(world.pg_factory, world.audio_dir)


def _retention(world: _World) -> None:
    run_generation_retention(world.pg_factory, world.audio_dir)


@pytest.mark.parametrize(
    ("detaching_run", "tables"),
    [(_purge, ("songs", "versions")), (_retention, ("generations",))],
    ids=["purge", "retention"],
)
def test_a_run_that_reads_a_link_before_the_last_detach_commits_keeps_row_and_file(
    world, detaching_run, tables,
) -> None:
    world.link_with_stale_stamp(via_take=detaching_run is _retention)
    if detaching_run is _purge:
        _trash_the_song_and_album(world)
    pause = CommitPause(lambda session: wrote_to_tables(session, *tables))
    answers: dict = {}
    detaching = in_thread(answers, "detach", lambda: detaching_run(world))
    pause.install(world.pg_factory)
    try:
        detaching.start()
        assert pause.reached.wait(WAIT_SECONDS), "The detaching run never reached its commit"
        report = world.delete_announced()
    finally:
        pause.release.set()
        stuck = stop_workers(world.pg_factory, (detaching,), (pause.backend_pid,))
        pause.remove(world.pg_factory)
    assert not stuck
    if isinstance(answers.get("detach"), BaseException):
        raise answers["detach"]

    assert report == AnnouncedDeletionReport(skipped=1)
    assert world.reference_rows() == 1
    assert world.stored_file.exists()

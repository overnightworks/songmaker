"""The daily run deletes a reference only after the date the list announces, row before file."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from support.failing_reference_stamp import drop_with_bounded_waits
from support.reference_countdown import (
    MALFORMED_PUBLICATION,
    publish_countdown,
    remove_countdown_row,
    stored_file,
)
from support.reference_rows import a_reference

from songmaker_cli import reference_audio
from songmaker_cli.db.models import Album, Generation, ReferenceRecording, Song, User, Version
from songmaker_cli.db.queries.reference_recordings import ReferenceLinkCounts
from songmaker_cli.reference_audio import (
    AnnouncedDeletionReport,
    delete_announced_references,
    reconcile_reference_remnants,
)

OWNER = "owner"
DAYS = 30
HOUR = 3
SECRET_NAME = "secret-reference-name.wav"
LONG_AGO = datetime(2026, 1, 1, tzinfo=timezone.utc)
PUBLISHED = datetime(2026, 1, 5, 9, tzinfo=timezone.utc)
# The countdown of LONG_AGO and PUBLISHED ends on 2026-02-04 09:00; the next 03:00 run is the 5th.
FIRST_RUN = datetime(2026, 2, 5, HOUR, tzinfo=timezone.utc)
AFTER_ALL = FIRST_RUN + timedelta(days=100)


@pytest.fixture
def world(pg_factory, tmp_path):
    with pg_factory() as session:
        session.add(User(id=OWNER, username=OWNER))
        session.commit()
    publish_countdown(pg_factory, PUBLISHED)
    return _World(pg_factory, tmp_path / "audio")


class _World:
    def __init__(self, factory, audio_dir) -> None:
        self.factory = factory
        self.audio_dir = audio_dir

    def add(
        self, name: str, *, stamp: datetime | None = LONG_AGO, kept: bool = False,
        storage_path: str | None = None, original_filename: str | None = None,
    ):
        with self.factory() as session:
            a_reference(
                session, OWNER, name=f"{name}.wav", reference_id=name, unused_since=stamp,
                is_kept=kept, storage_path=storage_path, original_filename=original_filename,
            )
            session.commit()
        file = stored_file(self.audio_dir, OWNER, f"{name}.wav")
        file.write_bytes(b"RIFF")
        return file

    def link(self, name: str, *, via: str = "version") -> None:
        with self.factory() as session:
            session.add(Album(id=f"album-{name}", title=name, artist="A", created_by=OWNER))
            session.flush()
            session.add(Song(
                id=f"song-{name}", title=name, album_id=f"album-{name}", track_number=1,
                slug=name,
            ))
            session.flush()
            session.add(Version(
                id=f"version-{name}", song_id=f"song-{name}", version_number=1, lyrics="la",
                prompt="p", reference_recording_id=name if via == "version" else None,
            ))
            session.flush()
            if via == "take":
                session.add(Generation(
                    id=f"take-{name}", song_id=f"song-{name}", version_id=f"version-{name}",
                    generation_number=1, mp3_path=f"{OWNER}/{name}.mp3",
                    reference_recording_id=name,
                ))
            session.commit()

    def run(self, now: datetime = AFTER_ALL) -> AnnouncedDeletionReport:
        return delete_announced_references(
            self.factory, self.audio_dir, days=DAYS, hour=HOUR, now=now,
        )

    def row_ids(self) -> list[str]:
        with self.factory() as session:
            return sorted(row_id for (row_id,) in session.query(ReferenceRecording.id))


def _levels(caplog, level: int) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.levelno == level]


@pytest.mark.parametrize(
    ("offset", "deleted"),
    [(-timedelta(microseconds=1), 0), (timedelta(0), 1)],
    ids=["one tick before the run", "at the run"],
)
def test_a_row_goes_at_the_rounded_run_and_not_one_tick_before(world, offset, deleted) -> None:
    file = world.add("old")

    report = world.run(FIRST_RUN + offset)

    assert report.deleted == deleted
    assert world.row_ids() == ([] if deleted else ["old"])
    assert file.exists() is not bool(deleted)


def test_the_later_of_the_stamp_and_the_publication_starts_the_countdown(world) -> None:
    world.add("restamped", stamp=PUBLISHED + timedelta(days=10))
    countdown_end = PUBLISHED + timedelta(days=10 + DAYS)
    run_after_end = countdown_end.replace(hour=HOUR) + timedelta(days=1)

    early = world.run(run_after_end - timedelta(days=1, microseconds=1))
    on_time = world.run(run_after_end)

    assert (early.deleted, on_time.deleted) == (0, 1)


def test_nothing_is_deleted_before_a_page_published_the_countdown(world, caplog) -> None:
    file = world.add("old")
    publish_countdown(world.factory, None)
    caplog.set_level(logging.INFO)

    report = world.run()

    assert report == AnnouncedDeletionReport()
    assert world.row_ids() == ["old"]
    assert file.exists()
    assert _levels(caplog, logging.INFO)
    assert not _levels(caplog, logging.ERROR)


@pytest.mark.parametrize("break_row", [
    lambda factory: publish_countdown(factory, MALFORMED_PUBLICATION),
    remove_countdown_row,
], ids=["malformed value", "missing row"])
def test_an_unusable_publication_deletes_nothing_and_logs_an_error(
    world, caplog, break_row,
) -> None:
    file = world.add("old")
    break_row(world.factory)

    report = world.run()

    assert report == AnnouncedDeletionReport()
    assert world.row_ids() == ["old"]
    assert file.exists()
    assert _levels(caplog, logging.ERROR)


def test_a_publication_that_turns_unusable_mid_run_ends_it_with_the_report_so_far(
    world, monkeypatch, caplog,
) -> None:
    first, second = world.add("a-first"), world.add("b-second")
    real_remove = reference_audio.remove_reference_file

    def remove_then_break_the_publication(*arguments):
        outcome = real_remove(*arguments)
        publish_countdown(world.factory, MALFORMED_PUBLICATION)
        return outcome

    monkeypatch.setattr(reference_audio, "remove_reference_file", remove_then_break_the_publication)
    caplog.set_level(logging.INFO)

    report = world.run()

    assert report == AnnouncedDeletionReport(deleted=1)
    assert world.row_ids() == ["b-second"]
    assert not first.exists()
    assert second.exists()
    assert _levels(caplog, logging.ERROR)
    assert any("deleted" in record.getMessage() for record in _levels(caplog, logging.INFO))


def test_a_failed_listing_deletes_nothing_and_logs_an_error(world, monkeypatch, caplog) -> None:
    file = world.add("old")

    def failing_listing(_session):
        raise OperationalError("listing", {}, Exception(SECRET_NAME))

    monkeypatch.setattr(reference_audio, "list_stamped_unkept_references", failing_listing)

    report = world.run()

    assert report == AnnouncedDeletionReport()
    assert world.row_ids() == ["old"]
    assert file.exists()
    assert _levels(caplog, logging.ERROR)
    assert SECRET_NAME not in caplog.text


def test_kept_unstamped_and_linked_rows_stay_and_only_the_linked_one_counts_as_skipped(
    world,
) -> None:
    kept = world.add("kept", kept=True)
    unstamped = world.add("unstamped", stamp=None)
    linked = world.add("linked")
    world.link("linked", via="take")

    report = world.run()

    assert report == AnnouncedDeletionReport(skipped=1)
    assert world.row_ids() == ["kept", "linked", "unstamped"]
    assert all(file.exists() for file in (kept, unstamped, linked))


@pytest.fixture
def failing_delete_of_b(world):
    """A PostgreSQL trigger that makes deleting the row ``b`` fail with a non-integrity error."""
    with world.factory() as session:
        session.execute(text(
            "CREATE FUNCTION fail_delete() RETURNS trigger LANGUAGE plpgsql AS $$ "
            f"BEGIN RAISE EXCEPTION '{SECRET_NAME}'; END $$"
        ))
        session.execute(text(
            "CREATE TRIGGER fail_delete BEFORE DELETE ON reference_recordings "
            "FOR EACH ROW WHEN (OLD.id = 'b') EXECUTE FUNCTION fail_delete()"
        ))
        session.commit()
    yield
    drop_with_bounded_waits(world.factory, (
        "DROP TRIGGER IF EXISTS fail_delete ON reference_recordings",
        "DROP FUNCTION IF EXISTS fail_delete()",
    ))


def test_one_rows_database_failure_leaves_the_other_rows_running_and_names_no_file(
    world, failing_delete_of_b, caplog,
) -> None:
    files = [world.add(name) for name in ("a", "b", "c")]

    report = world.run()

    assert report == AnnouncedDeletionReport(deleted=2, failed=1)
    assert world.row_ids() == ["b"]
    assert [file.exists() for file in files] == [False, True, False]
    assert any("b" in record.getMessage().split() for record in _levels(caplog, logging.ERROR))
    assert SECRET_NAME not in caplog.text


def test_a_file_that_cannot_be_unlinked_is_counted_warned_and_left_to_the_remnant_run(
    world, caplog,
) -> None:
    world.add("a").unlink()
    stuck = stored_file(world.audio_dir, OWNER, "a.wav")
    stuck.mkdir()
    caplog.set_level(logging.INFO)

    report = world.run()
    stuck.rmdir()
    stuck.write_bytes(b"RIFF")
    remnants = reconcile_reference_remnants(world.factory, world.audio_dir)

    assert report == AnnouncedDeletionReport(deleted=1, files_not_removed=1)
    assert world.row_ids() == []
    assert _levels(caplog, logging.WARNING)
    assert remnants.removed == 1
    assert not stuck.exists()


def test_a_row_whose_path_is_not_the_owners_stays_and_counts_as_failed(world, caplog) -> None:
    foreign = world.add("foreign", storage_path="other/refs/foreign.wav")

    report = world.run()

    assert report == AnnouncedDeletionReport(failed=1)
    assert world.row_ids() == ["foreign"]
    assert foreign.exists()
    assert _levels(caplog, logging.ERROR)


def test_a_foreign_key_refusal_keeps_row_and_file_counts_as_skipped_and_the_next_row_runs(
    world, monkeypatch,
) -> None:
    refused = world.add("a-refused")
    world.link("a-refused")
    next_one = world.add("b-next")
    monkeypatch.setattr(
        reference_audio, "reference_link_counts",
        lambda _session, ids: {
            reference_id: ReferenceLinkCounts(versions=0, takes=0) for reference_id in ids
        },
    )

    report = world.run()

    assert report == AnnouncedDeletionReport(deleted=1, skipped=1)
    assert world.row_ids() == ["a-refused"]
    assert refused.exists()
    assert not next_one.exists()


def test_a_commit_that_raises_unlinks_nothing_and_counts_as_failed(world) -> None:
    file = world.add("old")

    def failing_commit(_session):
        raise OperationalError("commit", {}, Exception(SECRET_NAME))

    event.listen(world.factory, "before_commit", failing_commit)
    try:
        report = world.run()
    finally:
        event.remove(world.factory, "before_commit", failing_commit)

    assert report == AnnouncedDeletionReport(failed=1)
    assert world.row_ids() == ["old"]
    assert file.exists()


def test_a_crash_after_the_commit_leaves_the_file_to_the_next_remnant_run(
    world, monkeypatch,
) -> None:
    file = world.add("old")

    def crash(*_arguments):
        raise KeyboardInterrupt

    monkeypatch.setattr(reference_audio, "remove_reference_file", crash)
    with pytest.raises(KeyboardInterrupt):
        world.run()
    monkeypatch.undo()

    assert world.row_ids() == []
    assert file.exists()
    assert reconcile_reference_remnants(world.factory, world.audio_dir).removed == 1
    assert not file.exists()


def test_the_report_counts_every_outcome_and_the_summary_names_them(world, caplog) -> None:
    world.add("a-gone")
    world.add("b-gone-file-stuck").unlink()
    stored_file(world.audio_dir, OWNER, "b-gone-file-stuck.wav").mkdir()
    world.add("c-linked")
    world.link("c-linked")
    world.add("d-foreign", storage_path="other/refs/d.wav")
    caplog.set_level(logging.INFO)

    report = world.run()

    assert report == AnnouncedDeletionReport(deleted=2, skipped=1, failed=1, files_not_removed=1)
    summaries = [
        record.getMessage() for record in _levels(caplog, logging.INFO)
        if "2 deleted, 1 skipped, 1 failed, 1 files not removed" in record.getMessage()
    ]
    assert len(summaries) == 1


def test_no_log_line_carries_a_filename_or_a_path(world, caplog) -> None:
    world.add(
        "a-deleted", original_filename=SECRET_NAME, storage_path=f"{OWNER}/refs/a-deleted.wav",
    )
    world.add("b-foreign", original_filename=SECRET_NAME, storage_path="other/refs/b.wav")
    world.add("c-linked", original_filename=SECRET_NAME)
    world.link("c-linked")
    world.add("d-stuck", original_filename=SECRET_NAME).unlink()
    stored_file(world.audio_dir, OWNER, "d-stuck.wav").mkdir()
    caplog.set_level(logging.DEBUG)

    world.run()

    assert caplog.records
    for forbidden in (SECRET_NAME, "refs/", ".wav", str(world.audio_dir)):
        assert forbidden not in caplog.text


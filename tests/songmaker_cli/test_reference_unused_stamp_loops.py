"""The background deletion loops stamp a reference that lost its last link after their commit."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from songmaker_cli.cleanup import run_cleanup_expired, run_generation_retention
from songmaker_cli.constants import REFERENCE_AUDIO_DIR, SONG_COVER_DIRNAME
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, Generation, ReferenceRecording, Song, User, Version

OWNER = "owner"
LONG_AGO = datetime.now(timezone.utc) - timedelta(days=3650)
REFERENCES = ("r1", "r2")


def _fail_stamp_trigger(reference_id: str | None) -> str:
    only_reference = f"WHEN NEW.id = '{reference_id}' " if reference_id else ""
    return (
        "CREATE TRIGGER fail_stamp BEFORE UPDATE OF unused_since ON reference_recordings "
        f"{only_reference}BEGIN SELECT RAISE(ABORT, 'secret.wav'); END"
    )


def _song_linking(
    session, song_id: str, album_id: str, *, version_reference: str | None,
    take_reference: str | None, archived: bool = False,
) -> None:
    session.add(Song(id=song_id, title=song_id, album_id=album_id, track_number=1, slug=song_id))
    session.flush()
    session.add(Version(
        id=f"{song_id}-v1", song_id=song_id, version_number=1, lyrics="la", prompt="p",
        reference_recording_id=version_reference,
    ))
    session.flush()
    session.add(Generation(
        id=f"{song_id}-take", song_id=song_id, version_id=f"{song_id}-v1", generation_number=1,
        mp3_path=f"{OWNER}/{song_id}-take.mp3", reference_recording_id=take_reference,
        is_archived=archived, archived_at=LONG_AGO if archived else None,
    ))


@pytest.fixture
def audio_dir(tmp_path: Path) -> Path:
    path = tmp_path / "audio"
    (path / OWNER).mkdir(parents=True)
    return path


@pytest.fixture
def factory(tmp_path: Path):
    factory = init_test_db(tmp_path / "loops.db")
    with factory() as session:
        session.add(User(id=OWNER, username=OWNER))
        session.flush()
        session.add_all(
            ReferenceRecording(
                id=name, user_id=OWNER, storage_path=f"{OWNER}/{REFERENCE_AUDIO_DIR}/{name}.wav",
                original_filename=f"{name}.wav", size_bytes=4,
            )
            for name in REFERENCES
        )
        session.add(Album(id="live", title="live", artist="A", created_by=OWNER))
        session.commit()
    return factory


@dataclass(frozen=True)
class PurgeSite:
    """A trashed album, or a trashed song in a live album, whose version and take link r1 and r2."""

    album_id: str
    album_trashed: bool


PURGE_SITES = {
    "album": PurgeSite("gone", album_trashed=True),
    "orphan_song": PurgeSite("live", album_trashed=False),
}


def _trash_song_world(factory, audio_dir: Path, site: PurgeSite) -> None:
    with factory() as session:
        if site.album_trashed:
            session.add(Album(
                id=site.album_id, title="gone", artist="A", created_by=OWNER,
                deleted_at=LONG_AGO,
            ))
            session.flush()
        _song_linking(
            session, "doomed", site.album_id, version_reference="r1", take_reference="r2",
        )
        if not site.album_trashed:
            session.get(Song, "doomed").deleted_at = LONG_AGO
        session.commit()
    (audio_dir / OWNER / "doomed-take.mp3").write_bytes(b"ID3")


def _keep_linked(factory, *references: str) -> None:
    with factory() as session:
        for number, reference in enumerate(references):
            _song_linking(
                session, f"keeper{number}", "live", version_reference=reference,
                take_reference=None,
            )
        session.commit()


def _stamped(factory) -> set[str]:
    with factory() as session:
        return {
            row.id for row in session.query(ReferenceRecording) if row.unused_since is not None
        }


def _add_failing_stamp(factory, reference_id: str | None = None) -> None:
    with factory() as session:
        session.execute(text(_fail_stamp_trigger(reference_id)))
        session.commit()


@pytest.fixture(params=PURGE_SITES)
def purge_site(request) -> PurgeSite:
    return PURGE_SITES[request.param]


def test_a_hard_delete_stamps_the_references_only_the_deleted_songs_linked(
    factory, audio_dir, purge_site,
):
    _trash_song_world(factory, audio_dir, purge_site)
    counts = run_cleanup_expired(factory, audio_dir)
    assert counts == ((1, 0) if purge_site.album_trashed else (0, 1))
    assert _stamped(factory) == {"r1", "r2"}
    assert not (audio_dir / OWNER / "doomed-take.mp3").exists()


@pytest.mark.parametrize("kept_reference", REFERENCES)
def test_a_reference_another_song_still_links_keeps_no_stamp_in_a_hard_delete(
    factory, audio_dir, purge_site, kept_reference,
):
    _trash_song_world(factory, audio_dir, purge_site)
    _keep_linked(factory, kept_reference)
    run_cleanup_expired(factory, audio_dir)
    assert _stamped(factory) == set(REFERENCES) - {kept_reference}


def test_a_failing_stamp_keeps_the_counts_the_unlinks_and_the_cover_removals(
    factory, audio_dir, purge_site, caplog,
):
    _trash_song_world(factory, audio_dir, purge_site)
    cover = audio_dir / SONG_COVER_DIRNAME / "doomed"
    cover.mkdir(parents=True)
    (cover / "cover.png").write_bytes(b"png")
    _add_failing_stamp(factory)
    with caplog.at_level(logging.ERROR):
        counts = run_cleanup_expired(factory, audio_dir)
    assert counts == ((1, 0) if purge_site.album_trashed else (0, 1))
    assert not (audio_dir / OWNER / "doomed-take.mp3").exists()
    assert not cover.exists()
    assert _stamped(factory) == set()
    [record] = [r for r in caplog.records if r.levelno == logging.ERROR]
    message = record.getMessage()
    assert "IntegrityError" in message
    assert "secret" not in message
    assert record.exc_info is None


def test_nothing_expired_stamps_nothing(factory, audio_dir):
    assert run_cleanup_expired(factory, audio_dir) == (0, 0)
    assert _stamped(factory) == set()


def _archived_takes(factory, audio_dir: Path, references: dict[str, str | None]) -> None:
    with factory() as session:
        for name, reference in references.items():
            _song_linking(
                session, name, "live", version_reference=None, take_reference=reference,
                archived=True,
            )
        session.commit()
    for name in references:
        (audio_dir / OWNER / f"{name}-take.mp3").write_bytes(b"ID3")


def test_retention_stamps_a_reference_only_the_deleted_take_linked(factory, audio_dir):
    _archived_takes(factory, audio_dir, {"ta": "r1"})
    report = run_generation_retention(factory, audio_dir)
    assert report.deleted_ids == ["ta-take"]
    assert _stamped(factory) == {"r1"}
    assert not (audio_dir / OWNER / "ta-take.mp3").exists()


def test_retention_keeps_no_stamp_for_a_reference_another_take_still_links(factory, audio_dir):
    _archived_takes(factory, audio_dir, {"ta": "r1"})
    _keep_linked(factory, "r1")
    run_generation_retention(factory, audio_dir)
    assert _stamped(factory) == set()


def test_retention_dry_run_stamps_nothing(factory, audio_dir):
    _archived_takes(factory, audio_dir, {"ta": "r1"})
    report = run_generation_retention(factory, audio_dir, dry_run=True)
    assert report.deleted_ids == ["ta-take"]
    assert _stamped(factory) == set()


def test_a_failed_stamp_on_one_take_still_unlinks_and_reports_it_and_goes_on(
    factory, audio_dir, caplog,
):
    _archived_takes(factory, audio_dir, {"ta": "r1", "tb": "r2"})
    _add_failing_stamp(factory, "r1")
    with caplog.at_level(logging.ERROR):
        report = run_generation_retention(factory, audio_dir)
    assert report.deleted_ids == ["ta-take", "tb-take"]
    assert not (audio_dir / OWNER / "ta-take.mp3").exists()
    assert not (audio_dir / OWNER / "tb-take.mp3").exists()
    assert _stamped(factory) == {"r2"}
    [record] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert "IntegrityError" in record.getMessage()
    assert "secret" not in record.getMessage()


def test_a_take_that_no_longer_qualifies_is_neither_stamped_nor_reported(factory, audio_dir):
    _archived_takes(factory, audio_dir, {"ta": "r1", "tb": "r2"})
    calls = 0

    def factory_that_keeps_ta_after_the_read():
        nonlocal calls
        calls += 1
        if calls == 2:
            with factory() as session:
                session.get(Generation, "ta-take").is_kept = True
                session.commit()
        return factory()

    report = run_generation_retention(factory_that_keeps_ta_after_the_read, audio_dir)
    assert report.deleted_ids == ["tb-take"]
    assert (audio_dir / OWNER / "ta-take.mp3").exists()
    assert _stamped(factory) == {"r2"}

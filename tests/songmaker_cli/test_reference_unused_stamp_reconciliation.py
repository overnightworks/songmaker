"""The daily reconciliation stamps unused, unkept references and clears used or kept stamps."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from support.failing_reference_stamp import failing_stamp_trigger

from songmaker_cli.constants import REFERENCE_AUDIO_DIR
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, Generation, ReferenceRecording, Song, User, Version
from songmaker_cli.reference_audio import ReconciledStamps, reconcile_unused_stamps

OWNER = "owner"
OLD_STAMP = datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
SECRET_NAME = "secret-reference"
EARLIER_NAME = "aaa-earlier-reference"


def _recording(name: str, *, stamp: datetime | None = None, kept: bool = False):
    return ReferenceRecording(
        id=name, user_id=OWNER, storage_path=f"{OWNER}/{REFERENCE_AUDIO_DIR}/{name}.wav",
        original_filename=f"{name}.wav", size_bytes=4, unused_since=stamp, is_kept=kept,
    )


def _link(session, name: str, *, via: str, trashed: bool = False, archived: bool = False) -> None:
    """A song whose version (``via`` "version") or take (``via`` "take") links the reference."""
    session.add(Album(
        id=f"album-{name}", title=name, artist="A", created_by=OWNER,
        deleted_at=datetime.now(timezone.utc) if trashed else None,
    ))
    session.flush()
    session.add(Song(
        id=f"song-{name}", title=name, album_id=f"album-{name}", track_number=1, slug=name,
    ))
    session.flush()
    session.add(Version(
        id=f"version-{name}", song_id=f"song-{name}", version_number=1, lyrics="la", prompt="p",
        reference_recording_id=name if via == "version" else None,
    ))
    session.flush()
    if via == "take":
        session.add(Generation(
            id=f"take-{name}", song_id=f"song-{name}", version_id=f"version-{name}",
            generation_number=1, mp3_path=f"{OWNER}/{name}.mp3", reference_recording_id=name,
            is_archived=archived,
        ))


@pytest.fixture
def factory(tmp_path: Path):
    factory = init_test_db(tmp_path / "reconciliation.db")
    with factory() as session:
        session.add(User(id=OWNER, username=OWNER))
        session.commit()
    return factory


def _add(factory, *rows) -> None:
    with factory() as session:
        session.add_all(rows)
        session.commit()


def _stamp(factory, name: str) -> datetime | None:
    with factory() as session:
        return session.get(ReferenceRecording, name).unused_since


def test_an_unused_unkept_row_without_a_stamp_is_stamped_from_the_start_of_the_run(factory) -> None:
    _add(factory, _recording("loose"))
    started = datetime.now(timezone.utc).replace(tzinfo=None)

    report = reconcile_unused_stamps(factory)

    assert report == ReconciledStamps(stamped=1, cleared=0)
    assert _stamp(factory, "loose").replace(tzinfo=None) >= started


def test_a_row_with_a_stamp_keeps_its_exact_value(factory) -> None:
    _add(factory, _recording("old", stamp=OLD_STAMP))

    report = reconcile_unused_stamps(factory)

    assert report == ReconciledStamps(stamped=0, cleared=0)
    assert _stamp(factory, "old").replace(tzinfo=None) == OLD_STAMP.replace(tzinfo=None)


@pytest.mark.parametrize(
    ("via", "trashed", "archived"),
    [
        ("version", False, False),
        ("take", False, False),
        ("take", False, True),
        ("version", True, False),
        ("take", True, False),
    ],
)
def test_a_stamped_row_that_a_version_or_take_links_loses_its_stamp(
    factory, via: str, trashed: bool, archived: bool,
) -> None:
    with factory() as session:
        session.add(_recording("linked", stamp=OLD_STAMP))
        session.flush()
        _link(session, "linked", via=via, trashed=trashed, archived=archived)
        session.commit()

    report = reconcile_unused_stamps(factory)

    assert report == ReconciledStamps(stamped=0, cleared=1)
    assert _stamp(factory, "linked") is None


def test_a_kept_row_loses_a_stamp_and_an_unstamped_kept_row_stays_unstamped(factory) -> None:
    _add(
        factory,
        _recording("kept-stamped", stamp=OLD_STAMP, kept=True),
        _recording("kept", kept=True),
    )

    report = reconcile_unused_stamps(factory)

    assert report == ReconciledStamps(stamped=0, cleared=1)
    assert _stamp(factory, "kept-stamped") is None
    assert _stamp(factory, "kept") is None


def test_a_used_row_without_a_stamp_stays_unstamped(factory) -> None:
    with factory() as session:
        session.add(_recording("used"))
        session.flush()
        _link(session, "used", via="version")
        session.commit()

    report = reconcile_unused_stamps(factory)

    assert report == ReconciledStamps(stamped=0, cleared=0)
    assert _stamp(factory, "used") is None


def test_a_failing_stamp_half_rolls_back_every_candidate_and_spares_the_clear_half(
    factory, caplog,
) -> None:
    with factory() as session:
        session.add_all([
            _recording(SECRET_NAME), _recording(EARLIER_NAME),
            _recording("stamped-kept", stamp=OLD_STAMP, kept=True),
        ])
        session.execute(text(failing_stamp_trigger(SECRET_NAME)))
        session.commit()

    with caplog.at_level(logging.INFO):
        report = reconcile_unused_stamps(factory)

    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert report == ReconciledStamps(stamped=0, cleared=1)
    assert len(errors) == 1
    assert errors[0].exc_info is None
    assert SECRET_NAME not in errors[0].getMessage()
    assert "for 2 reference candidates" in errors[0].getMessage()
    assert errors[0].getMessage().endswith("Error")
    assert _stamp(factory, EARLIER_NAME) is None
    assert _stamp(factory, SECRET_NAME) is None
    assert _stamp(factory, "stamped-kept") is None


def test_a_successful_run_logs_one_info_line_with_the_counts(factory, caplog) -> None:
    _add(factory, _recording("loose"), _recording("kept", stamp=OLD_STAMP, kept=True))

    with caplog.at_level(logging.INFO):
        reconcile_unused_stamps(factory)

    messages = [record.getMessage() for record in caplog.records if record.levelno == logging.INFO]
    assert [message for message in messages if "1 stamped, 1 cleared" in message]

"""Tests for the E2E take seeders in ``scripts/``."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, Generation, User

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import seed_e2e_job_states  # noqa: E402
import seed_e2e_song_takes  # noqa: E402

_OWNER_ID = "owner"
_ALBUM_ID = "album"


def _seed_song_takes(session, audio_dir: Path) -> str:
    return seed_e2e_song_takes.seed_song_takes(
        session, audio_dir, b"mp3",
        album_id=_ALBUM_ID, title="Takes", take_count=2, owner_id=_OWNER_ID,
    )


def _seed_song_at_version(session, audio_dir: Path) -> str:
    return seed_e2e_job_states.seed_song_at_version(
        session, audio_dir, b"mp3",
        album_id=_ALBUM_ID, title="Takes", version_number=2, take_count=2,
        owner_id=_OWNER_ID,
    )


@pytest.mark.parametrize("seed", [_seed_song_takes, _seed_song_at_version])
def test_seeded_takes_record_the_owner_as_their_maker(
    tmp_path: Path, seed: Callable[..., str],
) -> None:
    audio_dir = tmp_path / "audio"
    factory = init_test_db(tmp_path / "seed.db")
    with factory() as session:
        session.add(User(id=_OWNER_ID, username=_OWNER_ID))
        session.add(Album(id=_ALBUM_ID, title="A", artist="X"))
        session.commit()

        song_id = seed(session, audio_dir)

        makers = {g.created_by for g in session.query(Generation).filter_by(song_id=song_id)}
        assert makers == {_OWNER_ID}


@pytest.fixture
def seeded_job(tmp_path):
    from songmaker_cli.constants import JobStatus, JobType
    from songmaker_cli.db.queries.jobs import JobStatusUpdate, create_job, update_job_status

    factory = init_test_db(tmp_path / "completion.db")
    with factory() as session:
        session.add(User(id=_OWNER_ID, username=_OWNER_ID))
        session.add(Album(id=_ALBUM_ID, title="A", artist="X"))
        session.commit()
        audio_dir = tmp_path / "audio"
        song_id = _seed_song_at_version(session, audio_dir)
        job = create_job(session, JobType.GENERATE, user_id=_OWNER_ID, song_id=song_id)
        update_job_status(session, job.id, JobStatusUpdate(JobStatus.RUNNING, take_count=2))
        session.commit()
        yield session, audio_dir, job


@pytest.mark.parametrize("take_count", [1, 2])
def test_completion_preserves_takes_and_adds_the_declared_batch_without_events(
    seeded_job, take_count,
):
    from songmaker_cli.constants import JobStatus
    from songmaker_cli.db.models import ResourceEvent
    from songmaker_cli.db.queries.songs import get_song, update_song

    session, audio_dir, job = seeded_job
    existing_ids = {g.id for g in session.query(Generation)}
    events_before = session.query(ResourceEvent).count()
    # Completion belongs to the latest version, even if it changed after dispatch.
    update_song(session, job.song_id, force_new_version=True)
    job.take_count = take_count
    session.commit()
    version_id = get_song(session, job.song_id).latest_version.id

    audio = (SCRIPTS.parent / "frontend/e2e/fixtures/take.mp3").read_bytes()
    seed_e2e_job_states.complete_generation_job(session, audio_dir, audio, job_id=job.id)
    session.expire_all()

    takes = session.query(Generation).all()
    additions = [g for g in takes if g.id not in existing_ids]
    assert existing_ids <= {g.id for g in takes}
    assert len(additions) == take_count
    assert {(g.song_id, g.version_id, g.created_by) for g in additions} == {
        (job.song_id, version_id, _OWNER_ID),
    }
    assert all((audio_dir / g.mp3_path).read_bytes() == audio for g in additions)
    assert job.status == JobStatus.COMPLETED
    assert job.progress == 1.0
    assert session.query(ResourceEvent).count() == events_before


@pytest.mark.parametrize("status,take_count,audio", [
    ("completed", 2, b"mp3"), ("failed", 2, b"mp3"), ("cancelled", 2, b"mp3"),
    ("queued", 2, b"mp3"), ("running", None, b"mp3"), ("running", 0, b"mp3"),
    ("running", -1, b"mp3"), ("running", 2, b""),
])
def test_invalid_completion_writes_neither_takes_nor_audio(seeded_job, status, take_count, audio):
    session, audio_dir, job = seeded_job
    job.status, job.take_count = status, take_count
    session.commit()
    files_before = set(audio_dir.rglob("*.mp3"))
    ids_before = {g.id for g in session.query(Generation)}

    with pytest.raises(SystemExit):
        seed_e2e_job_states.complete_generation_job(session, audio_dir, audio, job_id=job.id)

    assert {g.id for g in session.query(Generation)} == ids_before
    assert set(audio_dir.rglob("*.mp3")) == files_before
    assert job.status == status


def test_failed_second_take_rolls_back_the_batch_and_terminal_status(seeded_job):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    session, audio_dir, job = seeded_job
    ids_before = {g.id for g in session.query(Generation)}
    files_before = set(audio_dir.rglob("*.mp3"))
    # A real database refusal on the second addition, after the first was flushed.
    session.execute(text("""
        CREATE TRIGGER reject_second_take BEFORE INSERT ON generations
        WHEN (SELECT COUNT(*) FROM generations) >= 3
        BEGIN SELECT RAISE(ABORT, 'fixture rejects second take'); END
    """))
    session.commit()

    with pytest.raises(IntegrityError, match="fixture rejects second take"):
        seed_e2e_job_states.complete_generation_job(session, audio_dir, b"mp3", job_id=job.id)
    session.expire_all()

    assert {g.id for g in session.query(Generation)} == ids_before
    assert job.status == "running"
    assert set(audio_dir.rglob("*.mp3")) == files_before


def test_queued_command_prints_a_real_owned_job_with_a_computed_position(seeded_job, capsys):
    import argparse

    from songmaker_cli.constants import JobStatus, JobType
    from songmaker_cli.db.queries.jobs import create_job, get_job, get_queue_position

    session, _, running = seeded_job
    ahead = create_job(session, JobType.GENERATE, user_id=_OWNER_ID, song_id=running.song_id)
    session.commit()
    seed_e2e_job_states.cmd_set_queued(
        session, argparse.Namespace(song_id=running.song_id, owner_username=_OWNER_ID),
    )
    job = get_job(session, capsys.readouterr().out.strip())

    assert job is not None
    assert (job.user_id, job.song_id, job.type, job.status) == (
        _OWNER_ID, running.song_id, JobType.GENERATE, JobStatus.QUEUED,
    )
    assert get_queue_position(session, ahead) == 1
    assert get_queue_position(session, job) == 2


@pytest.fixture
def cover_album(tmp_path):
    factory = init_test_db(tmp_path / "cover.db")
    with factory() as session:
        session.add(User(id=_OWNER_ID, username=_OWNER_ID))
        session.add(Album(id=_ALBUM_ID, title="A", artist="X"))
        session.commit()
        yield session, tmp_path / "audio"


def test_cover_running_command_prints_an_owned_job_started_in_the_past(cover_album, capsys):
    import argparse
    from datetime import datetime, timedelta, timezone

    from songmaker_cli.constants import JobStatus, JobType
    from songmaker_cli.db.queries.jobs import get_job

    session, _ = cover_album
    seed_e2e_job_states.cmd_set_cover_running(
        session,
        argparse.Namespace(album_id=_ALBUM_ID, owner_username=_OWNER_ID, started_offset=90),
    )
    job = get_job(session, capsys.readouterr().out.strip())

    assert job is not None
    assert (job.user_id, job.album_id, job.type, job.status) == (
        _OWNER_ID, _ALBUM_ID, JobType.COVER, JobStatus.RUNNING,
    )
    # SQLite returns the stored UTC instant without its zone.
    started_at = job.started_at.replace(tzinfo=timezone.utc)
    assert datetime.now(timezone.utc) - started_at >= timedelta(seconds=90)
    assert job.heartbeat_at is not None


def test_publishing_a_cover_suggestion_completes_the_run_and_waits_for_the_album(cover_album):
    from songmaker_cli.constants import JobStatus, JobType
    from songmaker_cli.cover_suggestions import resolve_suggestion_png
    from songmaker_cli.db.queries.cover_suggestions import list_album_cover_suggestions
    from songmaker_cli.db.queries.jobs import JobStatusUpdate, create_job, update_job_status

    session, audio_dir = cover_album
    job = create_job(session, JobType.COVER, user_id=_OWNER_ID, album_id=_ALBUM_ID)
    update_job_status(session, job.id, JobStatusUpdate(JobStatus.RUNNING))
    session.commit()

    seed_e2e_job_states.publish_cover_suggestion(session, audio_dir, b"png", job_id=job.id)
    session.expire_all()

    (suggestion,) = list_album_cover_suggestions(session, _ALBUM_ID)
    assert suggestion.job_id == job.id
    stored = resolve_suggestion_png(audio_dir, _ALBUM_ID, suggestion.id, suggestion.png_path)
    assert stored.read_bytes() == b"png"
    assert job.status == JobStatus.COMPLETED


@pytest.mark.parametrize("status,job_type,png", [
    ("completed", "cover", b"png"), ("failed", "cover", b"png"), ("queued", "cover", b"png"),
    ("running", "generate", b"png"), ("running", "cover", b""),
])
def test_invalid_cover_publication_writes_neither_suggestion_nor_file(
    cover_album, status, job_type, png,
):
    from songmaker_cli.constants import JobType
    from songmaker_cli.db.queries.cover_suggestions import list_album_cover_suggestions
    from songmaker_cli.db.queries.jobs import create_job

    session, audio_dir = cover_album
    job = create_job(session, JobType.COVER, user_id=_OWNER_ID, album_id=_ALBUM_ID)
    job.status, job.type = status, job_type
    session.commit()

    with pytest.raises(SystemExit):
        seed_e2e_job_states.publish_cover_suggestion(session, audio_dir, png, job_id=job.id)

    assert list_album_cover_suggestions(session, _ALBUM_ID) == []
    assert not list(audio_dir.rglob("*.png"))
    assert job.status == status


@pytest.mark.parametrize("owner_id", ["../outside", "..", ".", "", "/etc", "a/b"])
def test_an_owner_id_that_is_not_one_directory_name_writes_nothing(
    tmp_path: Path, owner_id: str
) -> None:
    audio_dir = tmp_path / "audio"
    factory = init_test_db(tmp_path / "seed.db")
    with factory() as session:
        session.add(Album(id=_ALBUM_ID, title="A", artist="X"))
        session.commit()
        with pytest.raises(ValueError, match="not a single directory name"):
            seed_e2e_song_takes.seed_song_takes(
                session, audio_dir, b"mp3",
                album_id=_ALBUM_ID, title="Takes", take_count=1, owner_id=owner_id,
            )
    assert not list(tmp_path.glob("outside/*"))
    assert not list(tmp_path.glob("*.mp3"))

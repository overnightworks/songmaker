"""A fetched take is music's own file: a failed fetch fails one take, a cancelled job drops it."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from support.generation_job_world import make_generation_dto, patch_generation_dispatch, run_async

from songmaker_cli.db.models import Generation, Version
from songmaker_cli.db.queries.jobs import JobStatusUpdate, get_job, update_job_status
from songmaker_cli.jobs import run_generation_job
from songmaker_cli.scheduler import WorkerTaskFailed


def _run_fetch_job(seeded_db, tmp_path: Path, dispatch, *, count: int) -> None:
    dispatch_patch, post_process, defaults = patch_generation_dispatch(dispatch)
    with dispatch_patch, post_process, defaults:
        run_async(run_generation_job(
            "j1", "s1", "v1", count, "u1", db_factory=seeded_db, audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data", redis=MagicMock(), target_model="sft",
        ))


def _count_saved_takes(seeded_db) -> int:
    with seeded_db() as session:
        return session.query(Generation).filter_by(song_id="s1").count()


def test_a_take_whose_fetch_failed_leaves_the_jobs_other_takes_saved(
    seeded_db, tmp_path: Path,
) -> None:
    fetch_failed = WorkerTaskFailed("Worker result fetch failed: peer closed connection")

    takes = [make_generation_dto(seed=1), fetch_failed, make_generation_dto(seed=3)]
    saved_before = _count_saved_takes(seeded_db)

    _run_fetch_job(seeded_db, tmp_path, takes, count=3)

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert (job.status, "1 failed" in job.error) == ("partial", True)
    assert _count_saved_takes(seeded_db) == saved_before + 2


def test_a_take_fetched_for_a_job_cancelled_meanwhile_leaves_no_local_file(
    seeded_db, tmp_path: Path,
) -> None:
    fetched = tmp_path / "music-take.wav"

    async def dispatch(**_kwargs):
        fetched.write_bytes(b"RIFF")
        with seeded_db() as session:
            update_job_status(session, "j1", JobStatusUpdate("cancelled"))
            session.commit()
        return make_generation_dto(audio_path=str(fetched))

    saved_before = _count_saved_takes(seeded_db)

    _run_fetch_job(seeded_db, tmp_path, dispatch, count=1)

    assert _count_saved_takes(seeded_db) == saved_before
    assert not fetched.exists()


def test_a_fetched_take_is_saved_for_the_song_and_version_the_job_requested(
    seeded_db, tmp_path: Path,
) -> None:
    """Spec: REQ-GENERATION-01 -- A take the generation job fetched is saved for the job's song
    and the version it requested, not the song's latest version."""
    with seeded_db() as session:
        session.add(Version(id="v2", song_id="s1", version_number=2, lyrics="later draft"))
        session.commit()

    _run_fetch_job(seeded_db, tmp_path, make_generation_dto(), count=1)

    with seeded_db() as session:
        takes = session.query(Generation).filter_by(song_id="s1").all()
        assert [(take.song_id, take.version_id) for take in takes] == [("s1", "v1")]

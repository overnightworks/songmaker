"""A fetched take is music's own file: a failed fetch fails one take, a cancelled job drops it."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from support.generation_job_world import (
    make_generation_dto,
    patch_generation_dispatch,
    run_async,
    worker_up,
)
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.db.models import Generation
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


def test_a_songs_settings_reach_the_worker_through_the_generate_request(
    seeded_db, tmp_path: Path,
) -> None:
    """Spec: REQ-PARAM-01 -- the settings saved on a song arrive in the config sent to the worker."""
    settings = {"inference_steps": 77, "lm_temperature": 0.3, "shift": 2.5, "thinking": False}
    app = make_router_app(
        make_router_ctx(tmp_path, db=seeded_db), user=make_authenticated_user("u1"),
    )
    client = web_client(app)
    assert client.put("/api/songs/s1", json={"generation_params": settings}).status_code == 200
    pool = AsyncMock()
    with worker_up(), patch("songmaker_cli.generation_api.get_arq_pool", return_value=pool):
        response = client.post("/api/songs/s1/generate", json={"count": 1, "model": "sft"})
    assert response.status_code == 200
    _function, job_id, song_id, version_id, count, user_id, seed, model = (
        pool.enqueue_job.call_args.args
    )

    dispatch = AsyncMock(return_value=make_generation_dto())
    dispatch_patch, post_process, defaults = patch_generation_dispatch(dispatch)
    with dispatch_patch, post_process, defaults:
        run_async(run_generation_job(
            job_id, song_id, version_id, count, user_id, db_factory=seeded_db,
            audio_dir=tmp_path / "audio", data_dir=tmp_path / "data", redis=MagicMock(),
            seed=seed, target_model=model,
        ))

    sent = dispatch.call_args.kwargs["ace_config"]
    assert {name: getattr(sent, name) for name in settings} == settings


def test_a_saved_take_records_the_seed_the_worker_reported(seeded_db, tmp_path: Path) -> None:
    """Spec: REQ-SEED-03 -- the take row holds the worker's seed, not the one requested."""
    dispatch_patch, post_process, defaults = patch_generation_dispatch(
        make_generation_dto(seed=987654),
    )
    with dispatch_patch, post_process, defaults:
        run_async(run_generation_job(
            "j1", "s1", "v1", 1, "u1", db_factory=seeded_db, audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data", redis=MagicMock(), seed=5, target_model="sft",
        ))

    with seeded_db() as session:
        assert [take.seed for take in session.query(Generation).filter_by(song_id="s1")] == [987654]

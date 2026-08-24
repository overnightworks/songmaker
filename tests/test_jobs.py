"""Tests for background job runners (generation + scoring)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from acestep_engine.models import AceStepConfig
from songmaker_cli.api_models import CoverTaskParams, RepaintTaskParams
from songmaker_cli.constants import ARQ_SCORING_QUEUE_NAME, JobFunction, JobType
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import (
    Album,
    Generation,
    Job,
    ResourceEvent,
    Score,
    Song,
    User,
    Version,
)
from songmaker_cli.db.queries import (
    count_user_jobs_in_window,
    get_generation,
    get_job,
    update_job_status,
)
from songmaker_cli.jobs import (
    GenerationContext,
    _apply_cover_overrides,
    _apply_repaint_overrides,
    _finalize_generation_job,
    _make_generation_progress_callback,
    _persist_generation_row,
    _update_job,
    run_generation_job,
    run_scoring_job,
)
from songmaker_cli.scheduler import GenerationTaskResultDTO
from songmaker_cli.scoring.models import (
    EmotionalDynamicsScore,
    ScorerOutcome,
    ScorerRun,
    SongScores,
    TextAccuracyScore,
)


def _run(coro):
    return asyncio.run(coro)


def _make_dto(
    seed: int = 42, audio_path: str = "/tmp/fake.wav",
    delivered_batch_size: int | None = None,
) -> GenerationTaskResultDTO:
    return GenerationTaskResultDTO(
        mode="turbo", audio_path=audio_path, seed=seed,
        cot_caption="", cot_lyrics="",
        delivered_batch_size=delivered_batch_size,
    )


def _persist_via_post_process(*, ctx, generation_id, db_factory, **kwargs):
    return _persist_generation_row(
        db_factory=db_factory,
        ctx=ctx,
        generation_id=generation_id,
        seed=kwargs.get("worker_seed", 0),
        cot_caption=kwargs.get("worker_cot_caption", ""),
        cot_lyrics=kwargs.get("worker_cot_lyrics", ""),
        delivered_batch_size=kwargs.get("worker_delivered_batch_size"),
        mp3_path=Path(f"/tmp/{generation_id}.mp3"),
        wav_path=Path(f"/tmp/{generation_id}.wav"),
        job_id=kwargs["job_id"],
    )


@pytest.fixture()
def db_factory(tmp_path: Path):
    factory = init_db(tmp_path / "test.db")
    yield factory


@pytest.fixture()
def seeded_db(db_factory, tmp_path: Path):
    with db_factory() as session:
        session.add(User(id="u1", username="user1", password_hash="hash", role="user"))
        session.flush()
        session.add(Album(id="rock", title="Rock", artist="Band", created_by="u1"))
        session.add(Song(
            id="s1", title="Song One", album_id="rock",
            track_number=1, vocal_language="en",
        ))
        session.add(Version(
            id="v1", song_id="s1", version_number=1,
            lyrics="Hello world", prompt="rock style", bpm=120,
            audio_duration=60, key_scale="Am",
        ))
        session.add(Job(id="j1", type="generate", status="queued", user_id="u1"))
        session.add(Job(id="j2", type="score", status="queued"))
        session.commit()

    mp3_dir = tmp_path / "audio" / "user1"
    mp3_dir.mkdir(parents=True)
    mp3 = mp3_dir / "g_seed42.mp3"
    mp3.write_bytes(b"\xff\xfb\x90\x00" * 100)

    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    return db_factory


# ── _update_job ─────────────────────────────────────────────────────


def test_update_job_success(seeded_db) -> None:
    _update_job(seeded_db, "j1", "running", progress=0.5)
    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "running"
        assert job.progress == 0.5


def test_update_job_raises_after_retries(db_factory) -> None:
    broken_factory = MagicMock(side_effect=RuntimeError("db broken"))
    with pytest.raises(RuntimeError, match="status update to 'running' failed after 2 attempts"):
        _update_job(broken_factory, "j1", "running")


# ── run_generation_job ──────────────────────────────────────────────


def _patch_dispatch_and_post_process(dto_or_side_effect):
    if isinstance(dto_or_side_effect, list):
        dispatch = AsyncMock(side_effect=dto_or_side_effect)
    elif isinstance(dto_or_side_effect, BaseException) or (
        isinstance(dto_or_side_effect, type) and issubclass(dto_or_side_effect, BaseException)
    ):
        dispatch = AsyncMock(side_effect=dto_or_side_effect)
    else:
        dispatch = AsyncMock(return_value=dto_or_side_effect)
    return (
        patch("songmaker_cli.jobs.dispatch_generation", dispatch),
        patch("songmaker_cli.jobs.post_process_generation", side_effect=_persist_via_post_process),
        patch("songmaker_cli.jobs.load_generation_defaults", return_value={}),
    )


def test_generation_job_happy_path(seeded_db, tmp_path: Path) -> None:
    dispatch, post_process, defaults = _patch_dispatch_and_post_process(_make_dto(seed=42))
    with dispatch, post_process, defaults:
        _run(run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=MagicMock(),
            target_model="sft",
        ))

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "completed"
        assert job.progress == 1.0

        gens = session.query(Generation).filter_by(song_id="s1").all()
        assert len(gens) == 1
        assert gens[0].seed == 42
        assert gens[0].model_mode == "sft"
        events = session.query(ResourceEvent).all()
        assert len(events) == 1
        assert events[0].generation_id == gens[0].id


def test_generation_job_multiple_count(seeded_db, tmp_path: Path) -> None:
    dtos = [_make_dto(seed=100 + i) for i in range(3)]
    dispatch, post_process, defaults = _patch_dispatch_and_post_process(dtos)
    with dispatch, post_process, defaults:
        _run(run_generation_job(
            "j1", "s1", "v1", 3, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=MagicMock(),
            target_model="sft",
        ))

    with seeded_db() as session:
        gens = session.query(Generation).filter_by(song_id="s1").all()
        assert len(gens) == 3
        assert session.query(ResourceEvent).count() == 3


def test_generation_job_partial_failure(seeded_db, tmp_path: Path) -> None:
    side_effects = [_make_dto(seed=100), RuntimeError("GPU OOM"), RuntimeError("GPU OOM")]
    dispatch, post_process, defaults = _patch_dispatch_and_post_process(side_effects)
    with dispatch, post_process, defaults:
        _run(run_generation_job(
            "j1", "s1", "v1", 3, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=MagicMock(),
            target_model="sft",
        ))

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "partial"
        assert "1/3 completed" in job.error
        assert "2 failed" in job.error

        gens = session.query(Generation).filter_by(song_id="s1").all()
        assert len(gens) == 1
        assert session.query(ResourceEvent).count() == 1


def test_generation_job_song_not_found(seeded_db, tmp_path: Path) -> None:
    _run(run_generation_job(
        "j1", "nonexistent", "v1", 1, "u1",
        db_factory=seeded_db,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        redis=MagicMock(),
        target_model="sft",
    ))

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "failed"
        assert "Song not found" in job.error
        assert session.query(ResourceEvent).count() == 0


def test_generation_job_version_not_found(seeded_db, tmp_path: Path) -> None:
    _run(run_generation_job(
        "j1", "s1", "nonexistent", 1, "u1",
        db_factory=seeded_db,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        redis=MagicMock(),
        target_model="sft",
    ))

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "failed"
        assert "Version not found" in job.error


def test_generation_job_rejects_foreign_reference_before_dispatch(
    seeded_db, tmp_path: Path,
) -> None:
    foreign_ref = tmp_path / "audio" / "u2" / "refs" / "secret.wav"
    foreign_ref.parent.mkdir(parents=True)
    foreign_ref.write_bytes(b"SECRET")
    with seeded_db() as session:
        version = session.query(Version).filter_by(id="v1").one()
        version.generation_params = {"reference_audio_path": "u2/refs/secret.wav"}
        session.commit()

    dispatch = AsyncMock()
    with (
        patch("songmaker_cli.jobs.dispatch_generation", dispatch),
        patch("songmaker_cli.jobs.load_generation_defaults", return_value={}),
    ):
        _run(run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=MagicMock(),
            target_model="sft",
        ))

    dispatch.assert_not_awaited()
    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "failed"
        assert job.error_type == "setup_error"
        assert job.error == "Reference audio not found"


def test_generation_job_no_capacity(seeded_db, tmp_path: Path) -> None:
    from songmaker_cli.scheduler import NoCapacityError

    dispatch, post_process, defaults = _patch_dispatch_and_post_process(
        NoCapacityError("no workers"),
    )
    with dispatch, post_process, defaults:
        _run(run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=MagicMock(),
            target_model="sft",
        ))

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "failed"
        assert job.error == "No ACE-Step workers available"


def test_generation_job_records_the_workers_own_cause(seeded_db, tmp_path: Path) -> None:
    from songmaker_cli.scheduler import WorkerGenerationFailed

    cause = "Music generation failed: Insufficient free VRAM: need ~2.0 GB, only 1.3 GB available"
    dispatch, post_process, defaults = _patch_dispatch_and_post_process(
        WorkerGenerationFailed(cause),
    )
    with dispatch, post_process, defaults:
        _run(run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=MagicMock(),
            target_model="sft",
        ))

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "failed"
        assert job.error == cause


def test_generation_job_keeps_worker_protocol_failures_generic(
    seeded_db, tmp_path: Path,
) -> None:
    """Only ACE-Step's own cause reaches the user; a broken worker event
    is our bug and stays behind the generic message."""
    from songmaker_cli.scheduler import WorkerProtocolError

    dispatch, post_process, defaults = _patch_dispatch_and_post_process(
        WorkerProtocolError("Worker done event missing 'result' field"),
    )
    with dispatch, post_process, defaults:
        _run(run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=MagicMock(),
            target_model="sft",
        ))

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "failed"
        assert job.error == "Worker generation failed"


def test_generation_job_exception(seeded_db, tmp_path: Path) -> None:
    dispatch, post_process, defaults = _patch_dispatch_and_post_process(
        RuntimeError("GPU error"),
    )
    with dispatch, post_process, defaults:
        _run(run_generation_job(
            "j1", "s1", "v1", 3, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=MagicMock(),
            target_model="sft",
        ))

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "failed"
        assert job.error == "Internal error during processing"
        assert session.query(Generation).count() == 0
        assert session.query(ResourceEvent).count() == 0
        assert session.query(Job).filter_by(type="score", song_id="s1").count() == 0


def test_generation_event_failure_rolls_back_generation(
    seeded_db, tmp_path: Path,
) -> None:
    def persist_with_artifacts(*, ctx, generation_id, db_factory, **kwargs):
        for suffix in (".mp3", ".wav", ".raw.wav"):
            path = ctx.audio_dir / ctx.user_id / f"{generation_id}{suffix}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"audio")
        _persist_via_post_process(
            ctx=ctx, generation_id=generation_id, db_factory=db_factory, **kwargs,
        )

    dispatch = AsyncMock(return_value=_make_dto())
    with (
        patch("songmaker_cli.jobs.dispatch_generation", dispatch),
        patch("songmaker_cli.jobs.post_process_generation", side_effect=persist_with_artifacts),
        patch("songmaker_cli.jobs.load_generation_defaults", return_value={}),
        patch(
            "songmaker_cli.jobs.generation.create_generation_created_event",
            side_effect=RuntimeError("event write failed"),
        ),
    ):
        _run(run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=MagicMock(),
            target_model="sft",
        ))

    with seeded_db() as session:
        assert get_job(session, "j1").status == "failed"
        assert session.query(Generation).count() == 0
        assert session.query(ResourceEvent).count() == 0
    assert list((tmp_path / "audio" / "u1").glob("*")) == []


# ── Auto-score trigger (issue #222) ────────────────────────────────


def _healthy_scoring_redis() -> MagicMock:
    redis = MagicMock()
    redis.exists = AsyncMock(return_value=1)
    redis.enqueue_job = AsyncMock()
    return redis


def test_generation_job_auto_scores_the_new_generation(seeded_db, tmp_path: Path) -> None:
    dispatch, post_process, defaults = _patch_dispatch_and_post_process(_make_dto(seed=42))
    redis = _healthy_scoring_redis()
    with dispatch, post_process, defaults:
        _run(run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=redis,
            target_model="sft",
        ))

    with seeded_db() as session:
        gen = session.query(Generation).filter_by(song_id="s1").one()
        score_job = session.query(Job).filter_by(type="score", song_id="s1").one()
        assert score_job.user_id is None
        assert score_job.status == "queued"
        gen_id = gen.id
        score_job_id = score_job.id

    redis.enqueue_job.assert_awaited_once()
    args, kwargs = redis.enqueue_job.await_args
    assert args[0] == JobFunction.SCORE
    assert args[1] == score_job_id
    assert args[2] == gen_id
    assert kwargs["_queue_name"] == ARQ_SCORING_QUEUE_NAME


def test_generation_job_auto_score_is_not_counted_against_the_users_rate_limit(
    seeded_db, tmp_path: Path,
) -> None:
    dispatch, post_process, defaults = _patch_dispatch_and_post_process(_make_dto())
    with dispatch, post_process, defaults:
        _run(run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=_healthy_scoring_redis(),
            target_model="sft",
        ))

    with seeded_db() as session:
        assert session.query(Job).filter_by(type="score", song_id="s1").count() == 1
        # count_user_jobs_in_window always filters on a specific user id, so
        # the auto-score job's user_id=None keeps it out of this count —
        # the manual re-score button's own budget stays untouched.
        assert count_user_jobs_in_window(session, "u1", JobType.SCORE, 3600) == 0


def test_generation_job_marks_auto_score_failed_when_scoring_worker_is_down(
    seeded_db, tmp_path: Path,
) -> None:
    dispatch, post_process, defaults = _patch_dispatch_and_post_process(_make_dto())
    redis = MagicMock()
    redis.exists = AsyncMock(return_value=0)
    redis.enqueue_job = AsyncMock()
    with dispatch, post_process, defaults:
        _run(run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=redis,
            target_model="sft",
        ))

    redis.enqueue_job.assert_not_awaited()
    with seeded_db() as session:
        score_job = session.query(Job).filter_by(type="score", song_id="s1").one()
        assert score_job.status == "failed"
        assert score_job.error_type == "setup_error"
        # The generation itself is unaffected by the down scoring worker —
        # only the follow-up auto-score job failed.
        assert get_job(session, "j1").status == "completed"
        assert session.query(Generation).filter_by(song_id="s1").count() == 1


def test_generation_job_version_gen_params_merged(seeded_db, tmp_path: Path) -> None:
    with seeded_db() as session:
        ver = session.query(Version).filter_by(id="v1").first()
        ver.generation_params = {"inference_steps": 50, "shift": 2.0}
        session.commit()

    dispatch, post_process, defaults = _patch_dispatch_and_post_process(_make_dto())
    with dispatch, post_process, defaults:
        _run(run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=MagicMock(),
            target_model="sft",
        ))

    with seeded_db() as session:
        gen = session.query(Generation).filter_by(song_id="s1").first()
        assert gen.generation_params["inference_steps"] == 50
        assert gen.generation_params["shift"] == 2.0


def test_generation_job_persists_requested_batch_size(seeded_db, tmp_path: Path) -> None:
    """A non-default requested batch_size lands on the generation row.

    `batch_size` was previously never copied from the resolved AceStepConfig
    onto `Generation.generation_params` — silently dropping the one number
    that "requested vs. delivered" (issue #211) needs on the requested side.
    """
    with seeded_db() as session:
        ver = session.query(Version).filter_by(id="v1").first()
        ver.generation_params = {"batch_size": 2}
        session.commit()

    dispatch, post_process, defaults = _patch_dispatch_and_post_process(_make_dto())
    with dispatch, post_process, defaults:
        _run(run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=MagicMock(),
            target_model="sft",
        ))

    with seeded_db() as session:
        gen = session.query(Generation).filter_by(song_id="s1").first()
        assert gen.generation_params["batch_size"] == 2


def test_generation_job_persists_vram_guard_batch_reduction(seeded_db, tmp_path: Path) -> None:
    """A worker-reported batch reduction lands on the generation, never silently.

    Requested batch_size comes from the version's own generation_params
    (what songmaker asked ACE-Step for); delivered_batch_size comes from
    the worker's task result (what ACE-Step's VRAM guard actually
    rendered). Both must be visible on the persisted row so nothing about
    "asked for 2, got 1" disappears between the two.
    """
    with seeded_db() as session:
        ver = session.query(Version).filter_by(id="v1").first()
        ver.generation_params = {"batch_size": 2}
        session.commit()

    dispatch, post_process, defaults = _patch_dispatch_and_post_process(
        _make_dto(delivered_batch_size=1),
    )
    with dispatch, post_process, defaults:
        _run(run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=MagicMock(),
            target_model="sft",
        ))

    with seeded_db() as session:
        gen = session.query(Generation).filter_by(song_id="s1").first()
        assert gen.generation_params["batch_size"] == 2
        assert gen.generation_params["delivered_batch_size"] == 1


def test_generation_job_omits_delivered_batch_size_when_it_matches_requested(
    seeded_db, tmp_path: Path,
) -> None:
    """A worker report that matches the request is not persisted as noise.

    Once the fork is fully live, every generation reports a concrete
    delivered_batch_size (not just reduced ones) — an unreduced batch=2
    request delivering exactly 2 must not add a redundant field to every
    ordinary generation's row.
    """
    with seeded_db() as session:
        ver = session.query(Version).filter_by(id="v1").first()
        ver.generation_params = {"batch_size": 2}
        session.commit()

    dispatch, post_process, defaults = _patch_dispatch_and_post_process(
        _make_dto(delivered_batch_size=2),
    )
    with dispatch, post_process, defaults:
        _run(run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=MagicMock(),
            target_model="sft",
        ))

    with seeded_db() as session:
        gen = session.query(Generation).filter_by(song_id="s1").first()
        assert gen.generation_params["batch_size"] == 2
        assert "delivered_batch_size" not in gen.generation_params


def test_generation_job_omits_default_batch_size(seeded_db, tmp_path: Path) -> None:
    """The trivial batch_size=1 default stays out of generation_params.

    There is nothing to reduce below 1, so persisting it would only ever
    be noise — matches the other resolved-default fields on this row
    (e.g. `use_cot_caption`), which stay absent unless they diverge.
    """
    dispatch, post_process, defaults = _patch_dispatch_and_post_process(_make_dto())
    with dispatch, post_process, defaults:
        _run(run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=MagicMock(),
            target_model="sft",
        ))

    with seeded_db() as session:
        gen = session.query(Generation).filter_by(song_id="s1").first()
        assert "delivered_batch_size" not in gen.generation_params
        assert "batch_size" not in gen.generation_params


def test_generation_job_global_defaults_loaded(seeded_db, tmp_path: Path) -> None:
    dispatch = AsyncMock(return_value=_make_dto())
    with (
        patch("songmaker_cli.jobs.dispatch_generation", dispatch),
        patch("songmaker_cli.jobs.post_process_generation", side_effect=_persist_via_post_process),
        patch(
            "songmaker_cli.jobs.load_generation_defaults",
            return_value={"sft": {"shift": 7.0}},
        ) as mock_load,
    ):
        _run(run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=MagicMock(),
            target_model="sft",
        ))

    mock_load.assert_called_once()


def test_generation_job_passes_target_model_to_dispatch(seeded_db, tmp_path: Path) -> None:
    dispatch = AsyncMock(return_value=_make_dto())
    with (
        patch("songmaker_cli.jobs.dispatch_generation", dispatch),
        patch("songmaker_cli.jobs.post_process_generation", side_effect=_persist_via_post_process),
        patch("songmaker_cli.jobs.load_generation_defaults", return_value={}),
    ):
        _run(run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=MagicMock(),
            target_model="xl-sft",
        ))

    dispatch.assert_awaited_once()
    kwargs = dispatch.await_args.kwargs
    assert kwargs["target_mode"] == "xl-sft"


def _cancel_job(factory, job_id: str) -> None:
    with factory() as session:
        update_job_status(session, job_id, "cancelled")
        session.commit()


def test_generation_job_queued_cancel_prevents_execution(seeded_db, tmp_path: Path) -> None:
    _cancel_job(seeded_db, "j1")
    dispatch = AsyncMock(return_value=_make_dto())
    with (
        patch("songmaker_cli.jobs.dispatch_generation", dispatch),
        patch("songmaker_cli.jobs.post_process_generation", side_effect=_persist_via_post_process),
        patch("songmaker_cli.jobs.load_generation_defaults", return_value={}),
    ):
        _run(run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=MagicMock(),
            target_model="sft",
        ))

    dispatch.assert_not_awaited()
    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "cancelled"
        assert job.completed_at is not None
        assert session.query(Generation).filter_by(song_id="s1").count() == 0
        assert session.query(ResourceEvent).count() == 0


def test_generation_job_cancel_after_first_variant_skips_rest(
    seeded_db, tmp_path: Path,
) -> None:
    def persist_then_cancel(*, ctx, generation_id, db_factory, **kwargs):
        result = _persist_via_post_process(
            ctx=ctx, generation_id=generation_id, db_factory=db_factory, **kwargs,
        )
        _cancel_job(db_factory, "j1")
        return result

    dispatch = AsyncMock(side_effect=[_make_dto(seed=100 + i) for i in range(3)])
    with (
        patch("songmaker_cli.jobs.dispatch_generation", dispatch),
        patch("songmaker_cli.jobs.post_process_generation", side_effect=persist_then_cancel),
        patch("songmaker_cli.jobs.load_generation_defaults", return_value={}),
    ):
        _run(run_generation_job(
            "j1", "s1", "v1", 3, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=MagicMock(),
            target_model="sft",
        ))

    assert dispatch.await_count == 1
    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "cancelled"
        assert job.completed_at is not None
        gens = session.query(Generation).filter_by(song_id="s1").all()
        assert len(gens) == 1
        assert gens[0].seed == 100
        assert session.query(ResourceEvent).count() == 1


def test_generation_job_cancel_after_worker_skips_persist(
    seeded_db, tmp_path: Path,
) -> None:
    async def dispatch_then_cancel(**kwargs):
        _cancel_job(seeded_db, "j1")
        return _make_dto(seed=7)

    dispatch = AsyncMock(side_effect=dispatch_then_cancel)
    with (
        patch("songmaker_cli.jobs.dispatch_generation", dispatch),
        patch(
            "songmaker_cli.jobs.post_process_generation",
            side_effect=_persist_via_post_process,
        ) as post_process,
        patch("songmaker_cli.jobs.load_generation_defaults", return_value={}),
    ):
        _run(run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=MagicMock(),
            target_model="sft",
        ))

    post_process.assert_not_called()
    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "cancelled"
        assert job.completed_at is not None
        assert session.query(Generation).filter_by(song_id="s1").count() == 0
        assert session.query(ResourceEvent).count() == 0


def test_generation_progress_does_not_revive_cancelled(seeded_db) -> None:
    _update_job(seeded_db, "j1", "running", progress=0.2)
    _cancel_job(seeded_db, "j1")
    callback = _make_generation_progress_callback(seeded_db, "j1", 0, 1)
    callback(0.9)
    _finalize_generation_job(seeded_db, "j1", 1, 1, None)

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "cancelled"
        assert job.completed_at is not None
        assert job.progress != 1.0


# ── run_scoring_job ─────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def stubbed_claude_judge():
    """The scoring job judges lyrical coherence in this process, right after
    the scorer child returns — no test may reach the real Claude CLI or API."""
    from songmaker_cli.claude.provider import ClaudeResponse

    with patch(
        "songmaker_cli.scoring.lyrical_coherence.call_claude",
        return_value=ClaudeResponse(text='{"score": 6, "issues": [], "summary": "fine"}'),
    ) as judge:
        yield judge


def _seed_generation(db_factory) -> None:
    with db_factory() as session:
        session.add(Generation(
            id="g1", song_id="s1", version_id="v1", generation_number=1,
            mp3_path="user1/g1.mp3", seed=42,
        ))
        session.commit()


def _audio_dir_with_mp3(tmp_path: Path) -> Path:
    audio_dir = tmp_path / "audio"
    mp3_file = audio_dir / "user1" / "g1.mp3"
    mp3_file.parent.mkdir(parents=True, exist_ok=True)
    mp3_file.write_bytes(b"fake-mp3")
    return audio_dir


def _scoring_result(
    with_whisper: bool = False, timed_out: bool = False,
) -> SongScores:
    """A finished scoring run: emotional_dynamics always, text_accuracy on
    request, and optionally a scorer that blew its budget."""
    from songmaker_cli.api_models.whisper import WhisperCue

    runs = [ScorerRun(scorer="emotional_dynamics", outcome=ScorerOutcome.OK)]
    if timed_out:
        runs.append(ScorerRun(scorer="text_accuracy", outcome=ScorerOutcome.TIMED_OUT))
    text_accuracy = None
    if with_whisper:
        text_accuracy = TextAccuracyScore(
            similarity_ratio=0.9,
            intended_line_texts=("hello", "world"),
            transcribed_line_texts=("hello", "world"),
            whisper_cues=(
                WhisperCue(start=0.0, end=0.8, text="hello"),
                WhisperCue(start=0.8, end=1.6, text="world"),
            ),
        )
        runs.append(ScorerRun(scorer="text_accuracy", outcome=ScorerOutcome.OK))

    return SongScores(
        emotional_dynamics=EmotionalDynamicsScore(
            pitch_cv=0.3, rms_contrast=2.0, onset_rate_cv=0.2,
            overall_expressiveness=0.55,
        ),
        text_accuracy=text_accuracy,
        runs=tuple(runs),
    )


@pytest.fixture()
def live_scorer_process():
    """A really spawned scorer child. Each test stubs the scoring call itself
    — the child's pid is the evidence here, not the scores."""
    from songmaker_cli.scoring.subprocess_runner import ScorerProcess

    process = ScorerProcess()
    process._ensure_started()
    yield process
    process.shutdown()


def test_scoring_job_recycles_the_child_a_scorer_was_left_running_in(
    seeded_db, tmp_path: Path, live_scorer_process, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scorer over budget is abandoned, not stopped — it keeps holding the
    child's models and GPU memory. This run's values are kept; the child is
    not, so nothing of it outlives the request."""
    _seed_generation(seeded_db)
    audio_dir = _audio_dir_with_mp3(tmp_path)
    pid_before = live_scorer_process._process.pid
    monkeypatch.setattr(
        live_scorer_process, "score",
        lambda *_args, **_kwargs: _scoring_result(timed_out=True),
    )

    with patch(
        "songmaker_cli.jobs.get_scorer_process", return_value=live_scorer_process,
    ):
        run_scoring_job("j2", "g1", None, db_factory=seeded_db, audio_dir=audio_dir)

    with seeded_db() as session:
        assert get_job(session, "j2").status == "completed"
        stored = session.query(Score).filter_by(generation_id="g1").one()
        assert stored.value["dynamics"] == 55.0

    with pytest.raises(OSError):
        os.kill(pid_before, 0)
    live_scorer_process._ensure_started()
    assert live_scorer_process._process.pid != pid_before


def test_scoring_job_keeps_the_child_when_every_scorer_stayed_in_budget(
    seeded_db, tmp_path: Path, live_scorer_process, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_generation(seeded_db)
    audio_dir = _audio_dir_with_mp3(tmp_path)
    pid_before = live_scorer_process._process.pid
    monkeypatch.setattr(
        live_scorer_process, "score", lambda *_args, **_kwargs: _scoring_result(),
    )

    with patch(
        "songmaker_cli.jobs.get_scorer_process", return_value=live_scorer_process,
    ):
        run_scoring_job("j2", "g1", None, db_factory=seeded_db, audio_dir=audio_dir)

    assert live_scorer_process.alive
    assert live_scorer_process._process.pid == pid_before


def test_a_cancelled_job_still_keeps_its_tainted_child_out_of_the_next_request(
    seeded_db, tmp_path: Path, live_scorer_process,
) -> None:
    """A job cancelled while scoring returns before it can recycle anything.
    The child it left a scorer running in must still not serve the next
    request — ScorerProcess refuses to hand it out."""
    from songmaker_cli.scoring.pipeline import PipelineConfig
    from songmaker_cli.scoring.subprocess_runner import ScorerProcess

    _seed_generation(seeded_db)
    audio_dir = _audio_dir_with_mp3(tmp_path)
    pid_before = live_scorer_process._process.pid

    def _cancel_and_report_a_timeout(*_args, **_kwargs) -> SongScores:
        _cancel_job(seeded_db, "j2")
        return _scoring_result(timed_out=True)

    with (
        patch(
            "songmaker_cli.jobs.get_scorer_process", return_value=live_scorer_process,
        ),
        patch.object(
            ScorerProcess, "_poll_response", side_effect=_cancel_and_report_a_timeout,
        ),
    ):
        run_scoring_job("j2", "g1", None, db_factory=seeded_db, audio_dir=audio_dir)

    with seeded_db() as session:
        assert get_job(session, "j2").status == "cancelled"
    assert live_scorer_process._process.pid == pid_before, (
        "the cancelled job returned before it could recycle anything"
    )

    live_scorer_process.score(
        audio_dir / "user1" / "g1.mp3", scorers=[], config=PipelineConfig(device="cpu"),
    )

    assert live_scorer_process._process.pid != pid_before


def test_scoring_job_keeps_the_child_when_only_the_parents_judge_timed_out(
    seeded_db, tmp_path: Path, live_scorer_process, monkeypatch: pytest.MonkeyPatch,
    stubbed_claude_judge, caplog: pytest.LogCaptureFixture,
) -> None:
    """The coherence judge runs here, not in the child. When it blows its
    budget the abandoned thread is this process's problem — killing the child
    would reclaim nothing, so it keeps running."""
    import logging
    import time

    monkeypatch.setenv("SCORER_TIMEOUT_SECONDS", "1")
    stubbed_claude_judge.side_effect = lambda *_args, **_kwargs: time.sleep(2)
    _seed_generation(seeded_db)
    audio_dir = _audio_dir_with_mp3(tmp_path)
    pid_before = live_scorer_process._process.pid
    monkeypatch.setattr(
        live_scorer_process, "score",
        lambda *_args, **_kwargs: _scoring_result(with_whisper=True),
    )

    with (
        caplog.at_level(logging.INFO),
        patch(
            "songmaker_cli.jobs.get_scorer_process", return_value=live_scorer_process,
        ),
    ):
        run_scoring_job("j2", "g1", None, db_factory=seeded_db, audio_dir=audio_dir)

    assert "lyrical_coherence=timed_out" in caplog.text
    assert live_scorer_process.alive
    assert live_scorer_process._process.pid == pid_before


def test_scoring_job_happy_path(seeded_db, tmp_path: Path) -> None:
    _seed_generation(seeded_db)
    audio_dir = _audio_dir_with_mp3(tmp_path)

    mock_result = _scoring_result()

    with (
        patch(
            "songmaker_cli.jobs.get_scorer_process",
            return_value=MagicMock(score=MagicMock(return_value=mock_result)),
        ),
    ):
        run_scoring_job("j2", "g1", None, db_factory=seeded_db, audio_dir=audio_dir)

    with seeded_db() as session:
        job = get_job(session, "j2")
        assert job.status == "completed"
        scores = session.query(Score).filter_by(generation_id="g1").all()
        assert len(scores) == 1
        assert scores[0].value["dynamics"] == 55.0
        gen = get_generation(session, "g1")
        assert gen.whisper_text is None
        assert gen.whisper_cues is None


def test_scoring_job_judges_coherence_here_and_sends_no_secret_to_the_child(
    seeded_db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scorer child is spawned with ANTHROPIC_API_KEY scrubbed and loads
    third-party model weights, so the key must not cross the pipe at all:
    this process judges coherence itself, on the result the child returned.
    """
    from pydantic import SecretStr

    monkeypatch.setenv("ANTHROPIC_API_KEY", "parent-resolved-key")
    _seed_generation(seeded_db)
    audio_dir = _audio_dir_with_mp3(tmp_path)

    captured: dict = {}

    def _capture_score(mp3_path, meta=None, scorers=None, config=None,
                       job_id=None, on_progress=None):
        captured["child_config"] = config
        return _scoring_result(with_whisper=True)

    def _capture_judge(scores, meta, config):
        captured["judged"] = scores
        captured["judge_config"] = config
        return scores

    with (
        patch(
            "songmaker_cli.jobs.get_scorer_process",
            return_value=MagicMock(score=_capture_score),
        ),
        patch("songmaker_cli.jobs.scoring.judge_lyrical_coherence", _capture_judge),
    ):
        run_scoring_job("j2", "g1", None, db_factory=seeded_db, audio_dir=audio_dir)

    assert captured["judge_config"].api_key == SecretStr("parent-resolved-key")
    assert captured["judged"].text_accuracy is not None
    assert not any(
        isinstance(value, SecretStr) for value in vars(captured["child_config"]).values()
    )


def test_scoring_job_never_asks_the_child_for_the_parent_hosted_scorer(
    seeded_db, tmp_path: Path,
) -> None:
    _seed_generation(seeded_db)
    audio_dir = _audio_dir_with_mp3(tmp_path)

    captured: dict = {}

    def _capture_score(mp3_path, meta=None, scorers=None, config=None,
                       job_id=None, on_progress=None):
        captured["scorers"] = scorers
        return _scoring_result()

    with (
        patch(
            "songmaker_cli.jobs.get_scorer_process",
            return_value=MagicMock(score=_capture_score),
        ),
        patch(
            "songmaker_cli.jobs.scoring.judge_lyrical_coherence",
            side_effect=lambda scores, meta, config: scores,
        ) as judge,
    ):
        run_scoring_job(
            "j2", "g1", ["silence", "lyrical_coherence"],
            db_factory=seeded_db, audio_dir=audio_dir,
        )

    assert captured["scorers"] == ["silence"]
    judge.assert_called_once()


def test_scoring_job_skips_the_judge_when_coherence_was_not_requested(
    seeded_db, tmp_path: Path,
) -> None:
    _seed_generation(seeded_db)
    audio_dir = _audio_dir_with_mp3(tmp_path)

    with (
        patch(
            "songmaker_cli.jobs.get_scorer_process",
            return_value=MagicMock(score=MagicMock(return_value=_scoring_result())),
        ),
        patch("songmaker_cli.jobs.scoring.judge_lyrical_coherence") as judge,
    ):
        run_scoring_job(
            "j2", "g1", ["silence"], db_factory=seeded_db, audio_dir=audio_dir,
        )

    judge.assert_not_called()


def test_scoring_job_saves_whisper_text(seeded_db, tmp_path: Path) -> None:
    _seed_generation(seeded_db)
    audio_dir = _audio_dir_with_mp3(tmp_path)

    mock_result = _scoring_result(with_whisper=True)

    with (
        patch(
            "songmaker_cli.jobs.get_scorer_process",
            return_value=MagicMock(score=MagicMock(return_value=mock_result)),
        ),
    ):
        run_scoring_job("j2", "g1", None, db_factory=seeded_db, audio_dir=audio_dir)

    with seeded_db() as session:
        gen = get_generation(session, "g1")
        assert gen.whisper_text == mock_result.text_accuracy.transcript
        assert gen.whisper_text == "hello\nworld"
        assert gen.whisper_cues == [
            {"start": 0.0, "end": 0.8, "text": "hello"},
            {"start": 0.8, "end": 1.6, "text": "world"},
        ]


def test_scoring_job_uses_generation_version_not_latest(
    seeded_db, tmp_path: Path,
) -> None:
    """Meta must come from the version this generation was produced with,
    not from the song's latest_version (which may have been edited since).
    Vocal language must propagate so Whisper can skip auto-detect."""
    audio_dir = tmp_path / "audio"
    mp3_file = audio_dir / "user1" / "g1.mp3"
    mp3_file.parent.mkdir(parents=True, exist_ok=True)
    mp3_file.write_bytes(b"fake-mp3")

    with seeded_db() as session:
        session.add(Version(
            id="v2", song_id="s1", version_number=2,
            lyrics="Brand new lyrics", prompt="new prompt",
            bpm=140, audio_duration=60, key_scale="Cm",
        ))
        session.add(Generation(
            id="g1", song_id="s1", version_id="v1", generation_number=1,
            mp3_path="user1/g1.mp3", seed=42,
        ))
        session.commit()

    captured: dict = {}

    def _capture_score(mp3_path, meta=None, scorers=None, config=None,
                       job_id=None, on_progress=None):
        captured["meta"] = meta
        return _scoring_result(with_whisper=True)

    with patch(
        "songmaker_cli.jobs.get_scorer_process",
        return_value=MagicMock(score=_capture_score),
    ):
        run_scoring_job("j2", "g1", None, db_factory=seeded_db, audio_dir=audio_dir)

    meta = captured["meta"]
    assert meta is not None
    assert meta.lyrics == "Hello world"
    assert meta.prompt == "rock style"
    assert meta.vocal_language == "en"


def test_scoring_job_no_version_still_scores(seeded_db, tmp_path: Path) -> None:
    """Generations with a deleted/null version still get scored — meta is
    minimal but text_accuracy can still transcribe."""
    audio_dir = tmp_path / "audio"
    mp3_file = audio_dir / "user1" / "g1.mp3"
    mp3_file.parent.mkdir(parents=True, exist_ok=True)
    mp3_file.write_bytes(b"fake-mp3")

    with seeded_db() as session:
        session.add(Generation(
            id="g1", song_id="s1", version_id=None, generation_number=1,
            mp3_path="user1/g1.mp3", seed=42,
        ))
        session.commit()

    captured: dict = {}

    def _capture_score(mp3_path, meta=None, scorers=None, config=None,
                       job_id=None, on_progress=None):
        captured["meta"] = meta
        return _scoring_result(with_whisper=True)

    with patch(
        "songmaker_cli.jobs.get_scorer_process",
        return_value=MagicMock(score=_capture_score),
    ):
        run_scoring_job("j2", "g1", None, db_factory=seeded_db, audio_dir=audio_dir)

    with seeded_db() as session:
        job = get_job(session, "j2")
        assert job.status == "completed"
        gen = get_generation(session, "g1")
        assert gen.whisper_text == "hello\nworld"
        assert gen.whisper_cues == [
            {"start": 0.0, "end": 0.8, "text": "hello"},
            {"start": 0.8, "end": 1.6, "text": "world"},
        ]

    meta = captured["meta"]
    assert meta is not None
    assert meta.lyrics == ""
    assert meta.vocal_language == "en"


def test_scoring_job_uses_configured_per_scorer_budgets(
    seeded_db, tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("SCORER_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("TEXT_ACCURACY_TIMEOUT_SECONDS", "600")

    _seed_generation(seeded_db)
    audio_dir = _audio_dir_with_mp3(tmp_path)

    captured: dict = {}

    def _capture_score(mp3_path, meta=None, scorers=None, config=None,
                       job_id=None, on_progress=None):
        captured["config"] = config
        return _scoring_result()

    with patch(
        "songmaker_cli.jobs.get_scorer_process",
        return_value=MagicMock(score=_capture_score),
    ):
        run_scoring_job("j2", "g1", None, db_factory=seeded_db, audio_dir=audio_dir)

    config = captured["config"]
    assert config.timeout_for("text_accuracy") == 600
    assert config.timeout_for("silence") == 45
    assert config.pipeline_timeout > 600


def test_scoring_job_generation_not_found(seeded_db) -> None:
    run_scoring_job(
        "j2", "nonexistent", None, db_factory=seeded_db, audio_dir=Path("/tmp/audio"),
    )

    with seeded_db() as session:
        job = get_job(session, "j2")
        assert job.status == "failed"
        assert "Generation not found" in job.error


def test_scoring_job_mp3_not_found(seeded_db, tmp_path: Path) -> None:
    with seeded_db() as session:
        session.add(Generation(
            id="g1", song_id="s1", version_id="v1", generation_number=1,
            mp3_path="user1/missing.mp3", seed=42,
        ))
        session.commit()

    run_scoring_job("j2", "g1", None, db_factory=seeded_db, audio_dir=tmp_path / "audio")

    with seeded_db() as session:
        job = get_job(session, "j2")
        assert job.status == "failed"
        assert job.error == "Audio file not found for scoring"


def test_scoring_job_queued_cancel_prevents_execution(seeded_db, tmp_path: Path) -> None:
    _seed_generation(seeded_db)
    audio_dir = _audio_dir_with_mp3(tmp_path)

    _cancel_job(seeded_db, "j2")
    scorer = MagicMock(score=MagicMock(return_value=_scoring_result()))
    with patch("songmaker_cli.jobs.get_scorer_process", return_value=scorer):
        run_scoring_job("j2", "g1", None, db_factory=seeded_db, audio_dir=audio_dir)

    scorer.score.assert_not_called()
    with seeded_db() as session:
        job = get_job(session, "j2")
        assert job.status == "cancelled"
        assert job.completed_at is not None
        assert session.query(Score).filter_by(generation_id="g1").count() == 0


def test_scoring_job_cancel_during_run_skips_finalize(seeded_db, tmp_path: Path) -> None:
    _seed_generation(seeded_db)
    audio_dir = _audio_dir_with_mp3(tmp_path)

    def _score_and_cancel(mp3_path, meta=None, scorers=None, config=None,
                          job_id=None, on_progress=None):
        if on_progress:
            on_progress(1, 2, "silence")
        _cancel_job(seeded_db, "j2")
        if on_progress:
            on_progress(2, 2, "silence")
        return _scoring_result()

    with patch(
        "songmaker_cli.jobs.get_scorer_process",
        return_value=MagicMock(score=_score_and_cancel),
    ):
        run_scoring_job("j2", "g1", None, db_factory=seeded_db, audio_dir=audio_dir)

    with seeded_db() as session:
        job = get_job(session, "j2")
        assert job.status == "cancelled"
        assert job.completed_at is not None
        assert session.query(Score).filter_by(generation_id="g1").count() == 0


def test_scoring_job_exception(seeded_db, tmp_path: Path) -> None:
    _seed_generation(seeded_db)
    audio_dir = _audio_dir_with_mp3(tmp_path)

    with (
        patch(
            "songmaker_cli.jobs.get_scorer_process",
            return_value=MagicMock(
                score=MagicMock(side_effect=RuntimeError("scorer crash")),
            ),
        ),
    ):
        run_scoring_job("j2", "g1", None, db_factory=seeded_db, audio_dir=audio_dir)

    with seeded_db() as session:
        job = get_job(session, "j2")
        assert job.status == "failed"
        assert job.error == "Internal error during processing"


# ── Job metrics queries ──────────────────────────────────────────


def test_job_counts_by_type_and_status(db_factory) -> None:
    from songmaker_cli.db.queries import job_counts_by_type_and_status

    with db_factory() as session:
        session.add(Job(type="generate", status="completed"))
        session.add(Job(type="generate", status="completed"))
        session.add(Job(type="generate", status="failed"))
        session.add(Job(type="score", status="completed"))
        session.commit()

    with db_factory() as session:
        counts = job_counts_by_type_and_status(session)
    assert counts["generate"]["completed"] == 2
    assert counts["generate"]["failed"] == 1
    assert counts["score"]["completed"] == 1


def test_job_counts_empty_db(db_factory) -> None:
    from songmaker_cli.db.queries import job_counts_by_type_and_status

    with db_factory() as session:
        counts = job_counts_by_type_and_status(session)
    assert counts == {}


def test_job_duration_stats(db_factory) -> None:
    from datetime import datetime, timedelta, timezone

    from songmaker_cli.db.queries import job_duration_stats

    now = datetime.now(timezone.utc)
    with db_factory() as session:
        j1 = Job(type="generate", status="completed")
        j1.started_at = now - timedelta(seconds=10)
        j1.completed_at = now
        session.add(j1)
        j2 = Job(type="generate", status="completed")
        j2.started_at = now - timedelta(seconds=20)
        j2.completed_at = now
        session.add(j2)
        session.commit()

    with db_factory() as session:
        stats = job_duration_stats(session)
    assert stats.avg is not None
    assert stats.min is not None
    assert stats.max is not None
    assert stats.min <= stats.avg <= stats.max


def test_job_duration_stats_no_completed(db_factory) -> None:
    from songmaker_cli.db.queries import job_duration_stats

    with db_factory() as session:
        session.add(Job(type="generate", status="running"))
        session.commit()

    with db_factory() as session:
        stats = job_duration_stats(session)
    assert stats.avg is None
    assert stats.min is None
    assert stats.max is None


# ── _apply_task_overrides ──────────────────────────────────────────


def test_repaint_converts_fractions_to_seconds(tmp_path: Path) -> None:
    from songmaker_cli.parser import AlbumMeta, SongMeta

    src_wav = tmp_path / "src.wav"
    src_wav.write_bytes(b"RIFF" + b"\x00" * 40)

    config = AceStepConfig(prompt="test", lyrics="la la", audio_duration=180)
    ctx = GenerationContext(
        song_id="s1", version_id="v1",
        meta=SongMeta(title="t", lyrics="la la", prompt="test"),
        album_meta=AlbumMeta(title="a", artist="b"),
        ace_config=config, audio_dir=tmp_path, user_id="u1",
        model_name="turbo",
    )
    params = RepaintTaskParams(
        src_wav_path=str(src_wav),
        src_generation_id="g0",
        repainting_start=0.3,
        repainting_end=0.8,
        lyrics="la la",
        prompt="test",
    )
    result = _apply_repaint_overrides(ctx, params)
    assert result.ace_config.repainting_start == pytest.approx(54.0)
    assert result.ace_config.repainting_end == pytest.approx(144.0)
    assert result.ace_config.task_type == "repaint"
    assert result.ace_config.thinking is True
    assert result.ace_config.src_audio_path.startswith(str(tmp_path / ".tmp"))
    assert Path(result.ace_config.src_audio_path).exists()
    assert result.src_generation_id == "g0"


def test_repaint_inherits_generation_settings(tmp_path: Path) -> None:
    from songmaker_cli.parser import AlbumMeta, SongMeta

    src_wav = tmp_path / "src.wav"
    src_wav.write_bytes(b"RIFF" + b"\x00" * 40)

    config = AceStepConfig(
        prompt="test", lyrics="la la", audio_duration=120,
        guidance_scale=5.0, inference_steps=50, shift=2.0, thinking=True,
    )
    ctx = GenerationContext(
        song_id="s1", version_id="v1",
        meta=SongMeta(title="t", lyrics="la la", prompt="test"),
        album_meta=AlbumMeta(title="a", artist="b"),
        ace_config=config, audio_dir=tmp_path, user_id="u1",
        model_name="sft",
    )
    params = RepaintTaskParams(
        src_wav_path=str(src_wav),
        src_generation_id="g0",
        repainting_start=0.1,
        repainting_end=0.3,
        lyrics="la la",
        prompt="test",
    )
    result = _apply_repaint_overrides(ctx, params)
    assert result.ace_config.guidance_scale == 5.0
    assert result.ace_config.inference_steps == 50
    assert result.ace_config.shift == 2.0
    assert result.ace_config.thinking is True


def test_cover_does_not_convert_fractions(tmp_path: Path) -> None:
    from songmaker_cli.parser import AlbumMeta, SongMeta

    src_wav = tmp_path / "src.wav"
    src_wav.write_bytes(b"RIFF" + b"\x00" * 40)

    config = AceStepConfig(prompt="test", lyrics="la la", audio_duration=180)
    ctx = GenerationContext(
        song_id="s1", version_id="v1",
        meta=SongMeta(title="t", lyrics="la la", prompt="test"),
        album_meta=AlbumMeta(title="a", artist="b"),
        ace_config=config, audio_dir=tmp_path, user_id="u1",
        model_name="turbo",
    )
    params = CoverTaskParams(
        src_wav_path=str(src_wav),
        src_generation_id="g0",
        audio_cover_strength=0.7,
        lyrics="la la",
        prompt="test",
    )
    result = _apply_cover_overrides(ctx, params)
    assert result.ace_config.audio_cover_strength == 0.7
    assert result.ace_config.task_type == "cover"
    assert result.ace_config.src_audio_path.startswith(str(tmp_path / ".tmp"))


# ── load_model_on_worker ────────────────────────────────────────────


def _seed_worker_row(factory, worker_id: str = "w1") -> None:
    from songmaker_cli.db.queries import register_worker

    with factory() as session:
        register_worker(
            session,
            worker_id=worker_id,
            host="acestep-worker",
            port=8001,
            gpu_id=0,
            vram_total_gb=24.0,
        )
        session.add(Job(id=f"{worker_id}-job", type="load_model_on_worker", status="queued"))
        session.commit()


def _run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


def test_load_model_on_worker_success(seeded_db) -> None:
    from unittest.mock import AsyncMock

    from songmaker_cli.jobs import load_model_on_worker

    _seed_worker_row(seeded_db)
    fake_response = MagicMock(status_code=200, text="ok")
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("httpx.AsyncClient", return_value=fake_client),
    ):
        _run(load_model_on_worker({}, "w1-job", "w1", "sft", db_factory=seeded_db))

    with seeded_db() as session:
        job = get_job(session, "w1-job")
        assert job.status == "completed"
        assert job.progress == 1.0
    fake_client.post.assert_called_once()
    args, kwargs = fake_client.post.call_args
    assert args[0] == "http://acestep-worker:8001/load_model"
    assert kwargs["json"] == {"mode": "sft"}


def test_load_model_on_worker_unknown_worker(seeded_db) -> None:
    from songmaker_cli.jobs import load_model_on_worker

    with seeded_db() as session:
        session.add(Job(id="job1", type="load_model_on_worker", status="queued"))
        session.commit()

    _run(load_model_on_worker({}, "job1", "missing", "sft", db_factory=seeded_db))

    with seeded_db() as session:
        job = get_job(session, "job1")
        assert job.status == "failed"
        assert "not registered" in job.error
        assert job.error_type == "worker_missing"


def test_load_model_on_worker_unreachable(seeded_db) -> None:
    from unittest.mock import AsyncMock

    import httpx

    from songmaker_cli.jobs import load_model_on_worker

    _seed_worker_row(seeded_db)
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("httpx.AsyncClient", return_value=fake_client),
    ):
        _run(load_model_on_worker({}, "w1-job", "w1", "sft", db_factory=seeded_db))

    with seeded_db() as session:
        job = get_job(session, "w1-job")
        assert job.status == "failed"
        assert job.error_type == "worker_unreachable"


def test_load_model_on_worker_returns_5xx(seeded_db) -> None:
    from unittest.mock import AsyncMock

    from songmaker_cli.jobs import load_model_on_worker

    _seed_worker_row(seeded_db)
    fake_response = MagicMock(status_code=500, text="boom")
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("httpx.AsyncClient", return_value=fake_client),
    ):
        _run(load_model_on_worker({}, "w1-job", "w1", "sft", db_factory=seeded_db))

    with seeded_db() as session:
        job = get_job(session, "w1-job")
        assert job.status == "failed"
        assert job.error_type == "worker_error"
        assert "500" in job.error


def test_load_model_on_worker_5xx_includes_long_tail(seeded_db) -> None:
    """502 from the worker carries the ACE-Step subprocess tail; we want
    enough of it to be useful (4000 chars), not 200."""
    from unittest.mock import AsyncMock

    from songmaker_cli.jobs import load_model_on_worker

    _seed_worker_row(seeded_db)
    long_tail = (
        "ACE-Step did not become healthy within 900s\n"
        "--- last log lines ---\n"
        + ("vllm: loading shard 2/4\n" * 50)
    )
    fake_response = MagicMock(status_code=502, text=long_tail)
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=fake_client):
        _run(load_model_on_worker({}, "w1-job", "w1", "sft", db_factory=seeded_db))

    with seeded_db() as session:
        job = get_job(session, "w1-job")
        assert job.status == "failed"
        assert "did not become healthy" in job.error
        assert job.error.count("loading shard 2/4") >= 30


# ── download_model_on_worker ────────────────────────────────────────


def _seed_download_job(factory, job_id: str = "dl-job") -> None:
    with factory() as session:
        session.add(Job(id=job_id, type="download_model_on_worker", status="queued"))
        session.commit()


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value if isinstance(value, str) else str(value)
        return True

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)


def _seed_online_worker(factory, redis: _FakeRedis, worker_id: str = "w1") -> None:
    import json

    from songmaker_cli.acestep_state import worker_state_key
    from songmaker_cli.db.queries import register_worker

    with factory() as session:
        register_worker(
            session,
            worker_id=worker_id,
            host="acestep-worker",
            port=8001,
            gpu_id=0,
            vram_total_gb=24.0,
        )
        session.commit()
    redis.store[worker_state_key(worker_id)] = json.dumps({"loaded": []})


def test_download_model_on_worker_unknown_mode(seeded_db) -> None:
    from songmaker_cli.jobs import download_model_on_worker

    _seed_download_job(seeded_db, "dl1")
    redis = _FakeRedis()
    _run(download_model_on_worker({"redis": redis}, "dl1", "ghost", db_factory=seeded_db))

    with seeded_db() as session:
        job = get_job(session, "dl1")
        assert job.status == "failed"
        assert job.error_type == "invalid_mode"


def test_download_model_on_worker_no_online_workers(seeded_db) -> None:
    from songmaker_cli.jobs import download_model_on_worker

    _seed_download_job(seeded_db, "dl2")
    redis = _FakeRedis()
    _run(download_model_on_worker({"redis": redis}, "dl2", "sft", db_factory=seeded_db))

    with seeded_db() as session:
        job = get_job(session, "dl2")
        assert job.status == "failed"
        assert job.error_type == "no_workers"


def test_download_model_on_worker_unreachable(seeded_db) -> None:
    from unittest.mock import AsyncMock

    import httpx

    from songmaker_cli.jobs import download_model_on_worker

    _seed_download_job(seeded_db, "dl3")
    redis = _FakeRedis()
    _seed_online_worker(seeded_db, redis)

    fake_client = AsyncMock()
    fake_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("httpx.AsyncClient", return_value=fake_client),
    ):
        _run(download_model_on_worker({"redis": redis}, "dl3", "sft", db_factory=seeded_db))

    with seeded_db() as session:
        job = get_job(session, "dl3")
        assert job.status == "failed"
        assert job.error_type == "worker_unreachable"


def test_download_model_on_worker_returns_5xx(seeded_db) -> None:
    from unittest.mock import AsyncMock

    from songmaker_cli.jobs import download_model_on_worker

    _seed_download_job(seeded_db, "dl4")
    redis = _FakeRedis()
    _seed_online_worker(seeded_db, redis)

    fake_response = MagicMock(status_code=500, text="boom")
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("httpx.AsyncClient", return_value=fake_client),
    ):
        _run(download_model_on_worker({"redis": redis}, "dl4", "sft", db_factory=seeded_db))

    with seeded_db() as session:
        job = get_job(session, "dl4")
        assert job.status == "failed"
        assert job.error_type == "worker_error"


def test_download_model_on_worker_happy_path(seeded_db) -> None:
    from unittest.mock import AsyncMock

    from songmaker_cli.jobs import download_model_on_worker
    from songmaker_cli.scheduler import DownloadTaskResultDTO

    _seed_download_job(seeded_db, "dl5")
    redis = _FakeRedis()
    _seed_online_worker(seeded_db, redis)

    fake_submit_response = MagicMock(status_code=200)
    fake_submit_response.json = MagicMock(return_value={"task_id": "task-123"})
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_submit_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    progress_calls: list[float] = []

    async def fake_consume(worker, task_id, *, on_progress, on_heartbeat, options):
        for f in (0.25, 0.5, 0.75):
            on_progress(f)
            progress_calls.append(f)
        return DownloadTaskResultDTO(mode="sft", size_bytes=12345)

    with (
        patch("httpx.AsyncClient", return_value=fake_client),
        patch("songmaker_cli.scheduler.consume_download_task_stream", new=fake_consume),
    ):
        _run(download_model_on_worker({"redis": redis}, "dl5", "sft", db_factory=seeded_db))

    with seeded_db() as session:
        job = get_job(session, "dl5")
        assert job.status == "completed"
        assert job.progress == 1.0
    assert progress_calls == [0.25, 0.5, 0.75]
    fake_client.post.assert_called_once()
    args, kwargs = fake_client.post.call_args
    assert args[0].endswith("/download_model")
    assert kwargs["json"] == {"mode": "sft"}


async def _instant_sleep(_seconds: float) -> None:
    return None


def test_download_model_on_worker_sse_error(seeded_db) -> None:
    from unittest.mock import AsyncMock

    from songmaker_cli.jobs import download_model_on_worker
    from songmaker_cli.scheduler import WorkerTaskFailed

    _seed_download_job(seeded_db, "dl6")
    redis = _FakeRedis()
    _seed_online_worker(seeded_db, redis)

    fake_submit_response = MagicMock(status_code=200)
    fake_submit_response.json = MagicMock(return_value={"task_id": "task-x"})
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_submit_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    consume_calls = {"count": 0}

    async def failing_consume(*args, **kwargs):
        consume_calls["count"] += 1
        raise WorkerTaskFailed("HF 401 unauthorized")

    with (
        patch("httpx.AsyncClient", return_value=fake_client),
        patch(
            "songmaker_cli.scheduler.consume_download_task_stream",
            new=failing_consume,
        ),
        patch("songmaker_cli.jobs.asyncio.sleep", new=_instant_sleep),
    ):
        _run(download_model_on_worker({"redis": redis}, "dl6", "sft", db_factory=seeded_db))

    with seeded_db() as session:
        job = get_job(session, "dl6")
        assert job.status == "failed"
        assert job.error_type == "download_error"
        assert "HF 401" in job.error
    assert consume_calls["count"] == 3


def test_download_model_on_worker_sse_transport_error(seeded_db) -> None:
    from unittest.mock import AsyncMock

    import httpx

    from songmaker_cli.jobs import download_model_on_worker

    _seed_download_job(seeded_db, "dl7")
    redis = _FakeRedis()
    _seed_online_worker(seeded_db, redis)

    fake_submit_response = MagicMock(status_code=200)
    fake_submit_response.json = MagicMock(return_value={"task_id": "task-y"})
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_submit_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    async def transport_drop(*args, **kwargs):
        raise httpx.ConnectError("dropped")

    with (
        patch("httpx.AsyncClient", return_value=fake_client),
        patch(
            "songmaker_cli.scheduler.consume_download_task_stream",
            new=transport_drop,
        ),
    ):
        _run(download_model_on_worker({"redis": redis}, "dl7", "sft", db_factory=seeded_db))

    with seeded_db() as session:
        job = get_job(session, "dl7")
        assert job.status == "failed"
        assert job.error_type == "sse_transport"


def test_download_model_on_worker_clears_redis_flag_on_success(seeded_db) -> None:
    from unittest.mock import AsyncMock

    from songmaker_cli.acestep_state import download_key
    from songmaker_cli.jobs import download_model_on_worker
    from songmaker_cli.scheduler import DownloadTaskResultDTO

    _seed_download_job(seeded_db, "dl8")
    redis = _FakeRedis()
    _seed_online_worker(seeded_db, redis)

    fake_submit_response = MagicMock(status_code=200)
    fake_submit_response.json = MagicMock(return_value={"task_id": "task-z"})
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_submit_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    async def fake_consume(*args, **kwargs):
        return DownloadTaskResultDTO(mode="sft", size_bytes=1)

    with (
        patch("httpx.AsyncClient", return_value=fake_client),
        patch("songmaker_cli.scheduler.consume_download_task_stream", new=fake_consume),
    ):
        _run(download_model_on_worker({"redis": redis}, "dl8", "sft", db_factory=seeded_db))

    assert download_key("sft") not in redis.store


def test_download_model_on_worker_clears_redis_flag_on_failure(seeded_db) -> None:
    from songmaker_cli.acestep_state import download_key
    from songmaker_cli.jobs import download_model_on_worker

    _seed_download_job(seeded_db, "dl9")
    redis = _FakeRedis()

    _run(download_model_on_worker({"redis": redis}, "dl9", "sft", db_factory=seeded_db))

    assert download_key("sft") not in redis.store


def test_download_model_on_worker_aborts_when_flag_already_set(seeded_db) -> None:
    from songmaker_cli.acestep_state import download_key
    from songmaker_cli.jobs import download_model_on_worker

    _seed_download_job(seeded_db, "dl10")
    redis = _FakeRedis()
    redis.store[download_key("sft")] = "previous-job"

    _run(download_model_on_worker({"redis": redis}, "dl10", "sft", db_factory=seeded_db))

    with seeded_db() as session:
        job = get_job(session, "dl10")
        assert job.status == "failed"
        assert job.error_type == "duplicate_download"
        assert "previous-job" in job.error
    assert redis.store[download_key("sft")] == "previous-job"


# ── D9: download retry tests ────────────────────────────────────────


def test_download_retries_on_worker_task_failed_then_succeeds(seeded_db) -> None:
    from unittest.mock import AsyncMock

    from songmaker_cli.jobs import download_model_on_worker
    from songmaker_cli.scheduler import DownloadTaskResultDTO, WorkerTaskFailed

    _seed_download_job(seeded_db, "dl-retry-1")
    redis = _FakeRedis()
    _seed_online_worker(seeded_db, redis)

    fake_submit_response = MagicMock(status_code=200)
    fake_submit_response.json = MagicMock(return_value={"task_id": "t"})
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_submit_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    consume_calls = {"count": 0}

    async def flaky_consume(*args, **kwargs):
        consume_calls["count"] += 1
        if consume_calls["count"] == 1:
            raise WorkerTaskFailed("HF rate limit 429")
        return DownloadTaskResultDTO(mode="sft", size_bytes=1)

    with (
        patch("httpx.AsyncClient", return_value=fake_client),
        patch(
            "songmaker_cli.scheduler.consume_download_task_stream",
            new=flaky_consume,
        ),
        patch("songmaker_cli.jobs.asyncio.sleep", new=_instant_sleep),
    ):
        _run(download_model_on_worker({"redis": redis}, "dl-retry-1", "sft", db_factory=seeded_db))

    with seeded_db() as session:
        job = get_job(session, "dl-retry-1")
        assert job.status == "completed"
        assert job.progress == 1.0
    assert consume_calls["count"] == 2


def test_download_retries_on_sse_drop_then_succeeds(seeded_db) -> None:
    from unittest.mock import AsyncMock

    import httpx

    from songmaker_cli.jobs import download_model_on_worker
    from songmaker_cli.scheduler import DownloadTaskResultDTO

    _seed_download_job(seeded_db, "dl-retry-2")
    redis = _FakeRedis()
    _seed_online_worker(seeded_db, redis)

    fake_submit_response = MagicMock(status_code=200)
    fake_submit_response.json = MagicMock(return_value={"task_id": "t"})
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_submit_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    consume_calls = {"count": 0}

    async def flaky_consume(*args, **kwargs):
        consume_calls["count"] += 1
        if consume_calls["count"] == 1:
            raise httpx.ReadError("dropped")
        return DownloadTaskResultDTO(mode="sft", size_bytes=1)

    with (
        patch("httpx.AsyncClient", return_value=fake_client),
        patch(
            "songmaker_cli.scheduler.consume_download_task_stream",
            new=flaky_consume,
        ),
        patch("songmaker_cli.jobs.asyncio.sleep", new=_instant_sleep),
    ):
        _run(download_model_on_worker({"redis": redis}, "dl-retry-2", "sft", db_factory=seeded_db))

    with seeded_db() as session:
        job = get_job(session, "dl-retry-2")
        assert job.status == "completed"
    assert consume_calls["count"] == 2


def test_download_does_not_retry_on_connect_error(seeded_db) -> None:
    from unittest.mock import AsyncMock

    import httpx

    from songmaker_cli.jobs import download_model_on_worker

    _seed_download_job(seeded_db, "dl-noretry")
    redis = _FakeRedis()
    _seed_online_worker(seeded_db, redis)

    fake_submit_response = MagicMock(status_code=200)
    fake_submit_response.json = MagicMock(return_value={"task_id": "t"})
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_submit_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    consume_calls = {"count": 0}

    async def connect_error_consume(*args, **kwargs):
        consume_calls["count"] += 1
        raise httpx.ConnectError("refused")

    with (
        patch("httpx.AsyncClient", return_value=fake_client),
        patch(
            "songmaker_cli.scheduler.consume_download_task_stream",
            new=connect_error_consume,
        ),
        patch("songmaker_cli.jobs.asyncio.sleep", new=_instant_sleep),
    ):
        _run(download_model_on_worker({"redis": redis}, "dl-noretry", "sft", db_factory=seeded_db))

    with seeded_db() as session:
        job = get_job(session, "dl-noretry")
        assert job.status == "failed"
        assert job.error_type == "sse_transport"
    assert consume_calls["count"] == 1


def test_download_redis_flag_held_across_retries(seeded_db) -> None:
    from unittest.mock import AsyncMock

    from songmaker_cli.acestep_state import download_key
    from songmaker_cli.jobs import download_model_on_worker
    from songmaker_cli.scheduler import WorkerTaskFailed

    _seed_download_job(seeded_db, "dl-flag")
    redis = _FakeRedis()
    _seed_online_worker(seeded_db, redis)

    fake_submit_response = MagicMock(status_code=200)
    fake_submit_response.json = MagicMock(return_value={"task_id": "t"})
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_submit_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    flag_key = download_key("sft")
    seen_during_retries: list[bool] = []

    async def consume_observing_flag(*args, **kwargs):
        seen_during_retries.append(flag_key in redis.store)
        raise WorkerTaskFailed("transient")

    with (
        patch("httpx.AsyncClient", return_value=fake_client),
        patch(
            "songmaker_cli.scheduler.consume_download_task_stream",
            new=consume_observing_flag,
        ),
        patch("songmaker_cli.jobs.asyncio.sleep", new=_instant_sleep),
    ):
        _run(download_model_on_worker({"redis": redis}, "dl-flag", "sft", db_factory=seeded_db))

    assert seen_during_retries == [True, True, True]
    assert flag_key not in redis.store

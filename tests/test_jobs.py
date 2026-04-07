"""Tests for background job runners (generation + scoring)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from acestep_engine.models import AceStepConfig
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import Album, Generation, Job, Score, Song, Version
from songmaker_cli.db.queries import get_generation, get_job
from songmaker_cli.jobs import (
    GenerationContext,
    _apply_task_overrides,
    _persist_generation_row,
    _update_job,
    run_generation_job,
    run_scoring_job,
)
from songmaker_cli.scheduler import GenerationTaskResultDTO


def _run(coro):
    return asyncio.run(coro)


def _make_dto(seed: int = 42, audio_path: str = "/tmp/fake.wav") -> GenerationTaskResultDTO:
    return GenerationTaskResultDTO(
        mode="turbo", audio_path=audio_path, seed=seed,
        cot_caption="", cot_lyrics="",
    )


def _persist_via_post_process(*, ctx, generation_id, db_factory, **kwargs):
    _persist_generation_row(
        db_factory=db_factory,
        ctx=ctx,
        generation_id=generation_id,
        seed=kwargs.get("worker_seed", 0),
        cot_caption=kwargs.get("worker_cot_caption", ""),
        cot_lyrics=kwargs.get("worker_cot_lyrics", ""),
        mp3_path=Path(f"/tmp/{generation_id}.mp3"),
        wav_path=Path(f"/tmp/{generation_id}.wav"),
    )


@pytest.fixture()
def db_factory(tmp_path: Path):
    factory = init_db(tmp_path / "test.db")
    yield factory


@pytest.fixture()
def seeded_db(db_factory, tmp_path: Path):
    with db_factory() as session:
        session.add(Album(id="rock", title="Rock", artist="Band"))
        session.add(Song(id="s1", title="Song One", album_id="rock", track_number=1, language="en"))
        session.add(Version(
            id="v1", song_id="s1", version_number=1,
            lyrics="Hello world", prompt="rock style", bpm=120, duration=60, key="Am",
        ))
        session.add(Job(id="j1", type="generate", status="queued"))
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
        ))

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "completed"
        assert job.progress == 1.0

        gens = session.query(Generation).filter_by(song_id="s1").all()
        assert len(gens) == 1
        assert gens[0].seed == 42
        assert gens[0].model_mode == "turbo"


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
        ))

    with seeded_db() as session:
        gens = session.query(Generation).filter_by(song_id="s1").all()
        assert len(gens) == 3


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
        ))

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "partial"
        assert "1/3 completed" in job.error
        assert "2 failed" in job.error

        gens = session.query(Generation).filter_by(song_id="s1").all()
        assert len(gens) == 1


def test_generation_job_song_not_found(seeded_db, tmp_path: Path) -> None:
    _run(run_generation_job(
        "j1", "nonexistent", "v1", 1, "u1",
        db_factory=seeded_db,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        redis=MagicMock(),
    ))

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "failed"
        assert "Song not found" in job.error


def test_generation_job_version_not_found(seeded_db, tmp_path: Path) -> None:
    _run(run_generation_job(
        "j1", "s1", "nonexistent", 1, "u1",
        db_factory=seeded_db,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        redis=MagicMock(),
    ))

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "failed"
        assert "Version not found" in job.error


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
        ))

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "failed"


def test_generation_job_exception(seeded_db, tmp_path: Path) -> None:
    dispatch, post_process, defaults = _patch_dispatch_and_post_process(
        RuntimeError("GPU error"),
    )
    with dispatch, post_process, defaults:
        _run(run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=MagicMock(),
        ))

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "failed"
        assert job.error == "Internal error during processing"


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
        ))

    with seeded_db() as session:
        gen = session.query(Generation).filter_by(song_id="s1").first()
        assert gen.generation_params["inference_steps"] == 50
        assert gen.generation_params["shift"] == 2.0


def test_generation_job_global_defaults_loaded(seeded_db, tmp_path: Path) -> None:
    dispatch = AsyncMock(return_value=_make_dto())
    with (
        patch("songmaker_cli.jobs.dispatch_generation", dispatch),
        patch("songmaker_cli.jobs.post_process_generation", side_effect=_persist_via_post_process),
        patch(
            "songmaker_cli.jobs.load_generation_defaults",
            return_value={"turbo": {"shift": 7.0}},
        ) as mock_load,
    ):
        _run(run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db,
            audio_dir=tmp_path / "audio",
            data_dir=tmp_path / "data",
            redis=MagicMock(),
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


# ── run_scoring_job ─────────────────────────────────────────────────


def _mock_scores(with_whisper: bool = False):
    scores = MagicMock()
    scores.to_dict.return_value = {"dynamics": 55.0}
    if with_whisper:
        ta = MagicMock()
        ta.transcribed_line_texts = ["hello", "world"]
        scores.text_accuracy = ta
    else:
        scores.text_accuracy = None
    return scores


def test_scoring_job_happy_path(seeded_db, tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    mp3_file = audio_dir / "user1" / "g1.mp3"
    mp3_file.parent.mkdir(parents=True, exist_ok=True)
    mp3_file.write_bytes(b"fake-mp3")

    with seeded_db() as session:
        session.add(Generation(
            id="g1", song_id="s1", version_id="v1", generation_number=1,
            mp3_path="user1/g1.mp3", seed=42,
        ))
        session.commit()

    mock_result = _mock_scores()

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


def test_scoring_job_saves_whisper_text(seeded_db, tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    mp3_file = audio_dir / "user1" / "g1.mp3"
    mp3_file.parent.mkdir(parents=True, exist_ok=True)
    mp3_file.write_bytes(b"fake-mp3")

    with seeded_db() as session:
        session.add(Generation(
            id="g1", song_id="s1", version_id="v1", generation_number=1,
            mp3_path="user1/g1.mp3", seed=42,
        ))
        session.commit()

    mock_result = _mock_scores(with_whisper=True)

    with (
        patch(
            "songmaker_cli.jobs.get_scorer_process",
            return_value=MagicMock(score=MagicMock(return_value=mock_result)),
        ),
    ):
        run_scoring_job("j2", "g1", None, db_factory=seeded_db, audio_dir=audio_dir)

    with seeded_db() as session:
        gen = get_generation(session, "g1")
        assert gen.whisper_text == "hello\nworld"


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


def test_scoring_job_exception(seeded_db, tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    mp3_file = audio_dir / "user1" / "g1.mp3"
    mp3_file.parent.mkdir(parents=True, exist_ok=True)
    mp3_file.write_bytes(b"fake-mp3")

    with seeded_db() as session:
        session.add(Generation(
            id="g1", song_id="s1", version_id="v1", generation_number=1,
            mp3_path="user1/g1.mp3", seed=42,
        ))
        session.commit()

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

    config = AceStepConfig(prompt="test", lyrics="la la", duration=180)
    ctx = GenerationContext(
        song_id="s1", version_id="v1",
        meta=SongMeta(title="t", lyrics="la la", prompt="test"),
        album_meta=AlbumMeta(title="a", artist="b"),
        ace_config=config, audio_dir=tmp_path, user_id="u1",
        model_name="turbo",
    )
    params = {
        "src_wav_path": str(src_wav),
        "repainting_start": 0.3,
        "repainting_end": 0.8,
        "lyrics": "la la",
        "prompt": "test",
    }
    result = _apply_task_overrides(ctx, "repaint", params)
    assert result.ace_config.repainting_start == pytest.approx(54.0)
    assert result.ace_config.repainting_end == pytest.approx(144.0)
    assert result.ace_config.task_type == "repaint"
    assert result.ace_config.think_mode == "deep"
    assert result.ace_config.src_audio.startswith(str(tmp_path / ".tmp"))
    assert Path(result.ace_config.src_audio).exists()


def test_repaint_inherits_generation_settings(tmp_path: Path) -> None:
    from songmaker_cli.parser import AlbumMeta, SongMeta

    src_wav = tmp_path / "src.wav"
    src_wav.write_bytes(b"RIFF" + b"\x00" * 40)

    config = AceStepConfig(
        prompt="test", lyrics="la la", duration=120,
        guidance_scale=5.0, inference_steps=50, shift=2.0, think_mode="deep",
    )
    ctx = GenerationContext(
        song_id="s1", version_id="v1",
        meta=SongMeta(title="t", lyrics="la la", prompt="test"),
        album_meta=AlbumMeta(title="a", artist="b"),
        ace_config=config, audio_dir=tmp_path, user_id="u1",
        model_name="sft",
    )
    params = {
        "src_wav_path": str(src_wav),
        "repainting_start": 0.1,
        "repainting_end": 0.3,
    }
    result = _apply_task_overrides(ctx, "repaint", params)
    assert result.ace_config.guidance_scale == 5.0
    assert result.ace_config.inference_steps == 50
    assert result.ace_config.shift == 2.0
    assert result.ace_config.think_mode == "deep"


def test_cover_does_not_convert_fractions(tmp_path: Path) -> None:
    from songmaker_cli.parser import AlbumMeta, SongMeta

    src_wav = tmp_path / "src.wav"
    src_wav.write_bytes(b"RIFF" + b"\x00" * 40)

    config = AceStepConfig(prompt="test", lyrics="la la", duration=180)
    ctx = GenerationContext(
        song_id="s1", version_id="v1",
        meta=SongMeta(title="t", lyrics="la la", prompt="test"),
        album_meta=AlbumMeta(title="a", artist="b"),
        ace_config=config, audio_dir=tmp_path, user_id="u1",
        model_name="turbo",
    )
    params = {
        "src_wav_path": str(src_wav),
        "audio_cover_strength": 0.7,
        "lyrics": "la la",
        "prompt": "test",
    }
    result = _apply_task_overrides(ctx, "cover", params)
    assert result.ace_config.audio_cover_strength == 0.7
    assert result.ace_config.task_type == "cover"
    assert result.ace_config.src_audio.startswith(str(tmp_path / ".tmp"))


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
        patch("songmaker_cli.worker_base._get_db_factory", return_value=seeded_db),
        patch("httpx.AsyncClient", return_value=fake_client),
    ):
        _run(load_model_on_worker({}, "w1-job", "w1", "sft"))

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

    with patch("songmaker_cli.worker_base._get_db_factory", return_value=seeded_db):
        _run(load_model_on_worker({}, "job1", "missing", "sft"))

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
        patch("songmaker_cli.worker_base._get_db_factory", return_value=seeded_db),
        patch("httpx.AsyncClient", return_value=fake_client),
    ):
        _run(load_model_on_worker({}, "w1-job", "w1", "sft"))

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
        patch("songmaker_cli.worker_base._get_db_factory", return_value=seeded_db),
        patch("httpx.AsyncClient", return_value=fake_client),
    ):
        _run(load_model_on_worker({}, "w1-job", "w1", "sft"))

    with seeded_db() as session:
        job = get_job(session, "w1-job")
        assert job.status == "failed"
        assert job.error_type == "worker_error"
        assert "500" in job.error

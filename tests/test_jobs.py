"""Tests for background job runners (generation + scoring)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from acestep_engine.models import AceStepConfig
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import Album, Generation, Job, Score, Song, Version
from songmaker_cli.db.queries import get_generation, get_job
from songmaker_cli.jobs import (
    GenerationContext,
    _apply_task_overrides,
    _update_job,
    run_generation_job,
    run_scoring_job,
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


def _mock_generate_result(mp3_name: str = "01_song_one_v1.mp3", seed: int = 42):
    wav_name = mp3_name.replace(".mp3", ".wav")
    result = MagicMock()
    result.mp3_path = Path(f"/output/rock/{mp3_name}")
    result.wav_path = Path(f"/output/rock/{wav_name}")
    result.seed = seed
    return result


def _mock_server_info(model: str = "acestep-v15-turbo"):
    info = MagicMock()
    info.model = model
    return info


def test_generation_job_happy_path(seeded_db, tmp_path: Path) -> None:
    result = _mock_generate_result()
    client = MagicMock()
    client.is_available = True
    client.server_info.return_value = _mock_server_info()

    with (
        patch("songmaker_cli.jobs.AceStepClient", return_value=client),
        patch("songmaker_cli.jobs.load_generation_defaults", return_value={}),
        patch("songmaker_cli.jobs.generate_single", return_value=result),
    ):
        run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db, audio_dir=tmp_path / "audio", data_dir=tmp_path / "data",
        )

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "completed"
        assert job.progress == 1.0

        gens = session.query(Generation).filter_by(song_id="s1").all()
        assert len(gens) == 1
        assert gens[0].seed == 42
        assert gens[0].generation_params["acestep_model"] == "acestep-v15-turbo"
        assert gens[0].model_mode == "turbo"


def test_generation_job_multiple_count(seeded_db, tmp_path: Path) -> None:
    results = [_mock_generate_result(f"song_v{i}.mp3", seed=100 + i) for i in range(3)]
    client = MagicMock()
    client.is_available = True
    client.server_info.return_value = _mock_server_info()

    with (
        patch("songmaker_cli.jobs.AceStepClient", return_value=client),
        patch("songmaker_cli.jobs.load_generation_defaults", return_value={}),
        patch("songmaker_cli.jobs.generate_single", side_effect=results),
    ):
        run_generation_job(
            "j1", "s1", "v1", 3, "u1",
            db_factory=seeded_db, audio_dir=tmp_path / "audio", data_dir=tmp_path / "data",
        )

    with seeded_db() as session:
        gens = session.query(Generation).filter_by(song_id="s1").all()
        assert len(gens) == 3


def test_generation_job_partial_failure(seeded_db, tmp_path: Path) -> None:
    ok_result = _mock_generate_result("song_v1.mp3", seed=100)
    client = MagicMock()
    client.is_available = True
    client.server_info.return_value = _mock_server_info()

    with (
        patch("songmaker_cli.jobs.AceStepClient", return_value=client),
        patch("songmaker_cli.jobs.load_generation_defaults", return_value={}),
        patch(
            "songmaker_cli.jobs.generate_single",
            side_effect=[ok_result, RuntimeError("GPU OOM"), RuntimeError("GPU OOM")],
        ),
    ):
        run_generation_job(
            "j1", "s1", "v1", 3, "u1",
            db_factory=seeded_db, audio_dir=tmp_path / "audio", data_dir=tmp_path / "data",
        )

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "partial"
        assert "1/3 completed" in job.error
        assert "2 failed" in job.error

        gens = session.query(Generation).filter_by(song_id="s1").all()
        assert len(gens) == 1


def test_generation_job_song_not_found(seeded_db) -> None:
    run_generation_job(
        "j1", "nonexistent", "v1", 1, "u1",
        db_factory=seeded_db, audio_dir=Path("/tmp/audio"), data_dir=Path("/tmp/data"),
    )

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "failed"
        assert "Song not found" in job.error


def test_generation_job_version_not_found(seeded_db) -> None:
    run_generation_job(
        "j1", "s1", "nonexistent", 1, "u1",
        db_factory=seeded_db, audio_dir=Path("/tmp/audio"), data_dir=Path("/tmp/data"),
    )

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "failed"
        assert "Version not found" in job.error


def test_generation_job_acestep_not_reachable(seeded_db) -> None:
    client = MagicMock()
    client.is_available = False

    with patch("songmaker_cli.jobs.AceStepClient", return_value=client):
        run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db, audio_dir=Path("/tmp/audio"), data_dir=Path("/tmp/data"),
        )

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "failed"
        assert "not reachable" in job.error


def test_generation_job_exception(seeded_db) -> None:
    client = MagicMock()
    client.is_available = True
    client.server_info.return_value = _mock_server_info()

    with (
        patch("songmaker_cli.jobs.AceStepClient", return_value=client),
        patch("songmaker_cli.jobs.load_generation_defaults", return_value={}),
        patch("songmaker_cli.jobs.generate_single", side_effect=RuntimeError("GPU error")),
    ):
        run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db, audio_dir=Path("/tmp/audio"), data_dir=Path("/tmp/data"),
        )

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "failed"
        assert job.error == "Internal error during processing"


def test_generation_job_version_gen_params_merged(seeded_db, tmp_path: Path) -> None:
    with seeded_db() as session:
        ver = session.query(Version).filter_by(id="v1").first()
        ver.generation_params = {"inference_steps": 50, "shift": 2.0}
        session.commit()

    result = _mock_generate_result()
    client = MagicMock()
    client.is_available = True
    client.server_info.return_value = _mock_server_info()

    with (
        patch("songmaker_cli.jobs.AceStepClient", return_value=client),
        patch("songmaker_cli.jobs.load_generation_defaults", return_value={}),
        patch("songmaker_cli.jobs.generate_single", return_value=result),
    ):
        run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db, audio_dir=tmp_path / "audio", data_dir=tmp_path / "data",
        )

    with seeded_db() as session:
        gen = session.query(Generation).filter_by(song_id="s1").first()
        assert gen.generation_params["inference_steps"] == 50
        assert gen.generation_params["shift"] == 2.0


def test_generation_job_global_defaults_loaded(seeded_db, tmp_path: Path) -> None:
    result = _mock_generate_result()
    client = MagicMock()
    client.is_available = True
    client.server_info.return_value = _mock_server_info()

    with (
        patch("songmaker_cli.jobs.AceStepClient", return_value=client),
        patch(
            "songmaker_cli.jobs.load_generation_defaults",
            return_value={"turbo": {"shift": 7.0}},
        ) as mock_load,
        patch("songmaker_cli.jobs.generate_single", return_value=result),
    ):
        run_generation_job(
            "j1", "s1", "v1", 1, "u1",
            db_factory=seeded_db, audio_dir=tmp_path / "audio", data_dir=tmp_path / "data",
        )

    mock_load.assert_called_once()


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
        model_name="turbo", client=MagicMock(),
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
    assert result.ace_config.think_mode == "off"
    assert result.ace_config.src_audio.startswith("/tmp/")
    assert Path(result.ace_config.src_audio).exists()


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
        model_name="turbo", client=MagicMock(),
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
    assert result.ace_config.src_audio.startswith("/tmp/")

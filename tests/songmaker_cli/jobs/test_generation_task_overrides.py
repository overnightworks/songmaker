"""The repaint and cover task overrides and the repaint splice of a take."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from acestep_engine.models import AceStepConfig
from songmaker_cli.api_models import CoverTaskParams, RepaintTaskParams
from songmaker_cli.generate import DecodedAudio
from songmaker_cli.jobs import (
    GenerationContext,
    _apply_cover_overrides,
    _apply_repaint_overrides,
)

# ── _apply_task_overrides ──────────────────────────────────────────


def _override_context(tmp_path: Path, config: AceStepConfig | None = None, model_name="turbo"):
    from songmaker_cli.parser import AlbumMeta, SongMeta

    return GenerationContext(
        song_id="s1",
        version_id="v1",
        meta=SongMeta(title="t", lyrics="la la", prompt="test"),
        album_meta=AlbumMeta(title="a", artist="b"),
        ace_config=config or AceStepConfig(prompt="test", lyrics="la la", audio_duration=0),
        audio_dir=tmp_path,
        user_id="u1", reference_recording_id=None,
        model_name=model_name,
    )


def _repaint_params(src_wav: Path, start: float, end: float) -> RepaintTaskParams:
    return RepaintTaskParams(
        src_wav_path=str(src_wav),
        src_generation_id="g0",
        repainting_start=start,
        repainting_end=end,
        lyrics="la la",
        prompt="test",
    )


def test_repaint_of_an_unreadable_source_take_fails_loud(tmp_path: Path) -> None:
    src_wav = tmp_path / "src.wav"
    src_wav.write_bytes(b"RIFF" + b"\x00" * 100)
    ctx = _override_context(tmp_path)
    params = _repaint_params(src_wav, 0.3, 0.8)
    with pytest.raises(ValueError, match="Cannot measure"):
        _apply_repaint_overrides(ctx, params)


def test_repaint_range_is_a_fraction_of_the_source_take(tmp_path: Path, make_wav_bytes) -> None:
    src_wav = tmp_path / "src.wav"
    src_wav.write_bytes(make_wav_bytes(b"\x80" * 2000, sampwidth=1, sample_rate=10))
    ctx = _override_context(tmp_path)

    result = _apply_repaint_overrides(ctx, _repaint_params(src_wav, 0.3, 0.8))

    assert result.ace_config.repainting_start == pytest.approx(60.0)
    assert result.ace_config.repainting_end == pytest.approx(160.0)
    assert result.ace_config.task_type == "repaint"
    assert result.ace_config.thinking is True
    assert result.ace_config.src_audio_path.startswith(str(tmp_path / ".tmp"))
    assert Path(result.ace_config.src_audio_path).exists()
    assert result.src_generation_id == "g0"


def test_repaint_inherits_generation_settings(tmp_path: Path, make_wav_bytes) -> None:
    src_wav = tmp_path / "src.wav"
    src_wav.write_bytes(make_wav_bytes(b"\x80" * 2000, sampwidth=1, sample_rate=10))
    config = AceStepConfig(
        prompt="test",
        lyrics="la la",
        audio_duration=120,
        guidance_scale=5.0,
        inference_steps=50,
        shift=2.0,
        thinking=True,
    )

    result = _apply_repaint_overrides(
        _override_context(tmp_path, config, "sft"), _repaint_params(src_wav, 0.1, 0.3),
    )

    assert result.ace_config.guidance_scale == 5.0
    assert result.ace_config.inference_steps == 50
    assert result.ace_config.shift == 2.0
    assert result.ace_config.thinking is True


_OPTIONAL_PARAMETERS = [
    pytest.param("repaint", "repaint_mode", "balanced", "aggressive", id="repaint_mode"),
    pytest.param("repaint", "repaint_strength", 0.9, 0.2, id="repaint_strength"),
    pytest.param(
        "repaint", "repaint_latent_crossfade_frames", 8, 3, id="repaint_latent_crossfade_frames",
    ),
    pytest.param("repaint", "repaint_wav_crossfade_sec", 0.4, 0.1, id="repaint_wav_crossfade_sec"),
    pytest.param("cover", "cover_noise_strength", 0.6, 0.3, id="cover_noise_strength"),
]


@pytest.mark.parametrize(("task", "field", "base_value", "set_value"), _OPTIONAL_PARAMETERS)
@pytest.mark.parametrize("is_set", [True, False])
def test_an_optional_task_parameter_reaches_ace_step_only_when_set(
    tmp_path: Path, make_wav_bytes, task: str, field: str, base_value, set_value, is_set: bool,
) -> None:
    src_wav = tmp_path / "src.wav"
    src_wav.write_bytes(make_wav_bytes(b"\x80" * 2000, sampwidth=1, sample_rate=10))
    config = AceStepConfig(prompt="test", lyrics="la la", audio_duration=120, **{field: base_value})
    ctx = _override_context(tmp_path, config)
    optional = {field: set_value if is_set else None}
    if task == "repaint":
        params = _repaint_params(src_wav, 0.3, 0.8).model_copy(update=optional)
        result = _apply_repaint_overrides(ctx, params)
    else:
        result = _apply_cover_overrides(ctx, CoverTaskParams(
            src_wav_path=str(src_wav), src_generation_id="g0", audio_cover_strength=0.7,
            lyrics="la la", prompt="test", **optional,
        ))

    assert getattr(result.ace_config, field) == (set_value if is_set else base_value)


@pytest.mark.parametrize("has_raw_wav", [True, False])
def test_the_repaint_splice_source_is_the_source_takes_raw_wav_when_it_has_one(
    tmp_path: Path, make_wav_bytes, has_raw_wav: bool,
) -> None:
    src_wav = tmp_path / "src.wav"
    src_wav.write_bytes(make_wav_bytes(b"\x80" * 2000, sampwidth=1, sample_rate=10))
    raw_wav = tmp_path / "src.raw.wav"
    if has_raw_wav:
        raw_wav.write_bytes(b"unmastered take")

    result = _apply_repaint_overrides(
        _override_context(tmp_path), _repaint_params(src_wav, 0.3, 0.8),
    )

    if has_raw_wav:
        assert result.raw_src_audio.startswith(str(tmp_path / ".tmp"))
        assert Path(result.raw_src_audio).read_bytes() == b"unmastered take"
    else:
        assert result.raw_src_audio is None


_SPLICE_RATE = 1000
_SOURCE_LEVEL = 0.25
_REPAINTED_LEVEL = 0.75


def _spliced_samples(seeded_db, tmp_path: Path, make_wav_bytes, repaint_mode: str) -> np.ndarray:
    """The left channel written for a repainted take; decode, encode and file write are stubbed."""
    from songmaker_cli.jobs.generation import post_process_generation

    source = tmp_path / "src.wav"
    source.write_bytes(make_wav_bytes(
        int(_SOURCE_LEVEL * 32768).to_bytes(2, "little", signed=True) * _SPLICE_RATE,
        sample_rate=_SPLICE_RATE,
    ))
    worker_audio = tmp_path / "worker.wav"
    worker_audio.write_bytes(b"RIFF")
    config = AceStepConfig(
        prompt="test", lyrics="la la", audio_duration=0, task_type="repaint",
        src_audio_path=str(source), repainting_start=0.3, repainting_end=0.7,
        repaint_mode=repaint_mode,
    )
    repainted = np.full(_SPLICE_RATE, _REPAINTED_LEVEL)
    written: list[np.ndarray] = []

    def write_raw_wav(path, left, *_rest):
        written.append(left)
        Path(path).write_bytes(b"audio")

    def write_encoded_outputs(_decoded, _seed, mp3_path, wav_path, *_meta):
        for path in (mp3_path, wav_path):
            Path(path).write_bytes(b"audio")

    with (
        patch(
            "songmaker_cli.jobs.generation._decode_audio",
            return_value=DecodedAudio(
                left=repainted, right=repainted.copy(), sample_rate=_SPLICE_RATE, duration=1.0,
            ),
        ),
        patch("audio_engine.write_stereo_wav", side_effect=write_raw_wav),
        patch("songmaker_cli.jobs.generation._write_output", side_effect=write_encoded_outputs),
    ):
        post_process_generation(
            worker_audio_path=str(worker_audio), worker_seed=1, worker_cot_caption="",
            worker_cot_lyrics="", worker_delivered_batch_size=None,
            ctx=_override_context(tmp_path, config), generation_id="g1",
            db_factory=seeded_db, job_id="j1",
        )
    return written[0]


def test_a_default_repaint_keeps_the_source_outside_the_window_away_from_the_edges(
    seeded_db, tmp_path: Path, make_wav_bytes,
) -> None:
    samples = _spliced_samples(seeded_db, tmp_path, make_wav_bytes, repaint_mode="")

    assert samples[:250] == pytest.approx(_SOURCE_LEVEL)
    assert samples[750:] == pytest.approx(_SOURCE_LEVEL)
    assert samples[350:650] == pytest.approx(_REPAINTED_LEVEL)


def test_a_repaint_with_a_server_side_mode_writes_the_unspliced_result(
    seeded_db, tmp_path: Path, make_wav_bytes,
) -> None:
    samples = _spliced_samples(seeded_db, tmp_path, make_wav_bytes, repaint_mode="balanced")

    assert samples == pytest.approx(_REPAINTED_LEVEL)


def test_cover_does_not_convert_fractions(tmp_path: Path) -> None:
    from songmaker_cli.parser import AlbumMeta, SongMeta

    src_wav = tmp_path / "src.wav"
    src_wav.write_bytes(b"RIFF" + b"\x00" * 40)

    config = AceStepConfig(prompt="test", lyrics="la la", audio_duration=180)
    ctx = GenerationContext(
        song_id="s1",
        version_id="v1",
        meta=SongMeta(title="t", lyrics="la la", prompt="test"),
        album_meta=AlbumMeta(title="a", artist="b"),
        ace_config=config,
        audio_dir=tmp_path,
        user_id="u1", reference_recording_id=None,
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

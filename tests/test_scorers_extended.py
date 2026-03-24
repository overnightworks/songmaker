"""Extended tests for spectral_quality, audiobox_aesthetics, text_accuracy, lyrical_coherence."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf

from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.models import AudioBoxScore, SpectralQualityScore, TextAccuracyScore
from songmaker_cli.scoring.pipeline import AudioData

SR = 22050


def _sine_wav(tmp_path: Path, duration: float = 3.0, name: str = "test.wav") -> Path:
    t = np.arange(int(SR * duration)) / SR
    audio = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    path = tmp_path / name
    sf.write(str(path), audio, SR)
    return path


# ── spectral_quality ────────────────────────────────────────────────


def test_spectral_quality_clean_audio(tmp_path: Path) -> None:
    from songmaker_cli.scoring.spectral_quality import score_spectral_quality

    wav = _sine_wav(tmp_path, duration=5.0)
    audio, sr = sf.read(str(wav))
    audio_data = AudioData(audio=audio.astype(np.float32), sr=sr)

    result = score_spectral_quality(wav, audio_data=audio_data)
    assert isinstance(result, SpectralQualityScore)
    assert result.mean_flatness >= 0
    assert result.artifact_count >= 0


def test_spectral_quality_short_audio(tmp_path: Path) -> None:
    from songmaker_cli.scoring.spectral_quality import score_spectral_quality

    audio = np.zeros(100, dtype=np.float32)
    audio_data = AudioData(audio=audio, sr=SR)

    result = score_spectral_quality(tmp_path / "x.wav", audio_data=audio_data)
    assert result.mean_flatness == 0.0
    assert result.artifact_count == 0


def test_spectral_quality_noisy_audio(tmp_path: Path) -> None:
    from songmaker_cli.scoring.spectral_quality import score_spectral_quality

    rng = np.random.default_rng(42)
    noise = rng.normal(0, 0.3, SR * 5).astype(np.float32)
    audio_data = AudioData(audio=noise, sr=SR)

    result = score_spectral_quality(tmp_path / "noise.wav", audio_data=audio_data)
    assert result.mean_flatness > 0
    assert result.max_flatness > 0


# ── audiobox_aesthetics ─────────────────────────────────────────────


def test_force_cpu_env_context_manager() -> None:
    from songmaker_cli.scoring.audiobox_aesthetics import _force_cpu_env

    original = os.environ.get("CUDA_VISIBLE_DEVICES")
    with _force_cpu_env():
        assert os.environ["CUDA_VISIBLE_DEVICES"] == ""
    if original is None:
        assert "CUDA_VISIBLE_DEVICES" not in os.environ
    else:
        assert os.environ["CUDA_VISIBLE_DEVICES"] == original


def test_force_cpu_env_restores_existing() -> None:
    from songmaker_cli.scoring.audiobox_aesthetics import _force_cpu_env

    os.environ["CUDA_VISIBLE_DEVICES"] = "0,1"
    try:
        with _force_cpu_env():
            assert os.environ["CUDA_VISIBLE_DEVICES"] == ""
        assert os.environ["CUDA_VISIBLE_DEVICES"] == "0,1"
    finally:
        os.environ["CUDA_VISIBLE_DEVICES"] = "0,1"
        os.environ.pop("CUDA_VISIBLE_DEVICES", None)


def test_get_predictor_caches() -> None:
    from songmaker_cli.scoring.audiobox_aesthetics import _get_predictor

    mock_cls = MagicMock(return_value=MagicMock())
    cache: dict = {}

    with patch("audiobox_aesthetics.infer.AesPredictor", mock_cls):
        p1 = _get_predictor(device="cpu", cache=cache)
        p2 = _get_predictor(device="cpu", cache=cache)

    assert p1 is p2
    assert mock_cls.call_count == 1


def test_get_predictor_cpu_uses_force_env() -> None:
    from songmaker_cli.scoring.audiobox_aesthetics import _get_predictor

    mock_cls = MagicMock(return_value=MagicMock())
    cache: dict = {}

    with patch("audiobox_aesthetics.infer.AesPredictor", mock_cls):
        _get_predictor(device="cpu", cache=cache)

    mock_cls.assert_called_once()


def test_get_predictor_cuda_no_force_env() -> None:
    from songmaker_cli.scoring.audiobox_aesthetics import _get_predictor

    mock_cls = MagicMock(return_value=MagicMock())
    cache: dict = {}

    with patch("audiobox_aesthetics.infer.AesPredictor", mock_cls):
        _get_predictor(device="cuda", cache=cache)

    mock_cls.assert_called_once()


def test_get_predictor_default_cache() -> None:
    from songmaker_cli.scoring import audiobox_aesthetics as ab
    from songmaker_cli.scoring.audiobox_aesthetics import _get_predictor

    mock_cls = MagicMock(return_value=MagicMock())
    key = "test_default"

    with patch("audiobox_aesthetics.infer.AesPredictor", mock_cls):
        result = _get_predictor(device="test_default")

    assert result is not None
    ab._predictor_cache.pop(key, None)


def test_score_audiobox(tmp_path: Path) -> None:
    from songmaker_cli.scoring.audiobox_aesthetics import score_audiobox
    from songmaker_cli.scoring.pipeline import PipelineConfig

    mock_predictor = MagicMock()
    mock_predictor.forward.return_value = [{"CE": 7.5, "CU": 6.0, "PC": 8.0, "PQ": 7.0}]

    target = "songmaker_cli.scoring.audiobox_aesthetics._get_predictor"
    with patch(target, return_value=mock_predictor):
        result = score_audiobox(tmp_path / "test.mp3", config=PipelineConfig(device="cpu"))

    assert isinstance(result, AudioBoxScore)
    assert result.content_enjoyment == 7.5
    assert result.production_quality == 7.0


# ── text_accuracy helpers ───────────────────────────────────────────


def test_clean_lyrics() -> None:
    from songmaker_cli.scoring.text_accuracy import clean_lyrics

    assert clean_lyrics("[verse] Hello World!") == "hello world"
    assert clean_lyrics("I'll don't won't") == "i will do not wo not"
    assert clean_lyrics("street-lights") == "street lights"


def test_is_vocalization() -> None:
    from songmaker_cli.scoring.text_accuracy import _is_vocalization

    assert _is_vocalization("oh oh oh") is True
    assert _is_vocalization("la la la") is True
    assert _is_vocalization("hello world") is False
    assert _is_vocalization("") is True


def test_is_hallucination_short() -> None:
    from songmaker_cli.scoring.text_accuracy import _is_hallucination

    assert _is_hallucination(("hello",)) is False
    assert _is_hallucination(("a", "b")) is False


def test_is_hallucination_repeated() -> None:
    from songmaker_cli.scoring.text_accuracy import _is_hallucination

    lines = tuple(["thank you"] * 6)
    assert _is_hallucination(lines) is True


def test_is_hallucination_varied() -> None:
    from songmaker_cli.scoring.text_accuracy import _is_hallucination

    lines = ("hello world", "goodbye moon", "sunny day", "rainy night", "happy times")
    assert _is_hallucination(lines) is False


def test_is_hallucination_known_phrases() -> None:
    from songmaker_cli.scoring.text_accuracy import _is_hallucination

    lines = ("thank you", "music", "applause", "thank you", "music", "laughter")
    assert _is_hallucination(lines) is True


def test_word_level_accuracy() -> None:
    from songmaker_cli.scoring.text_accuracy import _word_level_accuracy

    intended = ("hello world", "goodbye moon")
    transcribed = ("hello world", "goodbye moon")
    assert _word_level_accuracy(intended, transcribed) == pytest.approx(1.0)


def test_word_level_accuracy_partial() -> None:
    from songmaker_cli.scoring.text_accuracy import _word_level_accuracy

    intended = ("hello world foo bar",)
    transcribed = ("hello world",)
    ratio = _word_level_accuracy(intended, transcribed)
    assert 0.0 < ratio < 1.0


def test_word_level_accuracy_empty() -> None:
    from songmaker_cli.scoring.text_accuracy import _word_level_accuracy

    assert _word_level_accuracy((), ("hello",)) == 0.0
    assert _word_level_accuracy(("hello",), ()) == 0.0


def test_per_line_accuracy() -> None:
    from songmaker_cli.scoring.text_accuracy import _per_line_accuracy

    intended = ("hello world",)
    transcribed = ("hello world",)
    assert _per_line_accuracy(intended, transcribed) == pytest.approx(1.0)


def test_per_line_accuracy_empty() -> None:
    from songmaker_cli.scoring.text_accuracy import _per_line_accuracy

    assert _per_line_accuracy((), ("hello",)) == 0.0
    assert _per_line_accuracy(("hello",), ()) == 0.0


def test_build_vocabulary_prompt() -> None:
    from songmaker_cli.scoring.text_accuracy import _build_vocabulary_prompt

    lines = ("hello beautiful world", "lovely morning sunshine")
    result = _build_vocabulary_prompt(lines)
    assert result is not None
    assert "hello" in result
    assert "beautiful" in result


def test_build_vocabulary_prompt_empty() -> None:
    from songmaker_cli.scoring.text_accuracy import _build_vocabulary_prompt

    assert _build_vocabulary_prompt(()) is None


def test_segment_confidence() -> None:
    from songmaker_cli.scoring.text_accuracy import _segment_confidence

    good = {"avg_logprob": -0.2, "no_speech_prob": 0.01}
    bad = {"avg_logprob": -1.5, "no_speech_prob": 0.9}
    assert _segment_confidence(good) > _segment_confidence(bad)


def test_save_whisper_with_confidence(tmp_path: Path) -> None:
    from songmaker_cli.scoring.text_accuracy import _save_whisper_with_confidence

    segments = [
        {"text": "hello", "avg_logprob": -0.3, "no_speech_prob": 0.01},
        {"text": "world", "avg_logprob": -0.5, "no_speech_prob": 0.1},
        {"text": "", "avg_logprob": -1.0, "no_speech_prob": 0.9},
    ]
    path = tmp_path / "test.whisper"
    _save_whisper_with_confidence(path, segments)

    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert "|hello" in lines[0]
    assert "|world" in lines[1]


def test_get_whisper_model_caches() -> None:
    from songmaker_cli.scoring.text_accuracy import _get_whisper_model

    mock_whisper = MagicMock()
    mock_model = MagicMock()
    mock_whisper.load_model.return_value = mock_model
    cache: dict = {}

    with patch.dict("sys.modules", {"whisper": mock_whisper}):
        m1 = _get_whisper_model("base", device="cpu", cache=cache)
        m2 = _get_whisper_model("base", device="cpu", cache=cache)

    assert m1 is m2
    assert mock_whisper.load_model.call_count == 1


def test_get_whisper_model_default_cache() -> None:
    from songmaker_cli.scoring import text_accuracy as ta
    from songmaker_cli.scoring.text_accuracy import _get_whisper_model

    mock_whisper = MagicMock()
    mock_model = MagicMock()
    mock_whisper.load_model.return_value = mock_model
    key = "test_default:cpu"

    with patch.dict("sys.modules", {"whisper": mock_whisper}):
        result = _get_whisper_model("test_default", device="cpu")

    assert result is mock_model
    ta._whisper_model_cache.pop(key, None)


def test_transcribe() -> None:
    from songmaker_cli.scoring.text_accuracy import _transcribe

    mock_model = MagicMock()
    mock_model.transcribe.return_value = {
        "text": "hello world",
        "segments": [{"text": "hello world", "avg_logprob": -0.3}],
    }
    text, segments = _transcribe(Path("test.mp3"), "en", mock_model, "hint")
    assert text == "hello world"
    assert len(segments) == 1
    mock_model.transcribe.assert_called_once()


def test_score_text_accuracy_full(tmp_path: Path) -> None:
    from songmaker_cli.scoring.pipeline import PipelineConfig
    from songmaker_cli.scoring.text_accuracy import score_text_accuracy

    meta = SongMeta(prompt="test", lyrics="[verse]\nhello world\ngoodbye moon")

    mock_model = MagicMock()
    mock_model.transcribe.return_value = {
        "text": "hello world goodbye moon",
        "segments": [
            {"text": "hello world", "avg_logprob": -0.3, "no_speech_prob": 0.01},
            {"text": "goodbye moon", "avg_logprob": -0.4, "no_speech_prob": 0.02},
        ],
    }
    config = PipelineConfig(device="cpu", whisper_model="base")

    with patch("songmaker_cli.scoring.text_accuracy._get_whisper_model", return_value=mock_model):
        result = score_text_accuracy(tmp_path / "test.mp3", meta=meta, config=config)

    assert isinstance(result, TextAccuracyScore)
    assert result.similarity_ratio > 0


def test_score_text_accuracy_no_meta() -> None:
    from songmaker_cli.scoring.text_accuracy import score_text_accuracy

    with pytest.raises(ValueError, match="No lyrics"):
        score_text_accuracy(Path("test.mp3"), meta=None)


# ── lyrical_coherence ──────────────────────────────────────────────


def test_read_whisper_text_plain(tmp_path: Path) -> None:
    from songmaker_cli.scoring.lyrical_coherence import _read_whisper_text

    whisper = tmp_path / "test.whisper"
    whisper.write_text("hello world\ngoodbye moon\n")
    result = _read_whisper_text(whisper)
    assert result == "hello world\ngoodbye moon"


def test_read_whisper_text_confidence_format(tmp_path: Path) -> None:
    from songmaker_cli.scoring.lyrical_coherence import _read_whisper_text

    whisper = tmp_path / "test.whisper"
    whisper.write_text("0.85|hello world\n0.72|goodbye moon\n")
    result = _read_whisper_text(whisper)
    assert result == "hello world\ngoodbye moon"


def test_read_whisper_text_empty_lines(tmp_path: Path) -> None:
    from songmaker_cli.scoring.lyrical_coherence import _read_whisper_text

    whisper = tmp_path / "test.whisper"
    whisper.write_text("hello\n\n\nworld\n")
    result = _read_whisper_text(whisper)
    assert result == "hello\nworld"


def test_score_lyrical_coherence_no_meta() -> None:
    from songmaker_cli.scoring.lyrical_coherence import score_lyrical_coherence

    with pytest.raises(ValueError, match="No lyrics"):
        score_lyrical_coherence(Path("test.mp3"), meta=None)


def test_score_lyrical_coherence_no_whisper(tmp_path: Path) -> None:
    from songmaker_cli.scoring.lyrical_coherence import score_lyrical_coherence

    meta = SongMeta(prompt="test", lyrics="hello world")
    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"fake")

    with pytest.raises(ValueError, match="No Whisper transcription"):
        score_lyrical_coherence(mp3, meta=meta)


def test_score_text_accuracy_hallucination(tmp_path: Path) -> None:
    from songmaker_cli.scoring.pipeline import PipelineConfig
    from songmaker_cli.scoring.text_accuracy import score_text_accuracy

    meta = SongMeta(prompt="test", lyrics="[verse]\nhello world")

    mock_model = MagicMock()
    mock_model.transcribe.return_value = {
        "text": "thank you " * 10,
        "segments": [{"text": "thank you", "avg_logprob": -0.3, "no_speech_prob": 0.01}] * 6,
    }
    config = PipelineConfig(device="cpu", whisper_model="base")

    with patch("songmaker_cli.scoring.text_accuracy._get_whisper_model", return_value=mock_model):
        result = score_text_accuracy(tmp_path / "test.mp3", meta=meta, config=config)

    assert result.transcribed_line_texts == ()


def test_word_level_accuracy_all_vocalizations() -> None:
    from songmaker_cli.scoring.text_accuracy import _word_level_accuracy

    assert _word_level_accuracy(("oh oh oh",), ("hello",)) == 0.0


def test_word_level_accuracy_transcribed_all_vocalizations() -> None:
    from songmaker_cli.scoring.text_accuracy import _word_level_accuracy

    assert _word_level_accuracy(("hello world",), ("oh oh",)) == 0.0


def test_is_hallucination_all_empty_after_clean() -> None:
    from songmaker_cli.scoring.text_accuracy import _is_hallucination

    lines = ("...", "!!!", "???", "---")
    assert _is_hallucination(lines) is True


def test_per_line_accuracy_empty_after_clean() -> None:
    from songmaker_cli.scoring.text_accuracy import _per_line_accuracy

    assert _per_line_accuracy(("...",), ("hello",)) == 0.0
    assert _per_line_accuracy(("hello",), ("...",)) == 0.0


def test_spectral_quality_loads_audio_fallback(tmp_path: Path) -> None:
    from songmaker_cli.scoring.spectral_quality import score_spectral_quality

    wav = _sine_wav(tmp_path, duration=3.0, name="fallback.wav")
    result = score_spectral_quality(wav, audio_data=None)
    assert result.mean_flatness >= 0


def test_silence_detection_very_short_audio() -> None:
    from songmaker_cli.scoring.silence_detection import score_silence

    audio = np.zeros(100, dtype=np.float32)
    audio_data = AudioData(audio=audio, sr=SR)
    result = score_silence(Path("x.wav"), audio_data=audio_data)
    assert result.gap_count == 0


def test_emotional_dynamics_safe_cv_zero_mean() -> None:
    from songmaker_cli.scoring.emotional_dynamics import _safe_cv

    assert _safe_cv([0.0, 0.0, 0.0]) == 0.0


def test_emotional_dynamics_no_voiced_pitch() -> None:
    from songmaker_cli.scoring.emotional_dynamics import _section_median_pitch

    silent = np.zeros(SR, dtype=np.float32)
    result = _section_median_pitch(silent, SR)
    assert result is None


def test_emotional_dynamics_short_section() -> None:
    from songmaker_cli.scoring.emotional_dynamics import _onset_rate_coefficient_of_variation

    short = np.zeros(int(SR * 0.05), dtype=np.float32)
    result = _onset_rate_coefficient_of_variation([short], SR)
    assert result == 0.0


def test_bpm_detect_scalar_return() -> None:
    from songmaker_cli.scoring.bpm_accuracy import _detect_bpm

    with patch("librosa.beat.beat_track", return_value=(120.0, None)):
        bpm = _detect_bpm(np.zeros(SR), SR)
    assert bpm == 120.0


def test_bpm_detect_array_return() -> None:
    from songmaker_cli.scoring.bpm_accuracy import _detect_bpm

    with patch("librosa.beat.beat_track", return_value=(np.array([130.0]), None)):
        bpm = _detect_bpm(np.zeros(SR), SR)
    assert bpm == 130.0


# ── scoring/models.py gaps ──────────────────────────────────────────


def test_spectral_has_artifacts() -> None:
    from songmaker_cli.scoring.models import SpectralQualityScore

    s = SpectralQualityScore(
        mean_flatness=0.1, max_flatness=0.5, artifact_count=3, artifact_windows=(),
    )
    assert s.has_artifacts is True
    s2 = SpectralQualityScore(
        mean_flatness=0.1, max_flatness=0.2, artifact_count=0, artifact_windows=(),
    )
    assert s2.has_artifacts is False


def test_song_scores_to_dict_with_coherence() -> None:
    from songmaker_cli.scoring.models import LyricalCoherenceScore, SongScores, SpectralQualityScore

    scores = SongScores(
        spectral_quality=SpectralQualityScore(
            mean_flatness=0.1, max_flatness=0.2, artifact_count=1, artifact_windows=(),
        ),
        lyrical_coherence=LyricalCoherenceScore(
            score=8, issues=(), summary="good",
        ),
    )
    d = scores.to_dict()
    assert d["spectral_artifacts"] == 1
    assert d["lyrical_coherence"] == 8
    assert d["lyrical_summary"] == "good"


# ── scoring/pipeline.py gaps ────────────────────────────────────────


def test_available_scorers() -> None:
    from songmaker_cli.scoring.pipeline import available_scorers

    result = available_scorers()
    assert "text_accuracy" in result
    assert "spectral_quality" in result


def test_scorer_timeout() -> None:
    import time

    from songmaker_cli.scoring.pipeline import _run_with_timeout, _ScorerTimeout

    def slow_fn(*args, **kwargs):
        time.sleep(5)
        return None

    with pytest.raises(_ScorerTimeout):
        _run_with_timeout(slow_fn, Path("x"), None, None, None, timeout=1, name="slow")


def test_scorer_no_timeout() -> None:
    from songmaker_cli.scoring.pipeline import _run_with_timeout

    def fast_fn(mp3_path, meta, audio_data, config):
        return "result"

    result = _run_with_timeout(fast_fn, Path("x"), None, None, None, timeout=0, name="fast")
    assert result == "result"


def test_score_lyrical_coherence_happy_path(tmp_path: Path) -> None:
    from songmaker_cli.claude.provider import ClaudeResponse
    from songmaker_cli.scoring.lyrical_coherence import score_lyrical_coherence

    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"fake")
    whisper = tmp_path / "test.whisper"
    whisper.write_text("0.9|hello world\n0.8|goodbye moon\n")

    meta = SongMeta(prompt="test", lyrics="[verse]\nhello world\ngoodbye moon")
    mock_response = ClaudeResponse(text='{"score": 9, "issues": [], "summary": "great"}')

    with patch("songmaker_cli.scoring.lyrical_coherence.call_claude", return_value=mock_response):
        result = score_lyrical_coherence(mp3, meta=meta)

    assert result.score == 9
    assert result.summary == "great"

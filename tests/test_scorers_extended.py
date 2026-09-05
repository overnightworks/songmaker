"""Extended tests for spectral_quality, audiobox_aesthetics, text_accuracy, lyrical_coherence."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

librosa = pytest.importorskip("librosa")

from conftest import read_wav, write_wav
from songmaker_cli.api_models.whisper import WhisperCue, WhisperWordCue
from songmaker_cli.constants import JUDGE_FAILURE_TIMEOUT
from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.models import (
    AudioBoxScore,
    ScorerOutcome,
    ScorerRun,
    SongScores,
    SpectralQualityScore,
    TextAccuracyScore,
)
from songmaker_cli.scoring.pipeline import AudioData

SR = 22050


def _sine_wav(tmp_path: Path, duration: float = 3.0, name: str = "test.wav") -> Path:
    t = np.arange(int(SR * duration)) / SR
    audio = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    path = tmp_path / name
    write_wav(path, audio, SR)
    return path


# ── spectral_quality ────────────────────────────────────────────────


def test_spectral_quality_clean_audio(tmp_path: Path) -> None:
    from songmaker_cli.scoring.spectral_quality import score_spectral_quality

    wav = _sine_wav(tmp_path, duration=5.0)
    audio, sr = read_wav(wav)
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


def test_force_cpu_env_restores_existing(monkeypatch) -> None:
    from songmaker_cli.scoring.audiobox_aesthetics import _force_cpu_env

    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
    with _force_cpu_env():
        assert os.environ["CUDA_VISIBLE_DEVICES"] == ""
    assert os.environ["CUDA_VISIBLE_DEVICES"] == "0,1"


def test_get_predictor_caches() -> None:
    from songmaker_cli.scoring import audiobox_aesthetics as ab
    from songmaker_cli.scoring.audiobox_aesthetics import _get_predictor

    ab.clear_cache()
    mock_cls = MagicMock(return_value=MagicMock())

    with patch("audiobox_aesthetics.infer.AesPredictor", mock_cls):
        p1 = _get_predictor(device="cpu")
        p2 = _get_predictor(device="cpu")

    assert p1 is p2
    assert mock_cls.call_count == 1
    ab.clear_cache()


def test_get_predictor_cpu_uses_force_env() -> None:
    from songmaker_cli.scoring import audiobox_aesthetics as ab
    from songmaker_cli.scoring.audiobox_aesthetics import _get_predictor

    ab.clear_cache()
    mock_cls = MagicMock(return_value=MagicMock())

    with patch("audiobox_aesthetics.infer.AesPredictor", mock_cls):
        _get_predictor(device="cpu")

    mock_cls.assert_called_once()
    ab.clear_cache()


def test_get_predictor_cuda_no_force_env() -> None:
    from songmaker_cli.scoring import audiobox_aesthetics as ab
    from songmaker_cli.scoring.audiobox_aesthetics import _get_predictor

    ab.clear_cache()
    mock_cls = MagicMock(return_value=MagicMock())

    with patch("audiobox_aesthetics.infer.AesPredictor", mock_cls):
        _get_predictor(device="cuda")

    mock_cls.assert_called_once()
    ab.clear_cache()


def test_get_predictor_default_cache() -> None:
    from songmaker_cli.scoring import audiobox_aesthetics as ab
    from songmaker_cli.scoring.audiobox_aesthetics import _get_predictor

    ab.clear_cache()
    mock_cls = MagicMock(return_value=MagicMock())

    with patch("audiobox_aesthetics.infer.AesPredictor", mock_cls):
        result = _get_predictor(device="cpu")

    assert result is not None
    ab.clear_cache()


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


@pytest.mark.parametrize(
    "line",
    (
        "oh oh oh",
        "la la la",
        "ah na da hey yeah eh",
        "oo ooh hm hmm mm mmm wo woo wooh",
        "OH, YEAH",
    ),
)
def test_is_vocalization_recognizes_supported_vocalizations(line: str) -> None:
    from songmaker_cli.scoring.text_accuracy import _is_vocalization

    assert _is_vocalization(line) is True


@pytest.mark.parametrize("line", ("o", "h", "m", "who", "hello world"))
def test_is_vocalization_rejects_lyrics_and_partial_vocalizations(line: str) -> None:
    from songmaker_cli.scoring.text_accuracy import _is_vocalization

    assert _is_vocalization(line) is False


def test_is_vocalization_accepts_an_empty_line() -> None:
    from songmaker_cli.scoring.text_accuracy import _is_vocalization

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




def test_get_whisper_model_caches() -> None:
    from songmaker_cli.scoring import text_accuracy as ta
    from songmaker_cli.scoring.text_accuracy import _get_whisper_model

    ta.clear_cache()
    mock_model = MagicMock()

    with patch("faster_whisper.WhisperModel", return_value=mock_model) as mock_cls:
        m1 = _get_whisper_model("base", device="cpu")
        m2 = _get_whisper_model("base", device="cpu")

    assert m1 is m2
    assert mock_cls.call_count == 1
    ta.clear_cache()


def test_get_whisper_model_default_cache() -> None:
    from songmaker_cli.scoring import text_accuracy as ta
    from songmaker_cli.scoring.text_accuracy import _get_whisper_model

    ta.clear_cache()
    mock_model = MagicMock()

    with patch("faster_whisper.WhisperModel", return_value=mock_model):
        result = _get_whisper_model("base", device="cpu")

    assert result is mock_model
    ta.clear_cache()


def _whisper_word(text: str, start: float, end: float) -> MagicMock:
    word = MagicMock()
    word.word = text
    word.start = start
    word.end = end
    return word


def _whisper_segment(
    text: str, start: float, end: float, words: list[MagicMock] | None = None,
) -> MagicMock:
    seg = MagicMock()
    seg.text = text
    seg.start = start
    seg.end = end
    seg.words = words
    return seg


def test_transcribe() -> None:
    from songmaker_cli.scoring.text_accuracy import _transcribe

    mock_segment = _whisper_segment("hello world", 0.0, 1.25)
    mock_info = MagicMock()
    mock_info.language = "en"
    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter([mock_segment]), mock_info)
    text, segments, detected_lang = _transcribe(Path("test.mp3"), "en", mock_model, "hint")
    assert text == "hello world"
    assert len(segments) == 1
    assert segments[0] == WhisperCue(start=0.0, end=1.25, text="hello world")
    assert detected_lang == "en"
    mock_model.transcribe.assert_called_once()


def test_transcribe_keeps_segment_start_end() -> None:
    from songmaker_cli.scoring.text_accuracy import _transcribe

    mock_model = MagicMock()
    mock_model.transcribe.return_value = (
        iter([
            _whisper_segment("hello", 0.12, 0.80),
            _whisper_segment("world", 0.80, 1.64),
        ]),
        MagicMock(language="en"),
    )
    _text, cues, _lang = _transcribe(Path("test.mp3"), "en", mock_model)
    assert cues == [
        WhisperCue(start=0.12, end=0.80, text="hello"),
        WhisperCue(start=0.80, end=1.64, text="world"),
    ]


def test_transcribe_asks_whisper_for_word_timestamps() -> None:
    from songmaker_cli.scoring.text_accuracy import _transcribe

    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter([]), MagicMock(language="en"))

    _transcribe(Path("test.mp3"), "en", mock_model)

    assert mock_model.transcribe.call_args.kwargs["word_timestamps"] is True


def test_transcribe_keeps_the_word_timestamps_of_a_segment() -> None:
    from songmaker_cli.scoring.text_accuracy import _transcribe

    mock_model = MagicMock()
    mock_model.transcribe.return_value = (
        iter([_whisper_segment("hello world", 0.0, 1.25, [
            _whisper_word(" hello", 0.0, 0.6),
            _whisper_word(" world", 0.6, 1.25),
        ])]),
        MagicMock(language="en"),
    )

    _text, cues, _lang = _transcribe(Path("test.mp3"), "en", mock_model)

    assert cues == [WhisperCue(start=0.0, end=1.25, text="hello world", words=[
        WhisperWordCue(start=0.0, end=0.6, text="hello"),
        WhisperWordCue(start=0.6, end=1.25, text="world"),
    ])]


def test_transcribe_leaves_a_segment_without_word_timestamps_wordless() -> None:
    from songmaker_cli.scoring.text_accuracy import _transcribe

    mock_model = MagicMock()
    mock_model.transcribe.return_value = (
        iter([_whisper_segment("hello world", 0.0, 1.25)]),
        MagicMock(language="en"),
    )

    _text, cues, _lang = _transcribe(Path("test.mp3"), "en", mock_model)

    assert cues[0].words is None


def test_transcribe_drops_blank_words_and_keeps_the_rest() -> None:
    from songmaker_cli.scoring.text_accuracy import _transcribe

    mock_model = MagicMock()
    mock_model.transcribe.return_value = (
        iter([_whisper_segment("hello", 0.0, 1.0, [
            _whisper_word("   ", 0.0, 0.2),
            _whisper_word(" hello", 0.2, 1.0),
        ])]),
        MagicMock(language="en"),
    )

    _text, cues, _lang = _transcribe(Path("test.mp3"), "en", mock_model)

    assert cues[0].words == [WhisperWordCue(start=0.2, end=1.0, text="hello")]


def test_transcribe_leaves_a_segment_of_only_blank_words_wordless() -> None:
    from songmaker_cli.scoring.text_accuracy import _transcribe

    mock_model = MagicMock()
    mock_model.transcribe.return_value = (
        iter([_whisper_segment("hello", 0.0, 1.0, [_whisper_word("  ", 0.0, 1.0)])]),
        MagicMock(language="en"),
    )

    _text, cues, _lang = _transcribe(Path("test.mp3"), "en", mock_model)

    assert cues[0].words is None


def test_transcribe_missing_word_timing_is_rejected() -> None:
    from songmaker_cli.scoring.text_accuracy import _transcribe

    word = _whisper_word(" hello", 0.0, 1.0)
    word.end = None
    mock_model = MagicMock()
    mock_model.transcribe.return_value = (
        iter([_whisper_segment("hello", 0.0, 1.0, [word])]),
        MagicMock(language="en"),
    )

    with pytest.raises(ValueError, match="Whisper word is missing start or end"):
        _transcribe(Path("test.mp3"), "en", mock_model)


def test_transcribe_skips_empty_text_segments() -> None:
    from songmaker_cli.scoring.text_accuracy import _transcribe

    mock_model = MagicMock()
    mock_model.transcribe.return_value = (
        iter([
            _whisper_segment("   ", 0.0, 0.4),
            _whisper_segment("hello", 0.4, 1.1),
        ]),
        MagicMock(language="en"),
    )
    text, cues, _lang = _transcribe(Path("test.mp3"), "en", mock_model)
    assert text == "hello"
    assert cues == [WhisperCue(start=0.4, end=1.1, text="hello")]


def test_transcribe_missing_timing_is_rejected() -> None:
    from songmaker_cli.scoring.text_accuracy import _transcribe

    seg = MagicMock()
    seg.text = "hello"
    seg.start = None
    seg.end = 1.0
    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter([seg]), MagicMock(language="en"))
    with pytest.raises(ValueError, match="missing start or end"):
        _transcribe(Path("test.mp3"), "en", mock_model)


def test_transcribe_rejects_backward_range() -> None:
    from pydantic import ValidationError

    from songmaker_cli.scoring.text_accuracy import _transcribe

    mock_model = MagicMock()
    mock_model.transcribe.return_value = (
        iter([_whisper_segment("hello", 2.0, 1.0)]),
        MagicMock(language="en"),
    )
    with pytest.raises(ValidationError, match="end must not be before start"):
        _transcribe(Path("test.mp3"), "en", mock_model)


def test_transcribe_auto_detect_language() -> None:
    from songmaker_cli.scoring.text_accuracy import _transcribe

    mock_segment = _whisper_segment("hallo welt", 0.0, 0.9)
    mock_info = MagicMock()
    mock_info.language = "de"
    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter([mock_segment]), mock_info)
    text, segments, detected_lang = _transcribe(Path("test.mp3"), None, mock_model, "hint")
    assert text == "hallo welt"
    assert detected_lang == "de"
    call_kwargs = mock_model.transcribe.call_args[1]
    assert call_kwargs["language"] is None


def test_score_text_accuracy_full(tmp_path: Path) -> None:
    from songmaker_cli.scoring.pipeline import PipelineConfig
    from songmaker_cli.scoring.text_accuracy import score_text_accuracy

    meta = SongMeta(prompt="test", lyrics="[verse]\nhello world\ngoodbye moon")

    mock_info = MagicMock()
    mock_info.language = "en"
    mock_model = MagicMock()
    mock_model.transcribe.return_value = (
        iter([
            _whisper_segment("hello world", 0.0, 1.1),
            _whisper_segment("goodbye moon", 1.1, 2.4),
        ]),
        mock_info,
    )
    config = PipelineConfig(device="cpu", whisper_model="base")

    with patch("songmaker_cli.scoring.text_accuracy._get_whisper_model", return_value=mock_model):
        result = score_text_accuracy(tmp_path / "test.mp3", meta=meta, config=config)

    assert isinstance(result, TextAccuracyScore)
    assert result.similarity_ratio > 0
    assert result.detected_language == "en"
    assert result.transcript == "hello world\ngoodbye moon"
    assert result.whisper_cues == (
        WhisperCue(start=0.0, end=1.1, text="hello world"),
        WhisperCue(start=1.1, end=2.4, text="goodbye moon"),
    )


def test_score_text_accuracy_no_meta(tmp_path: Path) -> None:
    from songmaker_cli.scoring.pipeline import PipelineConfig
    from songmaker_cli.scoring.text_accuracy import score_text_accuracy

    info = MagicMock()
    info.language = "en"
    mock_model = MagicMock()
    mock_model.transcribe.return_value = (
        iter([_whisper_segment("la la la", 0.2, 1.8)]), info,
    )
    config = PipelineConfig(device="cpu", whisper_model="base")

    with patch(
        "songmaker_cli.scoring.text_accuracy._get_whisper_model",
        return_value=mock_model,
    ):
        result = score_text_accuracy(tmp_path / "test.mp3", meta=None, config=config)

    assert isinstance(result, TextAccuracyScore)
    assert result.similarity_ratio == 0.0
    assert result.intended_line_texts == ()
    assert "la la la" in result.transcribed_line_texts
    assert result.whisper_cues == (
        WhisperCue(start=0.2, end=1.8, text="la la la"),
    )
    assert result.transcript == "la la la"
    call_kwargs = mock_model.transcribe.call_args[1]
    assert call_kwargs["language"] is None
    assert "initial_prompt" not in call_kwargs


# ── TextAccuracyScore properties ────────────────────────────────────


def test_text_accuracy_score_intended_lines() -> None:
    from songmaker_cli.scoring.models import TextAccuracyScore

    score = TextAccuracyScore(
        similarity_ratio=0.9,
        intended_line_texts=("hello world", "goodbye moon", "third line"),
        transcribed_line_texts=("hello world",),
    )
    assert score.intended_lines == 3


def test_text_accuracy_score_transcribed_lines() -> None:
    from songmaker_cli.scoring.models import TextAccuracyScore

    score = TextAccuracyScore(
        similarity_ratio=0.8,
        intended_line_texts=("line one",),
        transcribed_line_texts=("line one", "extra line"),
    )
    assert score.transcribed_lines == 2


def test_text_accuracy_score_empty_lines() -> None:
    from songmaker_cli.scoring.models import TextAccuracyScore

    score = TextAccuracyScore(
        similarity_ratio=0.0,
        intended_line_texts=(),
        transcribed_line_texts=(),
    )
    assert score.intended_lines == 0
    assert score.transcribed_lines == 0


def test_text_accuracy_score_detected_language() -> None:
    from songmaker_cli.scoring.models import TextAccuracyScore

    score = TextAccuracyScore(
        similarity_ratio=0.9,
        intended_line_texts=("hallo welt",),
        transcribed_line_texts=("hallo welt",),
        detected_language="de",
    )
    assert score.detected_language == "de"


def test_text_accuracy_score_detected_language_default() -> None:
    from songmaker_cli.scoring.models import TextAccuracyScore

    score = TextAccuracyScore(
        similarity_ratio=0.9,
        intended_line_texts=("hello",),
        transcribed_line_texts=("hello",),
    )
    assert score.detected_language is None


# ── lyrical_coherence — judged in the worker parent ────────────────

_LYRICS = "[verse]\nhello world\ngoodbye moon"


def _child_result(*transcribed: str) -> SongScores:
    """What the scorer child sends back: a text_accuracy value and its run."""
    return SongScores(
        text_accuracy=TextAccuracyScore(
            similarity_ratio=0.9,
            intended_line_texts=("hello world", "goodbye moon"),
            transcribed_line_texts=transcribed,
        ),
        runs=(ScorerRun(scorer="text_accuracy", outcome=ScorerOutcome.OK),),
    )


def _judge(scores: SongScores, meta: SongMeta | None, **overrides: object) -> SongScores:
    from songmaker_cli.scoring.lyrical_coherence import (
        CoherenceJudgeConfig,
        judge_lyrical_coherence,
    )

    config = CoherenceJudgeConfig(
        **{"provider": "claude", "model": "claude-test", "timeout": 60, **overrides},
    )
    return judge_lyrical_coherence(scores, meta, config)


def _claude_answers(text: str) -> object:
    from songmaker_cli.claude.provider import ClaudeResponse

    return patch(
        "songmaker_cli.cowriter.claude_adapter.call_claude",
        return_value=ClaudeResponse(text=text),
    )


def test_the_judge_reads_the_same_transcript_the_generation_stores() -> None:
    """One owner for the text: TextAccuracyScore.transcript. The judge sees
    exactly what ends up in Generation.whisper_text."""
    child_result = _child_result("hello world", "goodbye moon")

    with _claude_answers('{"score": 9, "issues": [], "summary": "great"}') as claude:
        _judge(child_result, SongMeta(prompt="test", lyrics=_LYRICS))

    assert child_result.text_accuracy.transcript in claude.call_args.args[0]
    assert child_result.text_accuracy.transcript == "hello world\ngoodbye moon"


def test_judge_is_skipped_when_the_song_has_no_lyrics() -> None:
    judged = _judge(_child_result("hello world"), None)

    assert judged.lyrical_coherence is None
    assert judged.runs[-1].outcome is ScorerOutcome.SKIPPED
    assert "No lyrics" in judged.runs[-1].detail


def test_judge_is_skipped_when_the_run_produced_no_transcription() -> None:
    """text_accuracy runs in the child; without its value there is nothing
    for the judge to read, so lyrical_coherence keeps its stored score."""
    child_result = SongScores(
        runs=(ScorerRun(scorer="text_accuracy", outcome=ScorerOutcome.TIMED_OUT),),
    )

    judged = _judge(child_result, SongMeta(prompt="test", lyrics=_LYRICS))

    assert judged.lyrical_coherence is None
    assert judged.runs[-1].outcome is ScorerOutcome.SKIPPED
    assert "No Whisper transcription" in judged.runs[-1].detail
    assert judged.refreshed_output_keys() == frozenset()


def test_judge_scores_zero_when_no_vocals_were_transcribed() -> None:
    judged = _judge(_child_result(), SongMeta(prompt="test", lyrics=_LYRICS))

    assert judged.lyrical_coherence.score == 0
    assert "No vocals" in judged.lyrical_coherence.issues[0]
    assert judged.runs[-1].outcome is ScorerOutcome.OK


def test_judge_records_claudes_verdict_alongside_the_childs_scores() -> None:
    with _claude_answers('{"score": 9, "issues": [], "summary": "great"}'):
        judged = _judge(
            _child_result("hello world", "goodbye moon"),
            SongMeta(prompt="test", lyrics=_LYRICS),
        )

    assert judged.lyrical_coherence.score == 9
    assert judged.lyrical_coherence.summary == "great"
    assert judged.text_accuracy is not None
    assert [run.scorer for run in judged.runs] == ["text_accuracy", "lyrical_coherence"]
    assert "lyrical_coherence" in judged.refreshed_output_keys()


def test_judge_failure_leaves_the_stored_coherence_score_alone() -> None:
    with patch(
        "songmaker_cli.cowriter.claude_adapter.call_claude",
        side_effect=RuntimeError("Claude unreachable"),
    ):
        judged = _judge(
            _child_result("hello world"), SongMeta(prompt="test", lyrics=_LYRICS),
        )

    assert judged.lyrical_coherence is None
    assert judged.runs[-1].outcome is ScorerOutcome.FAILED
    assert judged.runs[-1].detail == "Selected route failed."
    assert "lyrical_coherence" not in judged.refreshed_output_keys()


def test_judge_config_rejects_a_timeout_shorter_than_the_cli_preflight() -> None:
    from songmaker_cli.scoring.lyrical_coherence import CoherenceJudgeConfig

    with pytest.raises(ValueError, match="at least 5 seconds"):
        CoherenceJudgeConfig(provider="claude", model="claude-test", timeout=4)


def test_judge_watchdog_is_the_last_safety_for_a_provider_that_ignores_its_budget() -> None:
    provider_release = threading.Event()
    provider_stopped = threading.Event()

    def ignores_timeout(*_args: object, **_kwargs: object) -> None:
        try:
            provider_release.wait()
        finally:
            provider_stopped.set()

    with (
        patch(
            "songmaker_cli.cowriter.claude_adapter.call_claude",
            side_effect=ignores_timeout,
        ),
        patch(
            "songmaker_cli.scoring.lyrical_coherence.judge_watchdog_timeout",
            return_value=0.01,
        ),
    ):
        judged = _judge(
            _child_result("hello world"),
            SongMeta(prompt="test", lyrics=_LYRICS),
            timeout=5,
        )
        provider_release.set()

    assert judged.runs[-1].outcome is ScorerOutcome.TIMED_OUT
    assert judged.runs[-1].detail == JUDGE_FAILURE_TIMEOUT
    assert judged.lyrical_coherence is None
    assert provider_stopped.wait(timeout=1)


def test_judge_uses_the_model_from_its_config_not_a_hardcoded_default() -> None:
    """Which model judges a song is a configured decision (#315) — the DB
    setting the caller resolved, never a value the judge picks itself."""
    with _claude_answers('{"score": 7, "issues": [], "summary": "ok"}') as mock_call_claude:
        _judge(
            _child_result("hello world"),
            SongMeta(prompt="test", lyrics=_LYRICS),
            model="test-model",
        )

    assert mock_call_claude.call_args.kwargs["model"] == "test-model"


def test_judge_claude_call_gets_its_credential_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Claude path still resolves its credential through Settings
    (#315), not something the adapter invents — ``call_claude`` must always
    receive the configured key explicitly rather than pick one up itself."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "settings-key")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()

    with _claude_answers('{"score": 7, "issues": [], "summary": "ok"}') as mock_call_claude:
        _judge(_child_result("hello world"), SongMeta(prompt="test", lyrics=_LYRICS))

    assert mock_call_claude.call_args.kwargs["api_key"] == "settings-key"
    get_settings.cache_clear()


def test_judge_routes_to_the_configured_provider_and_no_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The judge is provider-neutral (#315): a grok judge must call grok's
    adapter with grok's own credential, never fall back to Claude."""
    monkeypatch.setenv("XAI_API_KEY", "grok-key")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()

    with (
        patch(
            "songmaker_cli.cowriter.dispatch.call_openai_compatible_once",
            return_value='{"score": 8, "issues": [], "summary": "grok verdict"}',
        ) as grok_call,
        patch("songmaker_cli.cowriter.claude_adapter.call_claude") as claude_call,
    ):
        judged = _judge(
            _child_result("hello world"),
            SongMeta(prompt="test", lyrics=_LYRICS),
            provider="grok",
            model="grok-4.6",
        )

    assert judged.lyrical_coherence.score == 8
    assert judged.lyrical_coherence.summary == "grok verdict"
    assert grok_call.call_args.kwargs["provider"] == "grok"
    assert grok_call.call_args.kwargs["model"] == "grok-4.6"
    claude_call.assert_not_called()


def test_judge_fails_loud_and_named_when_its_provider_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unset credential for the chosen provider is a named failure, never
    a silent fallback to Claude (#315)."""
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()

    with patch("songmaker_cli.cowriter.claude_adapter.call_claude") as claude_call:
        judged = _judge(
            _child_result("hello world"),
            SongMeta(prompt="test", lyrics=_LYRICS),
            provider="grok",
            model="grok-4.6",
        )

    assert judged.lyrical_coherence is None
    assert judged.runs[-1].outcome is ScorerOutcome.FAILED
    assert judged.runs[-1].detail == "API key is not set."
    claude_call.assert_not_called()


def test_score_text_accuracy_hallucination(tmp_path: Path) -> None:
    from songmaker_cli.scoring.pipeline import PipelineConfig
    from songmaker_cli.scoring.text_accuracy import score_text_accuracy

    meta = SongMeta(prompt="test", lyrics="[verse]\nhello world")

    mock_segments = [
        _whisper_segment("thank you", float(i), float(i) + 0.5)
        for i in range(6)
    ]
    mock_info = MagicMock()
    mock_info.language = "en"
    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter(mock_segments), mock_info)
    config = PipelineConfig(device="cpu", whisper_model="base")

    with patch("songmaker_cli.scoring.text_accuracy._get_whisper_model", return_value=mock_model):
        result = score_text_accuracy(tmp_path / "test.mp3", meta=meta, config=config)

    assert result.transcribed_line_texts == ()
    assert result.whisper_cues == ()


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


def test_bpm_detect_extracts_first_element() -> None:
    from songmaker_cli.scoring.bpm_accuracy import _detect_bpm

    with patch("librosa.feature.tempo", return_value=np.array([120.0])):
        bpm = _detect_bpm(np.zeros(SR), SR)
    assert bpm == 120.0


def test_bpm_detect_multi_element_array() -> None:
    from songmaker_cli.scoring.bpm_accuracy import _detect_bpm

    with patch("librosa.feature.tempo", return_value=np.array([130.0, 65.0])):
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


def test_song_scores_to_dict_with_detected_language() -> None:
    from songmaker_cli.scoring.models import SongScores, TextAccuracyScore

    scores = SongScores(
        text_accuracy=TextAccuracyScore(
            similarity_ratio=0.85,
            intended_line_texts=("hallo",),
            transcribed_line_texts=("hallo",),
            detected_language="de",
        ),
    )
    d = scores.to_dict()
    assert d["text_accuracy"] == 85.0
    assert d["detected_language"] == "de"


def test_song_scores_to_dict_no_detected_language() -> None:
    from songmaker_cli.scoring.models import SongScores, TextAccuracyScore

    scores = SongScores(
        text_accuracy=TextAccuracyScore(
            similarity_ratio=0.9,
            intended_line_texts=("hello",),
            transcribed_line_texts=("hello",),
        ),
    )
    d = scores.to_dict()
    assert d["text_accuracy"] == 90.0
    assert "detected_language" not in d


# ── scoring/pipeline.py gaps ────────────────────────────────────────


def test_available_scorers() -> None:
    from songmaker_cli.scoring.pipeline import available_scorers

    result = available_scorers()
    assert "text_accuracy" in result
    assert "spectral_quality" in result


def test_scorer_timeout() -> None:
    import time

    from songmaker_cli.scoring.pipeline import _call_with_timeout, _ScorerTimeout

    def slow_fn() -> None:
        time.sleep(5)

    with pytest.raises(_ScorerTimeout):
        _call_with_timeout(slow_fn, timeout=1, name="slow")


def test_scorer_no_timeout() -> None:
    from songmaker_cli.scoring.pipeline import _call_with_timeout

    result = _call_with_timeout(lambda: "result", timeout=0, name="fast")
    assert result == "result"

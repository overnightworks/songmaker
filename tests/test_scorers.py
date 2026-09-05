"""Tests for silence, BPM, and emotional dynamics scorers."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
import pytest

librosa = pytest.importorskip("librosa")

from conftest import write_wav
from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.bpm_accuracy import (
    _closest_octave_match,
    _detect_bpm,
    score_bpm,
)
from songmaker_cli.scoring.emotional_dynamics import (
    _normalize_contrast,
    _normalize_cv,
    _rms_contrast_ratio,
    _safe_cv,
    _split_into_sections,
    score_emotional_dynamics,
)
from songmaker_cli.scoring.silence_detection import _find_gaps, score_silence

SR = 22050


@pytest.fixture
def wav_file(tmp_path: Path) -> Callable[..., Path]:
    """Factory: write a WAV file from a numpy array."""

    def _make(
        audio: np.ndarray, sr: int = SR, name: str = "test.wav",
    ) -> Path:
        path = tmp_path / name
        write_wav(path, audio, sr)
        return path

    return _make


def _sine(freq: float, duration: float, sr: int = SR) -> np.ndarray:
    t = np.arange(int(sr * duration)) / sr
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _silence_array(duration: float, sr: int = SR) -> np.ndarray:
    return np.zeros(int(sr * duration), dtype=np.float32)


def _click_track(bpm: float, duration: float, sr: int = SR) -> np.ndarray:
    """Generate a click track at the given BPM for beat detection."""
    n_samples = int(sr * duration)
    audio = np.zeros(n_samples, dtype=np.float32)
    interval = int(60 / bpm * sr)
    click_len = min(int(0.01 * sr), interval // 2)
    for i in range(0, n_samples, interval):
        audio[i: i + click_len] = 0.8
    return audio


def _make_song_meta(bpm: int = 120) -> SongMeta:
    return SongMeta(
        title="Test", album="test", prompt="test", lyrics="hello",
        bpm=bpm,
    )


# ── Silence detection ────────────────────────────────────────────────


class TestSilenceDetection:
    def test_clean_audio_no_gaps(self, wav_file: Callable[..., Path]) -> None:
        audio = _sine(440, 10.0)
        path = wav_file(audio)
        result = score_silence(path)
        assert result.gap_count == 0
        assert result.longest_gap_seconds == 0.0

    def test_audio_with_silence_gap(self, wav_file: Callable[..., Path]) -> None:
        parts = [_sine(440, 4.0), _silence_array(4.0), _sine(440, 4.0)]
        audio = np.concatenate(parts)
        path = wav_file(audio)
        result = score_silence(path)
        assert result.gap_count >= 1
        assert result.longest_gap_seconds >= 2.0

    def test_short_gaps_ignored(self, wav_file: Callable[..., Path]) -> None:
        parts = [_sine(440, 4.0), _silence_array(1.0), _sine(440, 4.0)]
        audio = np.concatenate(parts)
        path = wav_file(audio)
        result = score_silence(path)
        assert result.gap_count == 0

    def test_intro_outro_silence_trimmed(self, wav_file: Callable[..., Path]) -> None:
        parts = [_silence_array(3.0), _sine(440, 6.0), _silence_array(3.0)]
        audio = np.concatenate(parts)
        path = wav_file(audio)
        result = score_silence(path)
        assert result.gap_count == 0

    def test_find_gaps_no_intervals(self) -> None:
        gaps = _find_gaps(np.array([]).reshape(0, 2), 44100, 44100)
        assert len(gaps) == 1
        assert gaps[0][1] == 1.0

    def test_has_problems_clean(self) -> None:
        from songmaker_cli.scoring.models import SilenceScore

        score = SilenceScore(total_silence_seconds=0.0, longest_gap_seconds=0.0, gap_count=0)
        assert score.has_problems is False

    def test_has_problems_with_gaps(self) -> None:
        from songmaker_cli.scoring.models import SilenceScore

        score = SilenceScore(total_silence_seconds=4.0, longest_gap_seconds=4.0, gap_count=1)
        assert score.has_problems is True


# ── BPM accuracy ─────────────────────────────────────────────────────


class TestBpmAccuracy:
    def test_perfect_bpm(self, wav_file: Callable[..., Path]) -> None:
        audio = _click_track(120, 15.0)
        path = wav_file(audio)
        meta = _make_song_meta(bpm=120)
        result = score_bpm(path, meta=meta)
        assert result.deviation_percent < 10.0

    def test_octave_correction_exact_half(self) -> None:
        best, corrected = _closest_octave_match(60.0, 120)
        assert best == 120.0
        assert corrected is True

    def test_octave_correction_double_closer(self) -> None:
        """When detected is 65 and requested is 120, double (130) is closer than raw (65)."""
        best, corrected = _closest_octave_match(65.0, 120)
        assert best == 130.0
        assert corrected is True

    def test_no_octave_correction_when_close(self) -> None:
        best, corrected = _closest_octave_match(118.0, 120)
        assert best == 118.0
        assert corrected is False

    def test_no_meta_raises(self, wav_file: Callable[..., Path]) -> None:
        audio = _sine(440, 5.0)
        path = wav_file(audio)
        with pytest.raises(ValueError, match="No BPM"):
            score_bpm(path, meta=None)

    def test_zero_bpm_raises(self, wav_file: Callable[..., Path]) -> None:
        audio = _sine(440, 5.0)
        path = wav_file(audio)
        meta = _make_song_meta(bpm=0)
        with pytest.raises(ValueError, match="No BPM"):
            score_bpm(path, meta=meta)

    def test_detect_bpm_returns_float(self) -> None:
        audio = _click_track(100, 10.0)
        result = _detect_bpm(audio, SR)
        assert isinstance(result, float)
        assert result > 0


# ── Emotional dynamics ───────────────────────────────────────────────


class TestEmotionalDynamics:
    def test_monotone_low_score(self, wav_file: Callable[..., Path]) -> None:
        audio = _sine(440, 12.0)
        path = wav_file(audio)
        result = score_emotional_dynamics(path)
        assert result.overall_expressiveness < 0.3
        assert result.pitch_cv < 0.1

    def test_varied_sections_higher_score(self, wav_file: Callable[..., Path]) -> None:
        sections = [
            _sine(220, 2.0) * 0.2,
            _sine(440, 2.0) * 0.8,
            _sine(330, 2.0) * 0.1,
            _sine(550, 2.0) * 0.9,
            _sine(220, 2.0) * 0.3,
            _sine(440, 2.0) * 0.7,
        ]
        audio = np.concatenate(sections)
        path = wav_file(audio)
        result = score_emotional_dynamics(path)
        assert result.overall_expressiveness > 0.2
        assert result.rms_contrast > 2.0

    def test_split_into_sections_even(self) -> None:
        audio = np.arange(120, dtype=np.float32)
        sections = _split_into_sections(audio, 6)
        assert len(sections) == 6
        assert len(sections[0]) == 20

    def test_split_into_sections_trailing_samples(self) -> None:
        audio = np.arange(125, dtype=np.float32)
        sections = _split_into_sections(audio, 6)
        assert len(sections) == 6
        total_samples = sum(len(s) for s in sections)
        assert total_samples == 125
        assert len(sections[-1]) == 20 + 5

    def test_rms_contrast_identical(self) -> None:
        sections = [np.ones(100) * 0.5, np.ones(100) * 0.5]
        ratio = _rms_contrast_ratio(sections)
        assert ratio == pytest.approx(1.0, abs=0.01)

    def test_rms_contrast_varied(self) -> None:
        sections = [np.ones(100) * 0.1, np.ones(100) * 0.9]
        ratio = _rms_contrast_ratio(sections)
        assert ratio == pytest.approx(9.0, abs=0.1)

    def test_safe_cv_empty(self) -> None:
        assert _safe_cv([]) == 0.0

    def test_safe_cv_single(self) -> None:
        assert _safe_cv([5.0]) == 0.0

    def test_safe_cv_normal(self) -> None:
        cv = _safe_cv([10.0, 20.0, 30.0])
        assert cv > 0
        assert cv < 1

    def test_normalize_cv_at_ceiling(self) -> None:
        assert _normalize_cv(0.5, max_cv=0.5) == 1.0

    def test_normalize_cv_above_ceiling(self) -> None:
        assert _normalize_cv(1.0, max_cv=0.5) == 1.0

    def test_normalize_cv_half(self) -> None:
        assert _normalize_cv(0.25, max_cv=0.5) == pytest.approx(0.5)

    def test_normalize_contrast_no_contrast(self) -> None:
        assert _normalize_contrast(1.0, max_contrast=3.0) == 0.0

    def test_normalize_contrast_at_ceiling(self) -> None:
        assert _normalize_contrast(3.0, max_contrast=3.0) == 1.0

    def test_normalize_contrast_midpoint(self) -> None:
        assert _normalize_contrast(2.0, max_contrast=3.0) == pytest.approx(0.5)

    def test_parallel_pyin_path(self, wav_file: Callable[..., Path]) -> None:
        """Exercise the ProcessPoolExecutor path (>5s per section)."""
        sections = [
            _sine(220, 6.0) * 0.2,
            _sine(440, 6.0) * 0.8,
            _sine(330, 6.0) * 0.1,
            _sine(550, 6.0) * 0.9,
            _sine(220, 6.0) * 0.3,
            _sine(440, 6.0) * 0.7,
        ]
        audio = np.concatenate(sections)
        path = wav_file(audio)
        result = score_emotional_dynamics(path)
        assert result.overall_expressiveness > 0
        assert result.pitch_cv > 0

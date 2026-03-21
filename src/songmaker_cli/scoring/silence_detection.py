"""Silence detection scorer — finds problematic gaps in generated audio."""

from __future__ import annotations

from pathlib import Path

import librosa
import numpy as np

from songmaker_cli.constants import (
    SCORING_SAMPLE_RATE,
    SILENCE_MIN_GAP_SECONDS,
    SILENCE_TOP_DB,
    SILENCE_TRIM_SECONDS,
)
from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.models import SilenceScore
from songmaker_cli.scoring.pipeline import register


@register("silence")
def score_silence(mp3_path: Path, meta: SongMeta | None = None) -> SilenceScore:
    """Detect problematic silence gaps in the interior of a song."""
    audio, sr = librosa.load(mp3_path, sr=SCORING_SAMPLE_RATE, mono=True)
    duration = len(audio) / sr

    trim_samples = int(SILENCE_TRIM_SECONDS * sr)
    interior = audio[trim_samples: len(audio) - trim_samples]

    if len(interior) == 0:
        return SilenceScore(total_silence_seconds=0.0, longest_gap_seconds=0.0, gap_count=0)

    non_silent = librosa.effects.split(interior, top_db=SILENCE_TOP_DB)

    gaps = _find_gaps(non_silent, len(interior), sr)
    problematic = [(start, dur) for start, dur in gaps if dur >= SILENCE_MIN_GAP_SECONDS]

    total = sum(dur for _, dur in problematic)
    longest = max((dur for _, dur in problematic), default=0.0)

    return SilenceScore(
        total_silence_seconds=round(total, 2),
        longest_gap_seconds=round(longest, 2),
        gap_count=len(problematic),
    )


def _find_gaps(
    non_silent_intervals: np.ndarray, total_samples: int, sr: int,
) -> list[tuple[float, float]]:
    """Find gaps between non-silent intervals.

    Returns list of (start_seconds, duration_seconds).
    """
    gaps: list[tuple[float, float]] = []

    if len(non_silent_intervals) == 0:
        return [(0.0, total_samples / sr)]

    prev_end = 0
    for start, end in non_silent_intervals:
        if start > prev_end:
            gap_start = prev_end / sr
            gap_duration = (start - prev_end) / sr
            gaps.append((gap_start, gap_duration))
        prev_end = end

    if prev_end < total_samples:
        gap_start = prev_end / sr
        gap_duration = (total_samples - prev_end) / sr
        gaps.append((gap_start, gap_duration))

    return gaps

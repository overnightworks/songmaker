"""BPM accuracy scorer — compares detected tempo to requested BPM."""

from __future__ import annotations

import logging
from pathlib import Path

import librosa

from songmaker_cli.constants import BPM_OCTAVE_ERROR_TOLERANCE, SCORING_SAMPLE_RATE
from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.models import BpmAccuracyScore
from songmaker_cli.scoring.pipeline import register

log = logging.getLogger(__name__)


@register("bpm_accuracy")
def score_bpm(mp3_path: Path, meta: SongMeta | None = None) -> BpmAccuracyScore:
    """Detect BPM and compare to requested value from song metadata."""
    requested_bpm = _extract_requested_bpm(meta)
    if requested_bpm is None or requested_bpm == 0:
        raise ValueError("No BPM in metadata — cannot score BPM accuracy")

    audio, sr = librosa.load(mp3_path, sr=SCORING_SAMPLE_RATE, mono=True)
    detected_bpm = _detect_bpm(audio, sr)

    best_bpm, octave_corrected = _closest_octave_match(detected_bpm, requested_bpm)
    deviation = abs(best_bpm - requested_bpm) / requested_bpm * 100

    log.info(
        "BPM: detected=%.1f, requested=%d, deviation=%.1f%%%s",
        detected_bpm, requested_bpm, deviation,
        " (octave-corrected)" if octave_corrected else "",
    )

    return BpmAccuracyScore(
        detected_bpm=round(best_bpm, 1),
        requested_bpm=requested_bpm,
        deviation_percent=round(deviation, 1),
        octave_corrected=octave_corrected,
    )


def _extract_requested_bpm(meta: SongMeta | None) -> int | None:
    if meta is None:
        return None
    return meta.generation_params.get("bpm")


def _detect_bpm(audio: librosa.core.audio, sr: int) -> float:
    tempo, _ = librosa.beat.beat_track(y=audio, sr=sr)
    if hasattr(tempo, "__len__"):
        return float(tempo[0])
    return float(tempo)


def _closest_octave_match(
    detected: float, requested: int,
) -> tuple[float, bool]:
    """Handle octave errors — librosa often detects half or double BPM.

    Returns (best_matching_bpm, was_octave_corrected).
    """
    candidates = [detected, detected * 2, detected / 2]
    deviations = [(abs(c - requested) / requested, c) for c in candidates]
    best_deviation, best_bpm = min(deviations)

    octave_corrected = best_bpm != detected and best_deviation < BPM_OCTAVE_ERROR_TOLERANCE
    if not octave_corrected:
        return detected, False
    return best_bpm, True

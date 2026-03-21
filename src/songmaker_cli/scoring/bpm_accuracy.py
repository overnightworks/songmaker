"""BPM accuracy scorer — compares detected tempo to requested BPM."""

from __future__ import annotations

import logging
from pathlib import Path

import librosa
import numpy as np

from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.models import BpmAccuracyScore
from songmaker_cli.scoring.pipeline import AudioData, PipelineConfig, register

log = logging.getLogger(__name__)


@register("bpm_accuracy")
def score_bpm(
    mp3_path: Path, meta: SongMeta | None = None, audio_data: AudioData | None = None,
    config: PipelineConfig | None = None,
) -> BpmAccuracyScore:
    """Detect BPM and compare to requested value from song metadata."""
    requested_bpm = _extract_requested_bpm(meta)
    if requested_bpm is None or requested_bpm == 0:
        raise ValueError("No BPM in metadata — cannot score BPM accuracy")

    if audio_data is None:
        from songmaker_cli.scoring.pipeline import load_audio

        audio_data = load_audio(mp3_path)
    detected_bpm = _detect_bpm(audio_data.audio, audio_data.sr)

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
    bpm = meta.generation_params.get("bpm")
    return int(bpm) if bpm is not None else None


def _detect_bpm(audio: np.ndarray, sr: int) -> float:
    tempo, _ = librosa.beat.beat_track(y=audio, sr=sr)
    if hasattr(tempo, "__len__"):
        return float(tempo[0])
    return float(tempo)


def _closest_octave_match(
    detected: float, requested: int,
) -> tuple[float, bool]:
    """Handle octave errors — librosa often detects half or double BPM.

    Always returns the candidate closest to the requested BPM.
    Reports octave_corrected=True if the best match is half or double.
    """
    candidates = [(detected, False), (detected * 2, True), (detected / 2, True)]
    best_bpm, octave_corrected = min(
        candidates, key=lambda c: abs(c[0] - requested),
    )
    return best_bpm, octave_corrected

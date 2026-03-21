"""Emotional dynamics scorer — measures vocal expressiveness across sections.

This is a novel scorer. It answers: "does the song have dynamic range in
its vocal delivery, or is it monotone?"

Approach:
- Divide audio into N equal sections (proxy for verse/chorus/bridge)
- Per section: measure pitch variance, RMS energy, onset density
- High variance across sections = expressive = good score
- Monotone delivery = low variance = low score

The coefficient of variation (std/mean) is used because it's scale-invariant —
a quiet song with dynamic whisper-to-shout transitions scores the same as a
loud one with the same relative dynamics.
"""

from __future__ import annotations

import logging
from pathlib import Path

import librosa
import numpy as np

from songmaker_cli.constants import (
    DYNAMICS_ONSET_CV_CEILING,
    DYNAMICS_ONSET_WEIGHT,
    DYNAMICS_PITCH_CV_CEILING,
    DYNAMICS_PITCH_WEIGHT,
    DYNAMICS_RMS_CONTRAST_CEILING,
    DYNAMICS_RMS_WEIGHT,
    SCORING_NUM_SECTIONS,
)
from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.models import EmotionalDynamicsScore
from songmaker_cli.scoring.pipeline import AudioData, register

log = logging.getLogger(__name__)


@register("emotional_dynamics")
def score_emotional_dynamics(
    mp3_path: Path, meta: SongMeta | None = None, audio_data: AudioData | None = None,
) -> EmotionalDynamicsScore:
    """Score vocal expressiveness by analyzing pitch, energy, and rhythm variance."""
    if audio_data is None:
        from songmaker_cli.scoring.pipeline import load_audio

        audio_data = load_audio(mp3_path)
    audio, sr = audio_data.audio, audio_data.sr
    sections = _split_into_sections(audio, SCORING_NUM_SECTIONS)

    pitch_cv = _pitch_coefficient_of_variation(sections, sr)
    rms_contrast = _rms_contrast_ratio(sections)
    onset_cv = _onset_rate_coefficient_of_variation(sections, sr)

    expressiveness = (
        DYNAMICS_PITCH_WEIGHT * _normalize_cv(pitch_cv, max_cv=DYNAMICS_PITCH_CV_CEILING)
        + DYNAMICS_RMS_WEIGHT * _normalize_contrast(rms_contrast, max_contrast=DYNAMICS_RMS_CONTRAST_CEILING)
        + DYNAMICS_ONSET_WEIGHT * _normalize_cv(onset_cv, max_cv=DYNAMICS_ONSET_CV_CEILING)
    )

    log.info(
        "Dynamics: pitch_cv=%.3f, rms_contrast=%.1f, onset_cv=%.3f, expressiveness=%.2f",
        pitch_cv, rms_contrast, onset_cv, expressiveness,
    )

    return EmotionalDynamicsScore(
        pitch_cv=round(pitch_cv, 3),
        rms_contrast=round(rms_contrast, 2),
        onset_rate_cv=round(onset_cv, 3),
        overall_expressiveness=round(expressiveness, 3),
    )


def _split_into_sections(
    audio: np.ndarray, num_sections: int,
) -> list[np.ndarray]:
    """Split audio into equal-length sections.

    Trailing samples (< one section length) are appended to the last section.
    """
    section_len = len(audio) // num_sections
    sections = [audio[i * section_len: (i + 1) * section_len] for i in range(num_sections)]
    remainder = len(audio) - section_len * num_sections
    if remainder > 0:
        sections[-1] = np.concatenate([sections[-1], audio[-remainder:]])
    return sections


def _pitch_coefficient_of_variation(
    sections: list[np.ndarray], sr: int,
) -> float:
    """Compute CV of median pitch across sections using pyin.

    Sections with no detected pitch (e.g. instrumental breaks) are excluded.
    """
    medians = []
    for section in sections:
        f0, voiced_flag, _ = librosa.pyin(
            section, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"), sr=sr,
        )
        voiced_f0 = f0[voiced_flag] if voiced_flag is not None else f0[~np.isnan(f0)]
        if len(voiced_f0) > 0:
            medians.append(float(np.median(voiced_f0)))

    return _safe_cv(medians)


def _rms_contrast_ratio(sections: list[np.ndarray]) -> float:
    """Ratio of loudest to quietest section RMS.

    A high ratio means big dynamic contrast (e.g. quiet verse → loud chorus).
    """
    rms_values = []
    for section in sections:
        rms = float(np.sqrt(np.mean(section ** 2)))
        rms_values.append(max(rms, 1e-10))

    if not rms_values:
        return 1.0

    return max(rms_values) / min(rms_values)


def _onset_rate_coefficient_of_variation(
    sections: list[np.ndarray], sr: int,
) -> float:
    """CV of onset density (onsets per second) across sections.

    High CV means some sections are rhythmically dense (fast rap) while
    others are sparse (held chorus notes, bridge). That's expressiveness.
    """
    rates = []
    for section in sections:
        duration = len(section) / sr
        if duration < 0.1:
            continue
        onsets = librosa.onset.onset_detect(y=section, sr=sr, units="time")
        rates.append(len(onsets) / duration)

    return _safe_cv(rates)


def _safe_cv(values: list[float]) -> float:
    """Coefficient of variation (std/mean), safe for empty or zero-mean data."""
    if len(values) < 2:
        return 0.0
    arr = np.array(values)
    mean = arr.mean()
    if mean < 1e-10:
        return 0.0
    return float(arr.std() / mean)


def _normalize_cv(cv: float, max_cv: float) -> float:
    """Normalize CV to 0-1 range, clamped."""
    return min(cv / max_cv, 1.0)


def _normalize_contrast(ratio: float, max_contrast: float) -> float:
    """Normalize contrast ratio to 0-1. Ratio of 1.0 = no contrast = 0 score."""
    return min((ratio - 1.0) / (max_contrast - 1.0), 1.0) if ratio > 1.0 else 0.0

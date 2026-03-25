"""Spectral quality scorer — detects noise artifacts anywhere in a song.

Slides a window across the audio and measures spectral flatness per window.
Music has low flatness (structured harmonics). Noise has high flatness
(flat spectrum). Windows with abnormally high flatness relative to the
song's median are flagged as artifacts.
"""

from __future__ import annotations

import logging
from pathlib import Path

import librosa
import numpy as np

from songmaker_cli.constants import (
    SPECTRAL_ABSOLUTE_THRESHOLD,
    SPECTRAL_ARTIFACT_MULTIPLIER,
    SPECTRAL_WINDOW_SECONDS,
)
from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.models import SpectralQualityScore
from songmaker_cli.scoring.pipeline import AudioData, PipelineConfig, register

log = logging.getLogger(__name__)


@register("spectral_quality")
def score_spectral_quality(
    mp3_path: Path, meta: SongMeta | None = None, audio_data: AudioData | None = None,
    config: PipelineConfig | None = None, shared_data: dict | None = None,
) -> SpectralQualityScore:
    """Detect noise artifacts by analyzing spectral flatness across the song."""
    if audio_data is None:
        from songmaker_cli.scoring.pipeline import load_audio

        audio_data = load_audio(mp3_path)
    audio, sr = audio_data.audio, audio_data.sr

    window_samples = int(SPECTRAL_WINDOW_SECONDS * sr)
    n_windows = max(1, len(audio) // window_samples)

    flatness_values = []
    for i in range(n_windows):
        start = i * window_samples
        end = min(start + window_samples, len(audio))
        chunk = audio[start:end]
        if len(chunk) < sr:
            continue
        flat = float(np.mean(librosa.feature.spectral_flatness(y=chunk)))
        flatness_values.append((start / sr, flat))

    if not flatness_values:
        return SpectralQualityScore(
            mean_flatness=0.0, max_flatness=0.0, artifact_count=0, artifact_windows=(),
        )

    flat_values = [f for _, f in flatness_values]
    median_flat = float(np.median(flat_values))
    relative_threshold = median_flat * SPECTRAL_ARTIFACT_MULTIPLIER
    threshold = max(relative_threshold, SPECTRAL_ABSOLUTE_THRESHOLD)

    artifacts = tuple(
        (round(t, 1), round(f, 4))
        for t, f in flatness_values
        if f > threshold
    )

    mean_flat = float(np.mean(flat_values))
    max_flat = float(np.max(flat_values))

    log.info(
        "Spectral: mean_flatness=%.4f, max=%.4f, artifacts=%d",
        mean_flat, max_flat, len(artifacts),
    )

    return SpectralQualityScore(
        mean_flatness=round(mean_flat, 4),
        max_flatness=round(max_flat, 4),
        artifact_count=len(artifacts),
        artifact_windows=artifacts,
    )

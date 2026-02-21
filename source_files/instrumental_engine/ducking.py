"""Vocal-instrumental ducking for automatic gain reduction during vocal sections.

Implements sidechain-style ducking that reduces instrumental volume when vocals
are present, using smooth cosine-interpolated attack/release envelopes for
click-free transitions. Ducking is always active when vocals are placed.

Architecture:
    1. Convert vocal placement + durations → sample-accurate regions
    2. Build per-sample gain envelope with cosine attack/release curves
    3. Apply envelope to stereo instrumental channels via multiplication
"""

from __future__ import annotations

import logging
import math
from typing import Final

from instrumental_engine.constants import SAMPLE_RATE

logger = logging.getLogger(__name__)

DEFAULT_REDUCTION_DB: Final[float] = -3.0
DEFAULT_ATTACK_SECONDS: Final[float] = 0.05
DEFAULT_RELEASE_SECONDS: Final[float] = 0.2


def _db_to_linear(db: float) -> float:
    """Convert decibel value to linear amplitude multiplier.

    Args:
        db: Gain value in decibels (negative for reduction).

    Returns:
        Linear amplitude multiplier (e.g., -3dB → ~0.708).
    """
    return 10.0 ** (db / 20.0)


def _build_vocal_regions(
    vocal_placement: list[tuple[str, float]],
    vocal_durations: dict[str, float],
    sample_rate: int,
) -> list[tuple[int, int]]:
    """Convert vocal placement and durations to sample-accurate regions.

    Args:
        vocal_placement: List of (section_id, start_seconds) tuples.
        vocal_durations: Dict mapping section_id → duration in seconds.
        sample_rate: Audio sample rate in Hz.

    Returns:
        Sorted list of (start_sample, end_sample) tuples.
    """
    regions: list[tuple[int, int]] = []
    for section_id, start_seconds in vocal_placement:
        duration = vocal_durations.get(section_id, 0.0)
        if duration <= 0.0:
            continue
        start_sample = int(start_seconds * sample_rate)
        end_sample = int((start_seconds + duration) * sample_rate)
        regions.append((start_sample, end_sample))
    return sorted(regions, key=lambda r: r[0])


def _build_gain_envelope(
    total_samples: int,
    vocal_regions: list[tuple[int, int]],
    reduction_linear: float,
    attack_samples: int,
    release_samples: int,
) -> list[float]:
    """Build sample-accurate gain envelope with smooth cosine attack/release.

    Uses lookahead: attack ramp begins before the vocal starts so the
    instrumental is fully ducked by the time the vocal arrives. Release
    ramp begins when the vocal ends and smoothly returns to full volume.

    Overlapping vocal regions are handled via min-gain: the deepest
    duck wins at any given sample position.

    Args:
        total_samples: Total length of the audio in samples.
        vocal_regions: Sorted list of (start_sample, end_sample) tuples.
        reduction_linear: Target gain during ducking (0.0–1.0).
        attack_samples: Duration of duck-down ramp in samples.
        release_samples: Duration of return-to-full ramp in samples.

    Returns:
        Per-sample gain envelope, values in [reduction_linear, 1.0].
    """
    envelope = [1.0] * total_samples

    for region_start, region_end in vocal_regions:
        attack_begin = max(0, region_start - attack_samples)
        safe_attack = max(attack_samples, 1)

        for i in range(attack_begin, min(region_start, total_samples)):
            progress = (i - attack_begin) / safe_attack
            gain = 1.0 + (reduction_linear - 1.0) * _cosine_ease(progress)
            envelope[i] = min(envelope[i], gain)

        for i in range(max(0, region_start), min(region_end, total_samples)):
            envelope[i] = min(envelope[i], reduction_linear)

        safe_release = max(release_samples, 1)
        release_end = min(total_samples, region_end + release_samples)

        for i in range(max(0, region_end), release_end):
            progress = (i - region_end) / safe_release
            gain = reduction_linear + (1.0 - reduction_linear) * _cosine_ease(progress)
            envelope[i] = min(envelope[i], gain)

    return envelope


def _cosine_ease(t: float) -> float:
    """Compute cosine-interpolated easing value for smooth transitions.

    Maps linear progress [0.0, 1.0] to an S-curve using cosine interpolation,
    producing click-free audio transitions.

    Args:
        t: Linear progress value, clamped to [0.0, 1.0].

    Returns:
        Eased value in [0.0, 1.0].
    """
    clamped = max(0.0, min(1.0, t))
    return 0.5 * (1.0 - math.cos(math.pi * clamped))


def apply_ducking(
    instrumental_left: list[float],
    instrumental_right: list[float],
    vocal_placement: list[tuple[str, float]],
    vocal_durations: dict[str, float],
    reduction_db: float = DEFAULT_REDUCTION_DB,
    attack_seconds: float = DEFAULT_ATTACK_SECONDS,
    release_seconds: float = DEFAULT_RELEASE_SECONDS,
    sample_rate: int = SAMPLE_RATE,
) -> tuple[list[float], list[float]]:
    """Apply sidechain-style ducking to instrumental during vocal sections.

    Creates a smooth gain envelope that reduces instrumental volume when
    vocals are present, then gradually releases when vocals end. Uses
    cosine-interpolated curves for click-free transitions and lookahead
    attack so ducking is fully engaged when the vocal arrives.

    Args:
        instrumental_left: Left channel instrumental audio samples.
        instrumental_right: Right channel instrumental audio samples.
        vocal_placement: List of (section_id, start_seconds) tuples
            specifying where each vocal section begins.
        vocal_durations: Dict mapping section_id → duration in seconds.
        reduction_db: Volume reduction in dB (negative, default -3.0).
        attack_seconds: Time to duck down in seconds (default 0.05).
        release_seconds: Time to return to full volume (default 0.2).
        sample_rate: Audio sample rate in Hz (default 44100).

    Returns:
        Tuple of (ducked_left, ducked_right) stereo audio channels.
    """
    total_samples = max(len(instrumental_left), len(instrumental_right))

    if not vocal_placement or not vocal_durations:
        return list(instrumental_left), list(instrumental_right)

    vocal_regions = _build_vocal_regions(
        vocal_placement,
        vocal_durations,
        sample_rate,
    )

    if not vocal_regions:
        return list(instrumental_left), list(instrumental_right)

    reduction_linear = _db_to_linear(reduction_db)
    attack_samples = int(attack_seconds * sample_rate)
    release_samples = int(release_seconds * sample_rate)

    envelope = _build_gain_envelope(
        total_samples,
        vocal_regions,
        reduction_linear,
        attack_samples,
        release_samples,
    )

    ducked_left = [sample * envelope[i] for i, sample in enumerate(instrumental_left)]
    ducked_right = [sample * envelope[i] for i, sample in enumerate(instrumental_right)]

    ducked_regions = sum(1 for s, e in vocal_regions if s < total_samples)
    logger.info(
        "Ducking: %.1fdB across %d vocal regions (attack=%.0fms, release=%.0fms)",
        reduction_db, ducked_regions,
        attack_seconds * 1000, release_seconds * 1000,
    )

    return ducked_left, ducked_right

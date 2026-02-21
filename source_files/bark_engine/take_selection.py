"""Multi-take vocal selection via quality scoring.

Generates multiple takes per VocalSection, scores each on objective
audio quality metrics, and auto-selects the best take. This addresses
Bark's stochastic output variance by picking the most consistent,
cleanest generation from N candidates.

Scoring Metrics:
    - Energy consistency: RMS variance across windows (lower = better)
    - Silence ratio: Fraction of audio below threshold (lower = better)
    - Clipping detection: Samples near ±1.0 (none = better)
    - Duration match: Actual vs expected duration (closer = better)
    - Composite: Weighted combination of all metrics (higher = better)
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

ENERGY_WEIGHT: Final[float] = 0.3
SILENCE_WEIGHT: Final[float] = 0.3
CLIPPING_WEIGHT: Final[float] = 0.2
DURATION_WEIGHT: Final[float] = 0.2

RMS_WINDOW_SECONDS: Final[float] = 0.05
SILENCE_THRESHOLD: Final[float] = 0.02
CLIPPING_THRESHOLD: Final[float] = 0.99
DURATION_TOLERANCE_SECONDS: Final[float] = 2.0

MIN_TAKES: Final[int] = 1
MAX_TAKES: Final[int] = 10


@dataclass(frozen=True)
class TakeScore:
    """Quality metrics for a single vocal take.

    Attributes:
        take_number: 1-based index of this take.
        energy_consistency: Normalized energy consistency (0.0–1.0, higher = better).
        silence_ratio: Fraction of audio below silence threshold (0.0–1.0, lower = better).
        clipping_detected: Whether hard clipping was detected.
        duration_match: Duration proximity score (0.0–1.0, higher = better).
        composite_score: Weighted overall quality (0.0–1.0, higher = better).
    """

    take_number: int
    energy_consistency: float
    silence_ratio: float
    clipping_detected: bool
    duration_match: float
    composite_score: float


def _calculate_rms_windows(
    samples: list[float],
    sample_rate: int,
    window_seconds: float = RMS_WINDOW_SECONDS,
) -> list[float]:
    """Calculate RMS energy for non-overlapping windows.

    Args:
        samples: Audio samples in [-1.0, 1.0].
        sample_rate: Sample rate in Hz.
        window_seconds: Window size in seconds.

    Returns:
        List of RMS values per window.
    """
    window_size = max(1, int(sample_rate * window_seconds))
    rms_values: list[float] = []

    for start in range(0, len(samples) - window_size + 1, window_size):
        window = samples[start : start + window_size]
        mean_square = sum(s * s for s in window) / window_size
        rms_values.append(math.sqrt(mean_square))

    return rms_values


def _score_energy_consistency(rms_values: list[float]) -> float:
    """Score energy consistency from RMS window values.

    Lower variance in RMS across windows indicates more consistent
    vocal delivery. Returns 0.0–1.0 where 1.0 is perfectly consistent.

    Args:
        rms_values: RMS values per analysis window.

    Returns:
        Energy consistency score (0.0–1.0, higher = better).
    """
    if len(rms_values) < 2:
        return 0.5

    mean_rms = sum(rms_values) / len(rms_values)
    if mean_rms < 1e-6:
        return 0.0

    variance = sum((r - mean_rms) ** 2 for r in rms_values) / len(rms_values)
    coefficient_of_variation = math.sqrt(variance) / mean_rms

    return max(0.0, min(1.0, 1.0 - coefficient_of_variation))


def _score_silence_ratio(
    samples: list[float],
    threshold: float = SILENCE_THRESHOLD,
) -> float:
    """Calculate fraction of audio below silence threshold.

    Args:
        samples: Audio samples in [-1.0, 1.0].
        threshold: Amplitude threshold for silence detection.

    Returns:
        Silence ratio (0.0–1.0, lower = less dead air = better).
    """
    if not samples:
        return 1.0

    silent_count = sum(1 for s in samples if abs(s) < threshold)
    return silent_count / len(samples)


def _detect_clipping(
    samples: list[float],
    threshold: float = CLIPPING_THRESHOLD,
) -> bool:
    """Detect hard clipping in audio samples.

    Args:
        samples: Audio samples in [-1.0, 1.0].
        threshold: Amplitude threshold for clipping detection.

    Returns:
        True if clipping is detected.
    """
    return any(abs(s) >= threshold for s in samples)


def _score_duration_match(
    samples: list[float],
    expected_duration_seconds: float,
    sample_rate: int,
    tolerance_seconds: float = DURATION_TOLERANCE_SECONDS,
) -> float:
    """Score how closely actual duration matches expected duration.

    Args:
        samples: Audio samples.
        expected_duration_seconds: Target duration in seconds.
        sample_rate: Sample rate in Hz.
        tolerance_seconds: Acceptable deviation range.

    Returns:
        Duration match score (0.0–1.0, higher = closer match).
    """
    if expected_duration_seconds <= 0.0:
        return 1.0

    actual_duration = len(samples) / sample_rate
    deviation = abs(actual_duration - expected_duration_seconds)

    return max(0.0, 1.0 - deviation / tolerance_seconds)


def _calculate_composite_score(
    energy_consistency: float,
    silence_ratio: float,
    clipping_detected: bool,
    duration_match: float,
) -> float:
    """Calculate weighted composite quality score.

    Weights: energy 30%, silence 30%, clipping 20%, duration 20%.

    Args:
        energy_consistency: Energy consistency score (0.0–1.0).
        silence_ratio: Silence ratio (0.0–1.0, lower = better).
        clipping_detected: Whether clipping was detected.
        duration_match: Duration match score (0.0–1.0).

    Returns:
        Composite score (0.0–1.0, higher = better).
    """
    silence_score = 1.0 - silence_ratio
    clipping_score = 0.0 if clipping_detected else 1.0

    return (
        ENERGY_WEIGHT * energy_consistency
        + SILENCE_WEIGHT * silence_score
        + CLIPPING_WEIGHT * clipping_score
        + DURATION_WEIGHT * duration_match
    )


def score_vocal_take(
    samples: list[float],
    take_number: int,
    expected_duration_seconds: float,
    sample_rate: int = 44100,
) -> TakeScore:
    """Score a single vocal take on multiple quality metrics.

    Evaluates energy consistency, silence ratio, clipping, and
    duration match, then computes a weighted composite score.

    Args:
        samples: Audio samples in [-1.0, 1.0].
        take_number: 1-based take index.
        expected_duration_seconds: Expected duration for pacing comparison.
        sample_rate: Audio sample rate in Hz.

    Returns:
        Frozen TakeScore with all metric values and composite.
    """
    rms_values = _calculate_rms_windows(samples, sample_rate)
    energy_consistency = _score_energy_consistency(rms_values)
    silence_ratio = _score_silence_ratio(samples)
    clipping_detected = _detect_clipping(samples)
    duration_match = _score_duration_match(
        samples, expected_duration_seconds, sample_rate
    )
    composite = _calculate_composite_score(
        energy_consistency, silence_ratio, clipping_detected, duration_match
    )

    return TakeScore(
        take_number=take_number,
        energy_consistency=energy_consistency,
        silence_ratio=silence_ratio,
        clipping_detected=clipping_detected,
        duration_match=duration_match,
        composite_score=composite,
    )


def select_best_take(
    takes: list[tuple[list[float], TakeScore]],
    verbose: bool = True,
) -> tuple[list[float], TakeScore]:
    """Select the take with the highest composite score.

    Args:
        takes: List of (samples, score) pairs.
        verbose: Print score comparison table.

    Returns:
        Tuple of (best samples, best TakeScore).

    Raises:
        ValueError: If takes list is empty.
    """
    if not takes:
        raise ValueError("Cannot select from empty takes list")

    if verbose:
        for _, score in takes:
            clipping_indicator = "⚠️" if score.clipping_detected else "✔️"
            print(
                f"      Take {score.take_number}: "
                f"energy={score.energy_consistency:.2f} "
                f"silence={score.silence_ratio:.2f} "
                f"clip={clipping_indicator} "
                f"duration={score.duration_match:.2f} "
                f"→ composite={score.composite_score:.3f}"
            )

    best_samples, best_score = max(takes, key=lambda t: t[1].composite_score)

    if verbose:
        print(
            f"   ✅ Selected take {best_score.take_number} "
            f"(score: {best_score.composite_score:.3f})"
        )

    return best_samples, best_score


def save_take_metadata(
    section_id: str,
    scores: list[TakeScore],
    selected_take: int,
    output_dir: Path,
) -> Path:
    """Save take scores and selection metadata as JSON.

    Args:
        section_id: Vocal section identifier.
        scores: All TakeScore results.
        selected_take: 1-based index of the selected take.
        output_dir: Directory to write metadata file.

    Returns:
        Path to the written JSON file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = output_dir / f"{section_id}_takes.json"

    metadata = {
        "section_id": section_id,
        "total_takes": len(scores),
        "selected_take": selected_take,
        "takes": [asdict(score) for score in scores],
    }

    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata_path

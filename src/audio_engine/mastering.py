"""Professional mastering chain for streaming-ready audio.

Pipeline: Multiband Compression -> Stereo Widening -> LUFS Normalization -> Soft Clipping

All processing is pure NumPy/scipy with no external mastering libraries.
Deterministic: identical input always produces identical output.

LUFS measurement follows a simplified ITU-R BS.1770-4 algorithm with
K-weighting pre-filter, 400ms gated blocks, and absolute/relative gating.
"""

from __future__ import annotations

import logging
import math

import numpy as np
import pyloudnorm as pyln
from numpy.typing import NDArray
from scipy.signal import butter, lfilter, sosfilt

from audio_engine.constants import (
    BUTTER_ORDER,
    CHANNEL_LENGTH_TOLERANCE,
    COMPRESSOR_ATTACK_SECONDS,
    COMPRESSOR_RELEASE_SECONDS,
    DEFAULT_COMPRESSION_RATIOS,
    DEFAULT_COMPRESSION_THRESHOLDS,
    DEFAULT_CROSSOVER_BANDS,
    DEFAULT_SOFT_CLIP_CEILING,
    DEFAULT_STEREO_WIDTH,
    DEFAULT_TARGET_LUFS,
    FALLBACK_SAMPLE_RATE,
    MAX_GAIN_DB,
    MIN_RMS_FLOOR,
    SOFT_CLIP_KNEE,
)
from audio_engine.errors import MasteringError

log = logging.getLogger(__name__)


def master_stereo(
    left: NDArray[np.float64],
    right: NDArray[np.float64],
    target_lufs: float = DEFAULT_TARGET_LUFS,
    stereo_width: float = DEFAULT_STEREO_WIDTH,
    sample_rate: int = FALLBACK_SAMPLE_RATE,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Apply professional mastering chain to stereo audio.

    Pipeline:
        1. Multiband compression (bass/mid/treble)
        2. Stereo widening (mid/side processing)
        3. LUFS normalization (streaming-ready loudness)
        4. Soft clipper (tanh saturation)
    """
    if len(left) == 0 or len(right) == 0:
        return left, right

    length_diff = abs(len(left) - len(right))
    if length_diff > CHANNEL_LENGTH_TOLERANCE:
        raise MasteringError(
            f"Left/right channel length mismatch: {len(left)} vs {len(right)} "
            f"(diff={length_diff}, tolerance={CHANNEL_LENGTH_TOLERANCE})"
        )
    n = min(len(left), len(right))
    left, right = left[:n], right[:n]

    return _master_chain(left, right, target_lufs, stereo_width, sample_rate)


def _master_chain(
    left: NDArray[np.float64],
    right: NDArray[np.float64],
    target_lufs: float,
    stereo_width: float,
    sample_rate: int,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Internal mastering chain operating on numpy arrays."""
    left, right = multiband_compress(left, right, sample_rate=sample_rate)
    left, right = widen_stereo(left, right, width=stereo_width)

    current_lufs = measure_lufs(left, right, sample_rate=sample_rate)
    left, right = normalize_to_lufs(
        left, right, target_lufs=target_lufs, current_lufs=current_lufs,
    )

    left = soft_clip(left, ceiling=DEFAULT_SOFT_CLIP_CEILING)
    right = soft_clip(right, ceiling=DEFAULT_SOFT_CLIP_CEILING)
    return left, right


def multiband_compress(
    left: NDArray[np.float64],
    right: NDArray[np.float64],
    bands: tuple[tuple[float, float], ...] = DEFAULT_CROSSOVER_BANDS,
    ratios: tuple[float, ...] = DEFAULT_COMPRESSION_RATIOS,
    thresholds: tuple[float, ...] = DEFAULT_COMPRESSION_THRESHOLDS,
    sample_rate: int = FALLBACK_SAMPLE_RATE,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Apply frequency-dependent compression across multiple bands."""
    if len(bands) != len(ratios) or len(bands) != len(thresholds):
        raise ValueError(
            f"Band count mismatch: {len(bands)} bands, "
            f"{len(ratios)} ratios, {len(thresholds)} thresholds"
        )

    nyquist = sample_rate / 2.0
    accumulated_left = np.zeros_like(left)
    accumulated_right = np.zeros_like(right)

    for (low_hz, high_hz), ratio, threshold in zip(bands, ratios, thresholds):
        band_left, band_right = _extract_band(
            left, right, low_hz, high_hz, nyquist,
        )
        band_left = _compress_signal(band_left, threshold, ratio, sample_rate)
        band_right = _compress_signal(band_right, threshold, ratio, sample_rate)
        accumulated_left += band_left
        accumulated_right += band_right

    return accumulated_left, accumulated_right


def measure_lufs(
    left: NDArray[np.float64],
    right: NDArray[np.float64],
    sample_rate: int = FALLBACK_SAMPLE_RATE,
) -> float:
    """Measure integrated LUFS using pyloudnorm (ITU-R BS.1770-4)."""
    if len(left) == 0 or len(right) == 0:
        log.warning("LUFS measurement skipped: empty audio channel")
        return -70.0

    stereo = np.column_stack([left, right])
    meter = pyln.Meter(sample_rate)
    lufs = meter.integrated_loudness(stereo)

    if lufs == float("-inf") or np.isnan(lufs):
        log.warning("LUFS measurement returned %s, falling back to -70.0", lufs)
        return -70.0

    return float(lufs)


def normalize_to_lufs(
    left: NDArray[np.float64],
    right: NDArray[np.float64],
    target_lufs: float,
    current_lufs: float,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Adjust gain to match target LUFS."""
    if current_lufs <= -70.0:
        return left, right

    gain_db = target_lufs - current_lufs
    gain_db = max(-MAX_GAIN_DB, min(MAX_GAIN_DB, gain_db))
    gain_linear = 10.0 ** (gain_db / 20.0)

    return left * gain_linear, right * gain_linear


def widen_stereo(
    left: NDArray[np.float64],
    right: NDArray[np.float64],
    width: float,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Apply mid/side stereo widening."""
    if abs(width - 1.0) < 1e-6:
        return left, right

    n = min(len(left), len(right))
    left = left[:n]
    right = right[:n]

    mid = (left + right) * 0.5
    side = (left - right) * 0.5
    side *= width

    return mid + side, mid - side


def soft_clip(
    samples: NDArray[np.float64],
    ceiling: float = DEFAULT_SOFT_CLIP_CEILING,
) -> NDArray[np.float64]:
    """Apply soft clipping: linear below knee, tanh saturation above.

    Signals below the knee pass through unchanged so that LUFS
    normalization is not undone for well-behaved audio.
    """
    if len(samples) == 0:
        return samples

    knee = SOFT_CLIP_KNEE * ceiling
    result = samples.copy()
    above = np.abs(samples) > knee

    if np.any(above):
        sign = np.sign(samples[above])
        magnitude = np.abs(samples[above])
        scaled = (magnitude - knee) / (ceiling - knee)
        result[above] = sign * (knee + (ceiling - knee) * np.tanh(scaled))

    return result


def _extract_band(
    left: NDArray[np.float64],
    right: NDArray[np.float64],
    low_hz: float,
    high_hz: float,
    nyquist: float,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Extract a frequency band from stereo audio using Butterworth filters."""
    low_norm = max(low_hz / nyquist, 0.001)
    high_norm = min(high_hz / nyquist, 0.999)

    if low_norm >= high_norm:
        return np.zeros_like(left), np.zeros_like(right)

    is_lowpass = low_hz <= 30.0
    is_highpass = high_hz >= nyquist * 0.95

    if is_lowpass:
        sos = butter(BUTTER_ORDER, high_norm, btype="low", output="sos")
    elif is_highpass:
        sos = butter(BUTTER_ORDER, low_norm, btype="high", output="sos")
    else:
        sos = butter(
            BUTTER_ORDER, [low_norm, high_norm], btype="band", output="sos",
        )

    band_left: NDArray[np.float64] = sosfilt(sos, left).astype(np.float64)
    band_right: NDArray[np.float64] = sosfilt(sos, right).astype(np.float64)
    return band_left, band_right


def _compress_signal(
    signal: NDArray[np.float64],
    threshold: float,
    ratio: float,
    sample_rate: int,
) -> NDArray[np.float64]:
    """Apply single-band compression with approximate envelope following.

    Uses vectorized lfilter for attack/release envelopes instead of a
    per-sample Python loop.  The envelope is max(attack_env, release_env)
    which approximates fast-attack / slow-release behaviour. A true
    conditional envelope follower (if x > env: attack else release) would
    require a per-sample loop that is prohibitively slow in pure Python
    for multi-minute audio at 48 kHz.  The approximation is sufficient
    for mastering-level dynamics control and produces musically acceptable
    results validated by the LUFS and clipping tests.
    """
    attack_coeff = math.exp(-1.0 / (COMPRESSOR_ATTACK_SECONDS * sample_rate))
    release_coeff = math.exp(-1.0 / (COMPRESSOR_RELEASE_SECONDS * sample_rate))
    abs_signal = np.abs(signal)

    # One-pole IIR smoothers: y[n] = coeff * y[n-1] + (1 - coeff) * x[n]
    # Attack (fast tracking) and release (slow decay)
    attack_env = lfilter([1.0 - attack_coeff], [1.0, -attack_coeff], abs_signal)
    release_env = lfilter([1.0 - release_coeff], [1.0, -release_coeff], abs_signal)

    # Fast attack (tracks rises quickly), slow release (holds during drops)
    envelope = np.maximum(attack_env, release_env)

    gain = np.ones_like(envelope)
    above_threshold = envelope > threshold
    gain[above_threshold] = (
        threshold + (envelope[above_threshold] - threshold) / ratio
    ) / np.maximum(envelope[above_threshold], MIN_RMS_FLOOR)

    return signal * gain

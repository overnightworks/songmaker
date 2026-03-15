"""Professional mastering chain for streaming-ready audio.

Pipeline: Multiband Compression -> Stereo Widening -> LUFS Normalization -> Soft Clipping

All processing is pure NumPy/scipy with no external mastering libraries.
Deterministic: identical input always produces identical output.

LUFS measurement follows a simplified ITU-R BS.1770-4 algorithm with
K-weighting pre-filter, 400ms gated blocks, and absolute/relative gating.
"""

from __future__ import annotations

import math
from typing import Final

import numpy as np
from numpy.typing import NDArray
from scipy.signal import butter, lfilter, sosfilt

from audio_engine.constants import FALLBACK_SAMPLE_RATE
from audio_engine.errors import MasteringError

_REFERENCE_LUFS: Final[float] = -0.691
_ABSOLUTE_GATE_LUFS: Final[float] = -70.0
_RELATIVE_GATE_OFFSET_LUFS: Final[float] = -10.0
_BLOCK_DURATION_SECONDS: Final[float] = 0.4
_BLOCK_OVERLAP_FRACTION: Final[float] = 0.75
_DEFAULT_TARGET_LUFS: Final[float] = -14.0
_DEFAULT_STEREO_WIDTH: Final[float] = 1.2
_DEFAULT_SOFT_CLIP_CEILING: Final[float] = 0.98
_DEFAULT_CROSSOVER_BANDS: Final[tuple[tuple[float, float], ...]] = (
    (20.0, 250.0),
    (250.0, 4000.0),
    (4000.0, 20000.0),
)
_DEFAULT_RATIOS: Final[tuple[float, ...]] = (3.0, 2.5, 2.0)
_DEFAULT_THRESHOLDS: Final[tuple[float, ...]] = (0.5, 0.6, 0.7)
_BUTTER_ORDER: Final[int] = 4
_COMPRESSOR_ATTACK_SECONDS: Final[float] = 0.005
_COMPRESSOR_RELEASE_SECONDS: Final[float] = 0.05
_K_WEIGHT_HIGH_SHELF_GAIN_DB: Final[float] = 4.0
_K_WEIGHT_HIGH_SHELF_FREQ: Final[float] = 1500.0
_K_WEIGHT_HIGHPASS_FREQ: Final[float] = 38.0
_MIN_RMS_FLOOR: Final[float] = 1e-10
_MAX_GAIN_DB: Final[float] = 24.0


_CHANNEL_LENGTH_TOLERANCE: Final[int] = 16


def master_stereo(
    left: NDArray[np.float64],
    right: NDArray[np.float64],
    target_lufs: float = _DEFAULT_TARGET_LUFS,
    stereo_width: float = _DEFAULT_STEREO_WIDTH,
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
    if length_diff > _CHANNEL_LENGTH_TOLERANCE:
        raise MasteringError(
            f"Left/right channel length mismatch: {len(left)} vs {len(right)} "
            f"(diff={length_diff}, tolerance={_CHANNEL_LENGTH_TOLERANCE})"
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

    left = soft_clip(left, ceiling=_DEFAULT_SOFT_CLIP_CEILING)
    right = soft_clip(right, ceiling=_DEFAULT_SOFT_CLIP_CEILING)
    return left, right


def multiband_compress(
    left: NDArray[np.float64],
    right: NDArray[np.float64],
    bands: tuple[tuple[float, float], ...] = _DEFAULT_CROSSOVER_BANDS,
    ratios: tuple[float, ...] = _DEFAULT_RATIOS,
    thresholds: tuple[float, ...] = _DEFAULT_THRESHOLDS,
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
    """Measure integrated LUFS following simplified ITU-R BS.1770-4."""
    if len(left) == 0 or len(right) == 0:
        return -70.0

    left_weighted = _apply_k_weighting(left, sample_rate)
    right_weighted = _apply_k_weighting(right, sample_rate)

    block_size = int(_BLOCK_DURATION_SECONDS * sample_rate)
    hop_size = int(block_size * (1.0 - _BLOCK_OVERLAP_FRACTION))

    if block_size < 1 or hop_size < 1:
        return -70.0

    block_energies = _compute_block_energies(
        left_weighted, right_weighted, block_size, hop_size,
    )

    if len(block_energies) == 0:
        return -70.0

    absolute_gate_energy = 10.0 ** ((_ABSOLUTE_GATE_LUFS - _REFERENCE_LUFS) / 10.0)
    above_absolute = block_energies[block_energies > absolute_gate_energy]

    if len(above_absolute) == 0:
        return -70.0

    ungated_mean = float(np.mean(above_absolute))
    ungated_lufs = _REFERENCE_LUFS + 10.0 * math.log10(
        max(ungated_mean, _MIN_RMS_FLOOR),
    )
    relative_gate_lufs = ungated_lufs + _RELATIVE_GATE_OFFSET_LUFS
    relative_gate_energy = 10.0 ** ((relative_gate_lufs - _REFERENCE_LUFS) / 10.0)

    above_relative = above_absolute[above_absolute > relative_gate_energy]

    if len(above_relative) == 0:
        return -70.0

    gated_mean = float(np.mean(above_relative))
    return _REFERENCE_LUFS + 10.0 * math.log10(max(gated_mean, _MIN_RMS_FLOOR))


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
    gain_db = max(-_MAX_GAIN_DB, min(_MAX_GAIN_DB, gain_db))
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


_SOFT_CLIP_KNEE: Final[float] = 0.85


def soft_clip(
    samples: NDArray[np.float64],
    ceiling: float = _DEFAULT_SOFT_CLIP_CEILING,
) -> NDArray[np.float64]:
    """Apply soft clipping: linear below knee, tanh saturation above.

    Signals below the knee pass through unchanged so that LUFS
    normalization is not undone for well-behaved audio.
    """
    if len(samples) == 0:
        return samples

    knee = _SOFT_CLIP_KNEE * ceiling
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
        sos = butter(_BUTTER_ORDER, high_norm, btype="low", output="sos")
    elif is_highpass:
        sos = butter(_BUTTER_ORDER, low_norm, btype="high", output="sos")
    else:
        sos = butter(
            _BUTTER_ORDER, [low_norm, high_norm], btype="band", output="sos",
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
    attack_coeff = math.exp(-1.0 / (_COMPRESSOR_ATTACK_SECONDS * sample_rate))
    release_coeff = math.exp(-1.0 / (_COMPRESSOR_RELEASE_SECONDS * sample_rate))
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
    ) / np.maximum(envelope[above_threshold], _MIN_RMS_FLOOR)

    return signal * gain


def _apply_k_weighting(
    signal: NDArray[np.float64],
    sample_rate: int,
) -> NDArray[np.float64]:
    """Apply K-weighting pre-filter for LUFS measurement."""
    nyquist = sample_rate / 2.0

    hp_freq = min(_K_WEIGHT_HIGHPASS_FREQ / nyquist, 0.999)
    if hp_freq > 0.001:
        hp_sos = butter(2, hp_freq, btype="high", output="sos")
        signal = sosfilt(hp_sos, signal).astype(np.float64)

    shelf_freq = min(_K_WEIGHT_HIGH_SHELF_FREQ / nyquist, 0.999)
    if shelf_freq > 0.001:
        shelf_sos = butter(1, shelf_freq, btype="high", output="sos")
        high_content: NDArray[np.float64] = sosfilt(
            shelf_sos, signal,
        ).astype(np.float64)
        shelf_gain = 10.0 ** (_K_WEIGHT_HIGH_SHELF_GAIN_DB / 20.0) - 1.0
        signal = signal + high_content * shelf_gain

    return signal


def _compute_block_energies(
    left_weighted: NDArray[np.float64],
    right_weighted: NDArray[np.float64],
    block_size: int,
    hop_size: int,
) -> NDArray[np.float64]:
    """Compute mean-square energy per block for LUFS gating."""
    n = min(len(left_weighted), len(right_weighted))
    n_blocks = max(0, (n - block_size) // hop_size + 1)

    if n_blocks == 0:
        return np.array([], dtype=np.float64)

    left_view = np.lib.stride_tricks.sliding_window_view(
        left_weighted[:n], block_size,
    )[::hop_size]
    right_view = np.lib.stride_tricks.sliding_window_view(
        right_weighted[:n], block_size,
    )[::hop_size]

    return np.mean(left_view**2, axis=1) + np.mean(right_view**2, axis=1)



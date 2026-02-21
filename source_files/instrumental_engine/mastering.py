"""Professional mastering chain for streaming-ready audio.

Pipeline: Multiband Compression → Stereo Widening → LUFS Normalization → Soft Clipping

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
from scipy.signal import butter, sosfilt

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


def master_stereo(
    left: list[float],
    right: list[float],
    target_lufs: float = _DEFAULT_TARGET_LUFS,
    stereo_width: float = _DEFAULT_STEREO_WIDTH,
    sample_rate: int = 44100,
) -> tuple[list[float], list[float]]:
    """Apply professional mastering chain to stereo audio.

    Pipeline:
        1. Multiband compression (bass/mid/treble)
        2. Stereo widening (mid/side processing)
        3. LUFS normalization (streaming-ready loudness)
        4. Soft clipper (tanh saturation)

    Args:
        left: Left channel audio samples in [-1.0, 1.0].
        right: Right channel audio samples in [-1.0, 1.0].
        target_lufs: Target integrated LUFS (-14 for streaming).
        stereo_width: Width multiplier (1.0 = no change, 1.2 = 20% wider).
        sample_rate: Audio sample rate in Hz.

    Returns:
        Tuple of (mastered_left, mastered_right).
    """
    if not left or not right:
        return left, right

    mastered_left, mastered_right = multiband_compress(
        left,
        right,
        sample_rate=sample_rate,
    )

    mastered_left, mastered_right = widen_stereo(
        mastered_left,
        mastered_right,
        width=stereo_width,
    )

    current_lufs = measure_lufs(mastered_left, mastered_right, sample_rate=sample_rate)
    mastered_left, mastered_right = normalize_to_lufs(
        mastered_left,
        mastered_right,
        target_lufs=target_lufs,
        current_lufs=current_lufs,
    )

    mastered_left = soft_clip(mastered_left, ceiling=_DEFAULT_SOFT_CLIP_CEILING)
    mastered_right = soft_clip(mastered_right, ceiling=_DEFAULT_SOFT_CLIP_CEILING)

    return mastered_left, mastered_right


def multiband_compress(
    left: list[float],
    right: list[float],
    bands: tuple[tuple[float, float], ...] = _DEFAULT_CROSSOVER_BANDS,
    ratios: tuple[float, ...] = _DEFAULT_RATIOS,
    thresholds: tuple[float, ...] = _DEFAULT_THRESHOLDS,
    sample_rate: int = 44100,
) -> tuple[list[float], list[float]]:
    """Apply frequency-dependent compression across multiple bands.

    Splits audio into frequency bands using Butterworth filters,
    compresses each band independently, and recombines.

    Args:
        left: Left channel audio samples.
        right: Right channel audio samples.
        bands: Frequency band boundaries as (low_hz, high_hz) tuples.
        ratios: Compression ratio per band (higher = more compression).
        thresholds: Compression threshold per band (0.0–1.0 amplitude).
        sample_rate: Audio sample rate in Hz.

    Returns:
        Tuple of (compressed_left, compressed_right).

    Raises:
        ValueError: If bands, ratios, and thresholds have mismatched lengths.
    """
    if len(bands) != len(ratios) or len(bands) != len(thresholds):
        raise ValueError(
            f"Band count mismatch: {len(bands)} bands, "
            f"{len(ratios)} ratios, {len(thresholds)} thresholds"
        )

    left_arr = np.asarray(left, dtype=np.float64)
    right_arr = np.asarray(right, dtype=np.float64)
    nyquist = sample_rate / 2.0

    accumulated_left = np.zeros_like(left_arr)
    accumulated_right = np.zeros_like(right_arr)

    for (low_hz, high_hz), ratio, threshold in zip(bands, ratios, thresholds):
        band_left, band_right = _extract_band(
            left_arr,
            right_arr,
            low_hz,
            high_hz,
            nyquist,
        )

        band_left = _compress_signal(
            band_left,
            threshold,
            ratio,
            sample_rate,
        )
        band_right = _compress_signal(
            band_right,
            threshold,
            ratio,
            sample_rate,
        )

        accumulated_left += band_left
        accumulated_right += band_right

    return accumulated_left.tolist(), accumulated_right.tolist()


def measure_lufs(
    left: list[float],
    right: list[float],
    sample_rate: int = 44100,
) -> float:
    """Measure integrated LUFS following simplified ITU-R BS.1770-4.

    Algorithm:
        1. Apply K-weighting filter (high-shelf boost at 1.5kHz, HP at 38Hz)
        2. Compute mean square energy in 400ms blocks with 75% overlap
        3. Absolute gating: discard blocks below -70 LUFS
        4. Relative gating: discard blocks below (ungated_mean - 10) LUFS
        5. Convert gated mean energy to LUFS

    Args:
        left: Left channel audio samples.
        right: Right channel audio samples.
        sample_rate: Audio sample rate in Hz.

    Returns:
        Integrated loudness in LUFS (typically -60 to 0).
    """
    if not left or not right:
        return -70.0

    left_arr = np.asarray(left, dtype=np.float64)
    right_arr = np.asarray(right, dtype=np.float64)

    left_weighted = _apply_k_weighting(left_arr, sample_rate)
    right_weighted = _apply_k_weighting(right_arr, sample_rate)

    block_size = int(_BLOCK_DURATION_SECONDS * sample_rate)
    hop_size = int(block_size * (1.0 - _BLOCK_OVERLAP_FRACTION))

    if block_size < 1 or hop_size < 1:
        return -70.0

    block_energies = _compute_block_energies(
        left_weighted,
        right_weighted,
        block_size,
        hop_size,
    )

    if len(block_energies) == 0:
        return -70.0

    absolute_gate_energy = 10.0 ** ((_ABSOLUTE_GATE_LUFS - _REFERENCE_LUFS) / 10.0)
    above_absolute = block_energies[block_energies > absolute_gate_energy]

    if len(above_absolute) == 0:
        return -70.0

    ungated_mean = float(np.mean(above_absolute))
    ungated_lufs = _REFERENCE_LUFS + 10.0 * math.log10(
        max(ungated_mean, _MIN_RMS_FLOOR)
    )
    relative_gate_lufs = ungated_lufs + _RELATIVE_GATE_OFFSET_LUFS
    relative_gate_energy = 10.0 ** ((relative_gate_lufs - _REFERENCE_LUFS) / 10.0)

    above_relative = above_absolute[above_absolute > relative_gate_energy]

    if len(above_relative) == 0:
        return -70.0

    gated_mean = float(np.mean(above_relative))
    return _REFERENCE_LUFS + 10.0 * math.log10(max(gated_mean, _MIN_RMS_FLOOR))


def normalize_to_lufs(
    left: list[float],
    right: list[float],
    target_lufs: float,
    current_lufs: float,
) -> tuple[list[float], list[float]]:
    """Adjust gain to match target LUFS.

    Computes the linear gain difference between current and target LUFS,
    then applies uniform gain scaling. Clamps maximum gain to prevent
    amplifying near-silence.

    Args:
        left: Left channel audio samples.
        right: Right channel audio samples.
        target_lufs: Desired LUFS level (e.g., -14.0).
        current_lufs: Measured current LUFS level.

    Returns:
        Tuple of (normalized_left, normalized_right).
    """
    if current_lufs <= -70.0:
        return left, right

    gain_db = target_lufs - current_lufs
    gain_db = max(-_MAX_GAIN_DB, min(_MAX_GAIN_DB, gain_db))
    gain_linear = 10.0 ** (gain_db / 20.0)

    return (
        [s * gain_linear for s in left],
        [s * gain_linear for s in right],
    )


def widen_stereo(
    left: list[float],
    right: list[float],
    width: float,
) -> tuple[list[float], list[float]]:
    """Apply mid/side stereo widening.

    Encodes L/R to mid/side, scales the side channel by the width
    factor, then decodes back to L/R. Width of 1.0 is unchanged,
    >1.0 widens, <1.0 narrows. Mono-compatible at width=0.0.

    Args:
        left: Left channel audio samples.
        right: Right channel audio samples.
        width: Width multiplier (1.0 = no change, 1.2 = 20% wider).

    Returns:
        Tuple of (widened_left, widened_right).
    """
    if abs(width - 1.0) < 1e-6:
        return left, right

    left_arr = np.asarray(left, dtype=np.float64)
    right_arr = np.asarray(right, dtype=np.float64)

    n = min(len(left_arr), len(right_arr))
    left_arr = left_arr[:n]
    right_arr = right_arr[:n]

    mid = (left_arr + right_arr) * 0.5
    side = (left_arr - right_arr) * 0.5

    side *= width

    widened_left = mid + side
    widened_right = mid - side

    return widened_left.tolist(), widened_right.tolist()


def soft_clip(
    samples: list[float], ceiling: float = _DEFAULT_SOFT_CLIP_CEILING
) -> list[float]:
    """Apply tanh soft clipping for warmth without hard digital clipping.

    Maps samples through a scaled tanh function so that output never
    exceeds the ceiling value. Provides gentle saturation that adds
    harmonic warmth.

    Args:
        samples: Audio samples to clip.
        ceiling: Maximum output amplitude (default 0.98).

    Returns:
        Soft-clipped audio samples guaranteed below ceiling.
    """
    arr = np.asarray(samples, dtype=np.float64)
    clipped = np.tanh(arr) * ceiling
    return clipped.tolist()


def _extract_band(
    left: NDArray[np.float64],
    right: NDArray[np.float64],
    low_hz: float,
    high_hz: float,
    nyquist: float,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Extract a frequency band from stereo audio using Butterworth filters.

    Args:
        left: Left channel array.
        right: Right channel array.
        low_hz: Lower band boundary in Hz.
        high_hz: Upper band boundary in Hz.
        nyquist: Nyquist frequency (sample_rate / 2).

    Returns:
        Tuple of (band_left, band_right) arrays.
    """
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
        sos = butter(_BUTTER_ORDER, [low_norm, high_norm], btype="band", output="sos")

    band_left: NDArray[np.float64] = sosfilt(sos, left).astype(np.float64)
    band_right: NDArray[np.float64] = sosfilt(sos, right).astype(np.float64)
    return band_left, band_right


def _compress_signal(
    signal: NDArray[np.float64],
    threshold: float,
    ratio: float,
    sample_rate: int,
) -> NDArray[np.float64]:
    """Apply single-band compression with envelope following.

    Uses a simple peak envelope follower with attack/release smoothing
    to compute gain reduction, then applies soft-knee compression.

    Args:
        signal: Audio signal array.
        threshold: Compression threshold (0.0–1.0 amplitude).
        ratio: Compression ratio (e.g., 3.0 = 3:1).
        sample_rate: Audio sample rate.

    Returns:
        Compressed signal array.
    """
    attack_coeff = math.exp(-1.0 / (_COMPRESSOR_ATTACK_SECONDS * sample_rate))
    release_coeff = math.exp(-1.0 / (_COMPRESSOR_RELEASE_SECONDS * sample_rate))

    envelope = np.zeros_like(signal)
    abs_signal = np.abs(signal)

    env_val = 0.0
    for i in range(len(abs_signal)):
        sample_val = abs_signal[i]
        if sample_val > env_val:
            env_val = attack_coeff * env_val + (1.0 - attack_coeff) * sample_val
        else:
            env_val = release_coeff * env_val + (1.0 - release_coeff) * sample_val
        envelope[i] = env_val

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
    """Apply K-weighting pre-filter for LUFS measurement.

    Implements a simplified K-weighting using:
        1. High-shelf boost at 1.5kHz (+4dB) to emphasize presence range
        2. High-pass filter at 38Hz to remove subsonic content

    Args:
        signal: Input audio signal.
        sample_rate: Audio sample rate.

    Returns:
        K-weighted signal.
    """
    nyquist = sample_rate / 2.0

    hp_freq = min(_K_WEIGHT_HIGHPASS_FREQ / nyquist, 0.999)
    if hp_freq > 0.001:
        hp_sos = butter(2, hp_freq, btype="high", output="sos")
        signal = sosfilt(hp_sos, signal).astype(np.float64)

    shelf_freq = min(_K_WEIGHT_HIGH_SHELF_FREQ / nyquist, 0.999)
    if shelf_freq > 0.001:
        shelf_sos = butter(1, shelf_freq, btype="high", output="sos")
        high_content: NDArray[np.float64] = sosfilt(shelf_sos, signal).astype(
            np.float64
        )
        shelf_gain = 10.0 ** (_K_WEIGHT_HIGH_SHELF_GAIN_DB / 20.0) - 1.0
        signal = signal + high_content * shelf_gain

    return signal


def _compute_block_energies(
    left_weighted: NDArray[np.float64],
    right_weighted: NDArray[np.float64],
    block_size: int,
    hop_size: int,
) -> NDArray[np.float64]:
    """Compute mean-square energy per block for LUFS gating.

    Calculates sum of left² and right² mean-square energies per
    overlapping block, as specified by ITU-R BS.1770-4.

    Args:
        left_weighted: K-weighted left channel.
        right_weighted: K-weighted right channel.
        block_size: Block size in samples.
        hop_size: Hop size in samples.

    Returns:
        Array of per-block energy values.
    """
    n = min(len(left_weighted), len(right_weighted))
    n_blocks = max(0, (n - block_size) // hop_size + 1)

    if n_blocks == 0:
        return np.array([], dtype=np.float64)

    energies = np.empty(n_blocks, dtype=np.float64)
    for i in range(n_blocks):
        start = i * hop_size
        end = start + block_size
        left_block = left_weighted[start:end]
        right_block = right_weighted[start:end]
        energies[i] = float(np.mean(left_block**2) + np.mean(right_block**2))

    return energies

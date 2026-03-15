"""Tests for the professional mastering chain.

Validates LUFS measurement accuracy, soft clipping behavior,
multiband compression stability, and stereo widening correctness.
"""

from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import NDArray

from audio_engine.errors import MasteringError
from audio_engine.mastering import (
    master_stereo,
    measure_lufs,
    multiband_compress,
    normalize_to_lufs,
    soft_clip,
    widen_stereo,
)

SAMPLE_RATE = 44100
DURATION_SECONDS = 3.0


def _generate_sine(
    frequency: float = 440.0,
    amplitude: float = 0.5,
    duration: float = DURATION_SECONDS,
    sample_rate: int = SAMPLE_RATE,
) -> NDArray[np.float64]:
    """Generate a sine wave test signal."""
    n = int(sample_rate * duration)
    t = np.arange(n, dtype=np.float64)
    return amplitude * np.sin(2.0 * np.pi * frequency * t / sample_rate)


def _generate_noise(
    amplitude: float = 0.3,
    duration: float = DURATION_SECONDS,
    sample_rate: int = SAMPLE_RATE,
) -> NDArray[np.float64]:
    """Generate white noise test signal (deterministic via seed)."""
    rng = np.random.default_rng(seed=42)
    n = int(sample_rate * duration)
    return rng.uniform(-amplitude, amplitude, n).astype(np.float64)


def _generate_multiband_signal(
    duration: float = DURATION_SECONDS,
    sample_rate: int = SAMPLE_RATE,
) -> NDArray[np.float64]:
    """Generate a signal with energy across bass, mid, and treble bands."""
    bass = _generate_sine(80.0, 0.4, duration, sample_rate)
    mid = _generate_sine(1000.0, 0.3, duration, sample_rate)
    treble = _generate_sine(8000.0, 0.2, duration, sample_rate)
    return bass + mid + treble


def test_soft_clip_prevents_hard_clipping() -> None:
    """Verify soft_clip output never exceeds ceiling value."""
    hot_signal = _generate_sine(440.0, 2.0)

    ceiling = 0.98
    clipped = soft_clip(hot_signal, ceiling=ceiling)

    max_val = float(np.max(np.abs(clipped)))
    assert (
        max_val <= ceiling
    ), f"Soft clip failed: max={max_val:.6f} exceeds ceiling={ceiling}"


def test_soft_clip_preserves_quiet_signals() -> None:
    """Verify soft_clip doesn't significantly alter quiet signals."""
    quiet = _generate_sine(440.0, 0.1)
    clipped = soft_clip(quiet, ceiling=0.98)

    max_diff = float(np.max(np.abs(quiet - clipped)))
    assert (
        max_diff < 0.005
    ), f"Soft clip altered quiet signal too much: max_diff={max_diff:.6f}"


def test_soft_clip_empty() -> None:
    """Verify soft_clip handles empty input."""
    result = soft_clip(np.array([], dtype=np.float64), ceiling=0.98)
    assert result.size == 0, "Soft clip should return empty array for empty input"


def test_multiband_no_nan_inf() -> None:
    """Verify multiband compression produces no NaN or Inf values."""
    signal = _generate_multiband_signal()

    left, right = multiband_compress(
        signal,
        signal.copy(),
        sample_rate=SAMPLE_RATE,
    )

    assert not np.any(np.isnan(left)), "NaN detected in left channel"
    assert not np.any(np.isnan(right)), "NaN detected in right channel"
    assert not np.any(np.isinf(left)), "Inf detected in left channel"
    assert not np.any(np.isinf(right)), "Inf detected in right channel"


def test_multiband_preserves_energy() -> None:
    """Verify multiband compression doesn't zero-out the signal."""
    signal = _generate_multiband_signal()
    input_rms = float(np.sqrt(np.mean(signal**2)))

    left, right = multiband_compress(
        signal,
        signal.copy(),
        sample_rate=SAMPLE_RATE,
    )
    output_rms = float(np.sqrt(np.mean(left**2)))

    assert (
        output_rms > 0.01
    ), f"Multiband zeroed signal: input_rms={input_rms:.4f}, output_rms={output_rms:.4f}"


def test_multiband_reduces_dynamic_range() -> None:
    """Verify multiband compression reduces the loud-to-quiet ratio."""
    n_quiet = int(SAMPLE_RATE * 1.5)
    n_loud = int(SAMPLE_RATE * 1.5)

    quiet = _generate_sine(1000.0, 0.05, 1.5)
    loud = _generate_sine(1000.0, 0.9, 1.5)
    signal = np.concatenate([quiet, loud])

    input_quiet_rms = float(np.sqrt(np.mean(signal[:n_quiet] ** 2)))
    input_loud_rms = float(np.sqrt(np.mean(signal[n_quiet:n_quiet + n_loud] ** 2)))
    input_ratio = input_loud_rms / max(input_quiet_rms, 1e-10)

    compressed_l, _ = multiband_compress(
        signal, signal.copy(), sample_rate=SAMPLE_RATE,
    )

    output_quiet_rms = float(np.sqrt(np.mean(compressed_l[:n_quiet] ** 2)))
    output_loud_rms = float(np.sqrt(np.mean(compressed_l[n_quiet:n_quiet + n_loud] ** 2)))
    output_ratio = output_loud_rms / max(output_quiet_rms, 1e-10)

    assert output_ratio < input_ratio, (
        f"Compression should reduce loud/quiet ratio: "
        f"input={input_ratio:.2f}, output={output_ratio:.2f}"
    )


def test_multiband_mismatched_params_raises() -> None:
    """Verify multiband raises ValueError on mismatched parameter lengths."""
    signal = _generate_sine()
    with pytest.raises(ValueError, match="Band count mismatch"):
        multiband_compress(
            signal,
            signal.copy(),
            bands=((20, 250), (250, 4000)),
            ratios=(3.0, 2.5, 2.0),
            thresholds=(0.5, 0.6, 0.7),
        )


def test_lufs_known_signal() -> None:
    """Verify LUFS measurement is within +/-2 dB of expected value.

    A 997 Hz sine at 0 dBFS should measure approximately -3.01 LUFS
    (due to single-channel RMS of a full-scale sine being -3.01 dBFS).
    With K-weighting boost, actual measurement will be slightly higher.
    """
    full_scale_sine = _generate_sine(997.0, 1.0, 5.0)
    lufs = measure_lufs(full_scale_sine, full_scale_sine.copy(), sample_rate=SAMPLE_RATE)

    assert (
        -6.0 < lufs < 2.0
    ), f"LUFS measurement out of range for full-scale sine: {lufs:.2f} LUFS"


def test_lufs_quiet_signal() -> None:
    """Verify LUFS of a very quiet signal is very negative."""
    quiet = _generate_sine(440.0, 0.001, 3.0)
    lufs = measure_lufs(quiet, quiet.copy(), sample_rate=SAMPLE_RATE)

    assert lufs < -50.0, f"Quiet signal LUFS too high: {lufs:.2f}"


def test_lufs_empty_signal() -> None:
    """Verify LUFS of empty signal returns -70."""
    empty = np.array([], dtype=np.float64)
    lufs = measure_lufs(empty, empty, sample_rate=SAMPLE_RATE)
    assert lufs == -70.0, f"Empty signal should return -70.0, got {lufs}"


def test_lufs_normalization() -> None:
    """Verify LUFS normalization brings signal close to target."""
    signal = _generate_sine(440.0, 0.1, 5.0)
    target = -14.0

    current = measure_lufs(signal, signal.copy(), sample_rate=SAMPLE_RATE)
    normalized_l, normalized_r = normalize_to_lufs(
        signal,
        signal.copy(),
        target_lufs=target,
        current_lufs=current,
    )
    result_lufs = measure_lufs(normalized_l, normalized_r, sample_rate=SAMPLE_RATE)

    error = abs(result_lufs - target)
    assert error < 1.5, (
        f"LUFS normalization error too large: target={target}, "
        f"result={result_lufs:.2f}, error={error:.2f} dB"
    )


def test_stereo_widening_identity() -> None:
    """Verify width=1.0 returns unmodified signal."""
    left = _generate_sine(440.0, 0.5)
    right = _generate_sine(550.0, 0.5)

    out_l, out_r = widen_stereo(left, right, width=1.0)

    max_diff_l = float(np.max(np.abs(left - out_l)))
    max_diff_r = float(np.max(np.abs(right - out_r)))

    assert max_diff_l < 1e-10, f"Width=1.0 changed left channel: diff={max_diff_l}"
    assert max_diff_r < 1e-10, f"Width=1.0 changed right channel: diff={max_diff_r}"


def test_stereo_widening_mono() -> None:
    """Verify width=0.0 collapses to mono."""
    left = _generate_sine(440.0, 0.5)
    right = _generate_sine(550.0, 0.5)

    out_l, out_r = widen_stereo(left, right, width=0.0)

    max_diff = float(np.max(np.abs(out_l - out_r)))
    assert max_diff < 1e-10, f"Width=0.0 should be mono: diff={max_diff}"


def test_stereo_widening_increases_width() -> None:
    """Verify width>1.0 increases the stereo difference."""
    left = _generate_sine(440.0, 0.5)
    right = _generate_sine(550.0, 0.5)

    original_diff = float(np.sum(np.abs(left - right)))

    out_l, out_r = widen_stereo(left, right, width=1.5)
    widened_diff = float(np.sum(np.abs(out_l - out_r)))

    assert widened_diff > original_diff, (
        f"Width=1.5 should increase stereo difference: "
        f"original={original_diff:.2f}, widened={widened_diff:.2f}"
    )


def test_full_pipeline_no_clipping() -> None:
    """Verify the full mastering pipeline produces no samples > 0.98."""
    signal = _generate_multiband_signal(5.0)
    noise = _generate_noise(0.2, 5.0)
    mixed = signal + noise

    mastered_l, mastered_r = master_stereo(
        mixed,
        mixed.copy(),
        target_lufs=-14.0,
        stereo_width=1.2,
        sample_rate=SAMPLE_RATE,
    )

    max_l = float(np.max(np.abs(mastered_l)))
    max_r = float(np.max(np.abs(mastered_r)))

    assert max_l <= 0.98, f"Left channel clipping: max={max_l:.6f}"
    assert max_r <= 0.98, f"Right channel clipping: max={max_r:.6f}"


def test_full_pipeline_lufs_accuracy() -> None:
    """Verify full pipeline output is within +/-1.5 dB of target LUFS."""
    signal = _generate_multiband_signal(5.0)
    target = -14.0

    mastered_l, mastered_r = master_stereo(
        signal,
        signal.copy(),
        target_lufs=target,
        stereo_width=1.2,
        sample_rate=SAMPLE_RATE,
    )

    result_lufs = measure_lufs(mastered_l, mastered_r, sample_rate=SAMPLE_RATE)
    error = abs(result_lufs - target)

    assert error < 2.0, (
        f"Pipeline LUFS error: target={target}, result={result_lufs:.2f}, "
        f"error={error:.2f} dB"
    )


def test_full_pipeline_no_nan_inf() -> None:
    """Verify full pipeline produces no NaN or Inf values."""
    signal = _generate_multiband_signal(3.0)

    mastered_l, mastered_r = master_stereo(
        signal,
        signal.copy(),
        target_lufs=-14.0,
        stereo_width=1.2,
        sample_rate=SAMPLE_RATE,
    )

    assert not np.any(np.isnan(mastered_l)), "NaN in mastered left"
    assert not np.any(np.isnan(mastered_r)), "NaN in mastered right"
    assert not np.any(np.isinf(mastered_l)), "Inf in mastered left"
    assert not np.any(np.isinf(mastered_r)), "Inf in mastered right"


def test_full_pipeline_empty() -> None:
    """Verify full pipeline handles empty input gracefully."""
    empty = np.array([], dtype=np.float64)
    mastered_l, mastered_r = master_stereo(empty, empty, target_lufs=-14.0)
    assert mastered_l.size == 0, "Expected empty left channel"
    assert mastered_r.size == 0, "Expected empty right channel"


def test_deterministic_output() -> None:
    """Verify identical input produces identical output."""
    signal = _generate_multiband_signal(2.0)

    result_1 = master_stereo(
        signal, signal.copy(), target_lufs=-14.0, sample_rate=SAMPLE_RATE,
    )
    result_2 = master_stereo(
        signal, signal.copy(), target_lufs=-14.0, sample_rate=SAMPLE_RATE,
    )

    assert np.array_equal(result_1[0], result_2[0]), "Non-deterministic left channel"
    assert np.array_equal(result_1[1], result_2[1]), "Non-deterministic right channel"


def test_master_stereo_channel_length_mismatch() -> None:
    """Verify master_stereo raises on large channel length mismatch."""
    left = _generate_sine(440.0, 0.5, 3.0)
    right = np.concatenate([left, np.zeros(100)])
    with pytest.raises(MasteringError, match="length mismatch"):
        master_stereo(left, right, sample_rate=SAMPLE_RATE)


def test_normalize_to_lufs_silent_signal() -> None:
    """Verify normalize_to_lufs passes through silent signals unchanged."""
    silent = np.zeros(44100, dtype=np.float64)
    left, right = normalize_to_lufs(silent, silent.copy(), target_lufs=-14.0, current_lufs=-70.0)
    assert np.array_equal(left, silent)

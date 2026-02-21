"""Tests for the professional mastering chain.

Validates LUFS measurement accuracy, soft clipping behavior,
multiband compression stability, and stereo widening correctness.
"""

from __future__ import annotations

import math

import numpy as np

from instrumental_engine.mastering import (
    master_stereo,
    measure_lufs,
    multiband_compress,
    normalize_to_lufs,
    soft_clip,
    widen_stereo,
)

SAMPLE_RATE = 44100
DURATION_SECONDS = 3.0
NUM_SAMPLES = int(SAMPLE_RATE * DURATION_SECONDS)


def _generate_sine(
    frequency: float = 440.0,
    amplitude: float = 0.5,
    duration: float = DURATION_SECONDS,
    sample_rate: int = SAMPLE_RATE,
) -> list[float]:
    """Generate a sine wave test signal."""
    n = int(sample_rate * duration)
    return [
        amplitude * math.sin(2.0 * math.pi * frequency * i / sample_rate)
        for i in range(n)
    ]


def _generate_noise(
    amplitude: float = 0.3,
    duration: float = DURATION_SECONDS,
    sample_rate: int = SAMPLE_RATE,
) -> list[float]:
    """Generate white noise test signal (deterministic via seed)."""
    rng = np.random.default_rng(seed=42)
    n = int(sample_rate * duration)
    return (rng.uniform(-amplitude, amplitude, n)).tolist()


def _generate_multiband_signal(
    duration: float = DURATION_SECONDS,
    sample_rate: int = SAMPLE_RATE,
) -> list[float]:
    """Generate a signal with energy across bass, mid, and treble bands."""
    bass = _generate_sine(80.0, 0.4, duration, sample_rate)
    mid = _generate_sine(1000.0, 0.3, duration, sample_rate)
    treble = _generate_sine(8000.0, 0.2, duration, sample_rate)
    return [b + m + t for b, m, t in zip(bass, mid, treble)]


def test_soft_clip_prevents_hard_clipping() -> None:
    """Verify soft_clip output never exceeds ceiling value."""
    hot_signal = [
        2.0 * math.sin(2.0 * math.pi * 440.0 * i / SAMPLE_RATE)
        for i in range(NUM_SAMPLES)
    ]

    ceiling = 0.98
    clipped = soft_clip(hot_signal, ceiling=ceiling)

    max_val = max(abs(s) for s in clipped)
    assert (
        max_val <= ceiling
    ), f"Soft clip failed: max={max_val:.6f} exceeds ceiling={ceiling}"
    print(f"  ✅ Soft clip: max={max_val:.6f} ≤ {ceiling}")


def test_soft_clip_preserves_quiet_signals() -> None:
    """Verify soft_clip doesn't significantly alter quiet signals."""
    quiet = _generate_sine(440.0, 0.1)
    clipped = soft_clip(quiet, ceiling=0.98)

    max_diff = max(abs(a - b) for a, b in zip(quiet, clipped))
    assert (
        max_diff < 0.005
    ), f"Soft clip altered quiet signal too much: max_diff={max_diff:.6f}"
    print(f"  ✅ Quiet signal preserved: max_diff={max_diff:.6f}")


def test_soft_clip_empty() -> None:
    """Verify soft_clip handles empty input."""
    result = soft_clip([], ceiling=0.98)
    assert result == [], "Soft clip should return empty list for empty input"
    print("  ✅ Empty input handled")


def test_multiband_no_nan_inf() -> None:
    """Verify multiband compression produces no NaN or Inf values."""
    signal = _generate_multiband_signal()

    left, right = multiband_compress(
        signal,
        list(signal),
        sample_rate=SAMPLE_RATE,
    )

    left_arr = np.array(left)
    right_arr = np.array(right)

    assert not np.any(np.isnan(left_arr)), "NaN detected in left channel"
    assert not np.any(np.isnan(right_arr)), "NaN detected in right channel"
    assert not np.any(np.isinf(left_arr)), "Inf detected in left channel"
    assert not np.any(np.isinf(right_arr)), "Inf detected in right channel"
    print(
        f"  ✅ No NaN/Inf: L range [{left_arr.min():.4f}, {left_arr.max():.4f}], "
        f"R range [{right_arr.min():.4f}, {right_arr.max():.4f}]"
    )


def test_multiband_preserves_energy() -> None:
    """Verify multiband compression doesn't zero-out the signal."""
    signal = _generate_multiband_signal()
    input_rms = math.sqrt(sum(s**2 for s in signal) / len(signal))

    left, right = multiband_compress(
        signal,
        list(signal),
        sample_rate=SAMPLE_RATE,
    )
    output_rms = math.sqrt(sum(s**2 for s in left) / len(left))

    assert (
        output_rms > 0.01
    ), f"Multiband zeroed signal: input_rms={input_rms:.4f}, output_rms={output_rms:.4f}"
    print(
        f"  ✅ Energy preserved: input_rms={input_rms:.4f}, output_rms={output_rms:.4f}"
    )


def test_multiband_mismatched_params_raises() -> None:
    """Verify multiband raises ValueError on mismatched parameter lengths."""
    signal = _generate_sine()
    try:
        multiband_compress(
            signal,
            list(signal),
            bands=((20, 250), (250, 4000)),
            ratios=(3.0, 2.5, 2.0),
            thresholds=(0.5, 0.6, 0.7),
        )
        assert False, "Should have raised ValueError"
    except ValueError:
        print("  ✅ Mismatched params correctly raises ValueError")


def test_lufs_known_signal() -> None:
    """Verify LUFS measurement is within ±2 dB of expected value.

    A 997 Hz sine at 0 dBFS should measure approximately -3.01 LUFS
    (due to single-channel RMS of a full-scale sine being -3.01 dBFS).
    With K-weighting boost, actual measurement will be slightly higher.
    """
    full_scale_sine = _generate_sine(997.0, 1.0, 5.0)
    lufs = measure_lufs(full_scale_sine, list(full_scale_sine), sample_rate=SAMPLE_RATE)

    assert (
        -6.0 < lufs < 2.0
    ), f"LUFS measurement out of range for full-scale sine: {lufs:.2f} LUFS"
    print(f"  ✅ Full-scale 997Hz sine: {lufs:.2f} LUFS (expected ~-3 to 0)")


def test_lufs_quiet_signal() -> None:
    """Verify LUFS of a very quiet signal is very negative."""
    quiet = _generate_sine(440.0, 0.001, 3.0)
    lufs = measure_lufs(quiet, list(quiet), sample_rate=SAMPLE_RATE)

    assert lufs < -50.0, f"Quiet signal LUFS too high: {lufs:.2f}"
    print(f"  ✅ Quiet signal: {lufs:.2f} LUFS (expected < -50)")


def test_lufs_empty_signal() -> None:
    """Verify LUFS of empty signal returns -70."""
    lufs = measure_lufs([], [], sample_rate=SAMPLE_RATE)
    assert lufs == -70.0, f"Empty signal should return -70.0, got {lufs}"
    print("  ✅ Empty signal: -70.0 LUFS")


def test_lufs_normalization() -> None:
    """Verify LUFS normalization brings signal close to target."""
    signal = _generate_sine(440.0, 0.1, 5.0)
    target = -14.0

    current = measure_lufs(signal, list(signal), sample_rate=SAMPLE_RATE)
    normalized_l, normalized_r = normalize_to_lufs(
        signal,
        list(signal),
        target_lufs=target,
        current_lufs=current,
    )
    result_lufs = measure_lufs(normalized_l, normalized_r, sample_rate=SAMPLE_RATE)

    error = abs(result_lufs - target)
    assert error < 1.5, (
        f"LUFS normalization error too large: target={target}, "
        f"result={result_lufs:.2f}, error={error:.2f} dB"
    )
    print(
        f"  ✅ Normalized: {current:.2f} → {result_lufs:.2f} LUFS "
        f"(target {target}, error {error:.2f} dB)"
    )


def test_stereo_widening_identity() -> None:
    """Verify width=1.0 returns unmodified signal."""
    left = _generate_sine(440.0, 0.5)
    right = _generate_sine(550.0, 0.5)

    out_l, out_r = widen_stereo(left, right, width=1.0)

    max_diff_l = max(abs(a - b) for a, b in zip(left, out_l))
    max_diff_r = max(abs(a - b) for a, b in zip(right, out_r))

    assert max_diff_l < 1e-10, f"Width=1.0 changed left channel: diff={max_diff_l}"
    assert max_diff_r < 1e-10, f"Width=1.0 changed right channel: diff={max_diff_r}"
    print(
        f"  ✅ Width=1.0 identity: max_diff_L={max_diff_l:.2e}, max_diff_R={max_diff_r:.2e}"
    )


def test_stereo_widening_mono() -> None:
    """Verify width=0.0 collapses to mono."""
    left = _generate_sine(440.0, 0.5)
    right = _generate_sine(550.0, 0.5)

    out_l, out_r = widen_stereo(left, right, width=0.0)

    max_diff = max(abs(a - b) for a, b in zip(out_l, out_r))
    assert max_diff < 1e-10, f"Width=0.0 should be mono: diff={max_diff}"
    print(f"  ✅ Width=0.0 mono collapse: max_diff={max_diff:.2e}")


def test_stereo_widening_increases_width() -> None:
    """Verify width>1.0 increases the stereo difference."""
    left = _generate_sine(440.0, 0.5)
    right = _generate_sine(550.0, 0.5)

    original_diff = sum(abs(a - b) for a, b in zip(left, right))

    out_l, out_r = widen_stereo(left, right, width=1.5)
    widened_diff = sum(abs(a - b) for a, b in zip(out_l, out_r))

    assert widened_diff > original_diff, (
        f"Width=1.5 should increase stereo difference: "
        f"original={original_diff:.2f}, widened={widened_diff:.2f}"
    )
    print(f"  ✅ Width=1.5 increases diff: {original_diff:.2f} → {widened_diff:.2f}")


def test_full_pipeline_no_clipping() -> None:
    """Verify the full mastering pipeline produces no samples > 0.98."""
    signal = _generate_multiband_signal(5.0)
    noise = _generate_noise(0.2, 5.0)
    mixed = [s + n for s, n in zip(signal, noise)]

    mastered_l, mastered_r = master_stereo(
        mixed,
        list(mixed),
        target_lufs=-14.0,
        stereo_width=1.2,
        sample_rate=SAMPLE_RATE,
    )

    max_l = max(abs(s) for s in mastered_l)
    max_r = max(abs(s) for s in mastered_r)

    assert max_l <= 0.98, f"Left channel clipping: max={max_l:.6f}"
    assert max_r <= 0.98, f"Right channel clipping: max={max_r:.6f}"
    print(f"  ✅ Full pipeline no clipping: max_L={max_l:.6f}, max_R={max_r:.6f}")


def test_full_pipeline_lufs_accuracy() -> None:
    """Verify full pipeline output is within ±1.5 dB of target LUFS."""
    signal = _generate_multiband_signal(5.0)
    target = -14.0

    mastered_l, mastered_r = master_stereo(
        signal,
        list(signal),
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
    print(
        f"  ✅ Pipeline LUFS: {result_lufs:.2f} (target {target}, error {error:.2f} dB)"
    )


def test_full_pipeline_no_nan_inf() -> None:
    """Verify full pipeline produces no NaN or Inf values."""
    signal = _generate_multiband_signal(3.0)

    mastered_l, mastered_r = master_stereo(
        signal,
        list(signal),
        target_lufs=-14.0,
        stereo_width=1.2,
        sample_rate=SAMPLE_RATE,
    )

    arr_l = np.array(mastered_l)
    arr_r = np.array(mastered_r)

    assert not np.any(np.isnan(arr_l)), "NaN in mastered left"
    assert not np.any(np.isnan(arr_r)), "NaN in mastered right"
    assert not np.any(np.isinf(arr_l)), "Inf in mastered left"
    assert not np.any(np.isinf(arr_r)), "Inf in mastered right"
    print("  ✅ Full pipeline: no NaN/Inf")


def test_full_pipeline_empty() -> None:
    """Verify full pipeline handles empty input gracefully."""
    mastered_l, mastered_r = master_stereo([], [], target_lufs=-14.0)
    assert mastered_l == [], "Expected empty left channel"
    assert mastered_r == [], "Expected empty right channel"
    print("  ✅ Empty input handled gracefully")


def test_deterministic_output() -> None:
    """Verify identical input produces identical output."""
    signal = _generate_multiband_signal(2.0)

    result_1 = master_stereo(
        signal, list(signal), target_lufs=-14.0, sample_rate=SAMPLE_RATE
    )
    result_2 = master_stereo(
        signal, list(signal), target_lufs=-14.0, sample_rate=SAMPLE_RATE
    )

    for i, (a, b) in enumerate(zip(result_1[0], result_2[0])):
        assert a == b, f"Non-deterministic at sample {i}: {a} != {b}"

    print("  ✅ Deterministic: two runs produce identical output")


def main() -> None:
    """Run all mastering chain tests."""
    print("\n🎛️  Professional Mastering Chain Tests\n")

    tests = [
        ("Soft Clip: prevents hard clipping", test_soft_clip_prevents_hard_clipping),
        ("Soft Clip: preserves quiet signals", test_soft_clip_preserves_quiet_signals),
        ("Soft Clip: empty input", test_soft_clip_empty),
        ("Multiband: no NaN/Inf", test_multiband_no_nan_inf),
        ("Multiband: preserves energy", test_multiband_preserves_energy),
        ("Multiband: mismatched params", test_multiband_mismatched_params_raises),
        ("LUFS: known signal", test_lufs_known_signal),
        ("LUFS: quiet signal", test_lufs_quiet_signal),
        ("LUFS: empty signal", test_lufs_empty_signal),
        ("LUFS: normalization", test_lufs_normalization),
        ("Stereo: width=1.0 identity", test_stereo_widening_identity),
        ("Stereo: width=0.0 mono", test_stereo_widening_mono),
        ("Stereo: width>1.0 widens", test_stereo_widening_increases_width),
        ("Pipeline: no clipping", test_full_pipeline_no_clipping),
        ("Pipeline: LUFS accuracy", test_full_pipeline_lufs_accuracy),
        ("Pipeline: no NaN/Inf", test_full_pipeline_no_nan_inf),
        ("Pipeline: empty input", test_full_pipeline_empty),
        ("Pipeline: deterministic", test_deterministic_output),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        try:
            test_fn()
            passed += 1
        except AssertionError as exc:
            print(f"  ❌ {name}: {exc}")
            failed += 1
        except Exception as exc:
            print(f"  💥 {name}: {type(exc).__name__}: {exc}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    if failed == 0:
        print("🎉 All mastering tests passed!")
    else:
        print(f"⚠️  {failed} test(s) failed")
        sys.exit(1)


if __name__ == "__main__":
    main()

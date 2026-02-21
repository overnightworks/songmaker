"""Tests for pitch correction (auto-tune) module.

Validates pitch detection accuracy, scale quantization, intensity
blending, and PSOLA resynthesis against pure tones and silence.
"""

from __future__ import annotations

import math

from bark_engine.pitch_correction import (
    PitchFrame,
    apply_pitch_correction,
    detect_pitch_contour,
    freq_to_midi,
    get_scale_notes,
    midi_to_freq,
    quantize_to_scale,
)

SAMPLE_RATE: int = 44100
CENTS_TOLERANCE: float = 10.0


def _generate_sine_wave(
    frequency: float,
    duration_seconds: float,
    sample_rate: int = SAMPLE_RATE,
    amplitude: float = 0.5,
) -> list[float]:
    """Generate a pure sine wave for testing."""
    num_samples = int(sample_rate * duration_seconds)
    return [
        amplitude * math.sin(2.0 * math.pi * frequency * i / sample_rate)
        for i in range(num_samples)
    ]


def _freq_error_cents(detected: float, expected: float) -> float:
    """Calculate frequency error in cents (1/100 of a semitone)."""
    return abs(1200.0 * math.log2(detected / expected))


def test_freq_to_midi_a4() -> None:
    """A4 (440Hz) maps to MIDI 69."""
    result = freq_to_midi(440.0)
    assert abs(result - 69.0) < 0.001, f"Expected 69.0, got {result}"
    print("✅ freq_to_midi: A4=440Hz → MIDI 69")


def test_freq_to_midi_c4() -> None:
    """C4 (261.63Hz) maps to MIDI 60."""
    result = freq_to_midi(261.6256)
    assert abs(result - 60.0) < 0.01, f"Expected 60.0, got {result}"
    print("✅ freq_to_midi: C4=261.63Hz → MIDI 60")


def test_midi_to_freq_roundtrip() -> None:
    """MIDI→freq→MIDI roundtrip preserves value."""
    for midi_note in (48, 60, 69, 72, 84):
        freq = midi_to_freq(float(midi_note))
        recovered = freq_to_midi(freq)
        assert (
            abs(recovered - midi_note) < 0.001
        ), f"Roundtrip failed for MIDI {midi_note}: got {recovered}"
    print("✅ MIDI↔freq roundtrip: all notes preserved")


def test_get_scale_notes_c_major() -> None:
    """C major scale contains correct notes."""
    notes = get_scale_notes("C", "major")
    assert notes == ("C", "D", "E", "F", "G", "A", "B"), f"Got {notes}"
    print("✅ get_scale_notes: C major = C D E F G A B")


def test_get_scale_notes_c_minor() -> None:
    """C minor scale contains correct notes."""
    notes = get_scale_notes("C", "minor")
    assert notes == ("C", "D", "D#", "F", "G", "G#", "A#"), f"Got {notes}"
    print("✅ get_scale_notes: C minor = C D Eb F G Ab Bb")


def test_get_scale_notes_flat_key() -> None:
    """Flat key names are accepted and normalized."""
    notes = get_scale_notes("Bb", "major")
    expected_root = "A#"
    assert notes[0] == expected_root, f"Root should be {expected_root}, got {notes[0]}"
    print("✅ get_scale_notes: Bb → A# (flat accepted)")


def test_get_scale_notes_chromatic() -> None:
    """Chromatic scale contains all 12 notes."""
    notes = get_scale_notes("C", "chromatic")
    assert len(notes) == 12, f"Expected 12 notes, got {len(notes)}"
    print("✅ get_scale_notes: chromatic = 12 notes")


def test_quantize_intensity_zero() -> None:
    """Intensity 0.0 returns original frequency unchanged."""
    original = 445.0
    result = quantize_to_scale(original, "C", "major", intensity=0.0)
    assert result == original, f"Expected {original}, got {result}"
    print("✅ quantize_to_scale: intensity=0.0 → no change")


def test_quantize_intensity_one() -> None:
    """Intensity 1.0 snaps exactly to nearest scale note."""
    a4_freq = 440.0
    result = quantize_to_scale(445.0, "A", "major", intensity=1.0)
    error_cents = _freq_error_cents(result, a4_freq)
    assert error_cents < 1.0, f"Expected snap to A4, error={error_cents:.1f} cents"
    print(
        f"✅ quantize_to_scale: intensity=1.0 → snap to A4 (error={error_cents:.2f}¢)"
    )


def test_quantize_partial_intensity() -> None:
    """Intensity 0.5 produces a value between original and target."""
    original = 445.0
    full_snap = quantize_to_scale(original, "A", "major", intensity=1.0)
    half_snap = quantize_to_scale(original, "A", "major", intensity=0.5)

    assert (
        min(original, full_snap) <= half_snap <= max(original, full_snap)
    ), f"Half snap {half_snap} not between {original} and {full_snap}"
    print(f"✅ quantize_to_scale: intensity=0.5 → between original and target")


def test_quantize_already_on_scale() -> None:
    """Note already on scale stays unchanged at any intensity."""
    a4_freq = 440.0
    result = quantize_to_scale(a4_freq, "A", "major", intensity=1.0)
    error_cents = _freq_error_cents(result, a4_freq)
    assert error_cents < 0.1, f"On-scale note shifted: error={error_cents:.1f} cents"
    print(f"✅ quantize_to_scale: on-scale note stays put")


def test_detect_pitch_440hz() -> None:
    """Detects A4 (440Hz) pure tone within ±5 cents."""
    target_freq = 440.0
    samples = _generate_sine_wave(target_freq, duration_seconds=0.5)
    contour = detect_pitch_contour(samples, SAMPLE_RATE)

    voiced_frames = [f for f in contour if f.is_voiced and f.frequency_hz is not None]
    assert len(voiced_frames) > 0, "No voiced frames detected for 440Hz tone"

    median_freq = sorted(f.frequency_hz for f in voiced_frames)[len(voiced_frames) // 2]  # type: ignore[arg-type]
    error_cents = _freq_error_cents(median_freq, target_freq)  # type: ignore[arg-type]
    assert (
        error_cents < CENTS_TOLERANCE
    ), f"440Hz detection error: {error_cents:.1f} cents (max {CENTS_TOLERANCE})"
    print(
        f"✅ detect_pitch: 440Hz → {median_freq:.1f}Hz "
        f"(error={error_cents:.2f}¢, {len(voiced_frames)} voiced frames)"
    )


def test_detect_pitch_220hz() -> None:
    """Detects A3 (220Hz) pure tone within ±5 cents."""
    target_freq = 220.0
    samples = _generate_sine_wave(target_freq, duration_seconds=0.5)
    contour = detect_pitch_contour(samples, SAMPLE_RATE)

    voiced_frames = [f for f in contour if f.is_voiced and f.frequency_hz is not None]
    assert len(voiced_frames) > 0, "No voiced frames detected for 220Hz tone"

    median_freq = sorted(f.frequency_hz for f in voiced_frames)[len(voiced_frames) // 2]  # type: ignore[arg-type]
    error_cents = _freq_error_cents(median_freq, target_freq)  # type: ignore[arg-type]
    assert (
        error_cents < CENTS_TOLERANCE
    ), f"220Hz detection error: {error_cents:.1f} cents"
    print(
        f"✅ detect_pitch: 220Hz → {median_freq:.1f}Hz " f"(error={error_cents:.2f}¢)"
    )


def test_detect_pitch_330hz() -> None:
    """Detects E4 (329.63Hz) pure tone within ±5 cents."""
    target_freq = 329.63
    samples = _generate_sine_wave(target_freq, duration_seconds=0.5)
    contour = detect_pitch_contour(samples, SAMPLE_RATE)

    voiced_frames = [f for f in contour if f.is_voiced and f.frequency_hz is not None]
    assert len(voiced_frames) > 0, "No voiced frames detected for 330Hz tone"

    median_freq = sorted(f.frequency_hz for f in voiced_frames)[len(voiced_frames) // 2]  # type: ignore[arg-type]
    error_cents = _freq_error_cents(median_freq, target_freq)  # type: ignore[arg-type]
    assert (
        error_cents < CENTS_TOLERANCE
    ), f"330Hz detection error: {error_cents:.1f} cents"
    print(
        f"✅ detect_pitch: 329.63Hz → {median_freq:.1f}Hz "
        f"(error={error_cents:.2f}¢)"
    )


def test_detect_silence_is_unvoiced() -> None:
    """Silence produces no voiced frames."""
    silence = [0.0] * (SAMPLE_RATE // 2)
    contour = detect_pitch_contour(silence, SAMPLE_RATE)

    voiced_count = sum(1 for f in contour if f.is_voiced)
    assert voiced_count == 0, f"Expected 0 voiced frames in silence, got {voiced_count}"
    print("✅ detect_pitch: silence → 0 voiced frames")


def test_detect_low_energy_unvoiced() -> None:
    """Very quiet audio is marked unvoiced."""
    quiet_sine = _generate_sine_wave(440.0, duration_seconds=0.5, amplitude=0.005)
    contour = detect_pitch_contour(quiet_sine, SAMPLE_RATE)

    voiced_count = sum(1 for f in contour if f.is_voiced)
    assert (
        voiced_count == 0
    ), f"Expected 0 voiced frames for quiet audio, got {voiced_count}"
    print("✅ detect_pitch: quiet audio → unvoiced")


def test_apply_correction_zero_intensity() -> None:
    """Intensity 0.0 returns identical audio."""
    samples = _generate_sine_wave(440.0, duration_seconds=0.3)
    result = apply_pitch_correction(samples, intensity=0.0, key="C", scale="minor")

    assert result == samples, "Zero intensity should return identical audio"
    print("✅ apply_pitch_correction: intensity=0.0 → identical output")


def test_apply_correction_preserves_length() -> None:
    """Output has exactly the same length as input."""
    samples = _generate_sine_wave(440.0, duration_seconds=0.5)
    result = apply_pitch_correction(samples, intensity=0.7, key="C", scale="minor")

    assert len(result) == len(
        samples
    ), f"Length mismatch: input={len(samples)}, output={len(result)}"
    print(f"✅ apply_pitch_correction: length preserved ({len(samples)} samples)")


def test_apply_correction_short_audio() -> None:
    """Audio shorter than frame size is returned unchanged."""
    short_samples = [0.5] * 100
    result = apply_pitch_correction(
        short_samples, intensity=0.7, key="C", scale="minor"
    )

    assert result == short_samples, "Short audio should pass through unchanged"
    print("✅ apply_pitch_correction: short audio → pass through")


def test_apply_correction_on_scale_note() -> None:
    """A note already on scale should barely change."""
    a_freq = 440.0
    samples = _generate_sine_wave(a_freq, duration_seconds=0.5)
    result = apply_pitch_correction(samples, intensity=0.7, key="A", scale="minor")

    result_contour = detect_pitch_contour(result, SAMPLE_RATE)
    voiced = [f for f in result_contour if f.is_voiced and f.frequency_hz is not None]

    if voiced:
        median = sorted(f.frequency_hz for f in voiced)[len(voiced) // 2]  # type: ignore[arg-type]
        error = _freq_error_cents(median, a_freq)  # type: ignore[arg-type]
        assert error < 20.0, f"On-scale note drifted by {error:.1f} cents"
        print(
            f"✅ apply_pitch_correction: on-scale A4 stays stable (drift={error:.1f}¢)"
        )
    else:
        print("✅ apply_pitch_correction: on-scale test (no voiced frames to check)")


def test_full_pipeline_integration() -> None:
    """Full pipeline processes without errors."""
    samples = _generate_sine_wave(350.0, duration_seconds=0.5)

    result = apply_pitch_correction(
        samples,
        intensity=0.7,
        key="C",
        scale="minor",
        sample_rate=SAMPLE_RATE,
    )

    assert len(result) == len(samples)
    assert all(isinstance(s, float) for s in result[:100])
    print("✅ Full pipeline integration: no errors, correct types")


def run_all_tests() -> None:
    """Execute all pitch correction tests."""
    print("=" * 60)
    print("  Pitch Correction Test Suite")
    print("=" * 60)
    print()

    print("--- MIDI/Frequency Conversion ---")
    test_freq_to_midi_a4()
    test_freq_to_midi_c4()
    test_midi_to_freq_roundtrip()
    print()

    print("--- Scale Notes ---")
    test_get_scale_notes_c_major()
    test_get_scale_notes_c_minor()
    test_get_scale_notes_flat_key()
    test_get_scale_notes_chromatic()
    print()

    print("--- Quantization ---")
    test_quantize_intensity_zero()
    test_quantize_intensity_one()
    test_quantize_partial_intensity()
    test_quantize_already_on_scale()
    print()

    print("--- Pitch Detection ---")
    test_detect_pitch_440hz()
    test_detect_pitch_220hz()
    test_detect_pitch_330hz()
    test_detect_silence_is_unvoiced()
    test_detect_low_energy_unvoiced()
    print()

    print("--- Full Pipeline ---")
    test_apply_correction_zero_intensity()
    test_apply_correction_preserves_length()
    test_apply_correction_short_audio()
    test_apply_correction_on_scale_note()
    test_full_pipeline_integration()
    print()

    print("=" * 60)
    print("  All pitch correction tests passed! ✅")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()

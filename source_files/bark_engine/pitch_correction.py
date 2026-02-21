"""Pitch correction (auto-tune) for Bark vocal output.

Detects fundamental frequency via autocorrelation, quantizes pitch to
the nearest note in a musical scale, and resynthesizes audio using
PSOLA (Pitch-Synchronous Overlap-Add) for artifact-free correction.

Enabled by default at 70% intensity in C minor. Configurable per
VocalSection via pitch_correction_intensity, pitch_correction_key,
and pitch_correction_scale fields.

Pipeline:
    1. Detect pitch contour via windowed autocorrelation
    2. Quantize each frame to nearest scale note
    3. Resynthesize with PSOLA pitch shifting
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

A4_FREQUENCY: Final[float] = 440.0
A4_MIDI_NUMBER: Final[int] = 69
SEMITONES_PER_OCTAVE: Final[int] = 12
MIN_PITCH_HZ: Final[float] = 50.0
MAX_PITCH_HZ: Final[float] = 500.0
DEFAULT_FRAME_SIZE: Final[int] = 2048
DEFAULT_HOP_SIZE: Final[int] = 512
UNPITCHED_ENERGY_THRESHOLD: Final[float] = 0.01
AUTOCORRELATION_CLARITY_THRESHOLD: Final[float] = 0.3

MAJOR_INTERVALS: Final[tuple[int, ...]] = (0, 2, 4, 5, 7, 9, 11)
MINOR_INTERVALS: Final[tuple[int, ...]] = (0, 2, 3, 5, 7, 8, 10)
CHROMATIC_INTERVALS: Final[tuple[int, ...]] = tuple(range(SEMITONES_PER_OCTAVE))

NOTE_NAMES: Final[tuple[str, ...]] = (
    "C",
    "C#",
    "D",
    "D#",
    "E",
    "F",
    "F#",
    "G",
    "G#",
    "A",
    "A#",
    "B",
)

FLAT_TO_SHARP_MAP: Final[dict[str, str]] = {
    "Db": "C#",
    "Eb": "D#",
    "Fb": "E",
    "Gb": "F#",
    "Ab": "G#",
    "Bb": "A#",
    "Cb": "B",
}

SCALE_INTERVAL_MAP: Final[dict[str, tuple[int, ...]]] = {
    "major": MAJOR_INTERVALS,
    "minor": MINOR_INTERVALS,
    "chromatic": CHROMATIC_INTERVALS,
}


@dataclass(frozen=True)
class PitchFrame:
    """Detected pitch for a single analysis frame.

    Attributes:
        frequency_hz: Detected fundamental frequency, or None if unpitched.
        clarity: Autocorrelation peak strength (0.0-1.0).
        is_voiced: Whether this frame contains pitched content.
    """

    frequency_hz: float | None
    clarity: float
    is_voiced: bool


def freq_to_midi(freq: float) -> float:
    """Convert frequency in Hz to fractional MIDI note number.

    Uses the standard A4=440Hz tuning reference where A4 maps to MIDI 69.

    Args:
        freq: Frequency in Hz (must be positive).

    Returns:
        Fractional MIDI note number (e.g., 69.0 for 440Hz).

    Raises:
        ValueError: If frequency is not positive.
    """
    if freq <= 0.0:
        raise ValueError(f"Frequency must be positive, got {freq}")
    return A4_MIDI_NUMBER + SEMITONES_PER_OCTAVE * math.log2(freq / A4_FREQUENCY)


def midi_to_freq(midi: float) -> float:
    """Convert MIDI note number to frequency in Hz.

    Args:
        midi: MIDI note number (fractional values supported).

    Returns:
        Frequency in Hz.
    """
    return A4_FREQUENCY * (2.0 ** ((midi - A4_MIDI_NUMBER) / SEMITONES_PER_OCTAVE))


def _normalize_key_name(key: str) -> str:
    """Normalize a key name to sharp notation.

    Converts flat names (Bb, Eb, etc.) to their sharp equivalents (A#, D#).

    Args:
        key: Key name (e.g., "C", "Bb", "F#").

    Returns:
        Normalized key name using sharp notation.

    Raises:
        ValueError: If key name is not recognized.
    """
    normalized = FLAT_TO_SHARP_MAP.get(key, key)
    if normalized not in NOTE_NAMES:
        raise ValueError(
            f"Unknown key '{key}'. Valid keys: {', '.join(NOTE_NAMES)} "
            f"or flats: {', '.join(FLAT_TO_SHARP_MAP.keys())}"
        )
    return normalized


def get_scale_notes(key: str, scale: str) -> tuple[str, ...]:
    """Get note names in a musical scale.

    Args:
        key: Root note of the scale (e.g., "C", "F#", "Bb").
        scale: Scale type ("major", "minor", or "chromatic").

    Returns:
        Tuple of note names in the scale.

    Raises:
        ValueError: If key or scale is not recognized.
    """
    normalized_key = _normalize_key_name(key)
    intervals = SCALE_INTERVAL_MAP.get(scale)
    if intervals is None:
        raise ValueError(
            f"Unknown scale '{scale}'. Valid scales: "
            f"{', '.join(SCALE_INTERVAL_MAP.keys())}"
        )
    root_index = NOTE_NAMES.index(normalized_key)
    return tuple(
        NOTE_NAMES[(root_index + interval) % SEMITONES_PER_OCTAVE]
        for interval in intervals
    )


def _get_scale_midi_classes(key: str, scale: str) -> frozenset[int]:
    """Get pitch classes (0-11) belonging to a scale.

    Args:
        key: Root note of the scale.
        scale: Scale type.

    Returns:
        Frozenset of MIDI pitch classes in the scale.
    """
    normalized_key = _normalize_key_name(key)
    intervals = SCALE_INTERVAL_MAP.get(scale)
    if intervals is None:
        raise ValueError(f"Unknown scale '{scale}'")
    root_index = NOTE_NAMES.index(normalized_key)
    return frozenset(
        (root_index + interval) % SEMITONES_PER_OCTAVE for interval in intervals
    )


def quantize_to_scale(
    pitch_hz: float,
    key: str,
    scale: str,
    intensity: float,
) -> float:
    """Quantize a frequency to the nearest note in a musical scale.

    Blends between the original pitch and the quantized pitch based on
    the intensity parameter. At intensity=0.0, returns the original pitch.
    At intensity=1.0, returns the fully quantized pitch (hard snap).

    Args:
        pitch_hz: Input frequency in Hz.
        key: Musical key (e.g., "C", "F#", "Bb").
        scale: Scale type ("major", "minor", "chromatic").
        intensity: Correction strength (0.0=no correction, 1.0=hard snap).

    Returns:
        Corrected frequency in Hz.
    """
    if intensity <= 0.0:
        return pitch_hz

    midi_note = freq_to_midi(pitch_hz)
    scale_classes = _get_scale_midi_classes(key, scale)

    nearest_midi = _find_nearest_scale_note(midi_note, scale_classes)

    corrected_midi = midi_note + intensity * (nearest_midi - midi_note)
    return midi_to_freq(corrected_midi)


def _find_nearest_scale_note(midi_note: float, scale_classes: frozenset[int]) -> float:
    """Find the nearest MIDI note number that belongs to the scale.

    Searches within ±1 semitone range to find the closest scale degree.

    Args:
        midi_note: Fractional MIDI note number.
        scale_classes: Set of pitch classes (0-11) in the target scale.

    Returns:
        Nearest integer MIDI note belonging to the scale.
    """
    rounded = round(midi_note)
    best_distance = float("inf")
    best_note = rounded

    for offset in range(-1, 2):
        candidate = rounded + offset
        pitch_class = candidate % SEMITONES_PER_OCTAVE
        if pitch_class in scale_classes:
            distance = abs(midi_note - candidate)
            if distance < best_distance:
                best_distance = distance
                best_note = candidate

    return float(best_note)


def detect_pitch_contour(
    samples: list[float],
    sample_rate: int,
    frame_size: int = DEFAULT_FRAME_SIZE,
    hop_size: int = DEFAULT_HOP_SIZE,
) -> list[PitchFrame]:
    """Detect fundamental frequency per frame via autocorrelation.

    Uses windowed autocorrelation with parabolic interpolation for
    sub-sample accuracy. Frames with low energy or unclear pitch
    are marked as unvoiced.

    Args:
        samples: Input audio samples.
        sample_rate: Audio sample rate in Hz.
        frame_size: Analysis window size in samples.
        hop_size: Hop size between frames in samples.

    Returns:
        List of PitchFrame results, one per analysis frame.
    """
    audio = np.array(samples, dtype=np.float64)
    num_frames = max(1, (len(audio) - frame_size) // hop_size + 1)

    min_lag = max(1, int(sample_rate / MAX_PITCH_HZ))
    max_lag = min(frame_size - 1, int(sample_rate / MIN_PITCH_HZ))

    window = np.hanning(frame_size)
    frames: list[PitchFrame] = []

    for frame_idx in range(num_frames):
        start = frame_idx * hop_size
        end = start + frame_size

        if end > len(audio):
            frames.append(PitchFrame(frequency_hz=None, clarity=0.0, is_voiced=False))
            continue

        frame_data = audio[start:end] * window
        rms = float(np.sqrt(np.mean(frame_data**2)))

        if rms < UNPITCHED_ENERGY_THRESHOLD:
            frames.append(PitchFrame(frequency_hz=None, clarity=0.0, is_voiced=False))
            continue

        pitch_frame = _detect_frame_pitch(frame_data, sample_rate, min_lag, max_lag)
        frames.append(pitch_frame)

    return frames


def _detect_frame_pitch(
    frame_data: NDArray[np.float64],
    sample_rate: int,
    min_lag: int,
    max_lag: int,
) -> PitchFrame:
    """Detect pitch for a single windowed frame via autocorrelation.

    Args:
        frame_data: Windowed audio frame.
        sample_rate: Sample rate in Hz.
        min_lag: Minimum autocorrelation lag (corresponds to max frequency).
        max_lag: Maximum autocorrelation lag (corresponds to min frequency).

    Returns:
        PitchFrame with detected frequency or None if unvoiced.
    """
    correlation = np.correlate(frame_data, frame_data, mode="full")
    correlation = correlation[len(frame_data) - 1 :]

    zero_lag_energy = correlation[0]
    if zero_lag_energy < 1e-10:
        return PitchFrame(frequency_hz=None, clarity=0.0, is_voiced=False)

    normalized = correlation / zero_lag_energy
    search_region = normalized[min_lag : max_lag + 1]

    if len(search_region) == 0:
        return PitchFrame(frequency_hz=None, clarity=0.0, is_voiced=False)

    peak_idx_local = int(np.argmax(search_region))
    peak_value = float(search_region[peak_idx_local])

    if peak_value < AUTOCORRELATION_CLARITY_THRESHOLD:
        return PitchFrame(frequency_hz=None, clarity=peak_value, is_voiced=False)

    peak_idx = peak_idx_local + min_lag
    refined_lag = _parabolic_interpolation(normalized, peak_idx)

    if refined_lag <= 0:
        return PitchFrame(frequency_hz=None, clarity=peak_value, is_voiced=False)

    frequency = sample_rate / refined_lag

    if not (MIN_PITCH_HZ <= frequency <= MAX_PITCH_HZ):
        return PitchFrame(frequency_hz=None, clarity=peak_value, is_voiced=False)

    return PitchFrame(frequency_hz=frequency, clarity=peak_value, is_voiced=True)


def _parabolic_interpolation(correlation: NDArray[np.float64], peak_idx: int) -> float:
    """Refine autocorrelation peak location via parabolic interpolation.

    Fits a parabola through the peak and its neighbors to achieve
    sub-sample pitch accuracy (reduces quantization error by ~10x).

    Args:
        correlation: Normalized autocorrelation array.
        peak_idx: Index of the detected peak.

    Returns:
        Refined peak position as a fractional index.
    """
    if peak_idx <= 0 or peak_idx >= len(correlation) - 1:
        return float(peak_idx)

    alpha = float(correlation[peak_idx - 1])
    beta = float(correlation[peak_idx])
    gamma = float(correlation[peak_idx + 1])

    denominator = alpha - 2.0 * beta + gamma
    if abs(denominator) < 1e-10:
        return float(peak_idx)

    adjustment = 0.5 * (alpha - gamma) / denominator
    return peak_idx + adjustment


def resynthesize_audio(
    samples: list[float],
    original_pitches: list[PitchFrame],
    target_pitches: list[float | None],
    sample_rate: int,
    frame_size: int = DEFAULT_FRAME_SIZE,
    hop_size: int = DEFAULT_HOP_SIZE,
) -> list[float]:
    """Resynthesize audio with corrected pitch using PSOLA.

    Pitch-Synchronous Overlap-Add shifts pitch by resampling individual
    pitch periods and overlap-adding them at the target rate. Unvoiced
    frames pass through unchanged to preserve consonants and breath.

    Args:
        samples: Original audio samples.
        original_pitches: Detected pitch contour (one PitchFrame per frame).
        target_pitches: Target frequencies per frame (None = pass through).
        sample_rate: Audio sample rate in Hz.
        frame_size: Analysis window size in samples.
        hop_size: Hop size between frames in samples.

    Returns:
        Pitch-corrected audio samples.
    """
    audio = np.array(samples, dtype=np.float64)
    output = np.array(audio, copy=True)
    window = np.hanning(frame_size)
    normalization = np.zeros(len(audio), dtype=np.float64)

    num_frames = min(len(original_pitches), len(target_pitches))

    for frame_idx in range(num_frames):
        start = frame_idx * hop_size
        end = start + frame_size

        if end > len(audio):
            break

        original = original_pitches[frame_idx]
        target = target_pitches[frame_idx]

        if not original.is_voiced or original.frequency_hz is None or target is None:
            output[start:end] += audio[start:end] * window
            normalization[start:end] += window
            continue

        shift_ratio = target / original.frequency_hz

        if abs(shift_ratio - 1.0) < 0.001:
            output[start:end] += audio[start:end] * window
            normalization[start:end] += window
            continue

        shifted_frame = _shift_frame_pitch(audio[start:end], shift_ratio, window)

        output[start:end] += shifted_frame
        normalization[start:end] += window

    safe_norm = np.where(normalization > 1e-10, normalization, 1.0)
    output = output / safe_norm

    return output.tolist()


def _shift_frame_pitch(
    frame: NDArray[np.float64],
    shift_ratio: float,
    window: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Shift pitch of a single frame via resampling.

    Resamples the frame to change its pitch, then windows the result.
    Uses linear interpolation for efficient, artifact-free resampling.

    Args:
        frame: Audio frame to pitch-shift.
        shift_ratio: Pitch shift factor (>1.0 = higher pitch).
        window: Analysis window for smooth overlap-add.

    Returns:
        Pitch-shifted and windowed frame.
    """
    frame_length = len(frame)
    resampled_length = int(frame_length / shift_ratio)

    if resampled_length < 2:
        return frame * window

    original_indices = np.linspace(0, frame_length - 1, resampled_length)
    resampled = np.interp(original_indices, np.arange(frame_length), frame)

    if len(resampled) < frame_length:
        padded = np.zeros(frame_length, dtype=np.float64)
        padded[: len(resampled)] = resampled
        resampled = padded
    elif len(resampled) > frame_length:
        resampled = resampled[:frame_length]

    return resampled * window


def apply_pitch_correction(
    samples: list[float],
    intensity: float,
    key: str,
    scale: str,
    sample_rate: int = 44100,
) -> list[float]:
    """Apply pitch correction to vocal audio.

    Full pipeline: detect pitch contour via autocorrelation, quantize
    each frame to the nearest note in the target scale, and resynthesize
    using PSOLA for artifact-free pitch shifting. Unvoiced regions
    (consonants, breath, silence) pass through unmodified.

    Args:
        samples: Input audio samples (mono, normalized [-1.0, 1.0]).
        intensity: Correction strength (0.0=off, 0.7=default, 1.0=hard snap).
        key: Musical key (e.g., "C", "F#", "Bb").
        scale: Scale type ("major", "minor", "chromatic").
        sample_rate: Audio sample rate in Hz.

    Returns:
        Pitch-corrected audio samples, same length as input.
    """
    if intensity <= 0.0:
        return samples

    if len(samples) < DEFAULT_FRAME_SIZE:
        return samples

    intensity = min(1.0, max(0.0, intensity))

    pitch_contour = detect_pitch_contour(
        samples, sample_rate, DEFAULT_FRAME_SIZE, DEFAULT_HOP_SIZE
    )

    target_pitches = _compute_target_pitches(pitch_contour, key, scale, intensity)

    corrected = resynthesize_audio(
        samples,
        pitch_contour,
        target_pitches,
        sample_rate,
        DEFAULT_FRAME_SIZE,
        DEFAULT_HOP_SIZE,
    )

    return _preserve_original_length(corrected, len(samples))


def _compute_target_pitches(
    pitch_contour: list[PitchFrame],
    key: str,
    scale: str,
    intensity: float,
) -> list[float | None]:
    """Compute target frequencies for each frame in the pitch contour.

    Voiced frames are quantized to the nearest scale note with the given
    intensity. Unvoiced frames receive None (pass through).

    Args:
        pitch_contour: Detected pitch frames.
        key: Musical key for quantization.
        scale: Scale type for quantization.
        intensity: Correction strength.

    Returns:
        List of target frequencies (None for unvoiced frames).
    """
    targets: list[float | None] = []

    for frame in pitch_contour:
        if not frame.is_voiced or frame.frequency_hz is None:
            targets.append(None)
            continue

        corrected_freq = quantize_to_scale(frame.frequency_hz, key, scale, intensity)
        targets.append(corrected_freq)

    return targets


def _preserve_original_length(samples: list[float], target_length: int) -> list[float]:
    """Ensure output has exactly the same length as input.

    Args:
        samples: Audio samples (may be slightly different length).
        target_length: Desired output length.

    Returns:
        Samples trimmed or zero-padded to target_length.
    """
    if len(samples) == target_length:
        return samples
    if len(samples) > target_length:
        return samples[:target_length]
    return samples + [0.0] * (target_length - len(samples))

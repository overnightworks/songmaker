"""Constants for the instrumental engine."""

from __future__ import annotations

from typing import Final

SAMPLE_RATE: Final[int] = 44100
TWO_PI: Final[float] = 6.283185307179586
CONCERT_A4: Final[float] = 440.0

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

A4_MIDI: Final[int] = 69
MIDDLE_C_MIDI: Final[int] = 60


def midi_to_freq(midi_note: int) -> float:
    """Convert MIDI note number to frequency in Hz.

    Args:
        midi_note: MIDI note number (0-127).

    Returns:
        Frequency in Hz.
    """
    return CONCERT_A4 * (2.0 ** ((midi_note - A4_MIDI) / 12.0))


def note_name_to_midi(name: str, octave: int = 4) -> int:
    """Convert note name and octave to MIDI note number.

    Args:
        name: Note name (e.g. "C", "F#", "Bb").
        octave: Octave number (default 4).

    Returns:
        MIDI note number.

    Raises:
        ValueError: If note name is invalid.
    """
    normalized = name.replace("b", "#")
    flat_to_sharp = {
        "D#": "D#",
        "Db": "C#",
        "Eb": "D#",
        "Fb": "E",
        "Gb": "F#",
        "Ab": "G#",
        "Bb": "A#",
        "Cb": "B",
    }
    resolved = flat_to_sharp.get(name, normalized)
    if resolved not in NOTE_NAMES:
        raise ValueError(f"Invalid note name: {name!r}")
    semitone = NOTE_NAMES.index(resolved)
    return (octave + 1) * 12 + semitone


def note_to_freq(name: str, octave: int = 4) -> float:
    """Convert note name and octave to frequency.

    Args:
        name: Note name (e.g. "C", "F#").
        octave: Octave number.

    Returns:
        Frequency in Hz.
    """
    return midi_to_freq(note_name_to_midi(name, octave))


# Pre-computed common note frequencies for quick access
FREQ_C3: Final[float] = midi_to_freq(48)
FREQ_E3: Final[float] = midi_to_freq(52)
FREQ_G3: Final[float] = midi_to_freq(55)
FREQ_C4: Final[float] = midi_to_freq(60)
FREQ_E4: Final[float] = midi_to_freq(64)
FREQ_G4: Final[float] = midi_to_freq(67)
FREQ_A4: Final[float] = CONCERT_A4

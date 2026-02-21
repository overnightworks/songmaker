"""Domain models for the instrumental engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Protocol


class NoteLength(StrEnum):
    """Musical note duration identifiers."""

    WHOLE = "whole"
    HALF = "half"
    QUARTER = "quarter"
    EIGHTH = "eighth"
    SIXTEENTH = "sixteenth"
    DOTTED_HALF = "dotted_half"
    DOTTED_QUARTER = "dotted_quarter"
    TRIPLET_QUARTER = "triplet_quarter"
    TRIPLET_EIGHTH = "triplet_eighth"


class DrumSound(IntEnum):
    """General MIDI drum map (channel 10)."""

    KICK = 36
    SNARE = 38
    CLOSED_HIHAT = 42
    OPEN_HIHAT = 46
    RIDE = 51
    CRASH = 49
    CLAP = 39
    TOM_LOW = 45
    TOM_MID = 47
    TOM_HIGH = 50
    RIMSHOT = 37
    COWBELL = 56
    SHAKER = 70


class GMProgram(IntEnum):
    """General MIDI program numbers for common instruments."""

    ACOUSTIC_GRAND_PIANO = 0
    BRIGHT_PIANO = 1
    ELECTRIC_PIANO = 4
    HARPSICHORD = 6
    NYLON_GUITAR = 24
    STEEL_GUITAR = 25
    ELECTRIC_GUITAR_CLEAN = 27
    ELECTRIC_GUITAR_MUTED = 28
    OVERDRIVEN_GUITAR = 29
    DISTORTION_GUITAR = 30
    ACOUSTIC_BASS = 32
    FINGERED_BASS = 33
    PICKED_BASS = 34
    SLAP_BASS = 36
    SYNTH_BASS_1 = 38
    VIOLIN = 40
    VIOLA = 41
    CELLO = 42
    STRINGS_ENSEMBLE = 48
    SYNTH_STRINGS = 50
    CHOIR_AAHS = 52
    VOICE_OOHS = 53
    TRUMPET = 56
    TROMBONE = 57
    FRENCH_HORN = 60
    BRASS_SECTION = 61
    SYNTH_LEAD_SQUARE = 80
    SYNTH_LEAD_SAW = 81
    SYNTH_PAD_WARM = 89
    SYNTH_PAD_CHOIR = 91
    SYNTH_PAD_SWEEP = 95


class SectionType(StrEnum):
    """Standard song section types."""

    INTRO = "intro"
    VERSE = "verse"
    PRE_CHORUS = "pre_chorus"
    CHORUS = "chorus"
    BRIDGE = "bridge"
    DROP = "drop"
    BREAKDOWN = "breakdown"
    OUTRO = "outro"
    BUILDUP = "buildup"
    SOLO = "solo"


class PanPosition(StrEnum):
    """Stereo pan positions."""

    HARD_LEFT = "hard_left"
    LEFT = "left"
    CENTER_LEFT = "center_left"
    CENTER = "center"
    CENTER_RIGHT = "center_right"
    RIGHT = "right"
    HARD_RIGHT = "hard_right"


PAN_VALUES: dict[PanPosition, float] = {
    PanPosition.HARD_LEFT: -1.0,
    PanPosition.LEFT: -0.7,
    PanPosition.CENTER_LEFT: -0.3,
    PanPosition.CENTER: 0.0,
    PanPosition.CENTER_RIGHT: 0.3,
    PanPosition.RIGHT: 0.7,
    PanPosition.HARD_RIGHT: 1.0,
}


@dataclass(frozen=True)
class Note:
    """A single musical note.

    Attributes:
        midi: MIDI note number (0-127).
        velocity: Note velocity / loudness (0.0 - 1.0).
        duration_beats: Duration in beats.
    """

    midi: int
    velocity: float = 0.8
    duration_beats: float = 1.0


@dataclass(frozen=True)
class Rest:
    """A silence period.

    Attributes:
        duration_beats: Duration in beats.
    """

    duration_beats: float = 1.0


@dataclass(frozen=True)
class Chord:
    """Multiple notes sounding together.

    Attributes:
        notes: MIDI note numbers forming the chord.
        velocity: Chord velocity / loudness.
        duration_beats: Duration in beats.
    """

    notes: tuple[int, ...]
    velocity: float = 0.7
    duration_beats: float = 1.0


NoteEvent = Note | Rest | Chord


@dataclass(frozen=True)
class DrumHit:
    """A single drum hit within a pattern.

    Attributes:
        sound: Which drum sound to trigger.
        velocity: Hit velocity (0.0 - 1.0).
        beat_position: Position within the pattern in beats.
    """

    sound: DrumSound
    velocity: float = 0.8
    beat_position: float = 0.0


@dataclass(frozen=True)
class DrumPattern:
    """A repeatable drum pattern.

    Attributes:
        name: Pattern identifier.
        hits: Sequence of drum hits.
        length_beats: Total pattern length in beats.
    """

    name: str
    hits: tuple[DrumHit, ...]
    length_beats: float = 4.0


@dataclass(frozen=True)
class InstrumentTrack:
    """Configuration for one instrument in an arrangement.

    Attributes:
        name: Human-readable track name.
        instrument_id: Identifier for the instrument to use.
        events: Sequence of note events in order.
        volume: Track volume (0.0 - 1.0).
        pan: Stereo pan position.
        gm_program: General MIDI program (for SoundFont instruments).
    """

    name: str
    instrument_id: str
    events: tuple[NoteEvent, ...] = ()
    volume: float = 0.7
    pan: PanPosition = PanPosition.CENTER
    gm_program: GMProgram = GMProgram.ACOUSTIC_GRAND_PIANO


@dataclass(frozen=True)
class SongSection:
    """A section of the song arrangement.

    Attributes:
        section_type: Type of section (verse, chorus, etc.).
        start_beat: Starting beat position in the song.
        length_beats: Length of this section in beats.
        bpm: Tempo for this section.
        tracks: Instrument tracks active in this section.
        drum_pattern: Optional drum pattern for this section.
        label: Optional human-readable label.
    """

    section_type: SectionType
    start_beat: float
    length_beats: float
    bpm: int
    tracks: tuple[InstrumentTrack, ...] = ()
    drum_pattern: DrumPattern | None = None
    label: str = ""


@dataclass(frozen=True)
class Arrangement:
    """Complete song arrangement.

    Attributes:
        title: Song title.
        default_bpm: Default tempo.
        sections: Ordered sequence of song sections.
        time_signature_numerator: Beats per bar.
        time_signature_denominator: Beat note value.
    """

    title: str
    default_bpm: int
    sections: tuple[SongSection, ...]
    time_signature_numerator: int = 4
    time_signature_denominator: int = 4


class InstrumentRenderer(Protocol):
    """Protocol for rendering audio from note events.

    All instrument implementations must conform to this interface.
    """

    def render_note(
        self, freq: float, duration_seconds: float, velocity: float
    ) -> list[float]:
        """Render a single note to audio samples at SAMPLE_RATE.

        Args:
            freq: Note frequency in Hz.
            duration_seconds: Duration in seconds.
            velocity: Volume/intensity (0.0 - 1.0).

        Returns:
            Audio samples in [-1.0, 1.0] range.
        """
        ...

    def render_chord(
        self,
        frequencies: tuple[float, ...],
        duration_seconds: float,
        velocity: float,
    ) -> list[float]:
        """Render multiple notes sounding together.

        Args:
            frequencies: Tuple of note frequencies in Hz.
            duration_seconds: Duration in seconds.
            velocity: Volume/intensity.

        Returns:
            Audio samples in [-1.0, 1.0] range.
        """
        ...


@dataclass(frozen=True)
class RenderedTrack:
    """Result of rendering an instrument track.

    Attributes:
        name: Track name.
        samples_left: Left channel audio samples.
        samples_right: Right channel audio samples.
        volume: Track volume multiplier.
    """

    name: str
    samples_left: list[float]
    samples_right: list[float]
    volume: float = 1.0

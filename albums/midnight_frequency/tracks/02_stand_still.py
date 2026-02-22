"""Track 02: Stand Still — Melodic House / Progressive House (Lane 8 × Rufus Du Sol).

Album: Midnight Frequency
Genre: Melodic House / Progressive House
BPM: 122
Key: A minor
Duration: 480 beats (3:56)

Emotional arc: Rushing → exhaustion → sudden stop → clarity → peace
Hook: "Stand still, let the whole world blur"
"""

from __future__ import annotations

import math
import os
import random
from typing import Final

from bark_engine import (
    BarkVocalEngine,
    VocalSection,
    VocalStyle,
    calculate_vocal_durations,
)
from bark_engine.models import VocalLanguage
from instrumental_engine import (
    SAMPLE_RATE,
    Arrangement,
    Chord,
    DrumHit,
    DrumPattern,
    DrumSound,
    InstrumentTrack,
    Note,
    PanPosition,
    Rest,
    SectionType,
    SongSection,
    apply_ducking,
    render_arrangement,
)
from instrumental_engine.mixer import (
    master_to_mp3,
    normalize_stereo,
    overlay_onto,
    write_stereo_wav,
)

# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════
BPM: Final[int] = 122
SECONDS_PER_BEAT: Final[float] = 60.0 / BPM
TOTAL_BEATS: Final[float] = 480.0

OUTPUT_DIR: Final[str] = "_output/midnight_frequency"
WAV_PATH: Final[str] = os.path.join(OUTPUT_DIR, "02_Stand_Still.wav")
MP3_PATH: Final[str] = os.path.join(OUTPUT_DIR, "02_Stand_Still.mp3")

# ═══════════════════════════════════════════════════════════════════════════
# MIDI note constants (A minor: A B C D E F G)
# ═══════════════════════════════════════════════════════════════════════════

# Bass octave (sub_bass)
A1: Final[int] = 33
C2: Final[int] = 36
D2: Final[int] = 38
E2: Final[int] = 40
F2: Final[int] = 41
G2: Final[int] = 43

# Pad octave
A2: Final[int] = 45
C3: Final[int] = 48
D3: Final[int] = 50
E3: Final[int] = 52
F3: Final[int] = 53
G3: Final[int] = 55
A3: Final[int] = 57
B3: Final[int] = 59

# Supersaw / chord octave
C4: Final[int] = 60
D4: Final[int] = 62
E4: Final[int] = 64
F4: Final[int] = 65
G4: Final[int] = 67
A4: Final[int] = 69
B4: Final[int] = 71

# Arpeggio octave (pluck)
C5: Final[int] = 72
D5: Final[int] = 74
E5: Final[int] = 76
F5: Final[int] = 77
G5: Final[int] = 79
A5: Final[int] = 81


# ═══════════════════════════════════════════════════════════════════════════
# White noise riser synthesis
# ═══════════════════════════════════════════════════════════════════════════

def _synth_white_noise_riser(
    duration_seconds: float,
    volume: float = 0.3,
) -> tuple[list[float], list[float]]:
    """Synthesize a white noise riser with rising filter sweep."""
    num_samples = int(duration_seconds * SAMPLE_RATE)
    left: list[float] = [0.0] * num_samples
    right: list[float] = [0.0] * num_samples

    prev_left = 0.0
    prev_right = 0.0

    for i in range(num_samples):
        progress = i / num_samples
        noise_l = random.uniform(-1.0, 1.0)
        noise_r = random.uniform(-1.0, 1.0)

        cutoff = 0.01 + 0.99 * (progress ** 2.0)
        envelope = progress * volume

        prev_left = prev_left + cutoff * (noise_l - prev_left)
        prev_right = prev_right + cutoff * (noise_r - prev_right)

        left[i] = prev_left * envelope
        right[i] = prev_right * envelope

    return left, right


def _synth_impact(volume: float = 0.5) -> tuple[list[float], list[float]]:
    """Synthesize a downlifter impact hit for drop entries."""
    duration_samples = int(0.8 * SAMPLE_RATE)
    left: list[float] = [0.0] * duration_samples
    right: list[float] = [0.0] * duration_samples

    for i in range(duration_samples):
        t = i / SAMPLE_RATE
        progress = i / duration_samples
        freq = 200.0 * (1.0 - progress) + 30.0
        envelope = math.exp(-4.0 * t) * volume
        sample = math.sin(2.0 * math.pi * freq * t) * envelope
        noise = random.uniform(-0.1, 0.1) * envelope * (1.0 - progress)
        left[i] = sample + noise
        right[i] = sample + noise

    return left, right


# ═══════════════════════════════════════════════════════════════════════════
# Drum patterns
# ═══════════════════════════════════════════════════════════════════════════

def _build_melodic_house_beat() -> DrumPattern:
    """Four-on-the-floor with offbeat hats and clap on 2/4."""
    return DrumPattern(
        name="melodic_house",
        length_beats=4.0,
        hits=(
            DrumHit(sound=DrumSound.KICK, beat_position=0.0, velocity=0.85),
            DrumHit(sound=DrumSound.KICK, beat_position=1.0, velocity=0.85),
            DrumHit(sound=DrumSound.KICK, beat_position=2.0, velocity=0.85),
            DrumHit(sound=DrumSound.KICK, beat_position=3.0, velocity=0.85),
            DrumHit(sound=DrumSound.CLAP, beat_position=1.0, velocity=0.55),
            DrumHit(sound=DrumSound.CLAP, beat_position=3.0, velocity=0.55),
            DrumHit(sound=DrumSound.CLOSED_HIHAT, beat_position=0.5, velocity=0.3),
            DrumHit(sound=DrumSound.CLOSED_HIHAT, beat_position=1.5, velocity=0.3),
            DrumHit(sound=DrumSound.CLOSED_HIHAT, beat_position=2.5, velocity=0.3),
            DrumHit(sound=DrumSound.CLOSED_HIHAT, beat_position=3.5, velocity=0.3),
        ),
    )


def _build_verse_beat() -> DrumPattern:
    """Lighter version — kick + closed hats only, softer."""
    return DrumPattern(
        name="verse_light",
        length_beats=4.0,
        hits=(
            DrumHit(sound=DrumSound.KICK, beat_position=0.0, velocity=0.7),
            DrumHit(sound=DrumSound.KICK, beat_position=1.0, velocity=0.7),
            DrumHit(sound=DrumSound.KICK, beat_position=2.0, velocity=0.7),
            DrumHit(sound=DrumSound.KICK, beat_position=3.0, velocity=0.7),
            DrumHit(sound=DrumSound.CLOSED_HIHAT, beat_position=0.5, velocity=0.2),
            DrumHit(sound=DrumSound.CLOSED_HIHAT, beat_position=1.5, velocity=0.2),
            DrumHit(sound=DrumSound.CLOSED_HIHAT, beat_position=2.5, velocity=0.2),
            DrumHit(sound=DrumSound.CLOSED_HIHAT, beat_position=3.5, velocity=0.2),
        ),
    )


def _build_build_beat() -> DrumPattern:
    """Snare roll building pattern for pre-chorus."""
    return DrumPattern(
        name="build_roll",
        length_beats=4.0,
        hits=(
            DrumHit(sound=DrumSound.KICK, beat_position=0.0, velocity=0.8),
            DrumHit(sound=DrumSound.KICK, beat_position=1.0, velocity=0.8),
            DrumHit(sound=DrumSound.KICK, beat_position=2.0, velocity=0.8),
            DrumHit(sound=DrumSound.KICK, beat_position=3.0, velocity=0.8),
            DrumHit(sound=DrumSound.SNARE, beat_position=0.0, velocity=0.25),
            DrumHit(sound=DrumSound.SNARE, beat_position=0.25, velocity=0.28),
            DrumHit(sound=DrumSound.SNARE, beat_position=0.5, velocity=0.3),
            DrumHit(sound=DrumSound.SNARE, beat_position=0.75, velocity=0.33),
            DrumHit(sound=DrumSound.SNARE, beat_position=1.0, velocity=0.35),
            DrumHit(sound=DrumSound.SNARE, beat_position=1.25, velocity=0.38),
            DrumHit(sound=DrumSound.SNARE, beat_position=1.5, velocity=0.4),
            DrumHit(sound=DrumSound.SNARE, beat_position=1.75, velocity=0.43),
            DrumHit(sound=DrumSound.SNARE, beat_position=2.0, velocity=0.45),
            DrumHit(sound=DrumSound.SNARE, beat_position=2.25, velocity=0.5),
            DrumHit(sound=DrumSound.SNARE, beat_position=2.5, velocity=0.55),
            DrumHit(sound=DrumSound.SNARE, beat_position=2.75, velocity=0.58),
            DrumHit(sound=DrumSound.SNARE, beat_position=3.0, velocity=0.6),
            DrumHit(sound=DrumSound.SNARE, beat_position=3.25, velocity=0.65),
            DrumHit(sound=DrumSound.SNARE, beat_position=3.5, velocity=0.7),
            DrumHit(sound=DrumSound.SNARE, beat_position=3.75, velocity=0.75),
        ),
    )


def _build_drop_beat() -> DrumPattern:
    """Full four-on-the-floor with open hats and crash on 1."""
    return DrumPattern(
        name="drop_full",
        length_beats=4.0,
        hits=(
            DrumHit(sound=DrumSound.KICK, beat_position=0.0, velocity=0.95),
            DrumHit(sound=DrumSound.KICK, beat_position=1.0, velocity=0.9),
            DrumHit(sound=DrumSound.KICK, beat_position=2.0, velocity=0.9),
            DrumHit(sound=DrumSound.KICK, beat_position=3.0, velocity=0.9),
            DrumHit(sound=DrumSound.CLAP, beat_position=1.0, velocity=0.7),
            DrumHit(sound=DrumSound.CLAP, beat_position=3.0, velocity=0.7),
            DrumHit(sound=DrumSound.OPEN_HIHAT, beat_position=0.5, velocity=0.35),
            DrumHit(sound=DrumSound.OPEN_HIHAT, beat_position=1.5, velocity=0.35),
            DrumHit(sound=DrumSound.OPEN_HIHAT, beat_position=2.5, velocity=0.35),
            DrumHit(sound=DrumSound.OPEN_HIHAT, beat_position=3.5, velocity=0.35),
            DrumHit(sound=DrumSound.CRASH, beat_position=0.0, velocity=0.5),
        ),
    )


def _build_outro_beat() -> DrumPattern:
    """Minimal fading pattern for outro."""
    return DrumPattern(
        name="outro_minimal",
        length_beats=4.0,
        hits=(
            DrumHit(sound=DrumSound.KICK, beat_position=0.0, velocity=0.5),
            DrumHit(sound=DrumSound.KICK, beat_position=2.0, velocity=0.4),
            DrumHit(sound=DrumSound.CLOSED_HIHAT, beat_position=1.0, velocity=0.15),
            DrumHit(sound=DrumSound.CLOSED_HIHAT, beat_position=3.0, velocity=0.1),
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Chord / melody patterns
# ═══════════════════════════════════════════════════════════════════════════

# --- Verse progression: Am → F → C → G (4 bars each, 16 beats each) ---

def _verse_pad_chords() -> tuple[Chord, ...]:
    """Warm pad chords for verses: Am → F → C → G, 16 beats each."""
    return (
        Chord(notes=(A2, C3, E3), velocity=0.4, duration_beats=16.0),   # Am
        Chord(notes=(F3, A3, C4), velocity=0.4, duration_beats=16.0),   # F
        Chord(notes=(C3, E3, G3), velocity=0.4, duration_beats=16.0),   # C
        Chord(notes=(G3, B3, D4), velocity=0.4, duration_beats=16.0),   # G
    )


def _chorus_pad_chords() -> tuple[Chord, ...]:
    """Supporting pad under drops: Am → F → G → Em, 16 beats each."""
    return (
        Chord(notes=(A2, C3, E3), velocity=0.35, duration_beats=16.0),  # Am
        Chord(notes=(F3, A3, C4), velocity=0.35, duration_beats=16.0),  # F
        Chord(notes=(G3, B3, D4), velocity=0.35, duration_beats=16.0),  # G
        Chord(notes=(E3, G3, B3), velocity=0.35, duration_beats=16.0),  # Em
    )


def _chorus_supersaw_chords() -> tuple[Chord, ...]:
    """Full supersaw chords for drops: Am → F → G → Em, 16 beats each."""
    return (
        Chord(notes=(A4, C5, E5), velocity=0.65, duration_beats=16.0),  # Am
        Chord(notes=(F4, A4, C5), velocity=0.65, duration_beats=16.0),  # F
        Chord(notes=(G4, B4, D5), velocity=0.65, duration_beats=16.0),  # G
        Chord(notes=(E4, G4, B4), velocity=0.65, duration_beats=16.0),  # Em
    )


def _final_supersaw_chords() -> tuple[Chord, ...]:
    """Stacked supersaw chords for final drop — octave doubled."""
    return (
        Chord(notes=(A3, A4, C5, E5), velocity=0.75, duration_beats=16.0),  # Am
        Chord(notes=(F3, F4, A4, C5), velocity=0.75, duration_beats=16.0),  # F
        Chord(notes=(G3, G4, B4, D5), velocity=0.75, duration_beats=16.0),  # G
        Chord(notes=(E3, E4, G4, B4), velocity=0.75, duration_beats=16.0),  # Em
    )


def _bridge_pad_chords() -> tuple[Chord, ...]:
    """Bridge tension chords: Am → E → F → Dm, 8 beats each."""
    return (
        Chord(notes=(A2, C3, E3), velocity=0.3, duration_beats=8.0),    # Am
        Chord(notes=(E3, G3, B3), velocity=0.3, duration_beats=8.0),    # E (using Em voicing)
        Chord(notes=(F3, A3, C4), velocity=0.35, duration_beats=8.0),   # F
        Chord(notes=(D3, F3, A3), velocity=0.35, duration_beats=8.0),   # Dm
    )


def _intro_pad_chord() -> tuple[Chord, ...]:
    """Single sustained Am chord for intro atmosphere."""
    return (
        Chord(notes=(A2, C3, E3), velocity=0.25, duration_beats=32.0),
    )


def _outro_pad_chord() -> tuple[Chord, ...]:
    """Fading Am chord for outro."""
    return (
        Chord(notes=(A2, C3, E3), velocity=0.2, duration_beats=32.0),
    )


# --- Bass patterns ---

def _verse_bass() -> tuple[Note | Rest, ...]:
    """Sub bass for verses: root notes, 16 beats each."""
    return (
        Note(midi=A1, velocity=0.6, duration_beats=14.0),   # Am
        Rest(duration_beats=2.0),
        Note(midi=F2, velocity=0.6, duration_beats=14.0),   # F
        Rest(duration_beats=2.0),
        Note(midi=C2, velocity=0.6, duration_beats=14.0),   # C
        Rest(duration_beats=2.0),
        Note(midi=G2, velocity=0.6, duration_beats=14.0),   # G
        Rest(duration_beats=2.0),
    )


def _chorus_bass() -> tuple[Note | Rest, ...]:
    """Pumping sub bass for drops: root notes, 4-beat pulses."""
    elements: list[Note | Rest] = []
    roots = (A1, F2, G2, E2)  # Am → F → G → Em
    for root in roots:
        for _ in range(4):
            elements.append(Note(midi=root, velocity=0.75, duration_beats=3.5))
            elements.append(Rest(duration_beats=0.5))
    return tuple(elements)


def _final_bass() -> tuple[Note | Rest, ...]:
    """Maximum bass for final drop — octave doubled pulse."""
    elements: list[Note | Rest] = []
    roots = (A1, F2, G2, E2)
    for root in roots:
        for _ in range(4):
            elements.append(Note(midi=root, velocity=0.85, duration_beats=3.5))
            elements.append(Rest(duration_beats=0.5))
    return tuple(elements)


# --- Arpeggio patterns ---

def _verse_arpeggios() -> tuple[Note, ...]:
    """Pluck arpeggios for verses: 16th notes through chord tones."""
    notes: list[Note] = []
    chord_tones = (
        (A5, C5, E5, C5),   # Am
        (F5, A5, C5, A5),   # F
        (C5, E5, G5, E5),   # C
        (G4, B4, D5, B4),   # G
    )
    for chord in chord_tones:
        for _ in range(4):
            for tone in chord:
                notes.append(Note(midi=tone, velocity=0.35, duration_beats=0.25))
    return tuple(notes)


def _chorus_arpeggios() -> tuple[Note, ...]:
    """Brighter arpeggios for drops."""
    notes: list[Note] = []
    chord_tones = (
        (A5, C5, E5, C5),   # Am
        (F5, A5, C5, A5),   # F
        (G5, B4, D5, B4),   # G
        (E5, G5, B4, G5),   # Em
    )
    for chord in chord_tones:
        for _ in range(4):
            for tone in chord:
                notes.append(Note(midi=tone, velocity=0.4, duration_beats=0.25))
    return tuple(notes)


def _intro_pluck() -> tuple[Note | Rest, ...]:
    """Sparse intro pluck — single notes with space."""
    return (
        Note(midi=A5, velocity=0.25, duration_beats=2.0),
        Rest(duration_beats=2.0),
        Note(midi=E5, velocity=0.2, duration_beats=2.0),
        Rest(duration_beats=2.0),
        Note(midi=C5, velocity=0.25, duration_beats=2.0),
        Rest(duration_beats=2.0),
        Note(midi=A4, velocity=0.2, duration_beats=2.0),
        Rest(duration_beats=2.0),
        Note(midi=E5, velocity=0.25, duration_beats=2.0),
        Rest(duration_beats=2.0),
        Note(midi=C5, velocity=0.2, duration_beats=2.0),
        Rest(duration_beats=2.0),
        Note(midi=A5, velocity=0.25, duration_beats=2.0),
        Rest(duration_beats=2.0),
        Note(midi=E4, velocity=0.2, duration_beats=2.0),
        Rest(duration_beats=2.0),
    )


def _bridge_pluck() -> tuple[Note | Rest, ...]:
    """Sparse reverbed pluck for bridge breakdown."""
    return (
        Note(midi=A5, velocity=0.3, duration_beats=4.0),
        Rest(duration_beats=4.0),
        Note(midi=E5, velocity=0.25, duration_beats=4.0),
        Rest(duration_beats=4.0),
        Note(midi=F5, velocity=0.3, duration_beats=4.0),
        Rest(duration_beats=4.0),
        Note(midi=D5, velocity=0.25, duration_beats=4.0),
        Rest(duration_beats=4.0),
    )


def _outro_pluck() -> tuple[Note | Rest, ...]:
    """Final pluck notes fading out."""
    return (
        Note(midi=A5, velocity=0.2, duration_beats=4.0),
        Rest(duration_beats=4.0),
        Note(midi=E5, velocity=0.15, duration_beats=4.0),
        Rest(duration_beats=4.0),
        Note(midi=C5, velocity=0.1, duration_beats=4.0),
        Rest(duration_beats=4.0),
        Note(midi=A4, velocity=0.08, duration_beats=8.0),
    )


# --- Pre-chorus build chords ---

def _build_pad_chords() -> tuple[Chord, ...]:
    """Rising pad for pre-chorus build."""
    return (
        Chord(notes=(A2, C3, E3), velocity=0.5, duration_beats=8.0),    # Am
        Chord(notes=(F3, A3, C4), velocity=0.55, duration_beats=8.0),   # F
        Chord(notes=(G3, B3, D4), velocity=0.6, duration_beats=8.0),    # G
        Chord(notes=(A3, C4, E4), velocity=0.65, duration_beats=8.0),   # Am (octave up)
    )


def _build_bass() -> tuple[Note, ...]:
    """Sustained bass during build."""
    return (
        Note(midi=A1, velocity=0.5, duration_beats=16.0),
        Note(midi=A1, velocity=0.6, duration_beats=16.0),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Arrangement
# ═══════════════════════════════════════════════════════════════════════════

VERSE_BEAT: Final[DrumPattern] = _build_verse_beat()
BUILD_BEAT: Final[DrumPattern] = _build_build_beat()
DROP_BEAT: Final[DrumPattern] = _build_drop_beat()
OUTRO_BEAT: Final[DrumPattern] = _build_outro_beat()


def build_arrangement() -> Arrangement:
    """Build the complete arrangement for Stand Still."""
    return Arrangement(
        title="Stand Still",
        default_bpm=BPM,
        sections=(
            # ─── INTRO: 0-32 beats ───
            SongSection(
                section_type=SectionType.INTRO,
                start_beat=0.0,
                length_beats=32.0,
                bpm=BPM,
                tracks=(
                    InstrumentTrack(
                        name="pad", instrument_id="pad",
                        events=_intro_pad_chord(),
                        volume=0.3,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        name="pluck", instrument_id="pluck",
                        events=_intro_pluck(),
                        volume=0.25,
                        pan=PanPosition.CENTER_RIGHT,
                    ),
                ),
            ),
            # ─── VERSE 1: 32-96 beats ───
            SongSection(
                section_type=SectionType.VERSE,
                start_beat=32.0,
                length_beats=64.0,
                bpm=BPM,
                tracks=(
                    InstrumentTrack(
                        name="pad", instrument_id="pad",
                        events=_verse_pad_chords(),
                        volume=0.35,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        name="pluck", instrument_id="pluck",
                        events=_verse_arpeggios(),
                        volume=0.3,
                        pan=PanPosition.CENTER_LEFT,
                    ),
                    InstrumentTrack(
                        name="bass", instrument_id="sub_bass",
                        events=_verse_bass(),
                        volume=0.5,
                        pan=PanPosition.CENTER,
                    ),
                ),
                drum_pattern=VERSE_BEAT,
            ),
            # ─── PRE-CHORUS 1 / BUILD: 96-128 beats ───
            SongSection(
                section_type=SectionType.BRIDGE,
                start_beat=96.0,
                length_beats=32.0,
                bpm=BPM,
                tracks=(
                    InstrumentTrack(
                        name="pad", instrument_id="pad",
                        events=_build_pad_chords(),
                        volume=0.38,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        name="pluck", instrument_id="pluck",
                        events=_verse_arpeggios(),
                        volume=0.30,
                        pan=PanPosition.CENTER_RIGHT,
                    ),
                    InstrumentTrack(
                        name="bass", instrument_id="sub_bass",
                        events=_build_bass(),
                        volume=0.48,
                        pan=PanPosition.CENTER,
                    ),
                ),
                drum_pattern=BUILD_BEAT,
            ),
            # ─── DROP / CHORUS 1: 128-192 beats ───
            SongSection(
                section_type=SectionType.CHORUS,
                start_beat=128.0,
                length_beats=64.0,
                bpm=BPM,
                tracks=(
                    InstrumentTrack(
                        name="supersaw", instrument_id="supersaw",
                        events=_chorus_supersaw_chords(),
                        volume=0.50,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        name="pad", instrument_id="pad",
                        events=_chorus_pad_chords(),
                        volume=0.20,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        name="pluck", instrument_id="pluck",
                        events=_chorus_arpeggios(),
                        volume=0.20,
                        pan=PanPosition.CENTER_LEFT,
                    ),
                    InstrumentTrack(
                        name="bass", instrument_id="sub_bass",
                        events=_chorus_bass(),
                        volume=0.55,
                        pan=PanPosition.CENTER,
                    ),
                ),
                drum_pattern=DROP_BEAT,
            ),
            # ─── VERSE 2: 192-256 beats ───
            SongSection(
                section_type=SectionType.VERSE,
                start_beat=192.0,
                length_beats=64.0,
                bpm=BPM,
                tracks=(
                    InstrumentTrack(
                        name="pad", instrument_id="pad",
                        events=_verse_pad_chords(),
                        volume=0.3,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        name="pluck", instrument_id="pluck",
                        events=_verse_arpeggios(),
                        volume=0.28,
                        pan=PanPosition.CENTER_RIGHT,
                    ),
                    InstrumentTrack(
                        name="bass", instrument_id="sub_bass",
                        events=_verse_bass(),
                        volume=0.45,
                        pan=PanPosition.CENTER,
                    ),
                ),
                drum_pattern=VERSE_BEAT,
            ),
            # ─── PRE-CHORUS 2 / BUILD: 256-288 beats ───
            SongSection(
                section_type=SectionType.BRIDGE,
                start_beat=256.0,
                length_beats=32.0,
                bpm=BPM,
                tracks=(
                    InstrumentTrack(
                        name="pad", instrument_id="pad",
                        events=_build_pad_chords(),
                        volume=0.42,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        name="pluck", instrument_id="pluck",
                        events=_verse_arpeggios(),
                        volume=0.30,
                        pan=PanPosition.CENTER_LEFT,
                    ),
                    InstrumentTrack(
                        name="bass", instrument_id="sub_bass",
                        events=_build_bass(),
                        volume=0.50,
                        pan=PanPosition.CENTER,
                    ),
                ),
                drum_pattern=BUILD_BEAT,
            ),
            # ─── DROP / CHORUS 2: 288-352 beats ───
            SongSection(
                section_type=SectionType.CHORUS,
                start_beat=288.0,
                length_beats=64.0,
                bpm=BPM,
                tracks=(
                    InstrumentTrack(
                        name="supersaw", instrument_id="supersaw",
                        events=_chorus_supersaw_chords(),
                        volume=0.55,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        name="pad", instrument_id="pad",
                        events=_chorus_pad_chords(),
                        volume=0.22,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        name="pluck", instrument_id="pluck",
                        events=_chorus_arpeggios(),
                        volume=0.22,
                        pan=PanPosition.CENTER_RIGHT,
                    ),
                    InstrumentTrack(
                        name="bass", instrument_id="sub_bass",
                        events=_chorus_bass(),
                        volume=0.58,
                        pan=PanPosition.CENTER,
                    ),
                ),
                drum_pattern=DROP_BEAT,
            ),
            # ─── BRIDGE / BREAKDOWN: 352-384 beats ───
            SongSection(
                section_type=SectionType.BRIDGE,
                start_beat=352.0,
                length_beats=32.0,
                bpm=BPM,
                tracks=(
                    InstrumentTrack(
                        name="pad", instrument_id="pad",
                        events=_bridge_pad_chords(),
                        volume=0.2,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        name="pluck", instrument_id="pluck",
                        events=_bridge_pluck(),
                        volume=0.3,
                        pan=PanPosition.CENTER,
                    ),
                ),
            ),
            # ─── FINAL DROP: 384-448 beats ───
            SongSection(
                section_type=SectionType.CHORUS,
                start_beat=384.0,
                length_beats=64.0,
                bpm=BPM,
                tracks=(
                    InstrumentTrack(
                        name="supersaw", instrument_id="supersaw",
                        events=_final_supersaw_chords(),
                        volume=0.60,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        name="pad", instrument_id="pad",
                        events=_chorus_pad_chords(),
                        volume=0.22,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        name="pluck", instrument_id="pluck",
                        events=_chorus_arpeggios(),
                        volume=0.22,
                        pan=PanPosition.CENTER_LEFT,
                    ),
                    InstrumentTrack(
                        name="bass", instrument_id="sub_bass",
                        events=_final_bass(),
                        volume=0.60,
                        pan=PanPosition.CENTER,
                    ),
                ),
                drum_pattern=DROP_BEAT,
            ),
            # ─── OUTRO: 448-480 beats ───
            SongSection(
                section_type=SectionType.OUTRO,
                start_beat=448.0,
                length_beats=32.0,
                bpm=BPM,
                tracks=(
                    InstrumentTrack(
                        name="pad", instrument_id="pad",
                        events=_outro_pad_chord(),
                        volume=0.2,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        name="pluck", instrument_id="pluck",
                        events=_outro_pluck(),
                        volume=0.2,
                        pan=PanPosition.CENTER_RIGHT,
                    ),
                ),
                drum_pattern=OUTRO_BEAT,
            ),
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Vocals
# ═══════════════════════════════════════════════════════════════════════════

VOCALS: Final[list[VocalSection]] = [
    # ─── INTRO ───
    VocalSection(
        section_id="intro",
        text="Everyone is moving, everyone but me",
        style=VocalStyle.WHISPER,
        singing=True,
        volume=0.6,
        gap_after_seconds=0.0,
        num_takes=3,
        pitch_correction_intensity=0.5,
        pitch_correction_key="A",
        pitch_correction_scale="minor",
        language=VocalLanguage.ENGLISH,
        rvc_model="male_singer_v1",
    ),
    # ─── VERSE 1A ───
    VocalSection(
        section_id="verse_1a",
        text=(
            "I ran through every open door, "
            "before I knew where they led. "
            "I chased the clock around the block, "
            "and slept inside its hands"
        ),
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.8,
        gap_after_seconds=0.5,
        num_takes=3,
        pitch_correction_intensity=0.7,
        pitch_correction_key="A",
        pitch_correction_scale="minor",
        language=VocalLanguage.ENGLISH,
        rvc_model="male_singer_v1",
    ),
    # ─── VERSE 1B ───
    VocalSection(
        section_id="verse_1b",
        text=(
            "I filled the silence up with noise, "
            "and called the static peace. "
            "I wore my busy like a crown, "
            "until the gold turned green"
        ),
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.8,
        gap_after_seconds=0.3,
        num_takes=3,
        pitch_correction_intensity=0.7,
        pitch_correction_key="A",
        pitch_correction_scale="minor",
        language=VocalLanguage.ENGLISH,
        rvc_model="male_singer_v1",
    ),
    # ─── PRE-CHORUS 1 ───
    VocalSection(
        section_id="pre_chorus_1",
        text=(
            "My legs gave out, the world kept spinning, "
            "and I just stayed right here"
        ),
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.85,
        gap_after_seconds=0.0,
        num_takes=3,
        pitch_correction_intensity=0.7,
        pitch_correction_key="A",
        pitch_correction_scale="minor",
        language=VocalLanguage.ENGLISH,
        rvc_model="male_singer_v1",
    ),
    # ─── CHORUS 1A ───
    VocalSection(
        section_id="chorus_1a",
        text=(
            "Stand still, let the whole world blur. "
            "Stand still, every sound a color I never heard. "
            "I've been running all my life, "
            "stand still, stand still"
        ),
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.9,
        gap_after_seconds=0.3,
        num_takes=3,
        pitch_correction_intensity=0.8,
        pitch_correction_key="A",
        pitch_correction_scale="minor",
        language=VocalLanguage.ENGLISH,
        rvc_model="male_singer_v1",
    ),
    # ─── CHORUS 1B ───
    VocalSection(
        section_id="chorus_1b",
        text=(
            "Stand still, let the streetlights bend. "
            "Stand still, I don't need to know how this ends. "
            "I've been everywhere but here, "
            "stand still, stand still"
        ),
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.9,
        gap_after_seconds=0.5,
        num_takes=3,
        pitch_correction_intensity=0.8,
        pitch_correction_key="A",
        pitch_correction_scale="minor",
        language=VocalLanguage.ENGLISH,
        rvc_model="male_singer_v1",
    ),
    # ─── VERSE 2A ───
    VocalSection(
        section_id="verse_2a",
        text=(
            "The traffic parts around my skin, "
            "like water past a stone. "
            "The people blur like painted streaks, "
            "I'm solid and alone"
        ),
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.75,
        gap_after_seconds=0.5,
        num_takes=3,
        pitch_correction_intensity=0.7,
        pitch_correction_key="A",
        pitch_correction_scale="minor",
        language=VocalLanguage.ENGLISH,
        rvc_model="male_singer_v1",
    ),
    # ─── VERSE 2B ───
    VocalSection(
        section_id="verse_2b",
        text=(
            "My phone is ringing in my coat, "
            "I let it ring and ring. "
            "The wind knows every word I need, "
            "and says them all at once"
        ),
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.8,
        gap_after_seconds=0.3,
        num_takes=3,
        pitch_correction_intensity=0.7,
        pitch_correction_key="A",
        pitch_correction_scale="minor",
        language=VocalLanguage.ENGLISH,
        rvc_model="male_singer_v1",
    ),
    # ─── PRE-CHORUS 2 ───
    VocalSection(
        section_id="pre_chorus_2",
        text=(
            "The ground is warm, the sky is close, "
            "and I'm exactly where I am"
        ),
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.9,
        gap_after_seconds=0.0,
        num_takes=3,
        pitch_correction_intensity=0.7,
        pitch_correction_key="A",
        pitch_correction_scale="minor",
        language=VocalLanguage.ENGLISH,
        rvc_model="male_singer_v1",
    ),
    # ─── CHORUS 2A ───
    VocalSection(
        section_id="chorus_2a",
        text=(
            "Stand still, let the whole world blur. "
            "Stand still, every sound a color I never heard. "
            "I've been running all my life, "
            "stand still, stand still"
        ),
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.9,
        gap_after_seconds=0.3,
        num_takes=3,
        pitch_correction_intensity=0.8,
        pitch_correction_key="A",
        pitch_correction_scale="minor",
        language=VocalLanguage.ENGLISH,
        rvc_model="male_singer_v1",
    ),
    # ─── CHORUS 2B ───
    VocalSection(
        section_id="chorus_2b",
        text=(
            "Stand still, let the streetlights bend. "
            "Stand still, I don't need to know how this ends. "
            "I've been everywhere but here, "
            "stand still, stand still"
        ),
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.9,
        gap_after_seconds=0.5,
        num_takes=3,
        pitch_correction_intensity=0.8,
        pitch_correction_key="A",
        pitch_correction_scale="minor",
        language=VocalLanguage.ENGLISH,
        rvc_model="male_singer_v1",
    ),
    # ─── BRIDGE ───
    VocalSection(
        section_id="bridge",
        text=(
            "I'm not lost. I'm not late. "
            "I'm just here. "
            "And here is enough"
        ),
        style=VocalStyle.WHISPER,
        singing=True,
        volume=0.7,
        gap_after_seconds=0.0,
        num_takes=3,
        pitch_correction_intensity=0.3,
        pitch_correction_key="A",
        pitch_correction_scale="minor",
        language=VocalLanguage.ENGLISH,
        rvc_model="male_singer_v1",
    ),
    # ─── FINAL CHORUS A ───
    VocalSection(
        section_id="final_chorus_a",
        text=(
            "Stand still, let the whole world blur. "
            "Stand still, every sound a color I never heard. "
            "I stopped running from my life, "
            "stand still, stand still"
        ),
        style=VocalStyle.EPIC,
        singing=True,
        volume=1.0,
        gap_after_seconds=0.3,
        num_takes=3,
        pitch_correction_intensity=0.9,
        pitch_correction_key="A",
        pitch_correction_scale="minor",
        language=VocalLanguage.ENGLISH,
        rvc_model="male_singer_v1",
    ),
    # ─── FINAL CHORUS B ───
    VocalSection(
        section_id="final_chorus_b",
        text=(
            "Stand still, I don't need to move. "
            "Stand still, "
            "stand still and let the world come to you"
        ),
        style=VocalStyle.EPIC,
        singing=True,
        volume=1.0,
        gap_after_seconds=0.5,
        num_takes=3,
        pitch_correction_intensity=0.9,
        pitch_correction_key="A",
        pitch_correction_scale="minor",
        language=VocalLanguage.ENGLISH,
        rvc_model="male_singer_v1",
    ),
    # ─── OUTRO ───
    VocalSection(
        section_id="outro",
        text="Here is enough, here is enough",
        style=VocalStyle.WHISPER,
        singing=True,
        volume=0.5,
        gap_after_seconds=0.0,
        num_takes=3,
        pitch_correction_intensity=0.3,
        pitch_correction_key="A",
        pitch_correction_scale="minor",
        language=VocalLanguage.ENGLISH,
        rvc_model="male_singer_v1",
    ),
]

# Vocal placement: (section_id, start_beat)
VOCAL_PLACEMENT: Final[list[tuple[str, float]]] = [
    ("intro", 0.0),
    ("verse_1a", 32.0),
    ("verse_1b", 64.0),
    ("pre_chorus_1", 96.0),
    ("chorus_1a", 128.0),
    ("chorus_1b", 160.0),
    ("verse_2a", 192.0),
    ("verse_2b", 224.0),
    ("pre_chorus_2", 256.0),
    ("chorus_2a", 288.0),
    ("chorus_2b", 320.0),
    ("bridge", 352.0),
    ("final_chorus_a", 384.0),
    ("final_chorus_b", 416.0),
    ("outro", 452.0),
]

# SFX placement: (synth_func, beat, volume, left_gain, right_gain)
SFX_PLACEMENT: Final[
    list[tuple[str, float, float, float, float]]
] = [
    # White noise risers before drops
    ("riser", 96.0, 0.3, 1.0, 1.0),    # Pre-chorus 1 → drop 1
    ("riser", 256.0, 0.35, 1.0, 1.0),   # Pre-chorus 2 → drop 2
    ("riser", 352.0, 0.25, 1.0, 1.0),   # Bridge → final drop
    # Impact hits on drop entries
    ("impact", 128.0, 0.4, 1.0, 1.0),   # Drop 1 entry
    ("impact", 288.0, 0.45, 1.0, 1.0),  # Drop 2 entry
    ("impact", 384.0, 0.5, 1.0, 1.0),   # Final drop entry
]


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    """Generate Stand Still: instrumental + vocals + SFX → mastered MP3."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ── 1. Render instrumental ──
    print("🎹 Rendering instrumental arrangement...")
    arrangement = build_arrangement()
    inst_left, inst_right = render_arrangement(arrangement)

    # ── 2. Render SFX layer ──
    print("🔊 Synthesizing SFX (risers + impacts)...")
    total_samples = len(inst_left)
    sfx_left: list[float] = [0.0] * total_samples
    sfx_right: list[float] = [0.0] * total_samples

    for sfx_type, beat, volume, l_gain, r_gain in SFX_PLACEMENT:
        start_sample = int(beat * SECONDS_PER_BEAT * SAMPLE_RATE)

        if sfx_type == "riser":
            riser_duration = 32.0 * SECONDS_PER_BEAT
            s_left, s_right = _synth_white_noise_riser(riser_duration, volume)
        elif sfx_type == "impact":
            s_left, s_right = _synth_impact(volume)
        else:
            continue

        for i, (sl, sr) in enumerate(zip(s_left, s_right)):
            idx = start_sample + i
            if idx < total_samples:
                sfx_left[idx] += sl * l_gain
                sfx_right[idx] += sr * r_gain

    overlay_onto(inst_left, inst_right, sfx_left, sfx_right, 0)

    # ── 3. Generate vocals ──
    print("🎤 Generating vocals with Bark AI...")
    engine = BarkVocalEngine()
    engine.preload_models()
    generated_vocals = engine.generate_vocals(VOCALS)
    engine.cleanup()

    # ── 4. Apply ducking ──
    print("🔉 Applying vocal-instrumental ducking (-6dB)...")
    vocal_durations = calculate_vocal_durations(generated_vocals)
    vocal_placement_seconds: list[tuple[str, float]] = [
        (sid, beat * SECONDS_PER_BEAT) for sid, beat in VOCAL_PLACEMENT
    ]
    ducked_left, ducked_right = apply_ducking(
        inst_left,
        inst_right,
        vocal_placement_seconds,
        vocal_durations,
        reduction_db=-6.0,
        attack_seconds=0.08,
        release_seconds=0.3,
    )

    # ── 5. Overlay vocals onto ducked instrumental ──
    print("🎚️  Mixing vocals onto instrumental...")
    vocal_map = {v.section_id: v.samples for v in generated_vocals}

    # Vocal gain boost — compensates for Bark's quiet output
    VOCAL_GAIN: float = 1.4

    for section_id, beat in VOCAL_PLACEMENT:
        samples = vocal_map.get(section_id)
        if samples is None:
            continue
        start_sample = int(beat * SECONDS_PER_BEAT * SAMPLE_RATE)
        vocal_mono = [s * VOCAL_GAIN for s in samples]
        overlay_onto(
            ducked_left,
            ducked_right,
            vocal_mono,
            vocal_mono,
            start_sample,
        )

    # ── 6. Normalize and export ──
    print("📊 Normalizing stereo mix...")
    final_left, final_right = normalize_stereo(ducked_left, ducked_right)

    print(f"💾 Writing WAV: {WAV_PATH}")
    write_stereo_wav(WAV_PATH, final_left, final_right)

    print(f"🎵 Mastering to MP3: {MP3_PATH}")
    master_to_mp3(WAV_PATH, MP3_PATH, target_lufs=-14.0, stereo_width=1.2)

    duration_seconds = TOTAL_BEATS * SECONDS_PER_BEAT
    minutes = int(duration_seconds // 60)
    seconds = int(duration_seconds % 60)
    print(f"✅ Done! {MP3_PATH} ({minutes}:{seconds:02d})")


if __name__ == "__main__":
    main()

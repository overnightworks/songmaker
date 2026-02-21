"""Track 01: Let Me Fall — Melodic House (CYRIL x Avicii Style).

Album: Midnight Frequency
Genre: Melodic House
BPM: 120
Key: D minor
Duration: 480 beats (4:00)

Emotional arc: Suffocation → grip slipping → freefall → euphoria → transcendence
Hook: "Let me fall, I don't need the ground / Let me fall into the sound"
"""

from __future__ import annotations

import math
import os
import random
import sys
from typing import Final

sys.path.insert(0, "source_files")

from bark_engine import (
    BarkVocalEngine,
    VocalSection,
    VocalStyle,
    calculate_vocal_durations,
)
from instrumental_engine import (
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

SAMPLE_RATE: Final[int] = 44100
BPM: Final[int] = 120
SECONDS_PER_BEAT: Final[float] = 60.0 / BPM
TOTAL_BEATS: Final[float] = 480.0

OUTPUT_DIR: Final[str] = "albums/midnight_frequency/output"
WAV_PATH: Final[str] = os.path.join(OUTPUT_DIR, "01_Let_Me_Fall.wav")
MP3_PATH: Final[str] = os.path.join(OUTPUT_DIR, "01_Let_Me_Fall.mp3")

# ═══════════════════════════════════════════════════════════════════════════
# MIDI note constants (D minor: D E F G A Bb C)
# ═══════════════════════════════════════════════════════════════════════════

# Bass octave (sub_bass)
D2: Final[int] = 38
F2: Final[int] = 41
G2: Final[int] = 43
A2: Final[int] = 45
BB2: Final[int] = 46
C3: Final[int] = 48

# Pad / supersaw octave
D3: Final[int] = 50
F3: Final[int] = 53
G3: Final[int] = 55
A3: Final[int] = 57
BB3: Final[int] = 58
C4: Final[int] = 60
CS4: Final[int] = 61
D4: Final[int] = 62
E4: Final[int] = 64
F4: Final[int] = 65
G4: Final[int] = 67
A4: Final[int] = 69
BB4: Final[int] = 70

# Arpeggio octave (pluck)
D5: Final[int] = 74
F5: Final[int] = 77
A5: Final[int] = 81


# ═══════════════════════════════════════════════════════════════════════════
# White noise riser synthesis
# ═══════════════════════════════════════════════════════════════════════════

def _synth_white_noise_riser(
    duration_seconds: float,
    volume: float = 0.3,
) -> tuple[list[float], list[float]]:
    """Synthesize a white noise riser with rising filter sweep.

    Args:
        duration_seconds: Length of riser in seconds.
        volume: Peak volume (0.0-1.0).

    Returns:
        Stereo tuple (left, right) of float samples.
    """
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
    """Synthesize a downlifter impact hit for drop entries.

    Args:
        volume: Peak volume.

    Returns:
        Stereo tuple (left, right) of float samples.
    """
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
            # Kick: every beat
            DrumHit(sound=DrumSound.KICK, beat_offset=0.0, velocity=0.85),
            DrumHit(sound=DrumSound.KICK, beat_offset=1.0, velocity=0.85),
            DrumHit(sound=DrumSound.KICK, beat_offset=2.0, velocity=0.85),
            DrumHit(sound=DrumSound.KICK, beat_offset=3.0, velocity=0.85),
            # Clap on 2 and 4
            DrumHit(sound=DrumSound.CLAP, beat_offset=1.0, velocity=0.6),
            DrumHit(sound=DrumSound.CLAP, beat_offset=3.0, velocity=0.6),
            # Closed hats: offbeat 8ths
            DrumHit(sound=DrumSound.HIHAT_CLOSED, beat_offset=0.5, velocity=0.3),
            DrumHit(sound=DrumSound.HIHAT_CLOSED, beat_offset=1.5, velocity=0.3),
            DrumHit(sound=DrumSound.HIHAT_CLOSED, beat_offset=2.5, velocity=0.3),
            DrumHit(sound=DrumSound.HIHAT_CLOSED, beat_offset=3.5, velocity=0.3),
        ),
    )


def _build_verse_beat() -> DrumPattern:
    """Lighter version — kick + closed hats only, softer."""
    return DrumPattern(
        name="verse_light",
        length_beats=4.0,
        hits=(
            DrumHit(sound=DrumSound.KICK, beat_offset=0.0, velocity=0.7),
            DrumHit(sound=DrumSound.KICK, beat_offset=1.0, velocity=0.7),
            DrumHit(sound=DrumSound.KICK, beat_offset=2.0, velocity=0.7),
            DrumHit(sound=DrumSound.KICK, beat_offset=3.0, velocity=0.7),
            DrumHit(sound=DrumSound.HIHAT_CLOSED, beat_offset=0.5, velocity=0.2),
            DrumHit(sound=DrumSound.HIHAT_CLOSED, beat_offset=1.5, velocity=0.2),
            DrumHit(sound=DrumSound.HIHAT_CLOSED, beat_offset=2.5, velocity=0.2),
            DrumHit(sound=DrumSound.HIHAT_CLOSED, beat_offset=3.5, velocity=0.2),
        ),
    )


def _build_build_beat() -> DrumPattern:
    """Snare roll building pattern for pre-chorus."""
    return DrumPattern(
        name="build_roll",
        length_beats=4.0,
        hits=(
            DrumHit(sound=DrumSound.KICK, beat_offset=0.0, velocity=0.8),
            DrumHit(sound=DrumSound.KICK, beat_offset=1.0, velocity=0.8),
            DrumHit(sound=DrumSound.KICK, beat_offset=2.0, velocity=0.8),
            DrumHit(sound=DrumSound.KICK, beat_offset=3.0, velocity=0.8),
            # Snare roll: 16th notes, increasing velocity
            DrumHit(sound=DrumSound.SNARE, beat_offset=0.0, velocity=0.25),
            DrumHit(sound=DrumSound.SNARE, beat_offset=0.25, velocity=0.28),
            DrumHit(sound=DrumSound.SNARE, beat_offset=0.5, velocity=0.3),
            DrumHit(sound=DrumSound.SNARE, beat_offset=0.75, velocity=0.33),
            DrumHit(sound=DrumSound.SNARE, beat_offset=1.0, velocity=0.35),
            DrumHit(sound=DrumSound.SNARE, beat_offset=1.25, velocity=0.38),
            DrumHit(sound=DrumSound.SNARE, beat_offset=1.5, velocity=0.4),
            DrumHit(sound=DrumSound.SNARE, beat_offset=1.75, velocity=0.43),
            DrumHit(sound=DrumSound.SNARE, beat_offset=2.0, velocity=0.45),
            DrumHit(sound=DrumSound.SNARE, beat_offset=2.25, velocity=0.5),
            DrumHit(sound=DrumSound.SNARE, beat_offset=2.5, velocity=0.55),
            DrumHit(sound=DrumSound.SNARE, beat_offset=2.75, velocity=0.58),
            DrumHit(sound=DrumSound.SNARE, beat_offset=3.0, velocity=0.6),
            DrumHit(sound=DrumSound.SNARE, beat_offset=3.25, velocity=0.65),
            DrumHit(sound=DrumSound.SNARE, beat_offset=3.5, velocity=0.7),
            DrumHit(sound=DrumSound.SNARE, beat_offset=3.75, velocity=0.75),
        ),
    )


def _build_drop_beat() -> DrumPattern:
    """Full four-on-the-floor with open hats and crash on 1."""
    return DrumPattern(
        name="drop_full",
        length_beats=4.0,
        hits=(
            DrumHit(sound=DrumSound.KICK, beat_offset=0.0, velocity=0.95),
            DrumHit(sound=DrumSound.KICK, beat_offset=1.0, velocity=0.9),
            DrumHit(sound=DrumSound.KICK, beat_offset=2.0, velocity=0.9),
            DrumHit(sound=DrumSound.KICK, beat_offset=3.0, velocity=0.9),
            # Clap on 2 and 4
            DrumHit(sound=DrumSound.CLAP, beat_offset=1.0, velocity=0.7),
            DrumHit(sound=DrumSound.CLAP, beat_offset=3.0, velocity=0.7),
            # Open hats: offbeat
            DrumHit(sound=DrumSound.HIHAT_OPEN, beat_offset=0.5, velocity=0.35),
            DrumHit(sound=DrumSound.HIHAT_OPEN, beat_offset=1.5, velocity=0.35),
            DrumHit(sound=DrumSound.HIHAT_OPEN, beat_offset=2.5, velocity=0.35),
            DrumHit(sound=DrumSound.HIHAT_OPEN, beat_offset=3.5, velocity=0.35),
            # Crash on beat 1
            DrumHit(sound=DrumSound.CRASH, beat_offset=0.0, velocity=0.5),
        ),
    )


def _build_outro_beat() -> DrumPattern:
    """Minimal fading pattern for outro."""
    return DrumPattern(
        name="outro_minimal",
        length_beats=4.0,
        hits=(
            DrumHit(sound=DrumSound.KICK, beat_offset=0.0, velocity=0.5),
            DrumHit(sound=DrumSound.KICK, beat_offset=2.0, velocity=0.4),
            DrumHit(sound=DrumSound.HIHAT_CLOSED, beat_offset=1.0, velocity=0.15),
            DrumHit(sound=DrumSound.HIHAT_CLOSED, beat_offset=3.0, velocity=0.1),
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Chord / melody patterns
# ═══════════════════════════════════════════════════════════════════════════

# --- Verse progression: Dm → Bb → F → C (4 bars each, 16 beats each) ---

def _verse_pad_chords() -> tuple[Chord, ...]:
    """Warm pad chords for verses: Dm → Bb → F → C, 16 beats each."""
    return (
        Chord(notes=(D3, F3, A3), velocity=0.4, duration_beats=16.0),
        Chord(notes=(BB3, D4, F4), velocity=0.4, duration_beats=16.0),
        Chord(notes=(F3, A3, C4), velocity=0.4, duration_beats=16.0),
        Chord(notes=(C4, E4, G4), velocity=0.4, duration_beats=16.0),
    )


def _chorus_pad_chords() -> tuple[Chord, ...]:
    """Supporting pad under drops: Dm → Bb → C → Gm, 16 beats each."""
    return (
        Chord(notes=(D3, F3, A3), velocity=0.35, duration_beats=16.0),
        Chord(notes=(BB3, D4, F4), velocity=0.35, duration_beats=16.0),
        Chord(notes=(C4, E4, G4), velocity=0.35, duration_beats=16.0),
        Chord(notes=(G3, BB3, D4), velocity=0.35, duration_beats=16.0),
    )


def _chorus_supersaw_chords() -> tuple[Chord, ...]:
    """Full supersaw chords for drops: Dm → Bb → C → Gm, 16 beats each."""
    return (
        Chord(notes=(D4, F4, A4), velocity=0.8, duration_beats=16.0),
        Chord(notes=(BB3, D4, F4), velocity=0.8, duration_beats=16.0),
        Chord(notes=(C4, E4, G4), velocity=0.8, duration_beats=16.0),
        Chord(notes=(G3, BB3, D4), velocity=0.8, duration_beats=16.0),
    )


def _final_supersaw_chords() -> tuple[Chord, ...]:
    """Stacked supersaw chords for final drop — octave doubled."""
    return (
        Chord(notes=(D3, D4, F4, A4), velocity=0.9, duration_beats=16.0),
        Chord(notes=(BB2, BB3, D4, F4), velocity=0.9, duration_beats=16.0),
        Chord(notes=(C3, C4, E4, G4), velocity=0.9, duration_beats=16.0),
        Chord(notes=(G2, G3, BB3, D4), velocity=0.9, duration_beats=16.0),
    )


def _bridge_pad_chords() -> tuple[Chord, ...]:
    """Bridge tension chords: Dm → A → Bb → Gm, 8 beats each."""
    return (
        Chord(notes=(D3, F3, A3), velocity=0.3, duration_beats=8.0),
        Chord(notes=(A3, CS4, E4), velocity=0.3, duration_beats=8.0),
        Chord(notes=(BB3, D4, F4), velocity=0.35, duration_beats=8.0),
        Chord(notes=(G3, BB3, D4), velocity=0.35, duration_beats=8.0),
    )


def _intro_pad_chord() -> tuple[Chord, ...]:
    """Single sustained Dm chord for intro atmosphere."""
    return (
        Chord(notes=(D3, F3, A3), velocity=0.25, duration_beats=32.0),
    )


def _outro_pad_chord() -> tuple[Chord, ...]:
    """Fading Dm chord for outro."""
    return (
        Chord(notes=(D3, F3, A3), velocity=0.2, duration_beats=32.0),
    )


# --- Bass patterns ---

def _verse_bass() -> tuple[Note | Rest, ...]:
    """Sub bass for verses: root notes, 16 beats each."""
    return (
        Note(midi=D2, velocity=0.6, duration_beats=14.0),
        Rest(duration_beats=2.0),
        Note(midi=BB2, velocity=0.6, duration_beats=14.0),
        Rest(duration_beats=2.0),
        Note(midi=F2, velocity=0.6, duration_beats=14.0),
        Rest(duration_beats=2.0),
        Note(midi=C3, velocity=0.6, duration_beats=14.0),
        Rest(duration_beats=2.0),
    )


def _chorus_bass() -> tuple[Note | Rest, ...]:
    """Pumping sub bass for drops: root notes, 4-beat pulses."""
    elements: list[Note | Rest] = []
    roots = (D2, BB2, C3, G2)
    for root in roots:
        for _ in range(4):
            elements.append(Note(midi=root, velocity=0.75, duration_beats=3.5))
            elements.append(Rest(duration_beats=0.5))
    return tuple(elements)


def _final_bass() -> tuple[Note | Rest, ...]:
    """Maximum bass for final drop — octave doubled pulse."""
    elements: list[Note | Rest] = []
    roots = (D2, BB2, C3, G2)
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
        (D5, F5, A5, F5),   # Dm
        (BB4, D5, F5, D5),  # Bb
        (F5, A5, F5, A5),   # F (using available notes)
        (C4, E4, G4, E4),   # C
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
        (D5, F5, A5, F5),   # Dm
        (BB4, D5, F5, D5),  # Bb
        (C4, E4, G4, E4),   # C
        (G4, BB4, D5, BB4), # Gm
    )
    for chord in chord_tones:
        for _ in range(4):
            for tone in chord:
                notes.append(Note(midi=tone, velocity=0.4, duration_beats=0.25))
    return tuple(notes)


def _intro_pluck() -> tuple[Note | Rest, ...]:
    """Sparse intro pluck — single notes with space."""
    return (
        Note(midi=D5, velocity=0.25, duration_beats=2.0),
        Rest(duration_beats=2.0),
        Note(midi=A4, velocity=0.2, duration_beats=2.0),
        Rest(duration_beats=2.0),
        Note(midi=F5, velocity=0.25, duration_beats=2.0),
        Rest(duration_beats=2.0),
        Note(midi=D5, velocity=0.2, duration_beats=2.0),
        Rest(duration_beats=2.0),
        Note(midi=A4, velocity=0.25, duration_beats=2.0),
        Rest(duration_beats=2.0),
        Note(midi=F4, velocity=0.2, duration_beats=2.0),
        Rest(duration_beats=2.0),
        Note(midi=D5, velocity=0.25, duration_beats=2.0),
        Rest(duration_beats=2.0),
        Note(midi=A5, velocity=0.2, duration_beats=2.0),
        Rest(duration_beats=2.0),
    )


def _bridge_pluck() -> tuple[Note | Rest, ...]:
    """Sparse reverbed pluck for bridge breakdown."""
    return (
        Note(midi=D5, velocity=0.3, duration_beats=4.0),
        Rest(duration_beats=4.0),
        Note(midi=CS4, velocity=0.25, duration_beats=4.0),
        Rest(duration_beats=4.0),
        Note(midi=BB4, velocity=0.3, duration_beats=4.0),
        Rest(duration_beats=4.0),
        Note(midi=A4, velocity=0.25, duration_beats=4.0),
        Rest(duration_beats=4.0),
    )


def _outro_pluck() -> tuple[Note | Rest, ...]:
    """Final pluck notes fading out."""
    return (
        Note(midi=D5, velocity=0.2, duration_beats=4.0),
        Rest(duration_beats=4.0),
        Note(midi=A4, velocity=0.15, duration_beats=4.0),
        Rest(duration_beats=4.0),
        Note(midi=F4, velocity=0.1, duration_beats=4.0),
        Rest(duration_beats=4.0),
        Note(midi=D5, velocity=0.08, duration_beats=8.0),
    )


# --- Pre-chorus build chords ---

def _build_pad_chords() -> tuple[Chord, ...]:
    """Rising pad for pre-chorus build."""
    return (
        Chord(notes=(D3, F3, A3), velocity=0.5, duration_beats=8.0),
        Chord(notes=(BB3, D4, F4), velocity=0.55, duration_beats=8.0),
        Chord(notes=(C4, E4, G4), velocity=0.6, duration_beats=8.0),
        Chord(notes=(D4, F4, A4), velocity=0.65, duration_beats=8.0),
    )


def _build_bass() -> tuple[Note, ...]:
    """Sustained bass during build."""
    return (
        Note(midi=D2, velocity=0.5, duration_beats=16.0),
        Note(midi=D2, velocity=0.6, duration_beats=16.0),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Arrangement
# ═══════════════════════════════════════════════════════════════════════════

VERSE_BEAT: Final[DrumPattern] = _build_verse_beat()
BUILD_BEAT: Final[DrumPattern] = _build_build_beat()
DROP_BEAT: Final[DrumPattern] = _build_drop_beat()
OUTRO_BEAT: Final[DrumPattern] = _build_outro_beat()


def build_arrangement() -> Arrangement:
    """Build the complete arrangement for Let Me Fall."""
    return Arrangement(
        title="Let Me Fall",
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
                        instrument_id="dark_pad",
                        events=_intro_pad_chord(),
                        volume=0.3,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        instrument_id="pluck",
                        events=_intro_pluck(),
                        volume=0.25,
                        pan=PanPosition.SLIGHT_RIGHT,
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
                        instrument_id="dark_pad",
                        events=_verse_pad_chords(),
                        volume=0.35,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        instrument_id="pluck",
                        events=_verse_arpeggios(),
                        volume=0.3,
                        pan=PanPosition.SLIGHT_LEFT,
                    ),
                    InstrumentTrack(
                        instrument_id="sub_bass",
                        events=_verse_bass(),
                        volume=0.5,
                        pan=PanPosition.CENTER,
                    ),
                ),
                drum_pattern=VERSE_BEAT,
                drum_volume=0.5,
            ),
            # ─── PRE-CHORUS 1 / BUILD: 96-128 beats ───
            SongSection(
                section_type=SectionType.BRIDGE,
                start_beat=96.0,
                length_beats=32.0,
                bpm=BPM,
                tracks=(
                    InstrumentTrack(
                        instrument_id="dark_pad",
                        events=_build_pad_chords(),
                        volume=0.45,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        instrument_id="pluck",
                        events=_verse_arpeggios(),
                        volume=0.35,
                        pan=PanPosition.SLIGHT_RIGHT,
                    ),
                    InstrumentTrack(
                        instrument_id="sub_bass",
                        events=_build_bass(),
                        volume=0.55,
                        pan=PanPosition.CENTER,
                    ),
                ),
                drum_pattern=BUILD_BEAT,
                drum_volume=0.6,
            ),
            # ─── DROP / CHORUS 1: 128-192 beats ───
            SongSection(
                section_type=SectionType.CHORUS,
                start_beat=128.0,
                length_beats=64.0,
                bpm=BPM,
                tracks=(
                    InstrumentTrack(
                        instrument_id="supersaw",
                        events=_chorus_supersaw_chords(),
                        volume=0.65,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        instrument_id="dark_pad",
                        events=_chorus_pad_chords(),
                        volume=0.25,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        instrument_id="pluck",
                        events=_chorus_arpeggios(),
                        volume=0.25,
                        pan=PanPosition.SLIGHT_LEFT,
                    ),
                    InstrumentTrack(
                        instrument_id="sub_bass",
                        events=_chorus_bass(),
                        volume=0.65,
                        pan=PanPosition.CENTER,
                    ),
                ),
                drum_pattern=DROP_BEAT,
                drum_volume=0.7,
            ),
            # ─── VERSE 2: 192-256 beats ───
            SongSection(
                section_type=SectionType.VERSE,
                start_beat=192.0,
                length_beats=64.0,
                bpm=BPM,
                tracks=(
                    InstrumentTrack(
                        instrument_id="dark_pad",
                        events=_verse_pad_chords(),
                        volume=0.3,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        instrument_id="pluck",
                        events=_verse_arpeggios(),
                        volume=0.28,
                        pan=PanPosition.SLIGHT_RIGHT,
                    ),
                    InstrumentTrack(
                        instrument_id="sub_bass",
                        events=_verse_bass(),
                        volume=0.45,
                        pan=PanPosition.CENTER,
                    ),
                ),
                drum_pattern=VERSE_BEAT,
                drum_volume=0.4,
            ),
            # ─── PRE-CHORUS 2 / BUILD: 256-288 beats ───
            SongSection(
                section_type=SectionType.BRIDGE,
                start_beat=256.0,
                length_beats=32.0,
                bpm=BPM,
                tracks=(
                    InstrumentTrack(
                        instrument_id="dark_pad",
                        events=_build_pad_chords(),
                        volume=0.5,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        instrument_id="pluck",
                        events=_verse_arpeggios(),
                        volume=0.35,
                        pan=PanPosition.SLIGHT_LEFT,
                    ),
                    InstrumentTrack(
                        instrument_id="sub_bass",
                        events=_build_bass(),
                        volume=0.6,
                        pan=PanPosition.CENTER,
                    ),
                ),
                drum_pattern=BUILD_BEAT,
                drum_volume=0.7,
            ),
            # ─── DROP / CHORUS 2: 288-352 beats ───
            SongSection(
                section_type=SectionType.CHORUS,
                start_beat=288.0,
                length_beats=64.0,
                bpm=BPM,
                tracks=(
                    InstrumentTrack(
                        instrument_id="supersaw",
                        events=_chorus_supersaw_chords(),
                        volume=0.7,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        instrument_id="dark_pad",
                        events=_chorus_pad_chords(),
                        volume=0.3,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        instrument_id="pluck",
                        events=_chorus_arpeggios(),
                        volume=0.28,
                        pan=PanPosition.SLIGHT_RIGHT,
                    ),
                    InstrumentTrack(
                        instrument_id="sub_bass",
                        events=_chorus_bass(),
                        volume=0.7,
                        pan=PanPosition.CENTER,
                    ),
                ),
                drum_pattern=DROP_BEAT,
                drum_volume=0.75,
            ),
            # ─── BRIDGE / BREAKDOWN: 352-384 beats ───
            SongSection(
                section_type=SectionType.BRIDGE,
                start_beat=352.0,
                length_beats=32.0,
                bpm=BPM,
                tracks=(
                    InstrumentTrack(
                        instrument_id="dark_pad",
                        events=_bridge_pad_chords(),
                        volume=0.2,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        instrument_id="pluck",
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
                        instrument_id="supersaw",
                        events=_final_supersaw_chords(),
                        volume=0.8,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        instrument_id="dark_pad",
                        events=_chorus_pad_chords(),
                        volume=0.3,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        instrument_id="pluck",
                        events=_chorus_arpeggios(),
                        volume=0.3,
                        pan=PanPosition.SLIGHT_LEFT,
                    ),
                    InstrumentTrack(
                        instrument_id="sub_bass",
                        events=_final_bass(),
                        volume=0.75,
                        pan=PanPosition.CENTER,
                    ),
                ),
                drum_pattern=DROP_BEAT,
                drum_volume=0.8,
            ),
            # ─── OUTRO: 448-480 beats ───
            SongSection(
                section_type=SectionType.OUTRO,
                start_beat=448.0,
                length_beats=32.0,
                bpm=BPM,
                tracks=(
                    InstrumentTrack(
                        instrument_id="dark_pad",
                        events=_outro_pad_chord(),
                        volume=0.2,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        instrument_id="pluck",
                        events=_outro_pluck(),
                        volume=0.2,
                        pan=PanPosition.SLIGHT_RIGHT,
                    ),
                ),
                drum_pattern=OUTRO_BEAT,
                drum_volume=0.25,
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
        text="I built these walls, with steady hands",
        style=VocalStyle.WHISPER,
        singing=True,
        volume=0.6,
        gap_after_seconds=0.0,
        num_takes=3,
        pitch_correction_intensity=0.5,
        pitch_correction_key="D",
        pitch_correction_scale="minor",
    ),
    # ─── VERSE 1A ───
    VocalSection(
        section_id="verse_1a",
        text=(
            "I built these walls with steady hands, "
            "but steady hands still shake at night. "
            "I held my breath for twenty years, "
            "forgot what air tastes like"
        ),
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.8,
        gap_after_seconds=0.5,
        num_takes=3,
        pitch_correction_intensity=0.7,
        pitch_correction_key="D",
        pitch_correction_scale="minor",
    ),
    # ─── VERSE 1B ───
    VocalSection(
        section_id="verse_1b",
        text=(
            "I drew the map, I marked the lines, "
            "colored inside every one. "
            "The picture looked like someone's life, "
            "but I don't know whose"
        ),
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.8,
        gap_after_seconds=0.3,
        num_takes=3,
        pitch_correction_intensity=0.7,
        pitch_correction_key="D",
        pitch_correction_scale="minor",
    ),
    # ─── PRE-CHORUS 1 ───
    VocalSection(
        section_id="pre_chorus_1",
        text=(
            "My fingers slip, the edge is gone, "
            "and I'm not scared anymore"
        ),
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.85,
        gap_after_seconds=0.0,
        num_takes=3,
        pitch_correction_intensity=0.7,
        pitch_correction_key="D",
        pitch_correction_scale="minor",
    ),
    # ─── CHORUS 1A ───
    VocalSection(
        section_id="chorus_1a",
        text=(
            "Let me fall, I don't need the ground. "
            "Let me fall into the sound. "
            "I've been holding on so long, "
            "let me fall where I belong"
        ),
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.9,
        gap_after_seconds=0.3,
        num_takes=3,
        pitch_correction_intensity=0.8,
        pitch_correction_key="D",
        pitch_correction_scale="minor",
    ),
    # ─── CHORUS 1B ───
    VocalSection(
        section_id="chorus_1b",
        text=(
            "Let me fall, through the noise and the light. "
            "Let me fall through the night. "
            "I don't need to understand, "
            "let me fall from my own hands"
        ),
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.9,
        gap_after_seconds=0.5,
        num_takes=3,
        pitch_correction_intensity=0.8,
        pitch_correction_key="D",
        pitch_correction_scale="minor",
    ),
    # ─── VERSE 2A ───
    VocalSection(
        section_id="verse_2a",
        text=(
            "I see the city from up here, "
            "the lights look just like breathing. "
            "My old life fits inside a window, "
            "too small to climb back through"
        ),
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.75,
        gap_after_seconds=0.5,
        num_takes=3,
        pitch_correction_intensity=0.7,
        pitch_correction_key="D",
        pitch_correction_scale="minor",
    ),
    # ─── VERSE 2B ───
    VocalSection(
        section_id="verse_2b",
        text=(
            "I kept a list of all the things "
            "that I was supposed to be. "
            "I folded it into a bird, "
            "and watched it leave without me"
        ),
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.8,
        gap_after_seconds=0.3,
        num_takes=3,
        pitch_correction_intensity=0.7,
        pitch_correction_key="D",
        pitch_correction_scale="minor",
    ),
    # ─── PRE-CHORUS 2 ───
    VocalSection(
        section_id="pre_chorus_2",
        text=(
            "The air is thin, the sky is wide, "
            "and I was never meant to land"
        ),
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.9,
        gap_after_seconds=0.0,
        num_takes=3,
        pitch_correction_intensity=0.7,
        pitch_correction_key="D",
        pitch_correction_scale="minor",
    ),
    # ─── CHORUS 2A ───
    VocalSection(
        section_id="chorus_2a",
        text=(
            "Let me fall, I don't need the ground. "
            "Let me fall into the sound. "
            "I've been holding on so long, "
            "let me fall where I belong"
        ),
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.9,
        gap_after_seconds=0.3,
        num_takes=3,
        pitch_correction_intensity=0.8,
        pitch_correction_key="D",
        pitch_correction_scale="minor",
    ),
    # ─── CHORUS 2B ───
    VocalSection(
        section_id="chorus_2b",
        text=(
            "Let me fall, through the noise and the light. "
            "Let me fall through the night. "
            "I don't need to understand, "
            "let me fall from my own hands"
        ),
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.9,
        gap_after_seconds=0.5,
        num_takes=3,
        pitch_correction_intensity=0.8,
        pitch_correction_key="D",
        pitch_correction_scale="minor",
    ),
    # ─── BRIDGE ───
    VocalSection(
        section_id="bridge",
        text=(
            "There is no bottom. There is no end. "
            "Just the fall. "
            "And falling feels like flying"
        ),
        style=VocalStyle.WHISPER,
        singing=True,
        volume=0.7,
        gap_after_seconds=0.0,
        num_takes=3,
        pitch_correction_intensity=0.3,
        pitch_correction_key="D",
        pitch_correction_scale="minor",
    ),
    # ─── FINAL CHORUS A ───
    VocalSection(
        section_id="final_chorus_a",
        text=(
            "Let me fall, I don't need the ground. "
            "Let me fall into the sound. "
            "I've been standing still so long, "
            "let me fall where I belong"
        ),
        style=VocalStyle.EPIC,
        singing=True,
        volume=1.0,
        gap_after_seconds=0.3,
        num_takes=3,
        pitch_correction_intensity=0.9,
        pitch_correction_key="D",
        pitch_correction_scale="minor",
    ),
    # ─── FINAL CHORUS B ───
    VocalSection(
        section_id="final_chorus_b",
        text=(
            "Let me fall, I don't need to understand. "
            "Let me fall, "
            "let me fall from my own hands"
        ),
        style=VocalStyle.EPIC,
        singing=True,
        volume=1.0,
        gap_after_seconds=0.5,
        num_takes=3,
        pitch_correction_intensity=0.9,
        pitch_correction_key="D",
        pitch_correction_scale="minor",
    ),
    # ─── OUTRO ───
    VocalSection(
        section_id="outro",
        text="Falling feels like flying, falling feels like flying",
        style=VocalStyle.WHISPER,
        singing=True,
        volume=0.5,
        gap_after_seconds=0.0,
        num_takes=3,
        pitch_correction_intensity=0.3,
        pitch_correction_key="D",
        pitch_correction_scale="minor",
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
    """Generate Let Me Fall: instrumental + vocals + SFX → mastered MP3."""
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
    print("🔉 Applying vocal-instrumental ducking (-3dB)...")
    vocal_durations = calculate_vocal_durations(generated_vocals)
    vocal_placement_seconds: list[tuple[str, float]] = [
        (sid, beat * SECONDS_PER_BEAT) for sid, beat in VOCAL_PLACEMENT
    ]
    ducked_left, ducked_right = apply_ducking(
        inst_left,
        inst_right,
        vocal_placement_seconds,
        vocal_durations,
        reduction_db=-3.0,
        attack_seconds=0.05,
        release_seconds=0.2,
    )

    # ── 5. Overlay vocals onto ducked instrumental ──
    print("🎚️  Mixing vocals onto instrumental...")
    vocal_map = {v.section_id: v.samples for v in generated_vocals}

    for section_id, beat in VOCAL_PLACEMENT:
        samples = vocal_map.get(section_id)
        if samples is None:
            continue
        start_sample = int(beat * SECONDS_PER_BEAT * SAMPLE_RATE)
        vocal_mono = list(samples)
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

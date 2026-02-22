"""Track 01: Let Me Fall — Melodic House (CYRIL x Avicii Style).

Album: Midnight Frequency
Genre: Melodic House
BPM: 120
Key: D minor
Duration: 480 beats (4:00)

Vocals: DiffSinger (TIGER v106) + RVC (whitney92)
Emotional arc: Suffocation → grip slipping → freefall → euphoria → transcendence
Hook: "Let me fall, I don't need the ground / Let me fall into the sound"
"""

from __future__ import annotations

import math
import os
import random
from pathlib import Path
from typing import Final

import numpy as np

from diffsinger_engine import DiffSingerEngine, VocalNote, VocalPhrase
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
            DrumHit(sound=DrumSound.KICK, beat_position=0.0, velocity=0.85),
            DrumHit(sound=DrumSound.KICK, beat_position=1.0, velocity=0.85),
            DrumHit(sound=DrumSound.KICK, beat_position=2.0, velocity=0.85),
            DrumHit(sound=DrumSound.KICK, beat_position=3.0, velocity=0.85),
            # Clap on 2 and 4
            DrumHit(sound=DrumSound.CLAP, beat_position=1.0, velocity=0.6),
            DrumHit(sound=DrumSound.CLAP, beat_position=3.0, velocity=0.6),
            # Closed hats: offbeat 8ths
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
            # Snare roll: 16th notes, increasing velocity
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
            # Clap on 2 and 4
            DrumHit(sound=DrumSound.CLAP, beat_position=1.0, velocity=0.7),
            DrumHit(sound=DrumSound.CLAP, beat_position=3.0, velocity=0.7),
            # Open hats: offbeat
            DrumHit(sound=DrumSound.OPEN_HIHAT, beat_position=0.5, velocity=0.35),
            DrumHit(sound=DrumSound.OPEN_HIHAT, beat_position=1.5, velocity=0.35),
            DrumHit(sound=DrumSound.OPEN_HIHAT, beat_position=2.5, velocity=0.35),
            DrumHit(sound=DrumSound.OPEN_HIHAT, beat_position=3.5, velocity=0.35),
            # Crash on beat 1
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
        Chord(notes=(D4, F4, A4), velocity=0.65, duration_beats=16.0),
        Chord(notes=(BB3, D4, F4), velocity=0.65, duration_beats=16.0),
        Chord(notes=(C4, E4, G4), velocity=0.65, duration_beats=16.0),
        Chord(notes=(G3, BB3, D4), velocity=0.65, duration_beats=16.0),
    )


def _final_supersaw_chords() -> tuple[Chord, ...]:
    """Stacked supersaw chords for final drop — octave doubled."""
    return (
        Chord(notes=(D3, D4, F4, A4), velocity=0.75, duration_beats=16.0),
        Chord(notes=(BB2, BB3, D4, F4), velocity=0.75, duration_beats=16.0),
        Chord(notes=(C3, C4, E4, G4), velocity=0.75, duration_beats=16.0),
        Chord(notes=(G2, G3, BB3, D4), velocity=0.75, duration_beats=16.0),
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
                        name="pad", instrument_id="dark_pad",
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
                        name="pad", instrument_id="dark_pad",
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
                        name="pad", instrument_id="dark_pad",
                        events=_build_pad_chords(),
                        volume=0.45,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        name="pluck", instrument_id="pluck",
                        events=_verse_arpeggios(),
                        volume=0.35,
                        pan=PanPosition.CENTER_RIGHT,
                    ),
                    InstrumentTrack(
                        name="bass", instrument_id="sub_bass",
                        events=_build_bass(),
                        volume=0.55,
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
                        name="pad", instrument_id="dark_pad",
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
                        name="pad", instrument_id="dark_pad",
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
                        name="pad", instrument_id="dark_pad",
                        events=_build_pad_chords(),
                        volume=0.40,
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
                        name="pad", instrument_id="dark_pad",
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
                        name="pad", instrument_id="dark_pad",
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
                        name="pad", instrument_id="dark_pad",
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
                        name="pad", instrument_id="dark_pad",
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

# ═══════════════════════════════════════════════════════════════════════════
# DiffSinger vocal phrases — melodies in D minor
# ═══════════════════════════════════════════════════════════════════════════
# D minor scale: D(62) E(64) F(65) G(67) A(69) Bb(70) C(72) D(74)
# Chord tones:
#   Dm = D F A    Bb = Bb D F    F = F A C    C = C E G
#   Gm = G Bb D   A = A C# E
#
# RVC: whitney92 for all phrases (warm female voice character)
# Voice: tiger_fresh for soft, tiger_electric for power

VOICEBANK_DIR = Path(__file__).resolve().parent.parent.parent.parent / "_diffsinger" / "checkpoints" / "tiger_voice"

RVC_MODEL = "whitney92"
RVC_PITCH_SHIFT = 0
RVC_INDEX_RATE = 0.3  # Low index for pronunciation clarity over timbre


def _n(midi: int, lyric: str, beats: float, vel: float = 1.0) -> VocalNote:
    """Shortcut for creating a VocalNote."""
    return VocalNote(midi=midi, lyric=lyric, duration_beats=beats, velocity=vel)


def _r(beats: float) -> VocalNote:
    """Shortcut for a rest."""
    return VocalNote(midi=0, lyric="", duration_beats=beats, is_rest=True)


# ── INTRO: "I built these walls / with steady hands" ─────────────
# Soft, intimate. Over Dm pad. Floating, almost whispered singing.
# All words >= 0.75 beats for clear articulation at 120 BPM.
intro_phrase = VocalPhrase(
    phrase_id="intro",
    bpm=BPM,
    voice="tiger_fresh",
    gender=-0.2,
    rvc_model=RVC_MODEL, rvc_pitch_shift=RVC_PITCH_SHIFT, rvc_index_rate=RVC_INDEX_RATE,
    notes=(
        _n(62, "I", 1.0),           # D4
        _n(65, "built", 1.5),       # F4
        _n(64, "these", 1.0),       # E4
        _n(62, "walls", 3.0),       # D4 — settle
        _r(2.0),
        _n(65, "with", 1.0),        # F4
        _n(67, "steady", 2.0),      # G4
        _n(65, "hands", 3.5),       # F4 — resolve down
        _r(1.0),
    ),
)

# ── VERSE 1A: "I built these walls..." ────────────────────────────
# Fewer words per phrase. Each word gets time to breathe.
verse_1a_phrase = VocalPhrase(
    phrase_id="verse_1a",
    bpm=BPM,
    voice="tiger_fresh",
    gender=-0.15,
    rvc_model=RVC_MODEL, rvc_pitch_shift=RVC_PITCH_SHIFT, rvc_index_rate=RVC_INDEX_RATE,
    notes=(
        # "I built these walls with steady hands" — over Dm
        _n(62, "I", 0.75),          # D4
        _n(65, "built", 1.25),      # F4
        _n(64, "these", 1.0),       # E4
        _n(62, "walls", 2.0),       # D4
        _n(65, "with", 0.75),       # F4
        _n(67, "steady", 1.5),      # G4
        _n(65, "hands", 2.5),       # F4
        _r(1.0),
        # "but steady hands still shake at night" — over Bb
        _n(65, "but", 0.75),        # F4
        _n(67, "steady", 1.5),      # G4
        _n(69, "hands", 1.25),      # A4
        _n(67, "still", 1.0),       # G4
        _n(70, "shake", 1.5),       # Bb4
        _n(69, "at", 0.75),         # A4
        _n(67, "night", 3.0),       # G4
        _r(1.0),
        # "I held my breath for twenty years" — over F
        _n(65, "I", 0.75),          # F4
        _n(69, "held", 1.5),        # A4
        _n(67, "my", 0.75),         # G4
        _n(65, "breath", 1.5),      # F4
        _n(67, "for", 0.75),        # G4
        _n(69, "twenty", 1.5),      # A4
        _n(72, "years", 2.5),       # C5
        _r(1.0),
        # "forgot what air tastes like" — over C
        _n(72, "forgot", 1.5),      # C5
        _n(69, "what", 0.75),       # A4
        _n(67, "air", 1.5),         # G4
        _n(65, "tastes", 1.25),     # F4
        _n(62, "like", 3.0),        # D4
        _r(1.0),
    ),
)

# ── VERSE 1B: "I drew the map..." ────────────────────────────────
verse_1b_phrase = VocalPhrase(
    phrase_id="verse_1b",
    bpm=BPM,
    voice="tiger_fresh",
    gender=-0.15,
    rvc_model=RVC_MODEL, rvc_pitch_shift=RVC_PITCH_SHIFT, rvc_index_rate=RVC_INDEX_RATE,
    notes=(
        # "I drew the map, I marked the lines" — over Dm
        _n(62, "I", 0.75),          # D4
        _n(65, "drew", 1.25),       # F4
        _n(64, "the", 0.75),        # E4
        _n(67, "map", 2.0),         # G4
        _r(0.75),
        _n(65, "I", 0.75),          # F4
        _n(69, "marked", 1.5),      # A4
        _n(67, "the", 0.75),        # G4
        _n(65, "lines", 2.5),       # F4
        _r(1.0),
        # "colored inside every one" — over Bb
        _n(67, "colored", 1.5),     # G4
        _n(69, "inside", 1.5),      # A4
        _n(70, "every", 1.5),       # Bb4
        _n(67, "one", 3.0),         # G4
        _r(1.0),
        # "the picture looked like someone's life" — over F
        _n(65, "the", 0.75),        # F4
        _n(69, "picture", 1.5),     # A4
        _n(67, "looked", 1.0),      # G4
        _n(65, "like", 0.75),       # F4
        _n(69, "someone's", 1.5),   # A4
        _n(72, "life", 2.5),        # C5
        _r(1.0),
        # "but I don't know whose" — over C
        _n(72, "but", 0.75),        # C5
        _n(69, "I", 0.75),          # A4
        _n(67, "don't", 1.0),       # G4
        _n(65, "know", 1.5),        # F4
        _n(62, "whose", 3.5),       # D4
        _r(1.0),
    ),
)

# ── PRE-CHORUS 1: "My fingers slip..." ────────────────────────────
pre_chorus_1_phrase = VocalPhrase(
    phrase_id="pre_chorus_1",
    bpm=BPM,
    voice="tiger_fresh",
    gender=-0.1,
    rvc_model=RVC_MODEL, rvc_pitch_shift=RVC_PITCH_SHIFT, rvc_index_rate=RVC_INDEX_RATE,
    notes=(
        # "My fingers slip"
        _n(65, "my", 0.75),         # F4
        _n(69, "fingers", 2.0),     # A4
        _n(72, "slip", 2.5),        # C5
        _r(1.5),
        # "the edge is gone"
        _n(70, "the", 0.75),        # Bb4
        _n(72, "edge", 1.5),        # C5
        _n(74, "is", 0.75),         # D5
        _n(72, "gone", 2.5),        # C5
        _r(1.5),
        # "and I'm not scared anymore"
        _n(72, "and", 0.75),        # C5
        _n(74, "I'm", 1.25),        # D5
        _n(72, "not", 0.75),        # C5
        _n(69, "scared", 2.0),      # A4
        _n(67, "anymore", 3.5),     # G4
        _r(1.0),
    ),
)

# ── CHORUS 1A: "Let me fall..." ───────────────────────────────────
# Hook with descending "let me fall" motif. All words >= 0.75 beats.
chorus_1a_phrase = VocalPhrase(
    phrase_id="chorus_1a",
    bpm=BPM,
    voice="tiger_electric",
    gender=-0.1,
    rvc_model=RVC_MODEL, rvc_pitch_shift=RVC_PITCH_SHIFT, rvc_index_rate=RVC_INDEX_RATE,
    notes=(
        # "Let me fall" — descending hook
        _n(74, "let", 1.0),         # D5
        _n(72, "me", 0.75),         # C5
        _n(69, "fall", 3.0),        # A4 — falling!
        _r(1.0),
        # "I don't need the ground"
        _n(69, "I", 0.75),          # A4
        _n(72, "don't", 1.25),      # C5
        _n(70, "need", 1.25),       # Bb4
        _n(69, "the", 0.75),        # A4
        _n(67, "ground", 2.5),      # G4
        _r(1.0),
        # "Let me fall into the sound"
        _n(74, "let", 1.0),         # D5
        _n(72, "me", 0.75),         # C5
        _n(69, "fall", 2.0),        # A4
        _n(70, "into", 1.25),       # Bb4
        _n(69, "the", 0.75),        # A4
        _n(67, "sound", 3.0),       # G4
        _r(1.0),
        # "I've been holding on so long"
        _n(67, "I've", 0.75),       # G4
        _n(69, "been", 1.0),        # A4
        _n(72, "holding", 2.0),     # C5
        _n(69, "on", 1.0),          # A4
        _n(67, "so", 0.75),         # G4
        _n(65, "long", 2.5),        # F4
        _r(1.0),
        # "let me fall where I belong"
        _n(74, "let", 1.0),         # D5
        _n(72, "me", 0.75),         # C5
        _n(69, "fall", 2.0),        # A4
        _n(67, "where", 1.0),       # G4
        _n(69, "I", 0.75),          # A4
        _n(70, "belong", 3.5),      # Bb4
        _r(0.75),
    ),
)

# ── CHORUS 1B: "Let me fall, through the noise..." ───────────────
chorus_1b_phrase = VocalPhrase(
    phrase_id="chorus_1b",
    bpm=BPM,
    voice="tiger_electric",
    gender=-0.1,
    rvc_model=RVC_MODEL, rvc_pitch_shift=RVC_PITCH_SHIFT, rvc_index_rate=RVC_INDEX_RATE,
    notes=(
        # "Let me fall"
        _n(74, "let", 1.0),         # D5
        _n(72, "me", 0.75),         # C5
        _n(69, "fall", 3.0),        # A4
        _r(1.0),
        # "through the noise and the light"
        _n(69, "through", 1.0),     # A4
        _n(70, "the", 0.75),        # Bb4
        _n(72, "noise", 1.5),       # C5
        _n(69, "and", 0.75),        # A4
        _n(67, "the", 0.75),        # G4
        _n(65, "light", 2.5),       # F4
        _r(1.0),
        # "Let me fall through the night"
        _n(74, "let", 1.0),         # D5
        _n(72, "me", 0.75),         # C5
        _n(69, "fall", 2.0),        # A4
        _n(67, "through", 1.0),     # G4
        _n(65, "the", 0.75),        # F4
        _n(62, "night", 3.0),       # D4
        _r(1.0),
        # "I don't need to understand"
        _n(65, "I", 0.75),          # F4
        _n(67, "don't", 1.0),       # G4
        _n(69, "need", 1.25),       # A4
        _n(67, "to", 0.75),         # G4
        _n(72, "understand", 3.5),  # C5
        _r(1.0),
        # "let me fall from my own hands"
        _n(74, "let", 1.0),         # D5
        _n(72, "me", 0.75),         # C5
        _n(69, "fall", 2.0),        # A4
        _n(67, "from", 0.75),       # G4
        _n(65, "my", 0.75),         # F4
        _n(67, "own", 1.0),         # G4
        _n(62, "hands", 3.5),       # D4
        _r(0.75),
    ),
)

# ── VERSE 2A: "I see the city from up here..." ───────────────────
verse_2a_phrase = VocalPhrase(
    phrase_id="verse_2a",
    bpm=BPM,
    voice="tiger_fresh",
    gender=-0.15,
    rvc_model=RVC_MODEL, rvc_pitch_shift=RVC_PITCH_SHIFT, rvc_index_rate=RVC_INDEX_RATE,
    notes=(
        # "I see the city from up here"
        _n(62, "I", 0.75),          # D4
        _n(65, "see", 1.25),        # F4
        _n(64, "the", 0.75),        # E4
        _n(67, "city", 2.0),        # G4
        _n(65, "from", 1.0),        # F4
        _n(69, "up", 1.0),          # A4
        _n(67, "here", 2.5),        # G4
        _r(1.0),
        # "the lights look just like breathing"
        _n(67, "the", 0.75),        # G4
        _n(70, "lights", 1.5),      # Bb4
        _n(69, "look", 1.0),        # A4
        _n(67, "just", 0.75),       # G4
        _n(65, "like", 1.0),        # F4
        _n(69, "breathing", 3.0),   # A4
        _r(1.0),
        # "my old life fits inside a window"
        _n(65, "my", 0.75),         # F4
        _n(69, "old", 1.25),        # A4
        _n(67, "life", 1.25),       # G4
        _n(65, "fits", 1.0),        # F4
        _n(69, "inside", 1.5),      # A4
        _n(67, "a", 0.75),          # G4
        _n(72, "window", 2.5),      # C5
        _r(1.0),
        # "too small to climb back through"
        _n(72, "too", 1.0),         # C5
        _n(69, "small", 1.25),      # A4
        _n(67, "to", 0.75),         # G4
        _n(65, "climb", 1.25),      # F4
        _n(64, "back", 1.0),        # E4
        _n(62, "through", 3.0),     # D4
        _r(1.0),
    ),
)

# ── VERSE 2B: "I kept a list..." ─────────────────────────────────
verse_2b_phrase = VocalPhrase(
    phrase_id="verse_2b",
    bpm=BPM,
    voice="tiger_fresh",
    gender=-0.15,
    rvc_model=RVC_MODEL, rvc_pitch_shift=RVC_PITCH_SHIFT, rvc_index_rate=RVC_INDEX_RATE,
    notes=(
        # "I kept a list of all the things"
        _n(62, "I", 0.75),          # D4
        _n(65, "kept", 1.25),       # F4
        _n(64, "a", 0.75),          # E4
        _n(67, "list", 1.5),        # G4
        _n(65, "of", 0.75),         # F4
        _n(69, "all", 1.25),        # A4
        _n(67, "the", 0.75),        # G4
        _n(65, "things", 2.5),      # F4
        _r(1.0),
        # "that I was supposed to be"
        _n(67, "that", 0.75),       # G4
        _n(69, "I", 0.75),          # A4
        _n(67, "was", 1.0),         # G4
        _n(70, "supposed", 2.0),    # Bb4
        _n(69, "to", 0.75),         # A4
        _n(67, "be", 3.0),          # G4
        _r(1.0),
        # "I folded it into a bird"
        _n(65, "I", 0.75),          # F4
        _n(69, "folded", 1.5),      # A4
        _n(67, "it", 0.75),         # G4
        _n(69, "into", 1.5),        # A4
        _n(67, "a", 0.75),          # G4
        _n(72, "bird", 2.5),        # C5
        _r(1.0),
        # "and watched it leave without me"
        _n(72, "and", 0.75),        # C5
        _n(69, "watched", 1.25),    # A4
        _n(67, "it", 0.75),         # G4
        _n(65, "leave", 1.5),       # F4
        _n(64, "without", 2.0),     # E4
        _n(62, "me", 3.5),          # D4
        _r(1.0),
    ),
)

# ── PRE-CHORUS 2: "The air is thin..." ───────────────────────────
pre_chorus_2_phrase = VocalPhrase(
    phrase_id="pre_chorus_2",
    bpm=BPM,
    voice="tiger_fresh",
    gender=-0.1,
    rvc_model=RVC_MODEL, rvc_pitch_shift=RVC_PITCH_SHIFT, rvc_index_rate=RVC_INDEX_RATE,
    notes=(
        # "The air is thin"
        _n(67, "the", 0.75),        # G4
        _n(69, "air", 2.0),         # A4
        _n(72, "is", 0.75),         # C5
        _n(74, "thin", 2.5),        # D5
        _r(1.5),
        # "the sky is wide"
        _n(72, "the", 0.75),        # C5
        _n(74, "sky", 2.0),         # D5
        _n(72, "is", 0.75),         # C5
        _n(70, "wide", 3.0),        # Bb4
        _r(1.5),
        # "and I was never meant to land"
        _n(72, "and", 0.75),        # C5
        _n(74, "I", 1.25),          # D5
        _n(72, "was", 0.75),        # C5
        _n(69, "never", 1.5),       # A4
        _n(67, "meant", 1.25),      # G4
        _n(65, "to", 0.75),         # F4
        _n(69, "land", 3.5),        # A4
        _r(1.0),
    ),
)

# ── CHORUS 2A = same melody as CHORUS 1A ──────────────────────────
chorus_2a_phrase = VocalPhrase(
    phrase_id="chorus_2a",
    bpm=BPM,
    voice="tiger_electric",
    gender=-0.1,
    rvc_model=RVC_MODEL, rvc_pitch_shift=RVC_PITCH_SHIFT, rvc_index_rate=RVC_INDEX_RATE,
    notes=chorus_1a_phrase.notes,
)

# ── CHORUS 2B = same melody as CHORUS 1B ──────────────────────────
chorus_2b_phrase = VocalPhrase(
    phrase_id="chorus_2b",
    bpm=BPM,
    voice="tiger_electric",
    gender=-0.1,
    rvc_model=RVC_MODEL, rvc_pitch_shift=RVC_PITCH_SHIFT, rvc_index_rate=RVC_INDEX_RATE,
    notes=chorus_1b_phrase.notes,
)

# ── BRIDGE: "There is no bottom..." ──────────────────────────────
bridge_phrase = VocalPhrase(
    phrase_id="bridge",
    bpm=BPM,
    voice="tiger_fresh",
    gender=-0.2,
    rvc_model=RVC_MODEL, rvc_pitch_shift=RVC_PITCH_SHIFT, rvc_index_rate=RVC_INDEX_RATE,
    notes=(
        # "There is no bottom"
        _n(62, "there", 1.25),      # D4
        _n(65, "is", 1.0),          # F4
        _n(67, "no", 1.0),          # G4
        _n(69, "bottom", 3.0),      # A4
        _r(2.0),
        # "There is no end"
        _n(64, "there", 1.25),      # E4
        _n(65, "is", 1.0),          # F4
        _n(67, "no", 1.0),          # G4
        _n(69, "end", 3.0),         # A4
        _r(2.0),
        # "Just the fall"
        _n(65, "just", 1.25),       # F4
        _n(67, "the", 0.75),        # G4
        _n(70, "fall", 3.5),        # Bb4
        _r(2.0),
        # "And falling feels like flying"
        _n(67, "and", 0.75),        # G4
        _n(69, "falling", 2.0),     # A4
        _n(67, "feels", 1.25),      # G4
        _n(65, "like", 1.0),        # F4
        _n(67, "flying", 3.5),      # G4
        _r(1.0),
    ),
)

# ── FINAL CHORUS A: "Let me fall..." (EPIC) ──────────────────────
# Same hook as chorus 1a but lyrics variation: "standing still" instead of "holding on"
final_chorus_a_phrase = VocalPhrase(
    phrase_id="final_chorus_a",
    bpm=BPM,
    voice="tiger_electric",
    gender=-0.1,
    rvc_model=RVC_MODEL, rvc_pitch_shift=RVC_PITCH_SHIFT, rvc_index_rate=RVC_INDEX_RATE,
    notes=(
        # "Let me fall"
        _n(74, "let", 1.0),         # D5
        _n(72, "me", 0.75),         # C5
        _n(69, "fall", 3.0),        # A4
        _r(1.0),
        # "I don't need the ground"
        _n(69, "I", 0.75),          # A4
        _n(72, "don't", 1.25),      # C5
        _n(70, "need", 1.25),       # Bb4
        _n(69, "the", 0.75),        # A4
        _n(67, "ground", 2.5),      # G4
        _r(1.0),
        # "Let me fall into the sound"
        _n(74, "let", 1.0),         # D5
        _n(72, "me", 0.75),         # C5
        _n(69, "fall", 2.0),        # A4
        _n(70, "into", 1.25),       # Bb4
        _n(69, "the", 0.75),        # A4
        _n(67, "sound", 3.0),       # G4
        _r(1.0),
        # "I've been standing still so long"
        _n(67, "I've", 0.75),       # G4
        _n(69, "been", 1.0),        # A4
        _n(72, "standing", 2.0),    # C5
        _n(69, "still", 1.0),       # A4
        _n(67, "so", 0.75),         # G4
        _n(65, "long", 2.5),        # F4
        _r(1.0),
        # "let me fall where I belong"
        _n(74, "let", 1.0),         # D5
        _n(72, "me", 0.75),         # C5
        _n(69, "fall", 2.0),        # A4
        _n(67, "where", 1.0),       # G4
        _n(69, "I", 0.75),          # A4
        _n(70, "belong", 3.5),      # Bb4
        _r(0.75),
    ),
)

# ── FINAL CHORUS B: "Let me fall..." (EPIC, shorter) ─────────────
final_chorus_b_phrase = VocalPhrase(
    phrase_id="final_chorus_b",
    bpm=BPM,
    voice="tiger_electric",
    gender=-0.1,
    rvc_model=RVC_MODEL, rvc_pitch_shift=RVC_PITCH_SHIFT, rvc_index_rate=RVC_INDEX_RATE,
    notes=(
        # "Let me fall"
        _n(74, "let", 1.0),         # D5
        _n(72, "me", 0.75),         # C5
        _n(69, "fall", 3.0),        # A4
        _r(1.0),
        # "I don't need to understand"
        _n(69, "I", 0.75),          # A4
        _n(72, "don't", 1.25),      # C5
        _n(70, "need", 1.25),       # Bb4
        _n(69, "to", 0.75),         # A4
        _n(72, "understand", 3.5),  # C5
        _r(1.0),
        # "Let me fall"
        _n(74, "let", 1.0),         # D5
        _n(72, "me", 0.75),         # C5
        _n(69, "fall", 3.5),        # A4
        _r(1.5),
        # "let me fall from my own hands"
        _n(74, "let", 1.0),         # D5
        _n(72, "me", 0.75),         # C5
        _n(69, "fall", 2.0),        # A4
        _n(67, "from", 0.75),       # G4
        _n(65, "my", 0.75),         # F4
        _n(67, "own", 1.0),         # G4
        _n(62, "hands", 4.5),       # D4
        _r(0.75),
    ),
)

# ── OUTRO: "Falling feels like flying" ───────────────────────────
outro_phrase = VocalPhrase(
    phrase_id="outro",
    bpm=BPM,
    voice="tiger_fresh",
    gender=-0.2,
    rvc_model=RVC_MODEL, rvc_pitch_shift=RVC_PITCH_SHIFT, rvc_index_rate=RVC_INDEX_RATE,
    notes=(
        # "Falling feels like flying"
        _n(67, "falling", 2.5),     # G4
        _n(65, "feels", 1.25),      # F4
        _n(64, "like", 1.0),        # E4
        _n(62, "flying", 3.5),      # D4
        _r(2.0),
        # "Falling feels like flying" — second, lower
        _n(65, "falling", 2.5),     # F4
        _n(64, "feels", 1.25),      # E4
        _n(62, "like", 1.0),        # D4
        _n(60, "flying", 4.5),      # C4
        _r(1.0),
    ),
)

# All vocal phrases with their beat placements
VOCAL_PHRASES: Final[list[tuple[VocalPhrase, float]]] = [
    (intro_phrase, 0.0),
    (verse_1a_phrase, 32.0),
    (verse_1b_phrase, 64.0),
    (pre_chorus_1_phrase, 96.0),
    (chorus_1a_phrase, 128.0),
    (chorus_1b_phrase, 160.0),
    (verse_2a_phrase, 192.0),
    (verse_2b_phrase, 224.0),
    (pre_chorus_2_phrase, 256.0),
    (chorus_2a_phrase, 288.0),
    (chorus_2b_phrase, 320.0),
    (bridge_phrase, 352.0),
    (final_chorus_a_phrase, 384.0),
    (final_chorus_b_phrase, 416.0),
    (outro_phrase, 452.0),
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
    """Generate Let Me Fall: instrumental + DiffSinger vocals + SFX → mastered MP3."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ── 1. Render instrumental ──
    print("Rendering instrumental arrangement...")
    arrangement = build_arrangement()
    inst_left, inst_right = render_arrangement(arrangement)

    # ── 2. Render SFX layer ──
    print("Synthesizing SFX (risers + impacts)...")
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

    # ── 3. Generate vocals with DiffSinger ──
    print("Generating vocals with DiffSinger + RVC...")
    ds_engine = DiffSingerEngine(voicebank_dir=str(VOICEBANK_DIR), device="cuda")

    vocal_results: dict[str, np.ndarray] = {}
    for phrase, _beat in VOCAL_PHRASES:
        print(f"\n  Generating: {phrase.phrase_id}")
        result = ds_engine.generate(phrase)
        vocal_results[phrase.phrase_id] = result.samples
        print(f"    Duration: {result.duration:.2f}s")

    # ── 3b. Trim vocals to fit beat windows (prevent overlap) ──
    print("\nTrimming vocals to beat windows...")
    FADE_OUT_MS: float = 80.0  # ms fade at end of each phrase
    fade_samples = int(FADE_OUT_MS / 1000.0 * SAMPLE_RATE)

    for i, (phrase, beat) in enumerate(VOCAL_PHRASES):
        samples = vocal_results.get(phrase.phrase_id)
        if samples is None:
            continue

        # Calculate max allowed duration from this phrase to the next
        if i + 1 < len(VOCAL_PHRASES):
            next_beat = VOCAL_PHRASES[i + 1][1]
            max_seconds = (next_beat - beat) * SECONDS_PER_BEAT
        else:
            # Last phrase: allow until song end
            max_seconds = (TOTAL_BEATS - beat) * SECONDS_PER_BEAT

        max_samples = int(max_seconds * SAMPLE_RATE)
        actual_samples = len(samples)

        if actual_samples > max_samples:
            # Trim and apply fade-out at the cut point
            trimmed = samples[:max_samples].copy()
            fade_len = min(fade_samples, max_samples)
            fade_curve = np.linspace(1.0, 0.0, fade_len, dtype=np.float32)
            trimmed[-fade_len:] *= fade_curve
            vocal_results[phrase.phrase_id] = trimmed
            print(f"  {phrase.phrase_id}: trimmed {actual_samples/SAMPLE_RATE:.2f}s -> {max_samples/SAMPLE_RATE:.2f}s")
        else:
            print(f"  {phrase.phrase_id}: {actual_samples/SAMPLE_RATE:.2f}s (fits in {max_seconds:.2f}s window)")

    # ── 4. Apply ducking ──
    print("\nApplying vocal-instrumental ducking (-3dB)...")
    vocal_durations: dict[str, float] = {}
    for phrase, _beat in VOCAL_PHRASES:
        samples = vocal_results.get(phrase.phrase_id)
        if samples is not None:
            vocal_durations[phrase.phrase_id] = len(samples) / SAMPLE_RATE

    vocal_placement_seconds: list[tuple[str, float]] = [
        (phrase.phrase_id, beat * SECONDS_PER_BEAT) for phrase, beat in VOCAL_PHRASES
    ]
    ducked_left, ducked_right = apply_ducking(
        inst_left,
        inst_right,
        vocal_placement_seconds,
        vocal_durations,
        reduction_db=-3.0,
        attack_seconds=0.08,
        release_seconds=0.3,
    )

    # ── 5. Overlay vocals onto ducked instrumental ──
    print("Mixing vocals onto instrumental...")
    VOCAL_GAIN: float = 0.85

    for phrase, beat in VOCAL_PHRASES:
        samples = vocal_results.get(phrase.phrase_id)
        if samples is None:
            continue
        start_sample = int(beat * SECONDS_PER_BEAT * SAMPLE_RATE)
        vocal_mono = (samples * VOCAL_GAIN).tolist()
        overlay_onto(
            ducked_left,
            ducked_right,
            vocal_mono,
            vocal_mono,
            start_sample,
        )

    # ── 6. Normalize and export ──
    print("Normalizing stereo mix...")
    final_left, final_right = normalize_stereo(ducked_left, ducked_right)

    print(f"Writing WAV: {WAV_PATH}")
    write_stereo_wav(WAV_PATH, final_left, final_right)

    print(f"Mastering to MP3: {MP3_PATH}")
    master_to_mp3(WAV_PATH, MP3_PATH, target_lufs=-14.0, stereo_width=1.2)

    duration_seconds = TOTAL_BEATS * SECONDS_PER_BEAT
    minutes = int(duration_seconds // 60)
    seconds = int(duration_seconds % 60)
    print(f"Done! {MP3_PATH} ({minutes}:{seconds:02d})")


if __name__ == "__main__":
    main()

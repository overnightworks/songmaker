"""Track 01: Let Me Fall — Melodic House (CYRIL x Avicii Style).

Album: Midnight Frequency
Genre: Melodic House
BPM: 120
Key: D minor
Duration: 480 beats (4:00)

Vocals: ACE-Step 1.5 (text-to-music AI)
Instrumental: Songmaker engine (dark_pad, supersaw, pluck, sub_bass, drums)

Three vocal modes (--mode):
    full-mix     ACE-Step generates everything (vocals + its own instruments)
    demucs       ACE-Step full mix → Demucs vocal extraction → Songmaker instrumentals
    songmaker    Songmaker instrumentals only (no vocals, for mixing later)

Emotional arc: Suffocation → grip slipping → freefall → euphoria → transcendence
Hook: "Let me fall, I don't need the ground / Let me fall into the sound"
"""

from __future__ import annotations

import math
import os
import random
import sys
from typing import Final

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
TOTAL_SECONDS: Final[float] = TOTAL_BEATS * SECONDS_PER_BEAT  # 240s = 4:00

OUTPUT_DIR: Final[str] = "_output/midnight_frequency"
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
# ACE-Step vocal configuration
# ═══════════════════════════════════════════════════════════════════════════

ACESTEP_PROMPT: Final[str] = (
    "melodic house, female vocal, supersaw synths, four-on-the-floor drums, "
    "dark pad, sub bass, emotional, euphoric drop, D minor, "
    "CYRIL style, Avicii inspired"
)

ACESTEP_LYRICS: Final[str] = """\
[intro]
I built these walls
With steady hands

[verse]
I built these walls with steady hands
But steady hands still shake at night
I held my breath for twenty years
Forgot what air tastes like

I drew the map, I marked the lines
Colored inside every one
The picture looked like someone's life
But I don't know whose

[pre-chorus]
My fingers slip
The edge is gone
And I'm not scared anymore

[chorus]
Let me fall
I don't need the ground
Let me fall into the sound
I've been holding on so long
Let me fall where I belong

Let me fall
Through the noise and the light
Let me fall through the night
I don't need to understand
Let me fall from my own hands

[verse]
I see the city from up here
The lights look just like breathing
My old life fits inside a window
Too small to climb back through

I kept a list of all the things
That I was supposed to be
I folded it into a bird
And watched it leave without me

[pre-chorus]
The air is thin
The sky is wide
And I was never meant to land

[chorus]
Let me fall
I don't need the ground
Let me fall into the sound
I've been holding on so long
Let me fall where I belong

Let me fall
Through the noise and the light
Let me fall through the night
I don't need to understand
Let me fall from my own hands

[bridge]
There is no bottom
There is no end
Just the fall
And falling feels like flying

[chorus]
Let me fall
I don't need the ground
Let me fall into the sound
I've been standing still so long
Let me fall where I belong

Let me fall
I don't need to understand
Let me fall
Let me fall from my own hands

[outro]
Falling feels like flying
Falling feels like flying
"""

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
    """Generate Let Me Fall with configurable vocal mode.

    Usage:
        python 01_let_me_fall.py                     # Default: full-mix
        python 01_let_me_fall.py --mode full-mix      # ACE-Step generates everything
        python 01_let_me_fall.py --mode demucs         # ACE-Step → Demucs extraction → Songmaker mix
        python 01_let_me_fall.py --mode songmaker      # Songmaker instrumentals only (no vocals)
        python 01_let_me_fall.py --seed 42             # Reproducible generation
    """
    import argparse
    import logging
    import time

    from bark_engine.audio_io import (
        normalize_audio,
        overlay_audio,
        write_wav_file,
    )

    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Generate Let Me Fall")
    parser.add_argument(
        "--mode", choices=["full-mix", "demucs", "songmaker"],
        default="full-mix",
        help="Vocal generation mode (default: full-mix)",
    )
    parser.add_argument("--seed", type=int, default=-1, help="Random seed (-1 = random)")
    args = parser.parse_args()

    start_time = time.time()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 60)
    print("  Let Me Fall — Melodic House")
    print(f"  Mode: {args.mode} | {BPM} BPM | D minor | 4:00")
    print("=" * 60)

    # ── Mode: full-mix — ACE-Step does everything ──
    if args.mode == "full-mix":
        _generate_full_mix(args.seed)

    # ── Mode: demucs — ACE-Step vocals + Songmaker instrumentals ──
    elif args.mode == "demucs":
        _generate_demucs_mix(args.seed)

    # ── Mode: songmaker — Songmaker instrumentals only ──
    elif args.mode == "songmaker":
        _generate_songmaker_only()

    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    print(f"\n{'=' * 60}")
    print(f"  Total time: {minutes}:{seconds:02d}")
    print(f"{'=' * 60}")


def _generate_full_mix(seed: int) -> None:
    """Mode 1: ACE-Step generates the entire song (vocals + instruments)."""
    from acestep_engine import AceStepClient, AceStepConfig, is_acestep_available
    from bark_engine.audio_io import write_wav_file

    print("\n  Checking ACE-Step server...")
    if not is_acestep_available():
        print("  ERROR: ACE-Step server not running!")
        print("  Start it with: python scripts/start_acestep.py")
        sys.exit(1)

    config = AceStepConfig(
        prompt=ACESTEP_PROMPT,
        lyrics=ACESTEP_LYRICS,
        bpm=BPM,
        duration=int(TOTAL_SECONDS),
        key="Dm",
        time_signature="4/4",
        vocal_language="en",
        seed=seed,
    )

    print(f"  Generating {config.duration}s via ACE-Step (this takes ~9 minutes)...")
    client = AceStepClient()
    result = client.generate(config)
    if result is None:
        print("  ERROR: ACE-Step generation failed!")
        sys.exit(1)

    print(f"  Generated: {result.duration:.1f}s, seed={result.seed}")

    # Write directly — ACE-Step's output IS the final mix
    write_wav_file(WAV_PATH, result.samples)
    print(f"  WAV: {WAV_PATH}")

    from bark_engine.audio_io import master_to_mp3 as mono_master
    mono_master(WAV_PATH, MP3_PATH)
    print(f"  MP3: {MP3_PATH}")


def _generate_demucs_mix(seed: int) -> None:
    """Mode 2: ACE-Step full mix → Demucs vocal extraction → Songmaker instrumentals."""
    from acestep_engine import AceStepClient, AceStepConfig, is_acestep_available
    from bark_engine.audio_io import normalize_audio, overlay_audio, write_wav_file
    from instrumental_engine.mixer import stereo_to_mono

    print("\n  Checking ACE-Step server...")
    if not is_acestep_available():
        print("  ERROR: ACE-Step server not running!")
        print("  Start it with: python scripts/start_acestep.py")
        sys.exit(1)

    # Step 1: Generate full mix via ACE-Step
    config = AceStepConfig(
        prompt=ACESTEP_PROMPT,
        lyrics=ACESTEP_LYRICS,
        bpm=BPM,
        duration=int(TOTAL_SECONDS),
        key="Dm",
        time_signature="4/4",
        vocal_language="en",
        seed=seed,
    )

    print(f"\n  Step 1/5: Generating {config.duration}s via ACE-Step...")
    client = AceStepClient()
    result = client.generate(config)
    if result is None:
        print("  ERROR: ACE-Step generation failed!")
        sys.exit(1)

    print(f"    Generated: {result.duration:.1f}s, seed={result.seed}")

    # Save raw ACE-Step output for reference
    raw_path = os.path.join(OUTPUT_DIR, "01_Let_Me_Fall_acestep_raw.wav")
    write_wav_file(raw_path, result.samples)

    # Step 2: Extract vocals with Demucs
    print("\n  Step 2/5: Extracting vocals with Demucs...")
    try:
        from stem_separator import DemucsSeparator, is_demucs_available

        if not is_demucs_available():
            print("    ERROR: Demucs not installed! Run: pip install -e \".[demucs]\"")
            sys.exit(1)

        separator = DemucsSeparator()
        stems = separator.separate(raw_path)
        if stems is None:
            print("    ERROR: Demucs separation failed!")
            sys.exit(1)

        vocals = stems.vocals
        print(f"    Extracted vocals: {len(vocals) / SAMPLE_RATE:.1f}s")

        # Save isolated vocals
        vocals_path = os.path.join(OUTPUT_DIR, "01_Let_Me_Fall_vocals.wav")
        write_wav_file(vocals_path, vocals)

    except ImportError:
        print("    ERROR: stem_separator not available!")
        sys.exit(1)

    # Step 3: Render Songmaker instrumentals
    print("\n  Step 3/5: Rendering Songmaker instrumentals + SFX...")
    arrangement = build_arrangement()
    inst_left, inst_right = render_arrangement(arrangement)
    _add_sfx(inst_left, inst_right)
    inst_mono = stereo_to_mono(inst_left, inst_right)

    # Step 4: Mix vocals onto instrumentals with ducking
    print("\n  Step 4/5: Mixing vocals onto instrumentals...")
    mixed = list(inst_mono)

    # Pad if vocals are longer than instrumental
    if len(vocals) > len(mixed):
        mixed.extend([0.0] * (len(vocals) - len(mixed)))

    # Apply simple ducking: reduce instrumental where vocals are active
    VOCAL_GAIN = 0.85
    DUCK_DB = -3.0
    duck_factor = 10 ** (DUCK_DB / 20.0)

    for i in range(min(len(vocals), len(mixed))):
        if abs(vocals[i]) > 0.01:
            mixed[i] *= duck_factor
        mixed[i] += vocals[i] * VOCAL_GAIN

    mixed = normalize_audio(mixed, 0.95)

    # Step 5: Master and export
    print("\n  Step 5/5: Mastering...")
    write_wav_file(WAV_PATH, mixed)
    print(f"  WAV: {WAV_PATH}")

    from bark_engine.audio_io import master_to_mp3 as mono_master
    mono_master(WAV_PATH, MP3_PATH)
    print(f"  MP3: {MP3_PATH}")


def _generate_songmaker_only() -> None:
    """Mode 3: Songmaker instrumentals only (no vocals)."""
    print("\n  Rendering Songmaker instrumentals + SFX...")
    arrangement = build_arrangement()
    inst_left, inst_right = render_arrangement(arrangement)
    _add_sfx(inst_left, inst_right)

    print("  Normalizing stereo mix...")
    final_left, final_right = normalize_stereo(inst_left, inst_right)

    print(f"  Writing WAV: {WAV_PATH}")
    write_stereo_wav(WAV_PATH, final_left, final_right)

    print(f"  Mastering to MP3: {MP3_PATH}")
    master_to_mp3(WAV_PATH, MP3_PATH, target_lufs=-14.0, stereo_width=1.2)

    duration_seconds = TOTAL_BEATS * SECONDS_PER_BEAT
    minutes = int(duration_seconds // 60)
    seconds = int(duration_seconds % 60)
    print(f"  Done! {MP3_PATH} ({minutes}:{seconds:02d})")


def _add_sfx(inst_left: list[float], inst_right: list[float]) -> None:
    """Add white noise risers and impact hits to the instrumental mix."""
    total_samples = len(inst_left)

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
                inst_left[idx] += sl * l_gain
                inst_right[idx] += sr * r_gain


if __name__ == "__main__":
    main()

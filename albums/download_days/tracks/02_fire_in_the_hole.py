"""Track 02: Fire in the Hole — Boom-Bap Hip-Hop (90s Counter-Strike Anthem).

A boom-bap hip-hop track about Counter-Strike LAN parties with the
Power Terminators clan. Features RAP verses, SINGING chorus, synthesized
game SFX (AWP, AK-47, Deagle, headshot dink, MONSTER KILL), and the
full stereo pipeline with ducking and professional mastering.

Key: A minor | BPM: 90 | Server: Dark Terrorists
Produced by Flex0r for MC Tobbisch.
"""

from __future__ import annotations

import math
import random
import sys
import time
from pathlib import Path
from typing import Final

sys.path.insert(0, "source_files")

from bark_engine import (
    BarkVocalEngine,
    VocalSection,
    VocalStyle,
    calculate_vocal_durations,
)
from bark_engine.models import VocalLanguage
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
    SAMPLE_RATE,
)
from instrumental_engine.mixer import (
    normalize_stereo,
    overlay_onto,
    write_stereo_wav,
    master_to_mp3,
)

# ═══════════════════════════════════════════════════════════════════
# Song Constants
# ═══════════════════════════════════════════════════════════════════

SONG_TITLE: Final[str] = "Fire in the Hole"
SONG_BPM: Final[int] = 90
SONG_KEY: Final[str] = "A"
SONG_SCALE: Final[str] = "minor"
OUTPUT_DIR: Final[Path] = Path("albums/download_days/output")
OUTPUT_NAME: Final[str] = "02_Fire_in_the_Hole"
SECONDS_PER_BEAT: Final[float] = 60.0 / SONG_BPM
TWO_PI: Final[float] = 2.0 * math.pi

# ── Jazzy 7th chord voicings (A minor tonality) ──
AM7: Final[tuple[int, ...]] = (57, 60, 64, 67)
FMAJ7: Final[tuple[int, ...]] = (53, 57, 60, 64)
G7: Final[tuple[int, ...]] = (55, 59, 62, 65)
EM7: Final[tuple[int, ...]] = (52, 55, 59, 62)
DM7: Final[tuple[int, ...]] = (50, 53, 57, 60)

# ── Bass root notes ──
BASS_A: Final[int] = 33
BASS_F: Final[int] = 29
BASS_G: Final[int] = 31
BASS_E: Final[int] = 28
BASS_D: Final[int] = 26

# ── Melody notes (A minor pentatonic) ──
MELODY_A: Final[int] = 69
MELODY_C: Final[int] = 72
MELODY_D: Final[int] = 74
MELODY_E: Final[int] = 76
MELODY_G: Final[int] = 79


# ═══════════════════════════════════════════════════════════════════
# Game SFX Synthesizers (pure DSP, no samples needed)
# ═══════════════════════════════════════════════════════════════════


def _synth_awp_shot(sample_rate: int = SAMPLE_RATE) -> list[float]:
    """Synthesize AWP sniper rifle shot: heavy crack + bass thump."""
    duration = 0.4
    n = int(duration * sample_rate)
    result: list[float] = []
    for i in range(n):
        t = i / sample_rate
        crack = random.uniform(-1.0, 1.0) * math.exp(-30.0 * t) * 0.8
        thump = math.sin(TWO_PI * 60.0 * t) * math.exp(-15.0 * t) * 0.7
        tail = math.sin(TWO_PI * 40.0 * t) * math.exp(-8.0 * t) * 0.3
        result.append((crack + thump + tail) * 0.7)
    return result


def _synth_awp_reload(sample_rate: int = SAMPLE_RATE) -> list[float]:
    """Synthesize AWP bolt-action reload: two metallic clicks."""
    duration = 0.35
    n = int(duration * sample_rate)
    result: list[float] = [0.0] * n
    for click_time in (0.05, 0.2):
        click_start = int(click_time * sample_rate)
        click_len = int(0.03 * sample_rate)
        for j in range(click_len):
            idx = click_start + j
            if idx < n:
                t_local = j / sample_rate
                click = math.sin(TWO_PI * 3500.0 * t_local) * math.exp(-150.0 * t_local) * 0.4
                noise = random.uniform(-0.2, 0.2) * math.exp(-100.0 * t_local)
                result[idx] += click + noise
    return result


def _synth_ak_spray(sample_rate: int = SAMPLE_RATE) -> list[float]:
    """Synthesize AK-47 spray: 4 rapid shots."""
    shot_interval = 0.09
    duration = shot_interval * 4 + 0.15
    n = int(duration * sample_rate)
    result: list[float] = [0.0] * n
    for shot in range(4):
        start = int(shot * shot_interval * sample_rate)
        shot_len = int(0.08 * sample_rate)
        for j in range(shot_len):
            idx = start + j
            if idx < n:
                t_local = j / sample_rate
                crack = random.uniform(-1.0, 1.0) * math.exp(-50.0 * t_local) * 0.6
                punch = math.sin(TWO_PI * 80.0 * t_local) * math.exp(-25.0 * t_local) * 0.4
                result[idx] += (crack + punch) * 0.5
    return result


def _synth_deagle(sample_rate: int = SAMPLE_RATE) -> list[float]:
    """Synthesize Desert Eagle shot: chunky single shot with reverb tail."""
    duration = 0.3
    n = int(duration * sample_rate)
    result: list[float] = []
    for i in range(n):
        t = i / sample_rate
        crack = random.uniform(-1.0, 1.0) * math.exp(-40.0 * t) * 0.7
        body = math.sin(TWO_PI * 90.0 * t) * math.exp(-12.0 * t) * 0.5
        result.append((crack + body) * 0.6)
    return result


def _synth_headshot_dink(sample_rate: int = SAMPLE_RATE) -> list[float]:
    """Synthesize headshot dink: high metallic ping."""
    duration = 0.15
    n = int(duration * sample_rate)
    result: list[float] = []
    for i in range(n):
        t = i / sample_rate
        ping = math.sin(TWO_PI * 4200.0 * t) * math.exp(-40.0 * t) * 0.5
        harmonic = math.sin(TWO_PI * 6300.0 * t) * math.exp(-50.0 * t) * 0.2
        result.append(ping + harmonic)
    return result


def _synth_round_start(sample_rate: int = SAMPLE_RATE) -> list[float]:
    """Synthesize CS round start beep."""
    duration = 0.6
    n = int(duration * sample_rate)
    result: list[float] = []
    for i in range(n):
        t = i / sample_rate
        beep_on = 1.0 if t < 0.15 or 0.25 < t < 0.4 else 0.0
        tone = math.sin(TWO_PI * 880.0 * t) * 0.3 * beep_on
        env = math.exp(-2.0 * t)
        result.append(tone * env)
    return result


def _synth_bomb_plant(sample_rate: int = SAMPLE_RATE) -> list[float]:
    """Synthesize bomb plant beep sequence."""
    duration = 1.5
    n = int(duration * sample_rate)
    result: list[float] = []
    for i in range(n):
        t = i / sample_rate
        beep_period = 0.3
        beep_on = 1.0 if (t % beep_period) < 0.08 else 0.0
        tone = math.sin(TWO_PI * 1200.0 * t) * 0.25 * beep_on
        fade = max(0.0, 1.0 - t / duration)
        result.append(tone * fade)
    return result


# ═══════════════════════════════════════════════════════════════════
# Boom-bap drum patterns
# ═══════════════════════════════════════════════════════════════════


def _build_boom_bap() -> DrumPattern:
    """Classic boom-bap: heavy kick, tight snare, dusty hihats."""
    hits: list[DrumHit] = [
        DrumHit(DrumSound.KICK, 0.95, 0.0),
        DrumHit(DrumSound.KICK, 0.7, 1.75),
        DrumHit(DrumSound.KICK, 0.85, 2.5),
        DrumHit(DrumSound.SNARE, 0.9, 1.0),
        DrumHit(DrumSound.SNARE, 0.9, 3.0),
        DrumHit(DrumSound.OPEN_HIHAT, 0.3, 3.5),
    ]
    for eighth in range(8):
        vel = 0.35 if eighth % 2 == 0 else 0.25
        hits.append(DrumHit(DrumSound.CLOSED_HIHAT, vel, eighth * 0.5))
    return DrumPattern("boom_bap", tuple(hits), 4.0)


def _build_intro_beat() -> DrumPattern:
    """Sparse intro: hihats only."""
    hits: list[DrumHit] = [
        DrumHit(DrumSound.CLOSED_HIHAT, 0.3, float(q))
        for q in range(4)
    ]
    return DrumPattern("intro_sparse", tuple(hits), 4.0)


def _build_bridge_beat() -> DrumPattern:
    """Half-time bridge beat."""
    return DrumPattern(
        "bridge_half",
        (
            DrumHit(DrumSound.KICK, 0.6, 0.0),
            DrumHit(DrumSound.SNARE, 0.4, 2.0),
            DrumHit(DrumSound.RIDE, 0.2, 0.0),
            DrumHit(DrumSound.RIDE, 0.15, 2.0),
        ),
        4.0,
    )


BOOM_BAP: Final[DrumPattern] = _build_boom_bap()
INTRO_BEAT: Final[DrumPattern] = _build_intro_beat()
BRIDGE_BEAT: Final[DrumPattern] = _build_bridge_beat()


# ═══════════════════════════════════════════════════════════════════
# Musical building blocks
# ═══════════════════════════════════════════════════════════════════


def _chord(notes: tuple[int, ...], beats: float, vel: float = 0.55) -> Chord:
    """Create a chord."""
    return Chord(notes=notes, velocity=vel, duration_beats=beats)


def _bass(midi: int, beats: float, vel: float = 0.75) -> Note:
    """Create a bass note."""
    return Note(midi=midi, velocity=vel, duration_beats=beats)


def _note(midi: int, beats: float, vel: float = 0.5) -> Note:
    """Create a melody note."""
    return Note(midi=midi, velocity=vel, duration_beats=beats)


def _verse_keys() -> tuple[Chord, ...]:
    """Am7 → Fmaj7 → G7 → Em7 (16 beats)."""
    return (
        _chord(AM7, 4.0),
        _chord(FMAJ7, 4.0),
        _chord(G7, 4.0),
        _chord(EM7, 4.0),
    )


def _chorus_keys() -> tuple[Chord, ...]:
    """Am7 → Dm7 → Fmaj7 → G7 (16 beats, brighter)."""
    return (
        _chord(AM7, 4.0, vel=0.65),
        _chord(DM7, 4.0, vel=0.65),
        _chord(FMAJ7, 4.0, vel=0.65),
        _chord(G7, 4.0, vel=0.65),
    )


def _verse_bass() -> tuple[Note | Rest, ...]:
    """Boom-bap bass: syncopated root notes (16 beats)."""
    pattern: list[Note | Rest] = []
    for midi in (BASS_A, BASS_F, BASS_G, BASS_E):
        pattern.extend([
            _bass(midi, 1.5, 0.85),
            _bass(midi, 0.5, 0.5),
            Rest(duration_beats=0.5),
            _bass(midi, 1.0, 0.7),
            _bass(midi, 0.5, 0.6),
        ])
    return tuple(pattern)


def _chorus_bass() -> tuple[Note, ...]:
    """Chorus bass: driving quarters (16 beats)."""
    pattern: list[Note] = []
    for midi in (BASS_A, BASS_D, BASS_F, BASS_G):
        pattern.extend([_bass(midi, 1.0, v) for v in (0.85, 0.6, 0.8, 0.55)])
    return tuple(pattern)


def _hook_melody() -> tuple[Note | Rest, ...]:
    """Catchy hook melody (8 beats)."""
    return (
        _note(MELODY_A, 1.0, 0.55),
        _note(MELODY_C, 0.5, 0.45),
        _note(MELODY_D, 0.5, 0.5),
        _note(MELODY_E, 1.5, 0.6),
        _note(MELODY_D, 0.5, 0.45),
        _note(MELODY_C, 1.0, 0.5),
        _note(MELODY_A, 1.0, 0.55),
        Rest(duration_beats=2.0),
    )


def _pad_chord(notes: tuple[int, ...], beats: float) -> Chord:
    """Long atmospheric pad chord."""
    return _chord(notes, beats, vel=0.2)


# ═══════════════════════════════════════════════════════════════════
# Arrangement
# ═══════════════════════════════════════════════════════════════════


def build_arrangement() -> Arrangement:
    """Build the 'Fire in the Hole' boom-bap arrangement."""
    beat: float = 0.0
    sections: list[SongSection] = []

    # --- INTRO: 8 beats ---
    sections.append(SongSection(
        section_type=SectionType.INTRO,
        start_beat=beat,
        length_beats=8.0,
        bpm=SONG_BPM,
        tracks=(
            InstrumentTrack(
                name="intro_keys", instrument_id="piano",
                events=(_chord(AM7, 8.0, vel=0.3),),
                volume=0.3, pan=PanPosition.CENTER,
            ),
            InstrumentTrack(
                name="intro_pad", instrument_id="dark_pad",
                events=(_pad_chord(AM7, 8.0),),
                volume=0.15, pan=PanPosition.CENTER,
            ),
        ),
        drum_pattern=INTRO_BEAT,
        label="Intro — Server connecting",
    ))
    beat += 8.0

    # --- VERSE 1: 64 beats (4× progression) ---
    sections.append(SongSection(
        section_type=SectionType.VERSE,
        start_beat=beat,
        length_beats=64.0,
        bpm=SONG_BPM,
        tracks=(
            InstrumentTrack(
                name="keys", instrument_id="piano",
                events=_verse_keys() * 4,
                volume=0.4, pan=PanPosition.CENTER_LEFT,
            ),
            InstrumentTrack(
                name="bass", instrument_id="sub_bass",
                events=_verse_bass() * 4,
                volume=0.55, pan=PanPosition.CENTER,
            ),
            InstrumentTrack(
                name="pad", instrument_id="dark_pad",
                events=(_pad_chord(AM7, 16.0),) * 4,
                volume=0.1, pan=PanPosition.CENTER,
            ),
        ),
        drum_pattern=BOOM_BAP,
        label="Verse 1 — LIVE in de_aztec",
    ))
    beat += 64.0

    # --- CHORUS 1: 32 beats ---
    sections.append(SongSection(
        section_type=SectionType.CHORUS,
        start_beat=beat,
        length_beats=32.0,
        bpm=SONG_BPM,
        tracks=(
            InstrumentTrack(
                name="chorus_keys", instrument_id="bright_piano",
                events=_chorus_keys() * 2,
                volume=0.5, pan=PanPosition.CENTER,
            ),
            InstrumentTrack(
                name="bass", instrument_id="sub_bass",
                events=_chorus_bass() * 2,
                volume=0.6, pan=PanPosition.CENTER,
            ),
            InstrumentTrack(
                name="hook", instrument_id="pluck",
                events=_hook_melody() * 4,
                volume=0.3, pan=PanPosition.CENTER_RIGHT,
            ),
            InstrumentTrack(
                name="pad", instrument_id="pad",
                events=(_chord(AM7, 8.0, 0.25), _chord(DM7, 8.0, 0.25),
                        _chord(FMAJ7, 8.0, 0.25), _chord(G7, 8.0, 0.25)),
                volume=0.18, pan=PanPosition.CENTER,
            ),
        ),
        drum_pattern=BOOM_BAP,
        label="Chorus 1 — FIRE IN THE HOLE!",
    ))
    beat += 32.0

    # --- VERSE 2: 96 beats (6× progression for 3 stanzas) ---
    sections.append(SongSection(
        section_type=SectionType.VERSE,
        start_beat=beat,
        length_beats=96.0,
        bpm=SONG_BPM,
        tracks=(
            InstrumentTrack(
                name="keys", instrument_id="piano",
                events=_verse_keys() * 6,
                volume=0.4, pan=PanPosition.CENTER_LEFT,
            ),
            InstrumentTrack(
                name="bass", instrument_id="sub_bass",
                events=_verse_bass() * 6,
                volume=0.55, pan=PanPosition.CENTER,
            ),
            InstrumentTrack(
                name="strings", instrument_id="warm_strings",
                events=(
                    _chord(AM7, 16.0, 0.15), _chord(FMAJ7, 16.0, 0.15),
                    _chord(G7, 16.0, 0.15), _chord(EM7, 16.0, 0.15),
                    _chord(AM7, 16.0, 0.15), _chord(DM7, 16.0, 0.15),
                ),
                volume=0.1, pan=PanPosition.CENTER,
            ),
        ),
        drum_pattern=BOOM_BAP,
        label="Verse 2 — All-night session + cheaters",
    ))
    beat += 96.0

    # --- CHORUS 2: 32 beats ---
    sections.append(SongSection(
        section_type=SectionType.CHORUS,
        start_beat=beat,
        length_beats=32.0,
        bpm=SONG_BPM,
        tracks=(
            InstrumentTrack(
                name="chorus_keys", instrument_id="bright_piano",
                events=_chorus_keys() * 2,
                volume=0.5, pan=PanPosition.CENTER,
            ),
            InstrumentTrack(
                name="bass", instrument_id="sub_bass",
                events=_chorus_bass() * 2,
                volume=0.6, pan=PanPosition.CENTER,
            ),
            InstrumentTrack(
                name="hook", instrument_id="pluck",
                events=_hook_melody() * 4,
                volume=0.3, pan=PanPosition.CENTER_RIGHT,
            ),
            InstrumentTrack(
                name="pad", instrument_id="pad",
                events=(_chord(AM7, 8.0, 0.3), _chord(DM7, 8.0, 0.3),
                        _chord(FMAJ7, 8.0, 0.3), _chord(G7, 8.0, 0.3)),
                volume=0.2, pan=PanPosition.CENTER,
            ),
        ),
        drum_pattern=BOOM_BAP,
        label="Chorus 2",
    ))
    beat += 32.0

    # --- BRIDGE: 16 beats ---
    sections.append(SongSection(
        section_type=SectionType.BRIDGE,
        start_beat=beat,
        length_beats=16.0,
        bpm=SONG_BPM,
        tracks=(
            InstrumentTrack(
                name="bridge_keys", instrument_id="piano",
                events=(_chord(DM7, 8.0, 0.4), _chord(AM7, 8.0, 0.35)),
                volume=0.35, pan=PanPosition.CENTER,
            ),
            InstrumentTrack(
                name="bridge_pad", instrument_id="dark_pad",
                events=(_pad_chord(AM7, 16.0),),
                volume=0.2, pan=PanPosition.CENTER,
            ),
        ),
        drum_pattern=BRIDGE_BEAT,
        label="Bridge — Servers offline",
    ))
    beat += 16.0

    # --- FINAL CHORUS: 32 beats (everything cranked) ---
    sections.append(SongSection(
        section_type=SectionType.CHORUS,
        start_beat=beat,
        length_beats=32.0,
        bpm=SONG_BPM,
        tracks=(
            InstrumentTrack(
                name="chorus_keys", instrument_id="bright_piano",
                events=_chorus_keys() * 2,
                volume=0.55, pan=PanPosition.CENTER,
            ),
            InstrumentTrack(
                name="bass", instrument_id="sub_bass",
                events=_chorus_bass() * 2,
                volume=0.65, pan=PanPosition.CENTER,
            ),
            InstrumentTrack(
                name="hook", instrument_id="pluck",
                events=_hook_melody() * 4,
                volume=0.35, pan=PanPosition.CENTER_RIGHT,
            ),
            InstrumentTrack(
                name="lead", instrument_id="synth_lead_saw",
                events=_hook_melody() * 4,
                volume=0.2, pan=PanPosition.LEFT,
            ),
            InstrumentTrack(
                name="pad", instrument_id="pad",
                events=(_chord(AM7, 8.0, 0.35), _chord(DM7, 8.0, 0.35),
                        _chord(FMAJ7, 8.0, 0.35), _chord(G7, 8.0, 0.35)),
                volume=0.22, pan=PanPosition.CENTER,
            ),
        ),
        drum_pattern=DrumPattern(
            "boom_bap_crash",
            (*BOOM_BAP.hits, DrumHit(DrumSound.CRASH, 0.5, 0.0)),
            4.0,
        ),
        label="FINAL CHORUS — Full squad roll call",
    ))
    beat += 32.0

    # --- OUTRO: 8 beats ---
    sections.append(SongSection(
        section_type=SectionType.OUTRO,
        start_beat=beat,
        length_beats=8.0,
        bpm=SONG_BPM,
        tracks=(
            InstrumentTrack(
                name="outro_keys", instrument_id="piano",
                events=(_chord(AM7, 8.0, 0.15),),
                volume=0.2, pan=PanPosition.CENTER,
            ),
        ),
        drum_pattern=DrumPattern(
            "outro_minimal",
            (DrumHit(DrumSound.KICK, 0.4, 0.0),),
            8.0,
        ),
        label="Outro — Server disconnected",
    ))

    return Arrangement(
        title=SONG_TITLE,
        default_bpm=SONG_BPM,
        sections=tuple(sections),
    )


# ═══════════════════════════════════════════════════════════════════
# Vocal Definitions (from approved lyrics)
# ═══════════════════════════════════════════════════════════════════

VOCALS: Final[list[VocalSection]] = [
    VocalSection(
        section_id="intro",
        text="Power Terminators connected. "
        "Server: Dark Terrorists. "
        "Map: de_aztec. Alle da? Let's go.",
        language=VocalLanguage.ENGLISH,
        style=VocalStyle.SPOKEN,
        singing=False,
        volume=0.85,
        gap_after_seconds=0.2,
        pitch_correction_intensity=0.0,
        pitch_correction_key=SONG_KEY,
        pitch_correction_scale=SONG_SCALE,
    ),
    VocalSection(
        section_id="v1_p1",
        text="Runde eins, CT Spawn, AWP schon in der Hand, "
        "Flexx0r scoped die Brücke, Fadenkreuz am Rand, "
        "Noob Saibot gibt die Ansage, links halten, rechts ist frei, "
        "Kill O Zap zieht die Deagle, Headshot, eins, zwei, drei!",
        language=VocalLanguage.GERMAN,
        style=VocalStyle.RAP,
        singing=False,
        volume=0.9,
        gap_after_seconds=0.3,
        pitch_correction_intensity=0.0,
        pitch_correction_key=SONG_KEY,
        pitch_correction_scale=SONG_SCALE,
    ),
    VocalSection(
        section_id="v1_p2",
        text="Tobbisch rennt mit AK rein, FIRE IN THE HOLE! "
        "Spray Control, vier Kills, der Typ hat keine Kontrolle? "
        "Doch! Ace! Der ganze Raum schreit, Monitor wackelt, "
        "Was war das, Wichser?! Nächste Runde, weiter geballert!",
        language=VocalLanguage.GERMAN,
        style=VocalStyle.RAP,
        singing=False,
        volume=0.9,
        gap_after_seconds=0.2,
        pitch_correction_intensity=0.0,
        pitch_correction_key=SONG_KEY,
        pitch_correction_scale=SONG_SCALE,
    ),
    VocalSection(
        section_id="chorus_1",
        text="Fire in the Hole! Power Terminators kommen rein, "
        "Dark Terrorists Server, cs_militia, de_aztec, alles mein! "
        "Fire in the Hole! AWP, AK, Deagle am Start, "
        "Frag um Frag um Frag, Power Terminators, hart! "
        "MONSTER KILL!",
        language=VocalLanguage.GERMAN,
        style=VocalStyle.SINGING,
        singing=True,
        volume=1.0,
        gap_after_seconds=0.3,
        pitch_correction_intensity=0.7,
        pitch_correction_key=SONG_KEY,
        pitch_correction_scale=SONG_SCALE,
    ),
    VocalSection(
        section_id="v2_p1",
        text="Vier Uhr morgens, Bildschirm brennt, Augen komplett rot, "
        "Pizza aufm Boden, Schlaf ist tot, Red Bull auch schon tot, "
        "Du Spasst, kauf Kevlar! Halt's Maul, ich spar auf AWP! "
        "Nächste Runde Eco, trotzdem Clutch, hört die Welt noch?",
        language=VocalLanguage.GERMAN,
        style=VocalStyle.RAP,
        singing=False,
        volume=0.9,
        gap_after_seconds=0.3,
        pitch_correction_intensity=0.0,
        pitch_correction_key=SONG_KEY,
        pitch_correction_scale=SONG_SCALE,
    ),
    VocalSection(
        section_id="v2_p2",
        text="Clan War läuft, plötzlich, Wallhack! Scheiß Cheater! "
        "Der Typ sieht durch die Wand, Autoaim, was ein Biter! "
        "Vote kick! Der hat Aimbot, Alter, meld den Wichser! "
        "Scheiß drauf, nächste Runde, wir sind trotzdem krasser!",
        language=VocalLanguage.GERMAN,
        style=VocalStyle.RAP,
        singing=False,
        volume=0.9,
        gap_after_seconds=0.3,
        pitch_correction_intensity=0.0,
        pitch_correction_key=SONG_KEY,
        pitch_correction_scale=SONG_SCALE,
    ),
    VocalSection(
        section_id="v2_p3",
        text="Noob Saibot ruft den Strat, Alle B, jetzt pushen! "
        "Kill O Zap, Deagle ready, Headshot durch die Büsche, "
        "Tobbisch sprüht die AK leer, der Smoke verzieht sich, "
        "Flexx0r wartet hinten, Scope, Zoom, Kopf, erledigt, sicher!",
        language=VocalLanguage.GERMAN,
        style=VocalStyle.RAP,
        singing=False,
        volume=0.9,
        gap_after_seconds=0.2,
        pitch_correction_intensity=0.0,
        pitch_correction_key=SONG_KEY,
        pitch_correction_scale=SONG_SCALE,
    ),
    VocalSection(
        section_id="chorus_2",
        text="Fire in the Hole! Power Terminators kommen rein, "
        "Dark Terrorists Server, cs_militia, de_aztec, alles mein! "
        "Fire in the Hole! AWP, AK, Deagle am Start, "
        "Frag um Frag um Frag, Power Terminators, hart! "
        "MONSTER KILL!",
        language=VocalLanguage.GERMAN,
        style=VocalStyle.SINGING,
        singing=True,
        volume=1.0,
        gap_after_seconds=0.5,
        pitch_correction_intensity=0.7,
        pitch_correction_key=SONG_KEY,
        pitch_correction_scale=SONG_SCALE,
    ),
    VocalSection(
        section_id="bridge",
        text="Die Server sind jetzt offline, "
        "kein Ping, kein Frag, kein Sound, "
        "Doch mach ich die Augen zu, "
        "hör ich Fire in the Hole, eine letzte Runde...",
        language=VocalLanguage.GERMAN,
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.75,
        gap_after_seconds=0.5,
        pitch_correction_intensity=0.5,
        pitch_correction_key=SONG_KEY,
        pitch_correction_scale=SONG_SCALE,
    ),
    VocalSection(
        section_id="final_chorus",
        text="FIRE IN THE HOLE! Power Terminators kommen rein! "
        "Dark Terrorists Server, Spassten, de_aztec ist mein! "
        "Noob Saibot! Kill O Zap! Tobbisch! Flexx0r! "
        "HEADSHOT! HEADSHOT! HEADSHOT! GAME OVER! "
        "MONSTER KILL!",
        language=VocalLanguage.GERMAN,
        style=VocalStyle.SHOUT,
        singing=True,
        volume=1.0,
        gap_after_seconds=0.3,
        pitch_correction_intensity=0.7,
        pitch_correction_key=SONG_KEY,
        pitch_correction_scale=SONG_SCALE,
    ),
    VocalSection(
        section_id="outro",
        text="Server disconnected. GG WP.",
        language=VocalLanguage.ENGLISH,
        style=VocalStyle.WHISPER,
        singing=False,
        volume=0.5,
        gap_after_seconds=0.0,
        pitch_correction_intensity=0.0,
        pitch_correction_key=SONG_KEY,
        pitch_correction_scale=SONG_SCALE,
    ),
]


# ═══════════════════════════════════════════════════════════════════
# Vocal + SFX placement (section_id → start_beat)
# ═══════════════════════════════════════════════════════════════════

VOCAL_PLACEMENT: Final[list[tuple[str, float]]] = [
    ("intro", 0.0),
    ("v1_p1", 8.0),
    ("v1_p2", 40.0),
    ("chorus_1", 72.0),
    ("v2_p1", 104.0),
    ("v2_p2", 136.0),
    ("v2_p3", 168.0),
    ("chorus_2", 200.0),
    ("bridge", 232.0),
    ("final_chorus", 248.0),
    ("outro", 280.0),
]

# SFX placement: (sfx_generator_func, start_beat, volume, pan_left_gain, pan_right_gain)
SFX_PLACEMENT: Final[list[tuple[object, float, float, float, float]]] = [
    # Intro
    (_synth_round_start, 0.0, 0.4, 0.7, 0.7),
    # Verse 1 — Kill O Zap Deagle
    (_synth_deagle, 22.0, 0.25, 0.4, 0.8),
    (_synth_headshot_dink, 22.5, 0.2, 0.5, 0.7),
    # Verse 1 — Tobbisch AK spray
    (_synth_ak_spray, 42.0, 0.2, 0.8, 0.4),
    # Verse 1 — Flexx0r AWP
    (_synth_awp_shot, 66.0, 0.3, 0.5, 0.5),
    (_synth_awp_reload, 67.0, 0.15, 0.5, 0.5),
    # Chorus 1 — MONSTER KILL at end
    (_synth_headshot_dink, 100.0, 0.15, 0.6, 0.6),
    # Verse 2 — Deagle + dink
    (_synth_deagle, 176.0, 0.2, 0.4, 0.8),
    (_synth_headshot_dink, 176.5, 0.18, 0.5, 0.7),
    # Verse 2 — AK spray
    (_synth_ak_spray, 182.0, 0.18, 0.8, 0.4),
    # Verse 2 — Flexx0r AWP
    (_synth_awp_shot, 190.0, 0.25, 0.5, 0.5),
    (_synth_awp_reload, 191.0, 0.12, 0.5, 0.5),
    # Bridge — Bomb plant (distant)
    (_synth_bomb_plant, 232.0, 0.1, 0.5, 0.5),
    # Final Chorus — All weapons
    (_synth_awp_shot, 268.0, 0.3, 0.5, 0.5),
    (_synth_deagle, 269.0, 0.25, 0.4, 0.8),
    (_synth_ak_spray, 270.0, 0.2, 0.8, 0.4),
    (_synth_headshot_dink, 271.0, 0.2, 0.6, 0.6),
    (_synth_headshot_dink, 272.0, 0.2, 0.5, 0.7),
    (_synth_headshot_dink, 273.0, 0.2, 0.7, 0.5),
    # Outro — reversed round start (just a quiet beep)
    (_synth_round_start, 282.0, 0.15, 0.5, 0.5),
]


# ═══════════════════════════════════════════════════════════════════
# SFX rendering
# ═══════════════════════════════════════════════════════════════════


def _render_sfx_layer(
    total_samples: int,
) -> tuple[list[float], list[float]]:
    """Render all SFX into a stereo layer at beat-synced positions."""
    left: list[float] = [0.0] * total_samples
    right: list[float] = [0.0] * total_samples

    for sfx_func, beat, volume, l_gain, r_gain in SFX_PLACEMENT:
        samples = sfx_func()
        start = int(beat * SECONDS_PER_BEAT * SAMPLE_RATE)
        for i, s in enumerate(samples):
            pos = start + i
            if 0 <= pos < total_samples:
                left[pos] += s * volume * l_gain
                right[pos] += s * volume * r_gain

    print(f"   🔫 Rendered {len(SFX_PLACEMENT)} SFX events into stereo layer")
    return left, right


# ═══════════════════════════════════════════════════════════════════
# Main Generation Pipeline
# ═══════════════════════════════════════════════════════════════════


def main() -> None:
    """Generate the complete 'Fire in the Hole' track.

    Pipeline:
        1. Render stereo instrumental
        2. Generate vocals via Bark (multi-take + pitch correction)
        3. Render SFX layer (synthesized game sounds)
        4. Apply ducking to instrumental
        5. Overlay vocals + SFX onto ducked instrumental
        6. Normalize and master to MP3
    """
    start_time = time.time()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(f"  🔫 Generating: {SONG_TITLE}")
    print(f"  🎵 BPM: {SONG_BPM} | Key: {SONG_KEY} {SONG_SCALE}")
    print(f"  🎮 Style: Boom-Bap | Server: Dark Terrorists")
    print("=" * 60)

    # ── Step 1: Render stereo instrumental ──
    print("\n📻 Step 1: Rendering stereo instrumental...")
    arrangement = build_arrangement()
    inst_left, inst_right = render_arrangement(arrangement)
    total_samples = max(len(inst_left), len(inst_right))
    print(f"   ✅ Instrumental: {total_samples / SAMPLE_RATE:.1f}s (stereo)")

    # ── Step 2: Generate vocals via Bark ──
    print("\n🎤 Step 2: Generating vocals with Bark AI...")
    print(f"   ⏳ {len(VOCALS)} sections × 3 takes each...")
    engine = BarkVocalEngine()
    engine.preload_models()
    generated_vocals = engine.generate_vocals(VOCALS)
    engine.cleanup()
    print(f"   ✅ Generated {len(generated_vocals)} vocal sections")

    # ── Step 3: Render SFX layer ──
    print("\n🔫 Step 3: Rendering game SFX layer...")
    sfx_left, sfx_right = _render_sfx_layer(total_samples)

    # ── Step 4: Apply ducking to instrumental ──
    print("\n📉 Step 4: Applying vocal-instrumental ducking...")
    vocal_durations = calculate_vocal_durations(generated_vocals)
    vocal_placement_seconds: list[tuple[str, float]] = [
        (sid, beat * SECONDS_PER_BEAT) for sid, beat in VOCAL_PLACEMENT
    ]
    ducked_left, ducked_right = apply_ducking(
        inst_left, inst_right,
        vocal_placement_seconds, vocal_durations,
        reduction_db=-3.0, attack_seconds=0.05, release_seconds=0.2,
    )

    # ── Step 5: Overlay SFX onto ducked instrumental ──
    print("\n🎚️  Step 5: Mixing SFX + vocals onto ducked instrumental...")
    overlay_onto(ducked_left, ducked_right, sfx_left, sfx_right, 0)

    vocal_lookup = {v.section_id: v for v in generated_vocals}
    for section_id, start_beat in VOCAL_PLACEMENT:
        vocal = vocal_lookup.get(section_id)
        if vocal is None:
            print(f"   ⚠️  Missing vocal: {section_id}")
            continue
        start_sample = int(start_beat * SECONDS_PER_BEAT * SAMPLE_RATE)
        scaled = [s * vocal.volume for s in vocal.samples]
        overlay_onto(ducked_left, ducked_right, scaled, scaled, start_sample)
        dur = len(vocal.samples) / SAMPLE_RATE
        print(f"   🎤 {section_id}: beat {start_beat:.0f} ({dur:.1f}s)")

    # ── Step 6: Normalize and master ──
    print("\n💿 Step 6: Normalizing and mastering to MP3...")
    ducked_left, ducked_right = normalize_stereo(ducked_left, ducked_right, 0.95)
    mixed_wav = str(OUTPUT_DIR / f"{OUTPUT_NAME}_mixed.wav")
    write_stereo_wav(mixed_wav, ducked_left, ducked_right)
    mp3_path = str(OUTPUT_DIR / f"{OUTPUT_NAME}.mp3")
    master_to_mp3(mixed_wav, mp3_path, target_lufs=-14.0, stereo_width=1.2)

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"  ✅ DONE: {mp3_path}")
    print(f"  ⏱️  Total time: {elapsed / 60:.1f} minutes")
    print(f"  🎵 Duration: {total_samples / SAMPLE_RATE:.1f}s")
    print(f"{'=' * 60}")
    print(f"\n  🎧 Play {mp3_path} to hear the result!")


if __name__ == "__main__":
    main()

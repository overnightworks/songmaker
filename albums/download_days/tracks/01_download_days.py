"""Track 01: Download Days — 90s Punk Rock Anthem (Offspring/Green Day Style).

A nostalgic punk rock tribute to the days of 56K modems, Napster downloads,
LAN parties, Counter-Strike, biking through Erlangen, and a friendship
that's indestructible. Features quiet-loud dynamics à la Nirvana.

Produced by Flex0r for MC Tobbisch.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Final

from bark_engine import (
    BarkVocalEngine,
    VocalSection,
    VocalStyle,
    normalize_audio,
    overlay_audio,
    write_wav_file,
)
from bark_engine import (
    master_to_mp3 as vocal_master_to_mp3,
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
    render_arrangement,
)
from instrumental_engine.mixer import (
    stereo_to_mono,
    write_mono_wav,
)

# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════

SONG_TITLE: Final[str] = "Download Days"
SONG_BPM: Final[int] = 175
OUTPUT_DIR: Final[Path] = Path("albums/download_days/output")
OUTPUT_NAME: Final[str] = "01_Download_Days"

# Power chord MIDI definitions (root + fifth)
E5: Final[tuple[int, ...]] = (40, 47)  # E2 + B2
C5: Final[tuple[int, ...]] = (48, 55)  # C3 + G3
G5: Final[tuple[int, ...]] = (43, 50)  # G2 + D3
D5: Final[tuple[int, ...]] = (50, 57)  # D3 + A3

# Bass root notes
BASS_E: Final[int] = 40  # E2
BASS_C: Final[int] = 36  # C2
BASS_G: Final[int] = 43  # G2
BASS_D: Final[int] = 38  # D2


# ═══════════════════════════════════════════════════════════════════
# Punk drum pattern (faster, more aggressive than basic_rock)
# ═══════════════════════════════════════════════════════════════════


def _build_punk_beat() -> DrumPattern:
    """Fast punk rock beat: driving kick, snappy snare, relentless hihats."""
    hits: list[DrumHit] = []
    # Kick on 1, 2.5, 3
    for beat in (0.0, 1.5, 2.0):
        hits.append(DrumHit(DrumSound.KICK, 0.9, beat))
    # Snare on 2 and 4
    for beat in (1.0, 3.0):
        hits.append(DrumHit(DrumSound.SNARE, 0.85, beat))
    # Constant 8th-note hihats
    for eighth in range(8):
        vel = 0.45 if eighth % 2 == 0 else 0.3
        hits.append(DrumHit(DrumSound.CLOSED_HIHAT, vel, eighth * 0.5))
    return DrumPattern("punk_beat", tuple(hits), 4.0)


def _build_bridge_beat() -> DrumPattern:
    """Quiet bridge beat: sparse, reflective."""
    hits: list[DrumHit] = []
    hits.append(DrumHit(DrumSound.KICK, 0.4, 0.0))
    hits.append(DrumHit(DrumSound.SNARE, 0.3, 2.0))
    for beat in (0.0, 1.0, 2.0, 3.0):
        hits.append(DrumHit(DrumSound.RIDE, 0.2, beat))
    return DrumPattern("bridge_beat", tuple(hits), 4.0)


PUNK_BEAT: Final[DrumPattern] = _build_punk_beat()
BRIDGE_BEAT: Final[DrumPattern] = _build_bridge_beat()


# ═══════════════════════════════════════════════════════════════════
# Chord patterns (reusable building blocks)
# ═══════════════════════════════════════════════════════════════════


def _power_chord(notes: tuple[int, ...], beats: float, vel: float = 0.85) -> Chord:
    """Create a power chord."""
    return Chord(notes=notes, velocity=vel, duration_beats=beats)


def _bass_note(midi: int, beats: float, vel: float = 0.7) -> Note:
    """Create a bass note."""
    return Note(midi=midi, velocity=vel, duration_beats=beats)


def _palm_mute_bar() -> tuple[Chord, ...]:
    """One bar of palm-muted E5 eighth notes."""
    return tuple(_power_chord(E5, 0.5, vel=0.6) for _ in range(8))


def _verse_progression() -> tuple[Chord, ...]:
    """E5 - C5 - G5 - D5, each 4 beats (1 bar each, 4 bars total)."""
    return (
        _power_chord(E5, 4.0),
        _power_chord(C5, 4.0),
        _power_chord(G5, 4.0),
        _power_chord(D5, 4.0),
    )


def _chorus_progression() -> tuple[Chord, ...]:
    """Chorus: C5 - G5 - D5 - E5, driving and higher energy."""
    return (
        _power_chord(C5, 4.0, vel=0.95),
        _power_chord(G5, 4.0, vel=0.95),
        _power_chord(D5, 4.0, vel=0.95),
        _power_chord(E5, 4.0, vel=0.95),
    )


def _bass_verse() -> tuple[Note, ...]:
    """Bass following verse root notes with rhythmic pattern."""
    result: list[Note] = []
    for midi in (BASS_E, BASS_C, BASS_G, BASS_D):
        result.extend(
            [
                _bass_note(midi, 1.0, 0.75),
                _bass_note(midi, 1.0, 0.6),
                _bass_note(midi, 0.5, 0.7),
                _bass_note(midi, 0.5, 0.5),
                _bass_note(midi, 1.0, 0.65),
            ]
        )
    return tuple(result)


def _bass_chorus() -> tuple[Note, ...]:
    """Bass following chorus root notes, driving 8ths."""
    result: list[Note] = []
    for midi in (BASS_C, BASS_G, BASS_D, BASS_E):
        result.extend([_bass_note(midi, 0.5, 0.8) for _ in range(8)])
    return tuple(result)


# ═══════════════════════════════════════════════════════════════════
# Arrangement Definition
# ═══════════════════════════════════════════════════════════════════


def build_arrangement() -> Arrangement:
    """Build the complete 'Download Days' punk arrangement."""
    current_beat = 0.0
    sections: list[SongSection] = []

    # --- INTRO: 16 beats (palm mute buildup) ---
    sections.append(
        SongSection(
            section_type=SectionType.INTRO,
            start_beat=current_beat,
            length_beats=16.0,
            bpm=SONG_BPM,
            tracks=(
                InstrumentTrack(
                    name="palm_mute",
                    instrument_id="palm_mute_guitar",
                    events=_palm_mute_bar() * 4,
                    volume=0.5,
                    pan=PanPosition.CENTER,
                ),
            ),
            drum_pattern=DrumPattern(
                "count_in",
                (
                    DrumHit(DrumSound.CLOSED_HIHAT, 0.6, 0.0),
                    DrumHit(DrumSound.CLOSED_HIHAT, 0.6, 1.0),
                    DrumHit(DrumSound.CLOSED_HIHAT, 0.6, 2.0),
                    DrumHit(DrumSound.CLOSED_HIHAT, 0.6, 3.0),
                ),
                4.0,
            ),
            label="Intro — Count in + Palm Mute",
        )
    )
    current_beat += 16.0

    # --- VERSE 1: 64 beats (2 stanzas × 16 beats each, repeated progression) ---
    sections.append(
        SongSection(
            section_type=SectionType.VERSE,
            start_beat=current_beat,
            length_beats=64.0,
            bpm=SONG_BPM,
            tracks=(
                InstrumentTrack(
                    name="rhythm_guitar",
                    instrument_id="distorted_guitar",
                    events=_verse_progression() * 4,
                    volume=0.55,
                    pan=PanPosition.LEFT,
                ),
                InstrumentTrack(
                    name="rhythm_guitar_r",
                    instrument_id="distorted_guitar",
                    events=_verse_progression() * 4,
                    volume=0.55,
                    pan=PanPosition.RIGHT,
                ),
                InstrumentTrack(
                    name="bass",
                    instrument_id="sub_bass",
                    events=_bass_verse() * 4,
                    volume=0.5,
                    pan=PanPosition.CENTER,
                ),
            ),
            drum_pattern=PUNK_BEAT,
            label="Verse 1",
        )
    )
    current_beat += 64.0

    # --- CHORUS 1: 32 beats ---
    sections.append(
        SongSection(
            section_type=SectionType.CHORUS,
            start_beat=current_beat,
            length_beats=32.0,
            bpm=SONG_BPM,
            tracks=(
                InstrumentTrack(
                    name="power_guitar_l",
                    instrument_id="power_guitar",
                    events=_chorus_progression() * 2,
                    volume=0.65,
                    pan=PanPosition.LEFT,
                ),
                InstrumentTrack(
                    name="power_guitar_r",
                    instrument_id="power_guitar",
                    events=_chorus_progression() * 2,
                    volume=0.65,
                    pan=PanPosition.RIGHT,
                ),
                InstrumentTrack(
                    name="bass",
                    instrument_id="sub_bass",
                    events=_bass_chorus() * 2,
                    volume=0.55,
                    pan=PanPosition.CENTER,
                ),
            ),
            drum_pattern=PUNK_BEAT,
            label="Chorus 1 — Those were the download days!",
        )
    )
    current_beat += 32.0

    # --- VERSE 2: 64 beats ---
    sections.append(
        SongSection(
            section_type=SectionType.VERSE,
            start_beat=current_beat,
            length_beats=64.0,
            bpm=SONG_BPM,
            tracks=(
                InstrumentTrack(
                    name="rhythm_guitar",
                    instrument_id="distorted_guitar",
                    events=_verse_progression() * 4,
                    volume=0.55,
                    pan=PanPosition.LEFT,
                ),
                InstrumentTrack(
                    name="rhythm_guitar_r",
                    instrument_id="distorted_guitar",
                    events=_verse_progression() * 4,
                    volume=0.55,
                    pan=PanPosition.RIGHT,
                ),
                InstrumentTrack(
                    name="bass",
                    instrument_id="sub_bass",
                    events=_bass_verse() * 4,
                    volume=0.5,
                    pan=PanPosition.CENTER,
                ),
            ),
            drum_pattern=PUNK_BEAT,
            label="Verse 2 — LAN party + bikes",
        )
    )
    current_beat += 64.0

    # --- CHORUS 2: 32 beats ---
    sections.append(
        SongSection(
            section_type=SectionType.CHORUS,
            start_beat=current_beat,
            length_beats=32.0,
            bpm=SONG_BPM,
            tracks=(
                InstrumentTrack(
                    name="power_guitar_l",
                    instrument_id="power_guitar",
                    events=_chorus_progression() * 2,
                    volume=0.65,
                    pan=PanPosition.LEFT,
                ),
                InstrumentTrack(
                    name="power_guitar_r",
                    instrument_id="power_guitar",
                    events=_chorus_progression() * 2,
                    volume=0.65,
                    pan=PanPosition.RIGHT,
                ),
                InstrumentTrack(
                    name="bass",
                    instrument_id="sub_bass",
                    events=_bass_chorus() * 2,
                    volume=0.55,
                    pan=PanPosition.CENTER,
                ),
            ),
            drum_pattern=PUNK_BEAT,
            label="Chorus 2",
        )
    )
    current_beat += 32.0

    # --- BRIDGE: 32 beats (quiet, clean guitar, Nirvana dynamics) ---
    bridge_chords = (
        Chord(notes=(40, 44, 47), velocity=0.35, duration_beats=8.0),  # Em
        Chord(notes=(48, 52, 55), velocity=0.3, duration_beats=8.0),  # C
        Chord(notes=(43, 47, 50), velocity=0.3, duration_beats=8.0),  # G
        Chord(notes=(50, 54, 57), velocity=0.35, duration_beats=8.0),  # D
    )
    sections.append(
        SongSection(
            section_type=SectionType.BRIDGE,
            start_beat=current_beat,
            length_beats=32.0,
            bpm=SONG_BPM,
            tracks=(
                InstrumentTrack(
                    name="clean_guitar",
                    instrument_id="pluck",
                    events=bridge_chords,
                    volume=0.3,
                    pan=PanPosition.CENTER,
                ),
            ),
            drum_pattern=BRIDGE_BEAT,
            label="Bridge — Quiet moment (Nintendo + Turnerbund)",
        )
    )
    current_beat += 32.0

    # --- SILENCE: 4 beats (the dramatic pause) ---
    sections.append(
        SongSection(
            section_type=SectionType.BREAKDOWN,
            start_beat=current_beat,
            length_beats=4.0,
            bpm=SONG_BPM,
            tracks=(),
            label="Silence — The tension before the explosion",
        )
    )
    current_beat += 4.0

    # --- FINAL CHORUS x2: 64 beats (everything cranked) ---
    sections.append(
        SongSection(
            section_type=SectionType.CHORUS,
            start_beat=current_beat,
            length_beats=64.0,
            bpm=SONG_BPM,
            tracks=(
                InstrumentTrack(
                    name="power_guitar_l",
                    instrument_id="power_guitar",
                    events=_chorus_progression() * 4,
                    volume=0.7,
                    pan=PanPosition.LEFT,
                ),
                InstrumentTrack(
                    name="power_guitar_r",
                    instrument_id="power_guitar",
                    events=_chorus_progression() * 4,
                    volume=0.7,
                    pan=PanPosition.RIGHT,
                ),
                InstrumentTrack(
                    name="bass",
                    instrument_id="808_bass",
                    events=_bass_chorus() * 4,
                    volume=0.6,
                    pan=PanPosition.CENTER,
                ),
                InstrumentTrack(
                    name="lead_hook",
                    instrument_id="synth_lead_saw",
                    events=(
                        Note(midi=72, velocity=0.5, duration_beats=2.0),
                        Note(midi=67, velocity=0.45, duration_beats=2.0),
                        Note(midi=74, velocity=0.5, duration_beats=2.0),
                        Note(midi=71, velocity=0.45, duration_beats=2.0),
                        Rest(duration_beats=8.0),
                    )
                    * 4,
                    volume=0.25,
                    pan=PanPosition.CENTER_RIGHT,
                ),
            ),
            drum_pattern=DrumPattern(
                "punk_crash",
                (
                    *PUNK_BEAT.hits,
                    DrumHit(DrumSound.CRASH, 0.7, 0.0),
                ),
                4.0,
            ),
            label="FINAL CHORUS x2 — FULL EXPLOSION",
        )
    )
    current_beat += 64.0

    # --- OUTRO: 16 beats (last chord ringing) ---
    sections.append(
        SongSection(
            section_type=SectionType.OUTRO,
            start_beat=current_beat,
            length_beats=16.0,
            bpm=SONG_BPM,
            tracks=(
                InstrumentTrack(
                    name="final_chord",
                    instrument_id="power_guitar",
                    events=(
                        _power_chord(E5, 12.0, vel=0.9),
                        Rest(duration_beats=4.0),
                    ),
                    volume=0.6,
                    pan=PanPosition.CENTER,
                ),
            ),
            drum_pattern=DrumPattern(
                "final_crash",
                (DrumHit(DrumSound.CRASH, 0.9, 0.0),),
                16.0,
            ),
            label="Outro — Last chord rings out",
        )
    )

    return Arrangement(
        title=SONG_TITLE,
        default_bpm=SONG_BPM,
        sections=tuple(sections),
    )


# ═══════════════════════════════════════════════════════════════════
# Vocal Definitions
# ═══════════════════════════════════════════════════════════════════

VOCALS: Final[list[VocalSection]] = [
    # Intro shout
    VocalSection(
        section_id="intro_count",
        text="One, two, three, four!",
        language=VocalLanguage.ENGLISH,
        style=VocalStyle.SHOUT,
        singing=False,
        volume=0.9,
        gap_after_seconds=0.0,
    ),
    # Verse 1, Stanza 1
    VocalSection(
        section_id="v1_s1",
        text="Sittin' at the screen, fifty-six-K, "
        "Napster running hot, downloading all day, "
        "Offspring, Nirvana, Green Day on repeat, "
        "Cold beer on the desk, sneakers on our feet!",
        language=VocalLanguage.ENGLISH,
        style=VocalStyle.SHOUT,
        singing=True,
        volume=0.85,
        gap_after_seconds=0.3,
    ),
    # Verse 1, Stanza 2
    VocalSection(
        section_id="v1_s2",
        text="Three AM, the modem's still alive, "
        "We don't need no sleep to feel this vibe, "
        "Hit refresh, hit play, hit download more, "
        "This is what we're living for!",
        language=VocalLanguage.ENGLISH,
        style=VocalStyle.SHOUT,
        singing=True,
        volume=0.85,
        gap_after_seconds=0.2,
    ),
    # Chorus 1
    VocalSection(
        section_id="chorus_1",
        text="Those were the download days! "
        "Before the world went sideways, before the haze! "
        "We didn't need a plan, we didn't need a stage, "
        "Just you and me and a stolen MP3! "
        "Those were the download days!",
        language=VocalLanguage.ENGLISH,
        style=VocalStyle.SHOUT,
        singing=True,
        volume=1.0,
        gap_after_seconds=0.3,
    ),
    # Verse 2, Stanza 1
    VocalSection(
        section_id="v2_s1",
        text="LAN party weekend, cables on the floor, "
        "Counter-Strike till sunrise, headshots by the score, "
        "Fire in the hole! Pizza getting cold, "
        "Stories from those nights that never get old!",
        language=VocalLanguage.ENGLISH,
        style=VocalStyle.SHOUT,
        singing=True,
        volume=0.85,
        gap_after_seconds=0.3,
    ),
    # Verse 2, Stanza 2
    VocalSection(
        section_id="v2_s2",
        text="Hop on the bikes when the morning breaks, "
        "Through Erlangen singing, making no mistakes, "
        "Well maybe every word was slightly wrong, "
        "But that's the beauty of a drunken song!",
        language=VocalLanguage.ENGLISH,
        style=VocalStyle.SHOUT,
        singing=True,
        volume=0.85,
        gap_after_seconds=0.2,
    ),
    # Chorus 2
    VocalSection(
        section_id="chorus_2",
        text="Those were the download days! "
        "Before the world went sideways, before the haze! "
        "We didn't need a plan, we didn't need a stage, "
        "Just you and me and a stolen MP3! "
        "Those were the download days!",
        language=VocalLanguage.ENGLISH,
        style=VocalStyle.SHOUT,
        singing=True,
        volume=1.0,
        gap_after_seconds=0.5,
    ),
    # Bridge (quiet, vulnerable)
    VocalSection(
        section_id="bridge",
        text="David on the couch, controllers in our hands, "
        "Wrestling on Nintendo, making stupid plans, "
        "Then you'd watch me run at Turnerbund all day, "
        "Cracking jokes from the sideline, making it okay...",
        language=VocalLanguage.ENGLISH,
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.7,
        gap_after_seconds=1.0,
    ),
    # Final Chorus (SCREAMING)
    VocalSection(
        section_id="final_chorus_1",
        text="THOSE WERE THE DOWNLOAD DAYS! "
        "Before the world went sideways, before the haze! "
        "We didn't need a plan, we didn't need a stage, "
        "Just you and me and a stolen MP3!",
        language=VocalLanguage.ENGLISH,
        style=VocalStyle.SHOUT,
        singing=True,
        volume=1.0,
        gap_after_seconds=0.2,
    ),
    # Final section
    VocalSection(
        section_id="final_chorus_2",
        text="And I don't care what the years will say, "
        "We'll always have those download days!",
        language=VocalLanguage.ENGLISH,
        style=VocalStyle.SHOUT,
        singing=True,
        volume=1.0,
        gap_after_seconds=0.5,
    ),
    # Outro
    VocalSection(
        section_id="outro",
        text="Those were the days... the download days...",
        language=VocalLanguage.ENGLISH,
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.6,
        gap_after_seconds=0.0,
    ),
]


# ═══════════════════════════════════════════════════════════════════
# Section timing map (beat → vocal section mapping)
# ═══════════════════════════════════════════════════════════════════

SECONDS_PER_BEAT: Final[float] = 60.0 / SONG_BPM

# (vocal_section_id, start_beat)
VOCAL_PLACEMENT: Final[list[tuple[str, float]]] = [
    ("intro_count", 0.0),
    ("v1_s1", 16.0),
    ("v1_s2", 48.0),
    ("chorus_1", 80.0),
    ("v2_s1", 112.0),
    ("v2_s2", 144.0),
    ("chorus_2", 176.0),
    ("bridge", 208.0),
    ("final_chorus_1", 244.0),
    ("final_chorus_2", 276.0),
    ("outro", 308.0),
]


# ═══════════════════════════════════════════════════════════════════
# Main Generation Pipeline
# ═══════════════════════════════════════════════════════════════════


def main() -> None:
    """Generate the complete 'Download Days' track."""
    start_time = time.time()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(f"  🎸 Generating: {SONG_TITLE}")
    print(f"  🎵 BPM: {SONG_BPM} | Style: Punk Rock")
    print("=" * 60)

    # ── Step 1: Render instrumental ──
    print("\n📻 Step 1: Rendering instrumental...")
    arrangement = build_arrangement()
    instrumental_left, instrumental_right = render_arrangement(arrangement)
    instrumental_mono = stereo_to_mono(instrumental_left, instrumental_right)
    instrumental_wav = str(OUTPUT_DIR / f"{OUTPUT_NAME}_instrumental.wav")
    write_mono_wav(instrumental_wav, instrumental_mono)
    inst_duration = len(instrumental_mono) / SAMPLE_RATE
    print(f"   ✅ Instrumental: {inst_duration:.1f}s")

    # ── Step 2: Generate vocals via Bark ──
    print("\n🎤 Step 2: Generating vocals with Bark AI...")
    print("   ⏳ This will take 10-20 minutes on CPU...")
    engine = BarkVocalEngine()
    engine.preload_models()
    generated_vocals = engine.generate_vocals(VOCALS)
    engine.cleanup()

    # ── Step 3: Mix vocals onto instrumental ──
    print("\n🎚️  Step 3: Mixing vocals onto instrumental...")
    vocal_lookup = {v.section_id: v for v in generated_vocals}
    mixed = list(instrumental_mono)

    for section_id, start_beat in VOCAL_PLACEMENT:
        vocal = vocal_lookup.get(section_id)
        if vocal is None:
            print(f"   ⚠️  Missing vocal: {section_id}")
            continue

        start_sample = int(start_beat * SECONDS_PER_BEAT * SAMPLE_RATE)
        scaled = [s * vocal.volume for s in vocal.samples]
        overlay_audio(mixed, scaled, start_sample)
        vocal_dur = len(vocal.samples) / SAMPLE_RATE
        print(f"   🎤 {section_id}: placed at beat {start_beat:.0f} ({vocal_dur:.1f}s)")

    # ── Step 4: Normalize and master ──
    print("\n💿 Step 4: Mastering to MP3...")
    mixed = normalize_audio(mixed, 0.95)
    mixed_wav = str(OUTPUT_DIR / f"{OUTPUT_NAME}_mixed.wav")
    write_wav_file(mixed_wav, mixed)

    mp3_path = str(OUTPUT_DIR / f"{OUTPUT_NAME}.mp3")
    vocal_master_to_mp3(mixed_wav, mp3_path)

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"  ✅ DONE: {mp3_path}")
    print(f"  ⏱️  Total time: {elapsed / 60:.1f} minutes")
    print(f"  🎵 Duration: {len(mixed) / SAMPLE_RATE:.1f}s")
    print(f"{'=' * 60}")
    print(f"\n  🎧 Play {mp3_path} to hear the result!")


if __name__ == "__main__":
    main()

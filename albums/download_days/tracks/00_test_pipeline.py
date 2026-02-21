"""Pipeline test: ~15 second mini-track to verify vocals + instrumentals.

Generates a short verse + chorus snippet with Bark vocals and DSP backing.
Quick smoke test — should complete in 2-5 minutes on GPU.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Final

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

from bark_engine import (
    BarkVocalEngine,
    VocalSection,
    VocalStyle,
    normalize_audio,
    overlay_audio,
    write_wav_file,
)
from bark_engine import master_to_mp3 as vocal_master_to_mp3
from bark_engine.models import VocalLanguage
from instrumental_engine import (
    SAMPLE_RATE,
    Arrangement,
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
from instrumental_engine.mixer import stereo_to_mono, write_mono_wav

SONG_TITLE: Final[str] = "Pipeline Test"
SONG_BPM: Final[int] = 140
OUTPUT_DIR: Final[Path] = Path("albums/download_days/output")
OUTPUT_NAME: Final[str] = "00_Pipeline_Test"

# Simple chord MIDI notes
C_CHORD: Final[tuple[int, ...]] = (48, 52, 55)  # C3 E3 G3
G_CHORD: Final[tuple[int, ...]] = (43, 47, 50)  # G2 B2 D3
AM_CHORD: Final[tuple[int, ...]] = (45, 48, 52)  # A2 C3 E3
F_CHORD: Final[tuple[int, ...]] = (41, 45, 48)   # F2 A2 C3


def _basic_beat() -> DrumPattern:
    """Simple rock beat: kick-snare pattern with hihats."""
    hits: list[DrumHit] = []
    for beat in (0.0, 2.0):
        hits.append(DrumHit(DrumSound.KICK, 0.85, beat))
    for beat in (1.0, 3.0):
        hits.append(DrumHit(DrumSound.SNARE, 0.8, beat))
    for i in range(8):
        hits.append(DrumHit(DrumSound.CLOSED_HIHAT, 0.5, i * 0.5))
    return DrumPattern("basic_rock", tuple(hits), 4.0)


BEAT = _basic_beat()


def build_arrangement() -> Arrangement:
    """Build a minimal 2-section arrangement (~15 seconds at 140 BPM)."""
    sections: list[SongSection] = []

    # 8 beats of verse (~3.4s)
    sections.append(
        SongSection(
            section_type=SectionType.VERSE,
            start_beat=0.0,
            length_beats=8.0,
            bpm=SONG_BPM,
            tracks=(
                InstrumentTrack(
                    name="pad",
                    instrument_id="pad",
                    events=(
                        Note(midi=48, velocity=0.5, duration_beats=4.0),
                        Note(midi=43, velocity=0.5, duration_beats=4.0),
                    ),
                    volume=0.4,
                    pan=PanPosition.CENTER,
                ),
                InstrumentTrack(
                    name="bass",
                    instrument_id="sub_bass",
                    events=(
                        Note(midi=36, velocity=0.7, duration_beats=2.0),
                        Rest(duration_beats=2.0),
                        Note(midi=31, velocity=0.7, duration_beats=2.0),
                        Rest(duration_beats=2.0),
                    ),
                    volume=0.5,
                    pan=PanPosition.CENTER,
                ),
            ),
            drum_pattern=BEAT,
            label="Verse snippet",
        )
    )

    # 16 beats of chorus (~6.9s)
    sections.append(
        SongSection(
            section_type=SectionType.CHORUS,
            start_beat=8.0,
            length_beats=16.0,
            bpm=SONG_BPM,
            tracks=(
                InstrumentTrack(
                    name="chords_l",
                    instrument_id="supersaw",
                    events=(
                        Note(midi=48, velocity=0.6, duration_beats=4.0),
                        Note(midi=43, velocity=0.6, duration_beats=4.0),
                        Note(midi=45, velocity=0.6, duration_beats=4.0),
                        Note(midi=41, velocity=0.6, duration_beats=4.0),
                    ),
                    volume=0.45,
                    pan=PanPosition.LEFT,
                ),
                InstrumentTrack(
                    name="chords_r",
                    instrument_id="supersaw",
                    events=(
                        Note(midi=55, velocity=0.6, duration_beats=4.0),
                        Note(midi=50, velocity=0.6, duration_beats=4.0),
                        Note(midi=52, velocity=0.6, duration_beats=4.0),
                        Note(midi=48, velocity=0.6, duration_beats=4.0),
                    ),
                    volume=0.45,
                    pan=PanPosition.RIGHT,
                ),
                InstrumentTrack(
                    name="bass",
                    instrument_id="sub_bass",
                    events=(
                        Note(midi=36, velocity=0.8, duration_beats=2.0),
                        Rest(duration_beats=2.0),
                        Note(midi=31, velocity=0.8, duration_beats=2.0),
                        Rest(duration_beats=2.0),
                    ) * 2,
                    volume=0.55,
                    pan=PanPosition.CENTER,
                ),
            ),
            drum_pattern=DrumPattern(
                "chorus_beat",
                (*BEAT.hits, DrumHit(DrumSound.CRASH, 0.7, 0.0)),
                4.0,
            ),
            label="Chorus snippet",
        )
    )

    # 4 beats of silence (outro tail)
    sections.append(
        SongSection(
            section_type=SectionType.OUTRO,
            start_beat=24.0,
            length_beats=4.0,
            bpm=SONG_BPM,
            tracks=(),
            drum_pattern=DrumPattern("silence", (), 4.0),
            label="Tail",
        )
    )

    return Arrangement(
        title=SONG_TITLE,
        default_bpm=SONG_BPM,
        sections=tuple(sections),
    )


# Two short vocal sections
VOCALS: Final[list[VocalSection]] = [
    VocalSection(
        section_id="verse_line",
        text="Testing one two three, can you hear me now?",
        language=VocalLanguage.ENGLISH,
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.85,
        gap_after_seconds=0.0,
    ),
    VocalSection(
        section_id="chorus_line",
        text="This is the pipeline test! Everything is sounding fresh!",
        language=VocalLanguage.ENGLISH,
        style=VocalStyle.SHOUT,
        singing=True,
        volume=1.0,
        gap_after_seconds=0.0,
    ),
]

SECONDS_PER_BEAT: Final[float] = 60.0 / SONG_BPM

VOCAL_PLACEMENT: Final[list[tuple[str, float]]] = [
    ("verse_line", 0.0),
    ("chorus_line", 8.0),
]


def main() -> None:
    """Generate the pipeline test track."""
    start_time = time.time()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(f"  Pipeline Test — {SONG_BPM} BPM, ~15 seconds")
    print("=" * 60)

    # Step 1: Instrumental
    print("\n  Step 1: Rendering instrumental...")
    arrangement = build_arrangement()
    instrumental_left, instrumental_right = render_arrangement(arrangement)
    instrumental_mono = stereo_to_mono(instrumental_left, instrumental_right)
    instrumental_wav = str(OUTPUT_DIR / f"{OUTPUT_NAME}_instrumental.wav")
    write_mono_wav(instrumental_wav, instrumental_mono)
    inst_duration = len(instrumental_mono) / SAMPLE_RATE
    print(f"   Done: {inst_duration:.1f}s")

    # Step 2: Vocals
    print("\n  Step 2: Generating vocals with Bark AI...")
    engine = BarkVocalEngine()
    engine.preload_models()
    generated_vocals = engine.generate_vocals(VOCALS)
    engine.cleanup()

    # Step 3: Mix
    print("\n  Step 3: Mixing...")
    vocal_lookup = {v.section_id: v for v in generated_vocals}
    mixed = list(instrumental_mono)

    for section_id, start_beat in VOCAL_PLACEMENT:
        vocal = vocal_lookup.get(section_id)
        if vocal is None:
            print(f"   Missing vocal: {section_id}")
            continue
        start_sample = int(start_beat * SECONDS_PER_BEAT * SAMPLE_RATE)
        scaled = [s * vocal.volume for s in vocal.samples]
        overlay_audio(mixed, scaled, start_sample)
        vocal_dur = len(vocal.samples) / SAMPLE_RATE
        print(f"   {section_id}: beat {start_beat:.0f} ({vocal_dur:.1f}s)")

    # Step 4: Master
    print("\n  Step 4: Mastering...")
    mixed = normalize_audio(mixed, 0.95)
    mixed_wav = str(OUTPUT_DIR / f"{OUTPUT_NAME}_mixed.wav")
    write_wav_file(mixed_wav, mixed)

    mp3_path = str(OUTPUT_DIR / f"{OUTPUT_NAME}.mp3")
    vocal_master_to_mp3(mixed_wav, mp3_path)

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"  Done: {mp3_path}")
    print(f"  Time: {elapsed:.0f}s | Duration: {len(mixed) / SAMPLE_RATE:.1f}s")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()

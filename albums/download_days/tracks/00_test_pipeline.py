"""Pipeline test: singing voice quality check.

Slow ballad with female Bark voice (speaker_index=1), minimal backing.
Focus: hear the raw singing quality with pitch correction.

Run: .venv\Scripts\python albums\download_days\tracks\00_test_pipeline.py
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
    InstrumentTrack,
    Note,
    PanPosition,
    Rest,
    SectionType,
    SongSection,
    render_arrangement,
)
from instrumental_engine.mixer import stereo_to_mono, write_mono_wav

SONG_TITLE: Final[str] = "Voice Test Ballad"
SONG_BPM: Final[int] = 72  # Slow ballad tempo
OUTPUT_DIR: Final[Path] = Path("_output/download_days")
OUTPUT_NAME: Final[str] = "00_Voice_Test"


def build_arrangement() -> Arrangement:
    """Minimal piano + strings backing for vocal test."""
    sections: list[SongSection] = []

    # 32 beats at 72 BPM = ~26 seconds
    sections.append(
        SongSection(
            section_type=SectionType.VERSE,
            start_beat=0.0,
            length_beats=32.0,
            bpm=SONG_BPM,
            tracks=(
                # Slow piano chords: C - Am - F - G
                InstrumentTrack(
                    name="piano",
                    instrument_id="piano",
                    events=(
                        # C major
                        Note(midi=60, velocity=0.4, duration_beats=8.0),
                        # A minor
                        Note(midi=57, velocity=0.4, duration_beats=8.0),
                        # F major
                        Note(midi=53, velocity=0.4, duration_beats=8.0),
                        # G major
                        Note(midi=55, velocity=0.4, duration_beats=8.0),
                    ),
                    volume=0.35,
                    pan=PanPosition.CENTER,
                ),
                # Gentle strings pad
                InstrumentTrack(
                    name="strings",
                    instrument_id="warm_strings",
                    events=(
                        Note(midi=67, velocity=0.3, duration_beats=8.0),  # G4
                        Note(midi=64, velocity=0.3, duration_beats=8.0),  # E4
                        Note(midi=65, velocity=0.3, duration_beats=8.0),  # F4
                        Note(midi=67, velocity=0.3, duration_beats=8.0),  # G4
                    ),
                    volume=0.2,
                    pan=PanPosition.CENTER,
                ),
                # Soft bass
                InstrumentTrack(
                    name="bass",
                    instrument_id="sub_bass",
                    events=(
                        Note(midi=36, velocity=0.5, duration_beats=4.0),  # C2
                        Rest(duration_beats=4.0),
                        Note(midi=33, velocity=0.5, duration_beats=4.0),  # A1
                        Rest(duration_beats=4.0),
                        Note(midi=29, velocity=0.5, duration_beats=4.0),  # F1
                        Rest(duration_beats=4.0),
                        Note(midi=31, velocity=0.5, duration_beats=4.0),  # G1
                        Rest(duration_beats=4.0),
                    ),
                    volume=0.3,
                    pan=PanPosition.CENTER,
                ),
            ),
            label="Ballad verse",
        )
    )

    # 4 beats of tail silence
    sections.append(
        SongSection(
            section_type=SectionType.OUTRO,
            start_beat=32.0,
            length_beats=4.0,
            bpm=SONG_BPM,
            tracks=(),
            label="Tail",
        )
    )

    return Arrangement(
        title=SONG_TITLE,
        default_bpm=SONG_BPM,
        sections=tuple(sections),
    )


# Female voice singing a love ballad snippet
# speaker_index=1 is typically female in Bark's English voices
# We test multiple speakers to compare
VOCALS: Final[list[VocalSection]] = [
    VocalSection(
        section_id="verse_1",
        text="If I should stay, I would only be in your way.",
        language=VocalLanguage.ENGLISH,
        speaker_index=1,
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.9,
        gap_after_seconds=0.3,
        num_takes=3,
        pitch_correction_intensity=0.5,
        pitch_correction_key="C",
        pitch_correction_scale="major",
    ),
    VocalSection(
        section_id="verse_2",
        text="So I'll go, but I know, I'll think of you every step of the way.",
        language=VocalLanguage.ENGLISH,
        speaker_index=1,
        style=VocalStyle.SINGING,
        singing=True,
        volume=0.9,
        gap_after_seconds=0.5,
        num_takes=3,
        pitch_correction_intensity=0.5,
        pitch_correction_key="C",
        pitch_correction_scale="major",
    ),
    VocalSection(
        section_id="chorus",
        text="And I will always love you. I will always love you.",
        language=VocalLanguage.ENGLISH,
        speaker_index=1,
        style=VocalStyle.SINGING,
        singing=True,
        volume=1.0,
        gap_after_seconds=0.0,
        num_takes=5,  # More takes for the key line
        pitch_correction_intensity=0.6,
        pitch_correction_key="C",
        pitch_correction_scale="major",
    ),
]

SECONDS_PER_BEAT: Final[float] = 60.0 / SONG_BPM

# Place vocals across the 32-beat verse
VOCAL_PLACEMENT: Final[list[tuple[str, float]]] = [
    ("verse_1", 0.0),     # Beat 0
    ("verse_2", 10.0),    # Beat 10
    ("chorus", 20.0),     # Beat 20
]


def main() -> None:
    """Generate the vocal test ballad."""
    start_time = time.time()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(f"  Voice Test Ballad -- {SONG_BPM} BPM, female speaker")
    print(f"  Testing Bark singing quality")
    print("=" * 60)

    # Step 1: Instrumental
    print("\n  Step 1: Rendering instrumental backing...")
    arrangement = build_arrangement()
    instrumental_left, instrumental_right = render_arrangement(arrangement)
    instrumental_mono = stereo_to_mono(instrumental_left, instrumental_right)
    instrumental_wav = str(OUTPUT_DIR / f"{OUTPUT_NAME}_instrumental.wav")
    write_mono_wav(instrumental_wav, instrumental_mono)
    inst_duration = len(instrumental_mono) / SAMPLE_RATE
    print(f"   Done: {inst_duration:.1f}s")

    # Step 2: Vocals (this is the main test)
    print("\n  Step 2: Generating vocals with Bark AI...")
    print(f"   Speaker: en_speaker_1 (female)")
    print(f"   Sections: {len(VOCALS)}")
    print(f"   Takes per section: {[v.num_takes for v in VOCALS]}")
    engine = BarkVocalEngine()
    engine.preload_models()
    generated_vocals = engine.generate_vocals(VOCALS)
    engine.cleanup()

    # Step 3: Mix
    print("\n  Step 3: Mixing vocals onto backing...")
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

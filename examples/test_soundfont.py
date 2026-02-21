"""SoundFont rendering demonstration script.

Renders two musical examples using SoundFont instruments via FluidSynth:
1. C major scale (C4–C5) with sf:piano (GM program 0)
2. Chord progression (C–F–G–C) with sf:strings (GM program 48)

Exports to examples/soundfont_test.mp3.

Usage::

    python examples/test_soundfont.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

sys.path.insert(0, "source_files")

from instrumental_engine import (
    Arrangement,
    Chord,
    GMProgram,
    InstrumentTrack,
    Note,
    PanPosition,
    Rest,
    SectionType,
    SongSection,
    render_and_export,
)
from instrumental_engine.soundfont_validator import (
    check_soundfont_health,
)

OUTPUT_DIR: Final[str] = "examples"
OUTPUT_NAME: Final[str] = "soundfont_test"

SCALE_BPM: Final[int] = 100
CHORD_BPM: Final[int] = 80

C_MAJOR_SCALE_MIDI: Final[tuple[int, ...]] = (60, 62, 64, 65, 67, 69, 71, 72)

C_MAJOR_CHORD: Final[tuple[int, ...]] = (48, 52, 55, 60)
F_MAJOR_CHORD: Final[tuple[int, ...]] = (53, 57, 60, 65)
G_MAJOR_CHORD: Final[tuple[int, ...]] = (43, 47, 50, 55)
C_MAJOR_CHORD_HIGH: Final[tuple[int, ...]] = (48, 52, 55, 64)


def _build_scale_section() -> SongSection:
    """Build a section with C major scale on SoundFont piano.

    Returns:
        SongSection containing ascending C major scale C4–C5.
    """
    scale_notes = tuple(
        Note(midi=midi, velocity=0.8, duration_beats=1.0) for midi in C_MAJOR_SCALE_MIDI
    )

    return SongSection(
        section_type=SectionType.INTRO,
        start_beat=0.0,
        length_beats=10.0,
        bpm=SCALE_BPM,
        label="C Major Scale — SoundFont Piano",
        tracks=(
            InstrumentTrack(
                name="sf_piano_scale",
                instrument_id="sf:piano",
                gm_program=GMProgram.ACOUSTIC_GRAND_PIANO,
                events=scale_notes + (Rest(duration_beats=2.0),),
                volume=0.85,
                pan=PanPosition.CENTER,
            ),
        ),
    )


def _build_chord_section() -> SongSection:
    """Build a section with C–F–G–C chord progression on SoundFont strings.

    Returns:
        SongSection containing four chords, each 4 beats long.
    """
    chord_events = (
        Chord(notes=C_MAJOR_CHORD, velocity=0.7, duration_beats=4.0),
        Chord(notes=F_MAJOR_CHORD, velocity=0.7, duration_beats=4.0),
        Chord(notes=G_MAJOR_CHORD, velocity=0.75, duration_beats=4.0),
        Chord(notes=C_MAJOR_CHORD_HIGH, velocity=0.7, duration_beats=4.0),
    )

    scale_duration_seconds = 10.0 * (60.0 / SCALE_BPM)
    start_beat_at_chord_bpm = scale_duration_seconds * (CHORD_BPM / 60.0)

    return SongSection(
        section_type=SectionType.CHORUS,
        start_beat=start_beat_at_chord_bpm,
        length_beats=18.0,
        bpm=CHORD_BPM,
        label="C-F-G-C Progression — SoundFont Strings",
        tracks=(
            InstrumentTrack(
                name="sf_strings_chords",
                instrument_id="sf:strings",
                gm_program=GMProgram.STRINGS_ENSEMBLE,
                events=chord_events + (Rest(duration_beats=2.0),),
                volume=0.75,
                pan=PanPosition.CENTER,
            ),
        ),
    )


def _build_arrangement() -> Arrangement:
    """Build the complete test arrangement.

    Returns:
        Arrangement combining piano scale and string chords.
    """
    return Arrangement(
        title="SoundFont Test — Piano Scale + String Chords",
        default_bpm=SCALE_BPM,
        sections=(
            _build_scale_section(),
            _build_chord_section(),
        ),
    )


def main() -> None:
    """Run SoundFont test: health check, render, and export.

    Side Effects:
        Creates examples/soundfont_test.mp3 (and .wav).
        Prints status messages to stdout.
    """
    print("🎹 SoundFont Rendering Test")
    print("=" * 50)
    print()

    print("Running health check...")
    health = check_soundfont_health()
    print(health.details)
    print()

    if health.status != "ready":
        print("❌ SoundFont rendering is not available.")
        print("   Run the validator for setup instructions:")
        print("   python source_files/instrumental_engine/soundfont_validator.py")
        raise SystemExit(1)

    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    output_path = f"{OUTPUT_DIR}/{OUTPUT_NAME}"

    print("Building arrangement...")
    arrangement = _build_arrangement()

    print()
    result_path = render_and_export(
        arrangement,
        output_path,
        fade_out_seconds=3.0,
        export_mp3=True,
    )

    print()
    print("=" * 50)
    print(f"✅ SoundFont test complete!")
    print(f"   Output: {result_path}")
    print()
    print("Contents:")
    print("  1. C major scale (C4–C5) — SoundFont Acoustic Grand Piano")
    print("  2. C–F–G–C chord progression — SoundFont String Ensemble")


if __name__ == "__main__":
    main()

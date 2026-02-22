"""ACE-Step vocal pipeline test.

Generates a 30-second ballad using ACE-Step for vocals, Demucs for
vocal extraction, and Songmaker instrumentals for the backing track.

Prerequisites:
    1. ACE-Step server running: python scripts/start_acestep.py
    2. Demucs installed: pip install -e ".[demucs]"

Run: .venv/Scripts/python albums/download_days/tracks/00_test_acestep.py
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Final

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

from acestep_engine import AceStepClient, AceStepConfig, is_acestep_available  # noqa: E402
from bark_engine.audio_io import (  # noqa: E402
    master_to_mp3,
    normalize_audio,
    overlay_audio,
    write_wav_file,
)
from instrumental_engine import (  # noqa: E402
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
from instrumental_engine.mixer import stereo_to_mono, write_mono_wav  # noqa: E402

logger = logging.getLogger(__name__)

SONG_BPM: Final[int] = 72
OUTPUT_DIR: Final[Path] = Path("albums/download_days/output")
OUTPUT_NAME: Final[str] = "00_ACEStep_Test"
SECONDS_PER_BEAT: Final[float] = 60.0 / SONG_BPM


def build_arrangement() -> Arrangement:
    """Simple piano + strings backing in C major, 32 beats."""
    return Arrangement(
        title="ACE-Step Voice Test",
        default_bpm=SONG_BPM,
        sections=(
            SongSection(
                section_type=SectionType.VERSE,
                start_beat=0.0,
                length_beats=32.0,
                bpm=SONG_BPM,
                tracks=(
                    InstrumentTrack(
                        name="piano",
                        instrument_id="piano",
                        events=(
                            Note(midi=60, velocity=0.4, duration_beats=8.0),
                            Note(midi=57, velocity=0.4, duration_beats=8.0),
                            Note(midi=53, velocity=0.4, duration_beats=8.0),
                            Note(midi=55, velocity=0.4, duration_beats=8.0),
                        ),
                        volume=0.3,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        name="strings",
                        instrument_id="warm_strings",
                        events=(
                            Note(midi=67, velocity=0.25, duration_beats=16.0),
                            Note(midi=65, velocity=0.25, duration_beats=16.0),
                        ),
                        volume=0.15,
                        pan=PanPosition.CENTER,
                    ),
                    InstrumentTrack(
                        name="bass",
                        instrument_id="sub_bass",
                        events=(
                            Note(midi=36, velocity=0.4, duration_beats=4.0),
                            Rest(duration_beats=4.0),
                            Note(midi=33, velocity=0.4, duration_beats=4.0),
                            Rest(duration_beats=4.0),
                            Note(midi=29, velocity=0.4, duration_beats=4.0),
                            Rest(duration_beats=4.0),
                            Note(midi=31, velocity=0.4, duration_beats=4.0),
                            Rest(duration_beats=4.0),
                        ),
                        volume=0.25,
                        pan=PanPosition.CENTER,
                    ),
                ),
                label="Verse",
            ),
            SongSection(
                section_type=SectionType.OUTRO,
                start_beat=32.0,
                length_beats=4.0,
                bpm=SONG_BPM,
                tracks=(),
                label="Tail",
            ),
        ),
    )


# ACE-Step generation config
ACESTEP_CONFIG: Final[AceStepConfig] = AceStepConfig(
    prompt="emotional female vocal, slow piano ballad, strings, intimate, warm",
    lyrics=(
        "[verse]\n"
        "If I should stay\n"
        "I would only be in your way\n"
        "So I'll go, but I know\n"
        "I'll think of you every step of the way\n"
        "\n"
        "[chorus]\n"
        "And I will always love you\n"
        "I will always love you\n"
    ),
    bpm=SONG_BPM,
    duration=30,
    key="C",
    time_signature="4/4",
    vocal_language="en",
    seed=42,
)


def main() -> None:
    start_time = time.time()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  ACE-Step Vocal Pipeline Test")
    print(f"  {SONG_BPM} BPM | C major | 30s ballad")
    print("=" * 60)

    # Step 1: Check ACE-Step server
    print("\n  Step 1: Checking ACE-Step server...")
    if not is_acestep_available():
        print("  ERROR: ACE-Step server not running!")
        print("  Start it with: python scripts/start_acestep.py")
        return

    # Step 2: Render Songmaker instrumentals
    print("\n  Step 2: Rendering Songmaker instrumentals...")
    arrangement = build_arrangement()
    inst_left, inst_right = render_arrangement(arrangement)
    inst_mono = stereo_to_mono(inst_left, inst_right)
    inst_wav = str(OUTPUT_DIR / f"{OUTPUT_NAME}_instrumental.wav")
    write_mono_wav(inst_wav, inst_mono)
    inst_dur = len(inst_mono) / SAMPLE_RATE
    print(f"    Done: {inst_dur:.1f}s")

    # Step 3: Generate full mix via ACE-Step
    print("\n  Step 3: Generating vocals via ACE-Step...")
    print(f"    Prompt: {ACESTEP_CONFIG.prompt}")
    print(f"    Duration: {ACESTEP_CONFIG.duration}s")
    client = AceStepClient()
    result = client.generate(ACESTEP_CONFIG)
    if result is None:
        print("  ERROR: ACE-Step generation failed!")
        return

    # Save the raw ACE-Step output for comparison
    acestep_wav = str(OUTPUT_DIR / f"{OUTPUT_NAME}_acestep_raw.wav")
    write_wav_file(acestep_wav, result.samples)
    print(f"    ACE-Step raw mix: {result.duration:.1f}s")

    # Step 4: Extract vocals with Demucs
    print("\n  Step 4: Extracting vocals with Demucs...")
    try:
        from stem_separator import DemucsSeparator, is_demucs_available

        if not is_demucs_available():
            print("    Demucs not installed, using raw ACE-Step mix as vocals")
            vocals = result.samples
        else:
            separator = DemucsSeparator()
            stems = separator.separate(acestep_wav)
            if stems is not None:
                vocals = stems.vocals
                # Save separated vocals
                vocals_wav = str(OUTPUT_DIR / f"{OUTPUT_NAME}_vocals.wav")
                write_wav_file(vocals_wav, vocals)
                print(f"    Extracted vocals: {len(vocals) / SAMPLE_RATE:.1f}s")
            else:
                print("    Demucs separation failed, using raw mix")
                vocals = result.samples
    except ImportError:
        print("    Demucs not available, using raw ACE-Step mix as vocals")
        vocals = result.samples

    # Step 5: Mix vocals onto Songmaker instrumentals
    print("\n  Step 5: Mixing vocals onto instrumentals...")
    mixed = list(inst_mono)

    # Pad mixed if vocals are longer
    if len(vocals) > len(mixed):
        mixed.extend([0.0] * (len(vocals) - len(mixed)))

    # Overlay vocals at the start (beat 0)
    scaled_vocals = [s * 0.85 for s in vocals]
    overlay_audio(mixed, scaled_vocals, 0)

    # Step 6: Master and export
    print("\n  Step 6: Mastering...")
    mixed = normalize_audio(mixed, 0.95)
    mixed_wav = str(OUTPUT_DIR / f"{OUTPUT_NAME}_mixed.wav")
    write_wav_file(mixed_wav, mixed)

    mp3_path = str(OUTPUT_DIR / f"{OUTPUT_NAME}.mp3")
    master_to_mp3(mixed_wav, mp3_path)

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"  Done: {mp3_path}")
    print(f"  Time: {elapsed:.0f}s | Duration: {len(mixed) / SAMPLE_RATE:.1f}s")
    print("  Files:")
    print(f"    Raw ACE-Step:  {acestep_wav}")
    print(f"    Final mix:     {mp3_path}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()

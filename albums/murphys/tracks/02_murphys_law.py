"""Track 02: Murphy's Law — Irish Folk Punk / Celtic Punk.

Album: Friday at Murphy's
Genre: Irish Folk Punk (Dropkick Murphys / Flogging Molly / The Pogues)
BPM: 160
Key: D major
Duration: 170s (~2:50)

Vocals: ACE-Step 1.5 (text-to-music AI)

Modes (--mode):
    full-mix    ACE-Step generates everything (default)
    songmaker   DSP instrumental preview only (no vocals)

Story: Felix arrives at Murphy's on St. Paddy's night. Peter is already
5 pints deep. Everything goes wrong — Guinness tap dies, pizza burned,
decorations ripped down, power cuts out — and it's the best night ever.
"""

from __future__ import annotations

import os
import sys
from typing import Final

# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════

BPM: Final[int] = 160
TOTAL_SECONDS: Final[int] = 170
KEY: Final[str] = "D major"

OUTPUT_DIR: Final[str] = "_output/murphys"
WAV_PATH: Final[str] = os.path.join(OUTPUT_DIR, "02_Murphys_Law.wav")
MP3_PATH: Final[str] = os.path.join(OUTPUT_DIR, "02_Murphys_Law.mp3")

# ═══════════════════════════════════════════════════════════════════════════
# ACE-Step configuration
# ═══════════════════════════════════════════════════════════════════════════

ACESTEP_PROMPT: Final[str] = (
    "irish folk punk, Celtic punk, energetic male vocal, gang vocals on chorus, "
    "fiddle lead melody, tin whistle, strummed acoustic guitar, distorted electric guitar, "
    "fast driving drums, stomping kick, crowd clapping, pub singalong energy, "
    "Dropkick Murphys style, Flogging Molly, The Pogues, rebellious joy, "
    "drunken Irish folk band in a German pub, D major, 160 BPM, "
    "raw authentic recording, live pub atmosphere"
)

ACESTEP_LYRICS: Final[str] = """\
[verse]
Walk in the door, St. Paddy's night, the place is packed in green,
Peter's five pints deep already, biggest smile I've seen,
He sees me, shouts my name, bear-hugs me at the bar,
Full Guinness down my good white shirt, night hasn't even start

[verse]
Nine o'clock, the Guinness tap goes dead, the whole pub moans,
Peter stares at it like someone took everything he owns,
I order Weizen, I'm just fine, Tom says "That's the Irish way,"
Hundred people dressed in green, drinking Hefe on St. Paddy's Day

[chorus]
Who cares, pour another round,
Who cares, we're not going home,
Everything's gone wrong but the beer is cold,
Best St. Paddy's, here we go!

[verse]
Peter ordered pizza early, smart for once, he said,
Vanessa pulls it from the oven, black as coal and dead,
Keyla's drowning in the kitchen, ten more orders deep,
Peter eats it anyway and swears it's the best he'll ever eat

[verse]
Peter bumps a tourist in a stupid leprechaun hat,
Full pint to the chest, the guy screams "What the hell was that?!"
Peter grabs the banner trying not to fall down flat,
Whole St. Paddy's decoration crashes, James just nods at that

[chorus]
Who cares, pour another round,
Who cares, we're not going home,
Everything's gone wrong but the beer is cold,
Best St. Paddy's, here we go!

[bridge]
Power's out at eleven, pitch black, Maria doesn't stop,
Pouring pints from memory, that woman never drops,
Someone starts a Danny Boy, the whole pub sings along,
Fifty phones light up the dark, worst and best sing-along

[chorus]
Who cares, pour another round,
Peter knocked the table, Gitty's beer is down,
Hartmut orders one more, doesn't even blink,
Best St. Paddy's ever, pour me one more drink!

[outro]
Wouldn't change a thing, not one! Sláinte!
"""


# ═══════════════════════════════════════════════════════════════════════════
# Songmaker DSP instrumental (preview mode only)
# ═══════════════════════════════════════════════════════════════════════════

def _build_arrangement():
    """Minimal Irish folk punk DSP arrangement for preview mode."""
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
    )

    # D major: D E F# G A B C#
    # MIDI notes
    D3, E3, FS3, G3, A3 = 50, 52, 54, 55, 57
    D4, E4, FS4, G4, A4, B4 = 62, 64, 66, 67, 69, 71
    D2, A2, G2 = 38, 45, 43

    def _punk_beat() -> DrumPattern:
        """Fast punk beat: kick on 1+3, snare on 2+4, 8th hats."""
        return DrumPattern(
            name="irish_punk",
            length_beats=4.0,
            hits=(
                DrumHit(sound=DrumSound.KICK, beat_position=0.0, velocity=0.9),
                DrumHit(sound=DrumSound.KICK, beat_position=2.0, velocity=0.85),
                DrumHit(sound=DrumSound.SNARE, beat_position=1.0, velocity=0.8),
                DrumHit(sound=DrumSound.SNARE, beat_position=3.0, velocity=0.8),
                DrumHit(sound=DrumSound.CLOSED_HIHAT, beat_position=0.0, velocity=0.4),
                DrumHit(sound=DrumSound.CLOSED_HIHAT, beat_position=0.5, velocity=0.35),
                DrumHit(sound=DrumSound.CLOSED_HIHAT, beat_position=1.0, velocity=0.4),
                DrumHit(sound=DrumSound.CLOSED_HIHAT, beat_position=1.5, velocity=0.35),
                DrumHit(sound=DrumSound.CLOSED_HIHAT, beat_position=2.0, velocity=0.4),
                DrumHit(sound=DrumSound.CLOSED_HIHAT, beat_position=2.5, velocity=0.35),
                DrumHit(sound=DrumSound.CLOSED_HIHAT, beat_position=3.0, velocity=0.4),
                DrumHit(sound=DrumSound.CLOSED_HIHAT, beat_position=3.5, velocity=0.35),
            ),
        )

    def _chorus_beat() -> DrumPattern:
        """Chorus: add crash on beat 1."""
        base = _punk_beat()
        return DrumPattern(
            name="irish_punk_chorus",
            length_beats=4.0,
            hits=base.hits + (
                DrumHit(sound=DrumSound.CRASH, beat_position=0.0, velocity=0.6),
            ),
        )

    # D major chord progression: D - G - A - D (I-IV-V-I)
    def _verse_chords():
        return (
            Chord(notes=(D3, FS3, A3), velocity=0.7, duration_beats=8.0),
            Chord(notes=(G3, B4, D4), velocity=0.7, duration_beats=8.0),
            Chord(notes=(A3, E4, A4), velocity=0.75, duration_beats=8.0),
            Chord(notes=(D3, FS3, A3), velocity=0.7, duration_beats=8.0),
        )

    def _chorus_chords():
        return (
            Chord(notes=(D3, FS3, A3), velocity=0.85, duration_beats=4.0),
            Chord(notes=(G3, B4, D4), velocity=0.85, duration_beats=4.0),
            Chord(notes=(A3, E4, A4), velocity=0.9, duration_beats=4.0),
            Chord(notes=(D3, FS3, A3), velocity=0.85, duration_beats=4.0),
            Chord(notes=(D3, FS3, A3), velocity=0.85, duration_beats=4.0),
            Chord(notes=(G3, B4, D4), velocity=0.85, duration_beats=4.0),
            Chord(notes=(A3, E4, A4), velocity=0.9, duration_beats=4.0),
            Chord(notes=(D3, FS3, A3), velocity=0.85, duration_beats=4.0),
        )

    def _bass_verse():
        return (
            Note(midi=D2, velocity=0.7, duration_beats=7.5), Rest(duration_beats=0.5),
            Note(midi=G2, velocity=0.7, duration_beats=7.5), Rest(duration_beats=0.5),
            Note(midi=A2, velocity=0.75, duration_beats=7.5), Rest(duration_beats=0.5),
            Note(midi=D2, velocity=0.7, duration_beats=7.5), Rest(duration_beats=0.5),
        )

    def _bass_chorus():
        roots = (D2, G2, A2, D2, D2, G2, A2, D2)
        notes = []
        for r in roots:
            notes.append(Note(midi=r, velocity=0.8, duration_beats=3.5))
            notes.append(Rest(duration_beats=0.5))
        return tuple(notes)

    PUNK = _punk_beat()
    CHORUS_BEAT = _chorus_beat()
    TOTAL_BEATS = int(TOTAL_SECONDS * BPM / 60)

    # Simple 4-section arrangement: verse / verse / chorus / verse / chorus / bridge / chorus / outro
    # ~170s at 160 BPM = 453 beats, rounded to 448 (28 bars of 16 beats)
    return Arrangement(
        title="Murphy's Law",
        default_bpm=BPM,
        sections=(
            SongSection(
                section_type=SectionType.VERSE, start_beat=0.0, length_beats=32.0, bpm=BPM,
                tracks=(
                    InstrumentTrack(name="guitar", instrument_id="distorted_guitar",
                                    events=_verse_chords(), volume=0.6, pan=PanPosition.CENTER_LEFT),
                    InstrumentTrack(name="bass", instrument_id="sub_bass",
                                    events=_bass_verse(), volume=0.6, pan=PanPosition.CENTER),
                ),
                drum_pattern=PUNK,
            ),
            SongSection(
                section_type=SectionType.VERSE, start_beat=32.0, length_beats=32.0, bpm=BPM,
                tracks=(
                    InstrumentTrack(name="guitar", instrument_id="distorted_guitar",
                                    events=_verse_chords(), volume=0.65, pan=PanPosition.CENTER_LEFT),
                    InstrumentTrack(name="bass", instrument_id="sub_bass",
                                    events=_bass_verse(), volume=0.6, pan=PanPosition.CENTER),
                ),
                drum_pattern=PUNK,
            ),
            SongSection(
                section_type=SectionType.CHORUS, start_beat=64.0, length_beats=32.0, bpm=BPM,
                tracks=(
                    InstrumentTrack(name="guitar", instrument_id="distorted_guitar",
                                    events=_chorus_chords(), volume=0.8, pan=PanPosition.CENTER),
                    InstrumentTrack(name="bass", instrument_id="sub_bass",
                                    events=_bass_chorus(), volume=0.7, pan=PanPosition.CENTER),
                ),
                drum_pattern=CHORUS_BEAT,
            ),
            SongSection(
                section_type=SectionType.VERSE, start_beat=96.0, length_beats=32.0, bpm=BPM,
                tracks=(
                    InstrumentTrack(name="guitar", instrument_id="distorted_guitar",
                                    events=_verse_chords(), volume=0.6, pan=PanPosition.CENTER_LEFT),
                    InstrumentTrack(name="bass", instrument_id="sub_bass",
                                    events=_bass_verse(), volume=0.6, pan=PanPosition.CENTER),
                ),
                drum_pattern=PUNK,
            ),
            SongSection(
                section_type=SectionType.VERSE, start_beat=128.0, length_beats=32.0, bpm=BPM,
                tracks=(
                    InstrumentTrack(name="guitar", instrument_id="distorted_guitar",
                                    events=_verse_chords(), volume=0.65, pan=PanPosition.CENTER_LEFT),
                    InstrumentTrack(name="bass", instrument_id="sub_bass",
                                    events=_bass_verse(), volume=0.6, pan=PanPosition.CENTER),
                ),
                drum_pattern=PUNK,
            ),
            SongSection(
                section_type=SectionType.CHORUS, start_beat=160.0, length_beats=32.0, bpm=BPM,
                tracks=(
                    InstrumentTrack(name="guitar", instrument_id="distorted_guitar",
                                    events=_chorus_chords(), volume=0.8, pan=PanPosition.CENTER),
                    InstrumentTrack(name="bass", instrument_id="sub_bass",
                                    events=_bass_chorus(), volume=0.7, pan=PanPosition.CENTER),
                ),
                drum_pattern=CHORUS_BEAT,
            ),
            SongSection(
                section_type=SectionType.BRIDGE, start_beat=192.0, length_beats=32.0, bpm=BPM,
                tracks=(
                    InstrumentTrack(name="guitar", instrument_id="distorted_guitar",
                                    events=_verse_chords(), volume=0.55, pan=PanPosition.CENTER_LEFT),
                    InstrumentTrack(name="bass", instrument_id="sub_bass",
                                    events=_bass_verse(), volume=0.55, pan=PanPosition.CENTER),
                ),
                drum_pattern=PUNK,
            ),
            SongSection(
                section_type=SectionType.CHORUS, start_beat=224.0, length_beats=32.0, bpm=BPM,
                tracks=(
                    InstrumentTrack(name="guitar", instrument_id="distorted_guitar",
                                    events=_chorus_chords(), volume=0.85, pan=PanPosition.CENTER),
                    InstrumentTrack(name="bass", instrument_id="sub_bass",
                                    events=_bass_chorus(), volume=0.75, pan=PanPosition.CENTER),
                ),
                drum_pattern=CHORUS_BEAT,
            ),
            SongSection(
                section_type=SectionType.OUTRO, start_beat=256.0, length_beats=16.0, bpm=BPM,
                tracks=(
                    InstrumentTrack(name="guitar", instrument_id="distorted_guitar",
                                    events=(Chord(notes=(D3, FS3, A3), velocity=0.5, duration_beats=16.0),),
                                    volume=0.4, pan=PanPosition.CENTER),
                ),
                drum_pattern=PUNK,
            ),
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    """Generate Murphy's Law.

    Usage:
        python 02_murphys_law.py                 # Default: full-mix (ACE-Step)
        python 02_murphys_law.py --mode full-mix  # ACE-Step generates everything
        python 02_murphys_law.py --mode songmaker # DSP instrumental preview only
        python 02_murphys_law.py --seed 42        # Reproducible generation
    """
    import argparse
    import logging
    import time

    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Generate Murphy's Law")
    parser.add_argument(
        "--mode", choices=["full-mix", "songmaker"],
        default="full-mix",
        help="Generation mode (default: full-mix)",
    )
    parser.add_argument("--seed", type=int, default=-1, help="Random seed (-1 = random)")
    args = parser.parse_args()

    start_time = time.time()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 60)
    print("  Murphy's Law — Irish Folk Punk")
    print(f"  Mode: {args.mode} | {BPM} BPM | D major | {TOTAL_SECONDS}s")
    print("=" * 60)

    if args.mode == "full-mix":
        _generate_full_mix(args.seed)
    elif args.mode == "songmaker":
        _generate_songmaker_only()

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"  Total time: {int(elapsed // 60)}:{int(elapsed % 60):02d}")
    print(f"{'=' * 60}")


def _generate_full_mix(seed: int) -> None:
    """ACE-Step generates the entire song (vocals + instruments)."""
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
        duration=TOTAL_SECONDS,
        key=KEY,
        time_signature="4/4",
        vocal_language="en",
        seed=seed,
        think_mode=True,
    )

    print(f"  Generating {config.duration}s via ACE-Step...")
    client = AceStepClient()
    result = client.generate(config)
    if result is None:
        print("  ERROR: ACE-Step generation failed!")
        sys.exit(1)

    print(f"  Generated: {result.duration:.1f}s, seed={result.seed}")
    write_wav_file(WAV_PATH, result.samples)
    print(f"  WAV: {WAV_PATH}")

    from bark_engine.audio_io import master_to_mp3 as mono_master
    mono_master(WAV_PATH, MP3_PATH)
    print(f"  MP3: {MP3_PATH}")


def _generate_songmaker_only() -> None:
    """DSP instrumental preview (no vocals)."""
    from instrumental_engine import render_arrangement
    from instrumental_engine.mixer import master_to_mp3, normalize_stereo, write_stereo_wav

    print("\n  Rendering DSP instrumental...")
    arrangement = _build_arrangement()
    left, right = render_arrangement(arrangement)

    left, right = normalize_stereo(left, right)
    write_stereo_wav(WAV_PATH, left, right)
    print(f"  WAV: {WAV_PATH}")

    master_to_mp3(WAV_PATH, MP3_PATH, target_lufs=-14.0, stereo_width=1.2)
    print(f"  MP3: {MP3_PATH}")


if __name__ == "__main__":
    main()

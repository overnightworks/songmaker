# MC Tobbisch Birthday Album — Project Guide

## Overview

AI-generated birthday album for MC Tobbisch, produced by Flex0r.
All music (vocals + instrumentals) is generated entirely in Python.

## Project Structure

```
d:/mc_tobbisch_birthday_album/
├── AGENTS.md                          ← You are here
├── source_files/
│   ├── bark_engine/                   ← Shared vocal engine (Bark AI singing)
│   │   ├── __init__.py                ← Public API
│   │   ├── engine.py                  ← Core BarkVocalEngine class
│   │   ├── models.py                  ← VocalSection, VocalStyle, GeneratedVocal
│   │   ├── constants.py               ← BARK_SAMPLE_RATE, TARGET_SAMPLE_RATE
│   │   ├── text_processing.py         ← Chunk splitting, ♪ markers
│   │   ├── audio_io.py                ← WAV read/write, mixing, MP3 mastering
│   │   ├── audio_utils.py             ← Trim, crossfade, resample
│   │   └── vocal_filters.py           ← FFmpeg filter chains per vocal style
│   │
│   ├── instrumental_engine/           ← Shared instrumental engine
│   │   ├── __init__.py                ← Public API
│   │   ├── arrangement_engine.py      ← Main orchestrator: renders Arrangement → audio
│   │   ├── models.py                  ← Arrangement, SongSection, Note, Chord, etc.
│   │   ├── constants.py               ← SAMPLE_RATE, midi_to_freq, note helpers
│   │   ├── synth_instruments.py       ← 8 DSP synths (supersaw, pad, pluck, etc.)
│   │   ├── drum_machine.py            ← Drum synthesis + pattern library
│   │   ├── soundfont_engine.py        ← FluidSynth/SoundFont integration
│   │   ├── effects.py                 ← Reverb, delay, chorus, sidechain, etc.
│   │   └── mixer.py                   ← Stereo mixing, panning, WAV/MP3 export
│   │
│   └── (legacy track generators)      ← Old edge-tts based scripts (deprecated)
│
├── albums/
│   └── mc_tobbisch_birthday/
│       ├── tracks/                    ← 1 file = 1 song (strict rule)
│       │   ├── 01_download_days.py
│       │   └── ...
│       └── output/                    ← Generated MP3 files
│           ├── 01_Download_Days.mp3
│           └── ...
│
├── soundfonts/                        ← SoundFont files (optional)
└── (legacy .mp3 files at root)        ← Old album output (deprecated)
```

## Core Rules

### 1. One Song = One File
Every track generator lives in `albums/<album_name>/tracks/` as a single Python file.
Never generate multiple songs from one file.

### 2. Engine Reuse
Both engines live in `source_files/` and are shared across all albums.
Track scripts add `source_files/` to `sys.path` for imports.

### 3. Song Generator Pattern
Every track script follows this structure:

```python
"""Track XX: Song Title — Genre Description."""
import sys
sys.path.insert(0, "source_files")

from bark_engine import BarkVocalEngine, VocalSection, VocalStyle
from instrumental_engine import (
    Arrangement, SongSection, InstrumentTrack, Note, Chord, Rest,
    PATTERN_LIBRARY, render_and_export, PanPosition, SectionType,
)

# 1. Define lyrics as VocalSection list
# 2. Define arrangement as Arrangement
# 3. Render instrumental → WAV
# 4. Generate vocals via BarkVocalEngine
# 5. Mix vocals onto instrumental
# 6. Master to MP3
```

## Vocal Engine (bark_engine)

### Key Concepts
- **Bark** by Suno: AI model that generates speech/singing from text
- **♪ markers**: Adding ♪ around text triggers Bark's singing mode
- **CPU-only**: ~60-90s per vocal section on CPU (no GPU required)
- **torch.load patch**: PyTorch 2.6+ needs `weights_only=False` for Bark checkpoints
- **Sample rate**: Bark outputs 24000 Hz, resampled to 44100 Hz

### Vocal Styles
| Style | Use Case | Processing |
|-------|----------|------------|
| `SINGING` | Melodic vocals, choruses | Compression + presence EQ + reverb |
| `RAP` | Rap verses | Heavy compression + crisp EQ + short echo |
| `SPOKEN` | Narration, intros | Moderate compression + clarity EQ |
| `SHOUT` | Punk/rock vocals, drops | Aggressive compression + bright EQ |
| `WHISPER` | Intimate moments | Light compression + air EQ + long reverb |
| `EPIC` | Cinematic, anthemic | Full compression + wide EQ + hall reverb |

### Usage
```python
engine = BarkVocalEngine()
engine.preload_models()  # ~2 min first time (downloads ~5GB)
vocals = engine.generate_vocals([
    VocalSection(section_id="chorus", text="Those were the download days!",
                 style=VocalStyle.SHOUT, singing=True),
])
engine.cleanup()
```

## Instrumental Engine (instrumental_engine)

### Available Synth Instruments
| ID | Type | Best For |
|----|------|----------|
| `piano` | Struck-string model | Ballads, pop |
| `bright_piano` | Bright piano | Pop, dance |
| `strings` | Ensemble strings | Ballads, cinematic |
| `warm_strings` | Lush strings | Emotional sections |
| `supersaw` | 7-voice detuned saw | EDM, trance drops |
| `pad` | Warm additive pad | Ambient, backgrounds |
| `dark_pad` | Deep warm pad | Atmospheric |
| `pluck` | Karplus-Strong | Guitar-like arpeggios |
| `sub_bass` | Sine + saturation | Deep bass lines |
| `808_bass` | Heavy 808 | Hip-hop, trap |
| `lead` | Square/saw blend | Melody lines |
| `synth_lead_saw` | Pure saw lead | Bright leads |
| `synth_lead_square` | Pure square lead | Retro leads |
| `distorted_guitar` | Distortion + harmonics | Rock, punk |
| `power_guitar` | Heavy distortion | Power chords |
| `palm_mute_guitar` | Muted distortion | Punk verses |
| `sf:*` | SoundFont (FluidSynth) | Any GM instrument |

### Drum Patterns (PATTERN_LIBRARY)
`basic_rock`, `four_on_floor`, `boom_bap`, `trap`, `reggaeton`, `ballad`, `schlager`, `synthwave`

### Song Structure
```python
Arrangement(
    title="Song Title",
    default_bpm=175,
    sections=(
        SongSection(
            section_type=SectionType.VERSE,
            start_beat=0.0,
            length_beats=32.0,
            bpm=175,
            tracks=(...),
            drum_pattern=PATTERN_LIBRARY["basic_rock"],
        ),
    ),
)
```

### Notes & Chords
```python
Note(midi=60, velocity=0.8, duration_beats=1.0)   # Middle C, 1 beat
Chord(notes=(40, 47), velocity=0.9, duration_beats=4.0)  # E5 power chord
Rest(duration_beats=2.0)
```

## Technical Notes

- **Sample rate**: 44100 Hz everywhere (Bark resampled from 24000)
- **Output format**: Stereo WAV → MP3 (192kbps via ffmpeg)
- **Mastering chain**: Compression → EQ → Limiting → MP3 encoding
- **No GPU required**: Everything runs on CPU
- **Python 3.12+**: Uses StrEnum, `X | Y` union syntax, etc.
- **Dependencies**: torch (CPU), bark, numpy, scipy, ffmpeg (CLI)

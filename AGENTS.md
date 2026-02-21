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
│   │   ├── engine.py                  ← Core BarkVocalEngine class (multi-take selection)
│   │   ├── models.py                  ← VocalSection, VocalStyle, GeneratedVocal
│   │   ├── constants.py               ← BARK_SAMPLE_RATE, TARGET_SAMPLE_RATE
│   │   ├── take_selection.py          ← Multi-take scoring + best-of-N selection
│   │   ├── text_processing.py         ← Chunk splitting, ♪ markers
│   │   ├── audio_io.py                ← WAV read/write, mixing, MP3 mastering, vocal durations
│   │   ├── audio_utils.py             ← Trim, crossfade, resample
│   │   ├── vocal_filters.py           ← FFmpeg filter chains per vocal style
│   │   └── pitch_correction.py        ← Auto-tune: pitch detection + PSOLA correction
│   │
│   ├── instrumental_engine/           ← Shared instrumental engine
│   │   ├── __init__.py                ← Public API
│   │   ├── arrangement_engine.py      ← Main orchestrator: renders Arrangement → audio
│   │   ├── models.py                  ← Arrangement, SongSection, Note, Chord, etc.
│   │   ├── constants.py               ← SAMPLE_RATE, midi_to_freq, note helpers
│   │   ├── synth_instruments.py       ← 8 DSP synths (supersaw, pad, pluck, etc.)
│   │   ├── drum_machine.py            ← Drum synthesis + pattern library
│   │   ├── soundfont_engine.py        ← FluidSynth/SoundFont integration
│   │   ├── ducking.py                 ← Vocal-instrumental ducking (always active)
│   │   ├── effects.py                 ← Reverb, delay, chorus, sidechain, etc.
│   │   ├── mastering.py               ← Professional mastering chain (multiband/LUFS/stereo/clip)
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

from bark_engine import BarkVocalEngine, VocalSection, VocalStyle, calculate_vocal_durations
from instrumental_engine import (
    Arrangement, SongSection, InstrumentTrack, Note, Chord, Rest,
    PATTERN_LIBRARY, render_and_export, PanPosition, SectionType,
    apply_ducking,
)

# 1. Define lyrics as VocalSection list
# 2. Define arrangement as Arrangement
# 3. Render instrumental → stereo WAV
# 4. Generate vocals via BarkVocalEngine
# 5. Apply ducking to instrumental (always active, -3dB during vocals)
# 6. Mix vocals onto ducked instrumental
# 7. Master to MP3
```

### 4. Vocal-Instrumental Ducking (Always Active)
Ducking automatically reduces instrumental volume by ~3dB when vocals are present,
using smooth cosine-interpolated attack/release envelopes for click-free transitions.

```python
from bark_engine import calculate_vocal_durations
from instrumental_engine import apply_ducking

vocal_durations = calculate_vocal_durations(generated_vocals)
vocal_placement_seconds = [(sid, beat * seconds_per_beat) for sid, beat in VOCAL_PLACEMENT]

ducked_left, ducked_right = apply_ducking(
    instrumental_left, instrumental_right,
    vocal_placement_seconds, vocal_durations,
    reduction_db=-3.0,    # Industry-standard ducking depth
    attack_seconds=0.05,  # 50ms duck-down (lookahead)
    release_seconds=0.2,  # 200ms return to full volume
)
```

**Parameters:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `reduction_db` | -3.0 | Volume reduction during vocals (negative dB) |
| `attack_seconds` | 0.05 | Time to duck down before vocal starts |
| `release_seconds` | 0.2 | Time to return to full volume after vocal ends |

## Vocal Engine (bark_engine)

### Key Concepts
- **Bark** by Suno: AI model that generates speech/singing from text
- **♪ markers**: Adding ♪ around text triggers Bark's singing mode
- **Multi-take selection**: Each section generates N takes (default 3), auto-selects best
- **Pitch correction**: Auto-tune enabled by default at 70% intensity in C minor
- **CPU-only**: ~60-90s per vocal take on CPU (×3 for default 3 takes)
- **torch.load patch**: PyTorch 2.6+ needs `weights_only=False` for Bark checkpoints
- **Sample rate**: Bark outputs 24000 Hz, resampled to 44100 Hz

### Multi-Take Selection (Best of N)
Bark output quality is stochastic — the same text can produce wildly different results.
Multi-take generation is the **default behavior** (not opt-in). Each VocalSection
generates `num_takes` candidates (default 3), scores each on quality metrics, and
auto-selects the highest-scoring take.

**Scoring Metrics:**
| Metric | Weight | Description |
|--------|--------|-------------|
| Energy consistency | 30% | RMS variance across windows (lower variance = better) |
| Silence ratio | 30% | Fraction of audio below threshold (lower = better) |
| Clipping detection | 20% | Samples near ±1.0 (no clipping = better) |
| Duration match | 20% | Actual vs expected duration (closer = better) |

**Console Output:**
```
🎤 Generating: chorus (take 1/3)...
🎤 Generating: chorus (take 2/3)...
🎤 Generating: chorus (take 3/3)...
   Take 1: energy=0.72 silence=0.15 clip=✔️ duration=0.85 → composite=0.812
   Take 2: energy=0.81 silence=0.08 clip=✔️ duration=0.91 → composite=0.873
   Take 3: energy=0.65 silence=0.22 clip=⚠️ duration=0.78 → composite=0.668
   ✅ Selected take 2 (score: 0.873)
```

**Metadata:** All take scores are saved as JSON in the temp directory for debugging:
`_temp_bark/{section_id}_takes.json`

### VocalSection Configuration
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `section_id` | `str` | *(required)* | Unique identifier |
| `text` | `str` | *(required)* | Raw lyrics text |
| `language` | `VocalLanguage` | `GERMAN` | Voice language |
| `speaker_index` | `int` | `0` | Bark speaker preset (0-9) |
| `style` | `VocalStyle` | `SINGING` | Post-processing style |
| `singing` | `bool` | `True` | Add ♪ markers for singing mode |
| `volume` | `float` | `1.0` | Relative volume (0.0–1.0) |
| `gap_after_seconds` | `float` | `0.5` | Silence gap after section |
| `num_takes` | `int` | `3` | Takes to generate (best auto-selected) |
| `pitch_correction_intensity` | `float` | `0.7` | Pitch correction strength (0.0=off, 1.0=hard snap) |
| `pitch_correction_key` | `str` | `"C"` | Musical key for quantization (C, C#, D, ..., B) |
| `pitch_correction_scale` | `str` | `"minor"` | Scale type (major, minor, chromatic) |

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
    # num_takes=3 is the default — generates 3 takes, picks best
])
engine.cleanup()

# Override for faster iteration (1 take = no selection):
VocalSection(section_id="test", text="Quick test", num_takes=1)

# Disable pitch correction for a section:
VocalSection(section_id="rap_verse", text="Yo!", pitch_correction_intensity=0.0)

# Custom key/scale:
VocalSection(section_id="chorus", text="La la la",
             pitch_correction_key="G", pitch_correction_scale="major",
             pitch_correction_intensity=0.9)
```

### Pitch Correction (Auto-Tune)
Bark doesn't follow musical keys — it produces pitch drift and occasional off-key
notes. Pitch correction detects the fundamental frequency per frame, quantizes it
to the nearest note in the target scale, and resynthesizes the audio using PSOLA.

**Enabled by default** at 70% intensity in C minor. Applied after multi-take
selection and before ffmpeg vocal processing.

**Pipeline:**
```
Input → Autocorrelation Pitch Detection → Scale Quantization → PSOLA Resynthesis → Output
```

**Intensity Levels:**
| Intensity | Effect | Use Case |
|-----------|--------|----------|
| `0.0` | No correction (bypass) | Spoken word, rap |
| `0.3` | Subtle smoothing | Natural singing feel |
| `0.5` | Moderate correction | Pop vocals |
| `0.7` | Standard (default) | Most vocal styles |
| `0.9` | Strong correction | Polished sound |
| `1.0` | Hard snap to scale | T-Pain / robotic effect |

**Supported Scales:**
| Scale | Intervals | Description |
|-------|-----------|-------------|
| `major` | W-W-H-W-W-W-H | Bright, happy (e.g., C D E F G A B) |
| `minor` | W-H-W-W-H-W-W | Dark, emotional (e.g., C D Eb F G Ab Bb) |
| `chromatic` | All 12 semitones | Minimal quantization, slight smoothing |

**Supported Keys:**
C, C#, D, D#, E, F, F#, G, G#, A, A#, B (flats like Bb/Eb also accepted)

**Algorithm Details:**
- **Pitch detection**: Windowed autocorrelation (2048-sample frames, 512-sample hop)
- **Sub-sample accuracy**: Parabolic interpolation on autocorrelation peak
- **Frequency range**: 50–500 Hz (covers bass to soprano)
- **Unvoiced handling**: Consonants, breath, and silence pass through unmodified
- **Resynthesis**: PSOLA (Pitch-Synchronous Overlap-Add) via resampling + OLA

**Console Output:**
```
🎵 Pitch correction (C minor, intensity=0.7)...
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

## Professional Mastering Chain

All tracks use a professional mastering pipeline (enabled by default, no opt-in):

```
Input → Multiband Compression → Stereo Widening → LUFS Normalization → Soft Clipping → MP3
```

### Pipeline Stages

| Stage | Description | Key Parameters |
|-------|-------------|----------------|
| **Multiband Compression** | 3-band Butterworth split (bass/mid/treble), independent compression per band | Bands: 20–250, 250–4000, 4000–20000 Hz |
| **Stereo Widening** | Mid/side encoding, side channel boost | Width: 1.2× (20% wider) |
| **LUFS Normalization** | ITU-R BS.1770-4 simplified measurement, gain adjustment | Target: -14 LUFS (Spotify/YouTube) |
| **Soft Clipping** | tanh saturation for warmth, prevents hard clipping | Ceiling: 0.98 |

### Usage

```python
from instrumental_engine import master_stereo, master_to_mp3

# Full mastering pipeline (used internally by master_to_mp3)
mastered_left, mastered_right = master_stereo(
    left, right,
    target_lufs=-14.0,    # Streaming platform standard
    stereo_width=1.2,     # 20% wider stereo image
    sample_rate=44100,
)

# Master and encode to MP3 (applies full pipeline automatically)
master_to_mp3(
    wav_path="output/mixed.wav",
    mp3_path="output/final.mp3",
    target_lufs=-14.0,    # Override LUFS target
    stereo_width=1.2,     # Override stereo width
)
```

### LUFS Targeting

| Platform | Recommended LUFS |
|----------|-----------------|
| Spotify | -14.0 |
| YouTube | -14.0 |
| Apple Music | -16.0 |
| Loud master | -10.0 |

### Individual Components

```python
from instrumental_engine import (
    multiband_compress,  # 3-band frequency-dependent compression
    widen_stereo,        # Mid/side stereo enhancement
    measure_lufs,        # ITU-R BS.1770-4 loudness measurement
    soft_clip,           # tanh saturation (warmth without clipping)
)
```

## Technical Notes

- **Sample rate**: 44100 Hz everywhere (Bark resampled from 24000)
- **Output format**: Stereo WAV → MP3 (192kbps via ffmpeg)
- **Mastering chain**: Multiband compression → Stereo widening → LUFS normalization (-14 LUFS) → Soft clipping → MP3 encoding
- **No GPU required**: Everything runs on CPU
- **Python 3.12+**: Uses StrEnum, `X | Y` union syntax, etc.
- **Dependencies**: torch (CPU), bark, numpy, scipy, ffmpeg (CLI)

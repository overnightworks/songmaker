# Songmaker — Project Guide

## Overview

AI-powered song generation engine by Flex0r.
All music (vocals + instrumentals) is generated entirely in Python.

**Creator**: Flex0r (the user)
**For**: MC Tobbisch (Tobias, the user's close friend)
**Purpose**: Generate complete songs (vocals + instrumentals) from pure Python scripts

## Quick Start

```bash
# Run a track (generates instrumental + vocals + mastered MP3)
python albums/download_days/tracks/01_download_days.py

# Output lands in: _output/download_days/01_Download_Days.mp3
`

## Dependencies

```bash
py -3.12 -m venv .venv && .venv/Scripts/activate
pip install -e .              # All core + RVC deps
# ffmpeg must be on PATH (for MP3 encoding + vocal processing)
# Optional: FluidSynth + SoundFont (.sf2) for realistic instruments
# Optional: python scripts/download_soundfonts.py  (download high-quality SoundFonts)
```

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full system architecture,
module map, isolated venv design, and hardware scaling guide.

## Existing Tracks

### Album: Download Days
| Track | File | Genre | BPM | Key |
|-------|------|-------|-----|-----|
| 01 Download Days | lbums/download_days/tracks/01_download_days.py | Punk Rock (Offspring/Green Day) | 175 | E minor |
| 02 Fire in the Hole | albums/download_days/tracks/02_fire_in_the_hole.py | Boom-Bap Hip-Hop | 90 | A minor |

**Lyrics theme**: Nostalgia for 90s youth in Erlangen, Germany — downloading MP3s (Green Day, Offspring, Nirvana), LAN parties playing Counter-Strike, biking through Erlangen singing songs, playing Nintendo wrestling with friend David, athletics training at Turnerbund Erlangen.

### Album: MC Tobbisch Birthday (Legacy)
Old birthday album with 15 tracks generated via edge-tts (deprecated). Archived in lbums/mc_tobbisch_birthday/legacy_sources/ and legacy_output/.

### Album: Midnight Frequency
| Track | File | Genre | BPM | Key |
|-------|------|-------|-----|-----|
| 01 Let Me Fall | albums/midnight_frequency/tracks/01_let_me_fall.py | Melodic House (CYRIL x Avicii) | 120 | D minor |

**Lyrics theme**: Surrender and freedom — the moment you stop gripping your life and discover the fall IS the destination. Physical imagery (walls, air, windows, birds, city lights). No nostalgia — pure present-tense sensation.

## Known Limitations

- **Bark CPU speed**: ~15-19 it/s on CPU, ~90s per vocal section, ~270s with 3 takes
- **Bark quality variance**: Stochastic output — same text produces different quality each run (mitigated by multi-take selection)
- **Bark pitch drift**: Vocals don’t follow musical key (mitigated by pitch correction at 70%)
- **GPU speedup**: Install pip install torch --index-url https://download.pytorch.org/whl/cu121 for 10-25× faster Bark generation (no code changes needed)
- **No real-time preview**: Full track generation takes 20-45 min on CPU

## Project Structure

```
d:/songmaker/
├── AGENTS.md                          ← You are here
├── source_files/
│   ├── bark_engine/                   ← Shared vocal engine (Bark AI singing)
│   │   ├── __init__.py                ← Public API
│   │   ├── engine.py                  ← Core BarkVocalEngine class (multi-take selection)
│   │   ├── models.py                  ← VocalSection, VocalStyle, GeneratedVocal
│   │   ├── constants.py               ← BARK_SAMPLE_RATE, TARGET_SAMPLE_RATE
│   │   ├── take_selection.py          ← Multi-take scoring + best-of-N selection
│   │   ├── pitch_correction.py        ← Auto-tune: pitch detection + PSOLA correction
│   │   ├── text_processing.py         ← Chunk splitting, ♪ markers
│   │   ├── audio_io.py                ← WAV read/write, mixing, MP3 mastering, vocal durations
│   │   ├── audio_utils.py             ← Trim, crossfade, resample
│   │   └── vocal_filters.py           ← FFmpeg filter chains per vocal style
│   │
│   └── instrumental_engine/           ← Shared instrumental engine
│       ├── __init__.py                ← Public API
│       ├── arrangement_engine.py      ← Main orchestrator: renders Arrangement → audio
│       ├── models.py                  ← Arrangement, SongSection, Note, Chord, etc.
│       ├── constants.py               ← SAMPLE_RATE, midi_to_freq, note helpers
│       ├── synth_instruments.py       ← 8 DSP synths (supersaw, pad, pluck, etc.)
│       ├── drum_machine.py            ← Drum synthesis + pattern library
│       ├── soundfont_engine.py        ← FluidSynth/SoundFont integration
│       ├── soundfont_validator.py      ← SoundFont health check + setup validation
│       ├── ducking.py                 ← Vocal-instrumental ducking (always active)
│       ├── effects.py                 ← Reverb, delay, chorus, sidechain, etc.
│       ├── mastering.py               ← Professional mastering chain (multiband/LUFS/stereo/clip)
│       └── mixer.py                   ← Stereo mixing, panning, WAV/MP3 export
│
├── albums/
│   ├── download_days/                 ← Album: Download Days
│   │   ├── lyrics/                    ← Lyrics drafts (review before coding)
│   │   │   └── 02_fire_in_the_hole.md ← Boom-Bap Hip-Hop (90 BPM, A minor)
│   │   ├── tracks/                    ← 1 file = 1 song (strict rule)
│   │   │   └── 01_download_days.py    ← Punk rock anthem (175 BPM, E minor)
│   │   │   └── 02_fire_in_the_hole.py    ← Boom-Bap Hip-Hop (90 BPM, A minor)
│   │   └── output/                    ← Generated MP3 files
│   │
│   └── mc_tobbisch_birthday/          ← Album: MC Tobbisch Birthday (legacy)
│       ├── tracks/                    ← Track scripts
│       ├── legacy_sources/            ← Archived old edge-tts scripts
│       ├── legacy_output/             ← Archived old MP3 outputs

### Album: Midnight Frequency
| Track | File | Genre | BPM | Key |
|-------|------|-------|-----|-----|
| 01 Let Me Fall | albums/midnight_frequency/tracks/01_let_me_fall.py | Melodic House (CYRIL x Avicii) | 120 | D minor |

**Lyrics theme**: Surrender and freedom — the moment you stop gripping your life and discover the fall IS the destination. Physical imagery (walls, air, windows, birds, city lights). No nostalgia — pure present-tense sensation.
│
├── _models/                           ← AI model weights (gitignored)
│   ├── diffsinger/                    ← DiffSinger ONNX models + voicebanks
│   ├── rvc/                           ← RVC voice models
│   ├── soundfonts/                    ← SoundFont .sf2 files
│   ├── acestep/                       ← ACE-Step repo + checkpoints
│   └── voice_refs/                    ← XTTS voice reference audio
├── _cache/                            ← Temp/cached files (gitignored)
├── _output/                           ← Generated audio per album (gitignored)
├── scripts/                           ← Utility scripts (setup, download)
├── docs/                              ← Setup guides (soundfont_setup.md, architecture.md)
└── tests/                             ← Unit tests
```

## Core Rules

### 0. Lyrics-First Workflow
Every new song starts as a lyrics markdown file, NOT a Python script.

**Workflow:**
1. Create lbums/<album>/lyrics/<NN>_<song_name>.md with section-tagged lyrics
2. Review and iterate on lyrics with Flex0r until status is  APPROVED
3. Only then create the Python track script in 	racks/

**Lyrics file format:**
- Header: title, album, genre, BPM, key, vocal styles, status
- Sections tagged: [INTRO], [VERSE 1], [CHORUS], [BRIDGE], [OUTRO]
- Each section notes the vocal style (RAP, SINGING, SPOKEN, SHOUT, WHISPER)
- Status:  DRAFT   REVIEW   APPROVED
- Notes section for language, rhyme scheme, personal references

**Never generate a Python track script from unapproved lyrics.**

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
`_cache/temp/{section_id}_takes.json`

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

## VocalSection Complete Reference

All fields with defaults:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| section_id | str | required | Unique identifier |
| text | str | required | Lyrics/spoken text |
| style | VocalStyle | required | SINGING, RAP, SHOUT, or SPOKEN |
| language | VocalLanguage | ENGLISH | ENGLISH or GERMAN |
| speaker_index | int | 0 | Bark voice preset (0-9) |
| singing | bool | False | Add musical markers |
| volume | float | 1.0 | Volume in final mix |
| gap_after_seconds | float | 0.0 | Silence padding after section |
| num_takes | int | 3 | Number of takes to generate (best-of-N) |
| pitch_correction_intensity | float | 0.7 | 0.0=off, 0.7=natural, 1.0=hard snap |
| pitch_correction_key | str | C | Musical key (C, C#, D, ..., B) |
| pitch_correction_scale | str | minor | major, minor, or chromatic |

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

## DiffSinger Vocal Engine (diffsinger_engine)

### Overview
DiffSinger generates isolated singing vocals from MIDI notes + phonemes via ONNX inference.
It replaces Bark for singing vocals with full control over pitch, timing, and expression.

**Pipeline**: Lyrics -> G2P phonemes -> DiffSinger (4 stages) -> optional RVC -> mix

### Critical Production Rules

**1. Two lyric lines per phrase (~12-16 notes) is the sweet spot**
- 4+ lines in one phrase (28+ notes): consonants get garbled mid-phrase
- 1 line per phrase (~5-8 notes): too short, DiffSinger lacks phoneme context,
  head/tail padding eats into content, Whisper can't transcribe reliably
- 2 lines per phrase (~12-16 notes, ~16 beats): best pronunciation clarity

```python
# BAD - 4 lines in one phrase (28+ notes, pronunciation garbled)
verse_1a = VocalPhrase(phrase_id="verse_1a", bpm=120, notes=(
    # line 1 + line 2 + line 3 + line 4 = too many phoneme transitions
))

# BAD - 1 line per phrase (~5 notes, too short for context)
verse_1a_L1 = VocalPhrase(phrase_id="verse_1a_L1", bpm=120, notes=(
    _n(62, "I", 0.5), _n(65, "built", 1.0), _n(67, "these", 0.5),
    _n(69, "walls", 1.25), _r(0.75),  # only 3 seconds of audio
))

# GOOD - 2 lines per phrase (~14 notes, enough context)
verse_1a = VocalPhrase(phrase_id="verse_1a", bpm=120, notes=(
    # "I built these walls with steady hands" -- line 1
    _n(62, "I", 0.5), _n(65, "built", 1.0), ...
    # "but steady hands still shake at night" -- line 2
    _n(65, "but", 0.5), _n(67, "steady", 1.25), ...
))
verse_1b = VocalPhrase(phrase_id="verse_1b", bpm=120, notes=(
    # lines 3-4 in separate phrase
))
```

**2. Beat budget: notes must fit the beat window**
Each phrase's total note durations must fit within its beat window (gap to next phrase).
Use `check_beat_budgets()` in validation.py to verify before generation.
Standard: ~8 beats per lyric line at 120 BPM.

**3. Consonant duration: 100ms minimum**
In ds_builder.py, consonants get a fixed duration (currently 100ms). This gives
plosives (t/d/k/p) and fricatives (s/sh/f) room to be heard in generated audio.

**4. Whisper validation for pronunciation**
After generation, run Whisper STT on each phrase and compare to expected lyrics.
The validation report flags phrases below 80% similarity. Target: >80% per phrase.
Integrated into `validate_all()` in validation.py.

**5. Safety trim, not content trim**
DiffSinger adds ~8 frames of head/tail padding per phrase. Safety trim only catches
this padding overshoot (with fade-out). Never aggressively trim content -- fix the
note durations instead so phrases fit by construction.

**6. RVC is optional post-processing**
Set `rvc_model=None` to skip voice conversion. RVC transforms timbre but damages
consonant clarity. Only enable when pronunciation is already clean.

### VocalNote Fields
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| midi | int | required | MIDI note number (60=C4) |
| lyric | str | required | Syllable text |
| duration_beats | float | required | Duration in beats |
| velocity | float | 0.8 | Volume/energy 0.0-1.0 |
| breathiness | float | 0.0 | 0.0=clean, 1.0=breathy |
| tension | float | 0.5 | 0.0=relaxed, 1.0=tense |
| is_rest | bool | False | Silent note |

### VocalPhrase Fields
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| phrase_id | str | required | Unique ID |
| notes | tuple[VocalNote] | required | Note sequence |
| bpm | int | required | Tempo for timing |
| voice | str | "tiger" | Voicebank speaker mode |
| gender | float | 0.0 | Formant shift (-1 male, +1 female) |
| rvc_model | str/None | None | RVC model name or None |
| rvc_pitch_shift | int | 0 | RVC pitch shift semitones |
| rvc_index_rate | float | 0.5 | RVC index rate |

### TIGER Voicebank Speaker Modes
| Mode | Character | Best For |
|------|-----------|----------|
| tiger_fresh | Clean, natural | Verses, soft sections |
| tiger_electric | Bright, energetic | Choruses, power sections |
| tiger_disco | Warm, groovy | Dance, upbeat |
| tiger_vinyl | Vintage, warm | Retro feel |
| tiger_glam | Dramatic | Big moments |
| tiger_mystic | Ethereal | Atmospheric |
| tiger_royal | Full, rich | Epic sections |

### Track Script Pattern (DiffSinger)
```python
# Helper functions
def _n(midi, lyric, beats, vel=1.0): return VocalNote(midi=midi, lyric=lyric, duration_beats=beats, velocity=vel)
def _r(beats): return VocalNote(midi=60, lyric="", duration_beats=beats, is_rest=True)

# One phrase per lyric line
verse_1_L1 = VocalPhrase(phrase_id="verse_1_L1", bpm=BPM, voice="tiger_fresh", gender=-0.15, notes=(...))
verse_1_L2 = VocalPhrase(phrase_id="verse_1_L2", bpm=BPM, voice="tiger_fresh", gender=-0.15, notes=(...))

# Placement: (phrase, start_beat)
VOCAL_PHRASES = [
    (verse_1_L1, 0.0),
    (verse_1_L2, 8.0),   # 8 beats after L1
    ...
]

# Generation + validation
engine = DiffSingerEngine(voicebank_dir=VOICEBANK_DIR)
for phrase, beat in VOCAL_PHRASES:
    result = engine.generate(phrase)
    vocal_results[phrase.phrase_id] = result.samples

report = validate_all(validation_data)  # includes Whisper pronunciation check
print(report.summary())
```

### Validation Checks (validation.py)
| Check | Type | Description |
|-------|------|-------------|
| Beat budget | Pre-generation | Notes fit beat window (raises ValueError if not) |
| Phoneme coverage | Pre-generation | G2P produces phonemes for every note |
| Duration | Post-generation | Audio fits beat window |
| Silence gaps | Post-generation | No unexpected silence mid-phrase |
| Clipping | Post-generation | No distortion |
| Loudness | Post-generation | RMS within range, consistent across phrases |
| Pronunciation | Post-generation | Whisper STT matches expected lyrics (>80% target) |

## Technical Notes

- **Sample rate**: 44100 Hz everywhere (Bark resampled from 24000)
- **Output format**: Stereo WAV -> MP3 (192kbps via ffmpeg)
- **Mastering chain**: Multiband compression -> Stereo widening -> LUFS normalization (-14 LUFS) -> Soft clipping -> MP3 encoding
- **No GPU required**: Everything runs on CPU (DiffSinger ONNX ~7s per 3s phrase)
- **Python 3.12+**: Uses StrEnum, `X | Y` union syntax, etc.
- **Dependencies**: torch (CPU), bark, numpy, scipy, ffmpeg (CLI), g2p_en, onnxruntime

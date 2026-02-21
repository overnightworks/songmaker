# Songmaker Architecture

## Pipeline Overview

```
Track Script (.py)
    │
    ├──────────────────────────┐
    │                          │
    ▼                          ▼
┌─────────────────┐   ┌─────────────────┐
│  INSTRUMENTAL    │   │     VOCAL       │
│    ENGINE        │   │    ENGINE       │
│                  │   │                 │
│ ┌─────────────┐ │   │ ┌─────────────┐ │
│ │ Arrangement │ │   │ │ VocalSection │ │
│ │  Builder    │ │   │ │   Config     │ │
│ └──────┬──────┘ │   │ └──────┬──────┘ │
│        │        │   │        │        │
│        ▼        │   │        ▼        │
│ ┌─────────────┐ │   │ ┌─────────────┐ │
│ │  DSP Synths │ │   │ │  Bark AI    │ │
│ │  + Drums    │ │   │ │  or XTTS v2 │ │
│ │  + SFX      │ │   │ └──────┬──────┘ │
│ └──────┬──────┘ │   │        │        │
│        │        │   │        ▼        │
│  (optional)     │   │ ┌─────────────┐ │
│ ┌─────────────┐ │   │ │ Multi-Take  │ │
│ │ SoundFont   │ │   │ │ Selection   │ │
│ │ (sf:*)      │ │   │ └──────┬──────┘ │
│ └─────────────┘ │   │        │        │
│                  │   │        ▼        │
│                  │   │ ┌─────────────┐ │
│                  │   │ │   Pitch     │ │
│                  │   │ │ Correction  │ │
│                  │   │ └──────┬──────┘ │
│                  │   │        │        │
│                  │   │        ▼        │
│                  │   │ ┌─────────────┐ │
│                  │   │ │   Vocal     │ │
│                  │   │ │  Filters    │ │
│                  │   │ │  (ffmpeg)   │ │
│                  │   │ └──────┬──────┘ │
│                  │   │        │        │
│                  │   │        ▼        │
│                  │   │ ┌─────────────┐ │
│                  │   │ │    RVC      │ │
│                  │   │ │  Voice Conv │ │
│                  │   │ │ (subprocess)│ │
│                  │   │ └──────┬──────┘ │
│                  │   │        │        │
└────────┬─────────┘   └────────┬────────┘
         │                      │
         ▼                      ▼
    Stereo L/R             Mono Samples
         │                      │
         ▼                      │
  ┌─────────────┐               │
  │   DUCKING   │◄──────────────┘
  │  -6dB when  │  (vocal timing)
  │ vocals play │
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │   MIXING    │◄── Vocal Gain (1.4×)
  │  Overlay    │
  │  Vocals     │
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │  NORMALIZE  │
  │  Peak 0.95  │
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │ WAV Export  │
  │ 16-bit PCM  │
  │ 44100 Hz    │
  └──────┬──────┘
         │
         ▼
  ┌─────────────────────────────┐
  │       MASTERING CHAIN       │
  │                             │
  │  1. Multiband Compression   │
  │     Bass  20-250 Hz (3.0:1) │
  │     Mids  250-4k Hz (2.5:1)│
  │     Treble 4k-20k Hz (2:1) │
  │                             │
  │  2. Stereo Widening (1.2×)  │
  │     Mid-Side processing     │
  │                             │
  │  3. LUFS Normalization      │
  │     Target: -14 LUFS       │
  │     ITU-R BS.1770-4        │
  │                             │
  │  4. Soft Clipping           │
  │     tanh() at 0.98 ceiling  │
  └──────────┬──────────────────┘
             │
             ▼
  ┌─────────────┐
  │ MP3 Encode  │
  │ ffmpeg      │
  │ 192 kbps    │
  └─────────────┘
```

---

## File Map

```
songmaker/
├── albums/
│   ├── midnight_frequency/
│   │   ├── lyrics/          # Markdown: draft → review → approved
│   │   ├── tracks/          # One .py per song (orchestration)
│   │   └── output/          # Generated MP3 files
│   └── download_days/
│       ├── lyrics/
│       ├── tracks/
│       └── output/
│
├── source_files/
│   ├── bark_engine/                 # VOCAL ENGINE
│   │   ├── engine.py                #   Core: BarkVocalEngine class
│   │   ├── models.py                #   VocalSection, VocalStyle, VocalLanguage
│   │   ├── text_processing.py       #   Chunking, ♪ markers, speaker presets
│   │   ├── audio_utils.py           #   Resample (24k→44.1k), crossfade, trim
│   │   ├── audio_io.py              #   WAV read/write, normalize
│   │   ├── pitch_correction.py      #   Autocorrelation + PSOLA resynthesis
│   │   ├── take_selection.py        #   Quality scoring, best-take selection
│   │   ├── vocal_filters.py         #   ffmpeg filter chains per VocalStyle
│   │   └── constants.py             #   BARK_SAMPLE_RATE=24000, TARGET=44100
│   │
│   ├── instrumental_engine/         # INSTRUMENTAL ENGINE
│   │   ├── arrangement_engine.py    #   render_arrangement() → stereo L/R
│   │   ├── models.py                #   Note, Chord, Rest, DrumPattern, Arrangement
│   │   ├── synth_instruments.py     #   SupersawSynth, PadSynth, PluckSynth, etc.
│   │   ├── drum_machine.py          #   Kick, snare, hat synthesis + patterns
│   │   ├── soundfont_engine.py      #   FluidSynth integration (sf:* instruments)
│   │   ├── ducking.py               #   Vocal-aware gain envelope
│   │   ├── mastering.py             #   4-stage mastering chain
│   │   ├── effects.py               #   Reverb, delay, chorus, sidechain
│   │   ├── mixer.py                 #   Stereo mixing, panning, WAV/MP3 export
│   │   └── constants.py             #   SAMPLE_RATE (44100), MIDI utilities
│   │
│   ├── rvc_engine/                  # RVC VOICE CONVERSION
│   │   ├── converter.py             #   RVCConverter (subprocess to venv)
│   │   └── _rvc_infer.py            #   Inference script (runs in .venv)
│   │
│   ├── xtts_engine/                 # XTTS v2 SPEECH SYNTHESIS
│   │   ├── converter.py             #   XTTSConverter (subprocess to venv)
│   │   └── _xtts_infer.py           #   Inference script (runs in .venv)
│   │
│   ├── ai_engine/                   # MusicGen AI INSTRUMENTALS
│   │   ├── musicgen_renderer.py     #   MusicGenRenderer — VRAM-aware model
│   │   └── _musicgen_infer.py       #   Inference script (runs in .venv)
│   │
│   └── stem_separator/              # Demucs STEM SEPARATION
│       ├── demucs_separator.py      #   DemucsSeparator — 4-stem splitter
│       └── _demucs_infer.py         #   Inference script (runs in .venv)
│
├── rvc_models/                      # RVC .pth voice models
│   └── male_singer_v1.pth
│
├── soundfonts/                      # SoundFont .sf2 files
│   ├── FluidR3_GM.sf2               #   141 MB — General MIDI
│   └── MuseScore_General.sf2        #   206 MB — General MIDI
│
├── voice_refs/                      # XTTS voice reference WAVs
│
└── .venv/                       # Isolated Python 3.12 venv
                                     #   (RVC + XTTS + AI dependencies)
```

---

## Vocal Engine Detail

```
VocalSection Config
    │
    ▼
┌───────────────────────────────────────────┐
│              BARK VOCAL ENGINE            │
│                                           │
│  1. Cache Check (SHA256 of all params)    │
│     ├── HIT  → return cached samples      │
│     └── MISS → continue ▼                 │
│                                           │
│  2. Text Processing                       │
│     ├── split_text_into_chunks()          │
│     ├── add_singing_markers() → ♪text♪    │
│     └── build_speaker_preset()            │
│         └── v2/{lang}_speaker_{idx}       │
│                                           │
│  3. Multi-Take Generation (default: 3)    │
│     ├── bark.generate_audio() @ 24kHz     │
│     ├── Chunk-wise with 5ms crossfade     │
│     ├── Resample 24kHz → 44.1kHz          │
│     └── Normalize to [-1.0, 1.0]          │
│                                           │
│  4. Take Selection (automatic)            │
│     Score each take on:                   │
│     ├── Energy consistency                │
│     ├── Silence ratio (≤ 10%)             │
│     ├── Clipping ratio                    │
│     └── Duration accuracy                 │
│     → Select highest scoring take         │
│                                           │
│  5. Pitch Correction                      │
│     ├── Detect F0 via autocorrelation     │
│     ├── Quantize to key/scale grid        │
│     └── PSOLA resynthesis                 │
│     Intensity: 0.0 (off) → 1.0 (hard)    │
│                                           │
│  6. Vocal Processing (ffmpeg)             │
│     Style-specific filter chains:         │
│     ├── SINGING: +6dB presence, compress  │
│     ├── WHISPER: +4dB high-shelf          │
│     ├── RAP: tight compression, presence  │
│     ├── EPIC: exciter, wide reverb        │
│     └── SHOUT: distortion, compression    │
│                                           │
│  7. RVC Voice Conversion (optional)       │
│     ├── Write temp WAV                    │
│     ├── Subprocess → .venv/python     │
│     │   └── _rvc_infer.py <config.json>   │
│     ├── RVCInference.infer_file()         │
│     │   ├── f0_method: rmvpe              │
│     │   ├── pitch_shift: ±24 semitones    │
│     │   └── index_rate: 0.0-1.0           │
│     └── Read converted WAV back           │
│                                           │
│  8. Cache Result + Return                 │
│     └── GeneratedVocal(samples, vol, gap) │
└───────────────────────────────────────────┘
```

---

## DSP Synthesizers

```
┌─────────────────────────────────────────────┐
│            SYNTH_REGISTRY                   │
│                                             │
│  "supersaw"  → SupersawSynth               │
│    7 detuned sawtooth oscillators           │
│    ±30 cents spread, LP filter              │
│    ADSR: 10ms / 100ms / 0.7 / 200ms        │
│                                             │
│  "pad"       → PadSynth                    │
│    Filtered noise + sine harmonics          │
│    Long attack (600ms), warm LP             │
│                                             │
│  "pluck"     → PluckSynth                  │
│    Karplus-Strong physical modeling         │
│    Noise excitation → delay feedback        │
│                                             │
│  "sub_bass"  → SubBassSynth                │
│    60Hz sine + saturation + sub-octave      │
│                                             │
│  "lead"      → LeadSynth                   │
│    Saw/square blend, tunable filter         │
│                                             │
│  "piano"     → PianoSynth                  │
│    10+ additive harmonics, brightness ctrl  │
│                                             │
│  "strings"   → StringsSynth                │
│    Multiple detuned voices per note         │
│                                             │
│  "distorted_guitar" → DistortedGuitarSynth │
│    String modeling + waveshaper overdrive   │
│                                             │
│  "sf:*"      → SoundFont (FluidSynth)      │
│    MIDI program → subprocess render         │
│    Auto-detect best .sf2 file               │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│            DRUM MACHINE                     │
│                                             │
│  KICK    Pitch-drop sine 150→45Hz           │
│  SNARE   Noise + 180Hz tone, dual envelope  │
│  CLAP    Layered noise bursts (0/8/16/25ms) │
│  HH_CL   Filtered noise, 60ms decay        │
│  HH_OP   Filtered noise, 250ms decay       │
│  TOM     Filtered sine, tunable pitch       │
│  CRASH   Bright noise sweep, 800ms          │
└─────────────────────────────────────────────┘
```

---

## Mastering Chain Detail

```
Input: Mixed stereo WAV (vocals + instrumentals)
  │
  ▼
┌──────────────────────────────────────┐
│  MULTIBAND COMPRESSION               │
│                                      │
│  Butterworth IIR crossover filters:  │
│                                      │
│  ┌──────┐  ┌──────┐  ┌──────┐       │
│  │ BASS │  │ MIDS │  │TREBLE│       │
│  │20-250│  │250-4k│  │4k-20k│       │
│  │ 3.0:1│  │ 2.5:1│  │ 2.0:1│       │
│  └──┬───┘  └──┬───┘  └──┬───┘       │
│     └────┬─────┴────┬────┘           │
│          ▼          ▼                │
│     Recombine with phase alignment   │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  STEREO WIDENING                     │
│                                      │
│  Encode:  M = (L+R)/2  S = (L-R)/2  │
│  Widen:   S × 1.2                    │
│  Decode:  L = (M+S)/2  R = (M-S)/2  │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  LUFS NORMALIZATION (ITU-R BS.1770)  │
│                                      │
│  K-weight → 400ms blocks → gate →    │
│  Target: -14 LUFS (streaming)        │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  SOFT CLIPPING                       │
│                                      │
│  tanh(x) saturation                  │
│  Ceiling: 0.98 (2% headroom)        │
└──────────────┬───────────────────────┘
               │
               ▼
         Final MP3
      192 kbps via ffmpeg
       -14 LUFS ready
```

---

## Isolated Venv Architecture

Several AI backends require Python 3.10-3.12 due to dependency conflicts
with Python 3.12 (faiss-cpu, numpy<=1.25, pyworld, etc.). These run in
an isolated virtual environment via subprocess:

```
Main Process (Python 3.12)
    │
    │  1. Write input audio to temp WAV file
    │  2. Write config to temp JSON file
    │  3. subprocess.run([venv_python, script.py, config.json])
    │  4. Read output WAV file back
    │
    └── Isolated Venv (Python 3.12, .venv/)
        ├── PyTorch + CUDA (auto-detected)
        ├── rvc-python       (voice conversion)
        ├── coqui-tts        (XTTS v2 speech)
        ├── audiocraft       (MusicGen AI)
        └── demucs           (stem separation)
```

**Key properties:**
- GPU auto-detection: CUDA used when available, CPU as fallback
- Hardware-agnostic: upgrading GPU requires zero code changes
- Modular: each backend is independently installable
- Failure-safe: missing backends are silently skipped

---

## SoundFont System

SoundFont instruments use the `sf:` prefix in track scripts:

```python
InstrumentTrack(
    name="piano",
    instrument_id="sf:piano",
    gm_program=GMProgram.ACOUSTIC_GRAND_PIANO,
)
```

**Discovery priority** (best first):
1. Instrument-specific SoundFont (e.g., Salamander for piano programs 0-7)
2. Quality-priority search: Timbres of Heaven > MuseScore General > FluidR3 > GeneralUser
3. Any `.sf2` file in `soundfonts/` (largest file preferred)
4. System-wide fallback paths

---

## Vocal Cache System

Generated vocals are cached in `_vocal_cache/` using SHA-256 hashes
of the full VocalSection configuration (text, style, speaker, RVC model, etc.).

```
_vocal_cache/
├── a1b2c3d4...meta.json    # Config hash + metadata
├── a1b2c3d4...wav           # Cached audio
└── ...
```

On re-runs, cached sections are loaded instantly. The Bark model is only
loaded into VRAM if at least one section needs generation.

---

## Track Script Pattern

Every song is a single `.py` file in `albums/<album>/tracks/`:

```python
import sys
sys.path.insert(0, "source_files")

from bark_engine.models import VocalSection, VocalStyle, VocalLanguage
from bark_engine.engine import BarkVocalEngine
from instrumental_engine import (
    Arrangement, SongSection, InstrumentTrack,
    Note, Chord, Rest, render_arrangement, apply_ducking, master_to_mp3,
)

# 1. Define vocals
VOCALS = [
    VocalSection(
        section_id="verse_1",
        text="Lyrics here",
        style=VocalStyle.SINGING,
        language=VocalLanguage.ENGLISH,
        rvc_model="male_singer_v1",       # Optional: RVC voice conversion
        pitch_correction_intensity=0.7,
        pitch_correction_key="A",
        pitch_correction_scale="minor",
    ),
]

# 2. Define instrumentals
ARRANGEMENT = Arrangement(title="Song Title", default_bpm=122, sections=(...))

# 3. Generate, mix, master, export
if __name__ == "__main__":
    engine = BarkVocalEngine()
    vocals = engine.generate_vocals(VOCALS)
    inst_left, inst_right = render_arrangement(ARRANGEMENT)
    ducked_l, ducked_r = apply_ducking(inst_left, inst_right, ...)
    # ... overlay vocals, normalize, master_to_mp3()
```

---

## Hardware Scaling

| GPU | Capabilities |
|-----|-------------|
| **CPU only** | Bark (slow), DSP synths, SoundFonts |
| **GTX 1660 Ti (6 GB)** | + RVC, + fast Bark, + XTTS |
| **RTX 3090 (24 GB)** | + MusicGen medium/large, + parallel backends |

Upgrading GPU requires zero code changes — all backends auto-detect CUDA
and available VRAM.

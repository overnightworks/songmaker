# Songmaker Architecture

## Pipeline Overview

```
songmaker generate <song>.md
    │
    ▼
┌────────────────────────────────────────────┐
│  SONGMAKER CLI                             │
│  Parse markdown → AceStepConfig → generate │
└────────────┬───────────────────────────────┘
             │
             ▼
┌────────────────────────┐     ┌──────────────────────────┐
│  ACE-Step Client       │────►│  ACE-Step API Server     │
│  acestep_engine/       │     │  (FastAPI, port 8001)    │
│  HTTP POST + polling   │◄────│  Turbo: 8-step inference │
└────────────┬───────────┘     │  ~4GB VRAM + ~8GB RAM    │
             │                 └──────────────────────────┘
             ▼
┌────────────────────────────────────────────┐
│  MASTERING CHAIN (bark_engine/audio_io.py) │
│                                            │
│  Multiband Compression → Stereo Widening   │
│  → LUFS Normalization → Soft Clipping      │
│  → MP3 Encoding (ffmpeg, 320kbps)          │
└────────────────────────────────────────────┘
```

For complex tracks with custom instrumentals:

```
Track Script (.py)
    │
    ├──────────────────────────┐
    │                          │
    ▼                          ▼
┌─────────────────┐   ┌─────────────────┐
│  INSTRUMENTAL    │   │   ACE-Step      │
│    ENGINE        │   │   Vocals        │
│  DSP Synths      │   │                 │
│  + Drums         │   │   prompt +      │
│  + SoundFonts    │   │   lyrics →      │
│                  │   │   full mix      │
└────────┬─────────┘   └────────┬────────┘
         │                      │
         ▼                      ▼
  ┌─────────────┐
  │   DUCKING   │  Instrumentals duck -3dB
  │   MIXING    │  during vocal sections
  │  MASTERING  │
  └─────────────┘
```

---

## File Map

```
songmaker/
├── source_files/
│   ├── acestep_engine/                ← ACE-Step REST API client
│   │   ├── client.py                  ←   HTTP client, task polling
│   │   ├── models.py                  ←   AceStepConfig, AceStepResult
│   │   └── __init__.py
│   │
│   ├── bark_engine/                   ← Audio I/O + mastering utilities
│   │   ├── audio_io.py                ←   WAV/MP3 read/write, mastering
│   │   ├── constants.py               ←   SAMPLE_RATE (44100)
│   │   ├── models.py                  ←   VocalLanguage, VocalStyle enums
│   │   └── __init__.py
│   │
│   ├── instrumental_engine/           ← DSP instrumental engine
│   │   ├── arrangement_engine.py      ←   Renders Arrangement → stereo audio
│   │   ├── models.py                  ←   Note, Chord, Rest, Arrangement, etc.
│   │   ├── synth_instruments.py       ←   DSP synths (supersaw, pad, pluck, etc.)
│   │   ├── drum_machine.py            ←   Drum synthesis + pattern library
│   │   ├── soundfont_engine.py        ←   FluidSynth/SoundFont integration
│   │   ├── ducking.py                 ←   Vocal-aware gain envelope
│   │   ├── mastering.py               ←   Mastering chain
│   │   ├── effects.py                 ←   Reverb, delay, chorus, sidechain
│   │   ├── mixer.py                   ←   Stereo mixing, panning, export
│   │   └── constants.py               ←   SAMPLE_RATE, MIDI utilities
│   │
│   └── songmaker_cli/                 ← CLI entry point
│       ├── main.py                    ←   generate, sync, check, player
│       └── player.py                  ←   HTML player generation
│
├── albums/
│   ├── <album>/lyrics/                ← Song markdown files
│   └── <album>/tracks/                ← Complex track scripts (.py)
│
├── _models/                           ← AI model weights (gitignored)
│   ├── soundfonts/                    ←   SoundFont .sf2 files
│   └── acestep/                       ←   ACE-Step checkpoints
├── _cache/                            ← Temp files (gitignored)
├── _output/                           ← Generated audio (gitignored)
├── scripts/                           ← Utilities
└── tests/                             ← Unit tests
```

---

## DSP Synthesizers

```
┌─────────────────────────────────────────────┐
│            SYNTH_REGISTRY                   │
│                                             │
│  "supersaw"  → SupersawSynth               │
│    7 detuned sawtooth oscillators           │
│                                             │
│  "pad"       → PadSynth                    │
│    Filtered noise + sine harmonics          │
│                                             │
│  "pluck"     → PluckSynth                  │
│    Karplus-Strong physical modeling         │
│                                             │
│  "sub_bass"  → SubBassSynth                │
│    60Hz sine + saturation + sub-octave      │
│                                             │
│  "lead"      → LeadSynth                   │
│    Saw/square blend, tunable filter         │
│                                             │
│  "piano"     → PianoSynth                  │
│    10+ additive harmonics                   │
│                                             │
│  "strings"   → StringsSynth                │
│    Multiple detuned voices per note         │
│                                             │
│  "distorted_guitar" → DistortedGuitarSynth │
│    String modeling + waveshaper overdrive   │
│                                             │
│  "sf:*"      → SoundFont (FluidSynth)      │
│    MIDI program → subprocess render         │
└─────────────────────────────────────────────┘
```

---

## Mastering Chain Detail

```
Input: Stereo audio
  │
  ▼
┌──────────────────────────────────────┐
│  MULTIBAND COMPRESSION               │
│  ┌──────┐  ┌──────┐  ┌──────┐       │
│  │ BASS │  │ MIDS │  │TREBLE│       │
│  │20-250│  │250-4k│  │4k-20k│       │
│  │ 3.0:1│  │ 2.5:1│  │ 2.0:1│       │
│  └──────┘  └──────┘  └──────┘       │
└──────────────┬───────────────────────┘
               ▼
┌──────────────────────────────────────┐
│  STEREO WIDENING (1.2×)              │
│  Mid-Side processing                 │
└──────────────┬───────────────────────┘
               ▼
┌──────────────────────────────────────┐
│  LUFS NORMALIZATION                  │
│  Target: -14 LUFS (streaming)        │
└──────────────┬───────────────────────┘
               ▼
┌──────────────────────────────────────┐
│  SOFT CLIPPING                       │
│  tanh() at 0.98 ceiling              │
└──────────────┬───────────────────────┘
               ▼
         MP3 (320 kbps)
```

---

## SoundFont System

SoundFont instruments use the `sf:` prefix:

```python
InstrumentTrack(
    name="piano",
    instrument_id="sf:piano",
    gm_program=GMProgram.ACOUSTIC_GRAND_PIANO,
)
```

**Discovery priority** (best first):
1. Instrument-specific SoundFont (e.g., Salamander for piano)
2. Quality-priority: Timbres of Heaven > MuseScore General > FluidR3
3. Any `.sf2` in `_models/soundfonts/`

---

## Hardware

| GPU | Capabilities |
|-----|-------------|
| **GTX 1660 Ti (6 GB)** | ACE-Step turbo (0.6B LM only) |
| **RTX 3090 (24 GB)** | ACE-Step turbo/SFT, all LM sizes |

GPU auto-detected — upgrading requires zero code changes.

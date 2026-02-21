# Songmaker Architecture

## Overview

Songmaker generates complete songs (vocals + instrumentals) from pure Python track scripts. Each track script defines vocal sections and instrumental arrangements, and the engine renders them to WAV/MP3.

```
Track Script (.py)
    │
    ├── Vocal Pipeline
    │   ├── BarkVocalEngine         (text-to-speech/singing via Bark AI)
    │   ├── Vocal Cache             (SHA-256 hash-based, skip regeneration)
    │   ├── Pitch Correction        (snap to musical scale)
    │   ├── FFmpeg Post-Processing  (EQ, compression per vocal style)
    │   └── RVC Voice Conversion    (optional, isolated Python 3.12 venv)
    │
    ├── Instrumental Pipeline
    │   ├── DSP Synthesizers        (supersaw, pad, pluck, bass, lead, etc.)
    │   ├── SoundFont Renderer      (FluidSynth + .sf2 files)
    │   ├── Drum Machine            (genre-specific pattern library)
    │   └── Effects Chain           (reverb, delay, chorus, sidechain)
    │
    └── Mastering Pipeline
        ├── Vocal-Instrumental Ducking  (-3 dB automatic)
        ├── Stereo Mixing               (per-track panning + volume)
        ├── Multiband Compression
        ├── Stereo Widening
        ├── LUFS Normalization (-14)
        ├── Soft Clipping
        └── MP3 Export (192 kbps via ffmpeg)
```

---

## Module Map

```
source_files/
├── bark_engine/                 # Vocal generation engine
│   ├── engine.py                # BarkVocalEngine — main orchestrator
│   ├── models.py                # VocalSection, VocalStyle, VocalLanguage
│   ├── audio_io.py              # WAV read/write utilities
│   └── constants.py             # Sample rates, cache dir name
│
├── instrumental_engine/         # Instrumental generation engine
│   ├── arrangement_engine.py    # Renders full arrangements from sections
│   ├── models.py                # Arrangement, SongSection, InstrumentTrack
│   ├── synth_instruments.py     # DSP synths (SupersawSynth, PadSynth, etc.)
│   ├── soundfont_engine.py      # FluidSynth SoundFont rendering
│   ├── soundfont_validator.py   # Health checks for SoundFont setup
│   ├── drum_machine.py          # Drum synthesis + pattern library
│   ├── effects.py               # Reverb, delay, chorus, sidechain
│   ├── mixer.py                 # Stereo mixing, panning, WAV/MP3 export
│   ├── mastering.py             # Multiband compression, LUFS, widening
│   ├── ducking.py               # Vocal-instrumental ducking
│   └── constants.py             # SAMPLE_RATE (44100), MIDI utilities
│
├── rvc_engine/                  # RVC voice conversion (isolated venv)
│   ├── converter.py             # RVCConverter — subprocess-based
│   └── _rvc_infer.py            # Inference script (runs in Python 3.12)
│
├── xtts_engine/                 # XTTS v2 text-to-speech (isolated venv)
│   ├── converter.py             # XTTSConverter — subprocess-based
│   └── _xtts_infer.py           # Inference script (runs in Python 3.12)
│
├── ai_engine/                   # MusicGen AI instrumentals (isolated venv)
│   ├── musicgen_renderer.py     # MusicGenRenderer — VRAM-aware model selection
│   └── _musicgen_infer.py       # Inference script (runs in Python 3.12)
│
└── stem_separator/              # Demucs stem separation (isolated venv)
    ├── demucs_separator.py      # DemucsSeparator — 4-stem audio splitter
    └── _demucs_infer.py         # Inference script (runs in Python 3.12)
```

---

## Isolated Venv Architecture

Several AI backends require Python 3.10-3.12 due to dependency conflicts
with Python 3.14 (faiss-cpu, numpy<=1.25, pyworld, etc.). These run in
an isolated virtual environment via subprocess:

```
Main Process (Python 3.14)
    │
    │  1. Write input audio to temp WAV file
    │  2. Write config to temp JSON file
    │  3. subprocess.run([venv_python, script.py, config.json])
    │  4. Read output WAV file back
    │
    └── Isolated Venv (Python 3.12, _rvc_venv/)
        ├── PyTorch + CUDA (auto-detected)
        ├── rvc-python
        └── (future: coqui-tts, audiocraft, demucs)
```

**Key properties:**
- GPU auto-detection: CUDA is used when available, CPU as fallback
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

**Setup:**
```bash
python download_soundfonts.py          # Download all recommended
python download_soundfonts.py --list   # Show available options
python download_soundfonts.py fluidr3  # Download specific one
```

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

from bark_engine.models import VocalSection, VocalStyle
from bark_engine.engine import BarkVocalEngine
from instrumental_engine import (
    Arrangement, SongSection, InstrumentTrack,
    Note, Chord, Rest, render_and_export, apply_ducking, master_stereo,
)

# 1. Define vocals
SECTIONS = [
    VocalSection(section_id="verse_1", text="...", style=VocalStyle.SINGING),
    # ...
]

# 2. Define instrumentals
ARRANGEMENT = Arrangement(title="Song Title", default_bpm=120, sections=(...))

# 3. Generate, mix, master, export
if __name__ == "__main__":
    engine = BarkVocalEngine()
    vocal_samples = engine.generate_vocals(SECTIONS)
    instrumental_left, instrumental_right = render_and_export(ARRANGEMENT, ...)
    # ... ducking, mastering, MP3 export
```

---

## Dependencies

**Core (required):**
- Python 3.12+
- PyTorch (CPU or CUDA)
- numpy, scipy
- suno-bark
- ffmpeg (on PATH)

**SoundFonts (optional):**
- FluidSynth (on PATH)
- `.sf2` SoundFont files in `soundfonts/`

**RVC voice conversion (optional):**
- Python 3.12 available as `py -3.12`
- Run `setup_rvc_venv.py` to create isolated venv
- Place `.pth` + `.index` voice models in `rvc_models/`

---

## Hardware Scaling

| GPU | Capabilities |
|-----|-------------|
| **CPU only** | Bark (slow), DSP synths, SoundFonts |
| **GTX 1660 Ti (6 GB)** | + RVC, + fast Bark, + XTTS (future) |
| **RTX 3090 (24 GB)** | + MusicGen medium/large, + parallel backends |

Upgrading GPU requires zero code changes — all backends auto-detect CUDA
and available VRAM.

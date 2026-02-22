# ACE-Step Integration Architecture

## Overview

ACE-Step 1.5 is a text-to-music AI model that generates full songs (vocals + instruments) from a text prompt and lyrics. Songmaker integrates it as a **vocal source** — ACE-Step generates a full mix, Demucs extracts the vocals, and optionally RVC converts the voice timbre.

This replaces Bark for high-quality singing. Bark remains available as a fallback.

## Why ACE-Step?

| Feature | Bark | ACE-Step 1.5 |
|---------|------|-------------|
| Singing quality | Poor (speech model) | Good (trained on music) |
| Lyrics alignment | Unreliable | Trained on lyrics |
| Duration | ~15s max | Up to 600s |
| Musical awareness | None | BPM, key, time signature |
| Voice variety | 10 presets per language | Style via text prompt |

## Architecture

```
Songmaker main venv (.venv)              ACE-Step venv (_acestep/.venv)
Python 3.12, torch 2.10+cu126           Python 3.12, torch 2.7.1+cu128

┌────────────────────────────┐           ┌──────────────────────────┐
│ Track script (.py)         │           │ ACE-Step API Server      │
│                            │   HTTP    │ (FastAPI, port 8001)     │
│  acestep_engine.client ────┼──────────►│                          │
│  AceStepClient             │           │ Model loaded once        │
│    .generate()             │◄──────────┤ ~4GB VRAM + ~8GB RAM     │
│    .is_available()         │  WAV data │ Turbo: 8-step inference   │
│                            │           └──────────────────────────┘
│  stem_separator            │
│    DemucsSeparator         │   Extract vocals from ACE-Step mix
│    .separate()             │
│                            │
│  rvc_engine                │   Optional voice timbre conversion
│    RVCConverter            │
│    .convert_samples()      │
│                            │
│  instrumental_engine       │   Songmaker's own instrumentals
│    render_arrangement()    │
│                            │
│  Mix + Master + Export     │
└────────────────────────────┘
```

## Why Two Venvs?

ACE-Step 1.5 on Windows pins `torch==2.7.1+cu128`. Songmaker's main venv uses `torch>=2.10+cu126`. These cannot coexist. The REST API server isolates the dependency conflict — ACE-Step runs in its own venv, Songmaker talks to it over HTTP on localhost.

**Overhead**: Near zero. HTTP on localhost adds ~1-5ms per request. Model load happens once at server start. Generation takes 30-120s depending on duration.

## Vocal Pipeline

```
1. Track script defines lyrics + style prompt
         │
2. AceStepClient.generate(prompt, lyrics, bpm, duration, key)
         │  HTTP POST to localhost:8001
         │
3. ACE-Step server generates full mix (vocals + instruments)
         │  Returns: 48kHz stereo WAV
         │
4. DemucsSeparator.separate(full_mix.wav)
         │  Extracts: vocals, drums, bass, other
         │
5. (Optional) RVCConverter.convert_samples(vocals)
         │  Converts voice to target timbre
         │
6. Mix ACE-Step vocals onto Songmaker instrumentals
         │  overlay_audio() at beat positions
         │
7. Master chain → MP3
```

## New Files

### source_files/acestep_engine/

```
acestep_engine/
├── __init__.py      # Public API: AceStepClient, AceStepConfig, is_acestep_available
├── models.py        # AceStepConfig, AceStepResult dataclasses
└── client.py        # AceStepClient — HTTP client for the REST API
```

### scripts/setup_acestep.py

Setup script that:
1. Clones ACE-Step 1.5 repo into `_acestep/`
2. Runs `uv sync` inside the repo (creates `_acestep/.venv` with all deps)
3. Downloads model checkpoints (turbo + 0.6B LM)

Requires `uv` (`pip install uv`). ACE-Step's `pyproject.toml` uses
`[tool.uv.sources]` for CUDA-specific torch wheels and local path deps
that only `uv` can resolve.

### scripts/start_acestep.py

Launches the ACE-Step API server via `uv run`:
```bash
uv run acestep-api --port 8001   # from _acestep/ dir
```

## Data Flow

### AceStepConfig (input)

```python
@dataclass(frozen=True)
class AceStepConfig:
    prompt: str              # Style description for ACE-Step
    lyrics: str              # Song lyrics with [verse]/[chorus] tags
    bpm: int = 120           # Tempo
    duration: int = 60       # Seconds (10-600)
    key: str = "Am"          # Musical key
    time_signature: str = "4/4"
    vocal_language: str = "en"
    instrumental: bool = False  # True = no vocals
    seed: int = -1           # -1 = random
```

### AceStepResult (output)

```python
@dataclass(frozen=True)
class AceStepResult:
    samples: list[float]     # Full mix audio at 44100 Hz, mono
    sample_rate: int         # 44100 (resampled from 48000)
    duration: float          # Actual duration in seconds
    seed: int                # Seed used for generation
```

## Track Script Usage

```python
from acestep_engine import AceStepClient, AceStepConfig
from stem_separator import DemucsSeparator
from rvc_engine import RVCConverter
from bark_engine.audio_io import write_wav_file, normalize_audio, overlay_audio

# 1. Generate full mix via ACE-Step
client = AceStepClient()  # localhost:8001
result = client.generate(AceStepConfig(
    prompt="emotional female vocal, slow ballad, piano, strings",
    lyrics="[verse]\nIf I should stay...\n[chorus]\nAnd I will always love you",
    bpm=72,
    duration=30,
    key="C",
))

# 2. Extract vocals with Demucs
write_wav_file("_temp/acestep_mix.wav", result.samples)
separator = DemucsSeparator()
stems = separator.separate("_temp/acestep_mix.wav")

# 3. Optional: convert voice with RVC
converter = RVCConverter(model_name="female_singer_v1")
vocals = converter.convert_samples(stems.vocals) or stems.vocals

# 4. Mix onto Songmaker instrumentals
overlay_audio(instrumental_mono, vocals, start_sample=0)
```

## System Requirements

- **GPU**: 6GB VRAM minimum (GTX 1660 Ti works)
- **RAM**: 16GB recommended (CPU offloading uses ~8GB)
- **Disk**: ~5GB for model checkpoints
- **Python**: 3.12 (both venvs)
- **CUDA**: 12.8 for ACE-Step venv (torch 2.7.1+cu128)

## Server Management

The ACE-Step server is a separate process. It should be started before running any track that uses ACE-Step vocals:

```bash
# Start server (blocks terminal)
python scripts/start_acestep.py

# Or run in background
start /B python scripts/start_acestep.py

# Health check
curl http://localhost:8001/health
```

The `AceStepClient` checks server availability before attempting generation and returns a clear error if the server is not running.

## Fallback Strategy

If ACE-Step is not available (server not running, not installed), tracks can:
1. Fall back to Bark for vocal generation (lower quality)
2. Skip vocal generation entirely (instrumental only)
3. Use pre-rendered ACE-Step vocals from cache

The `is_acestep_available()` function checks server connectivity.

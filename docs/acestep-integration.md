# ACE-Step Integration

## Overview

ACE-Step 1.5 is a text-to-music AI model that generates full songs (vocals + instruments) from a text prompt and lyrics. It is the primary (and only) vocal/music generation engine in Songmaker.

## Architecture

```
Songmaker (.venv)                       ACE-Step Server (_acestep/.venv)
Python 3.12                             Python 3.12, torch 2.7.1+cu128

┌────────────────────────────┐           ┌──────────────────────────┐
│ songmaker generate         │           │ ACE-Step API Server      │
│                            │   HTTP    │ (FastAPI, port 8001)     │
│  acestep_engine.client ────┼──────────►│                          │
│  AceStepClient             │           │ Model loaded once        │
│    .generate()             │◄──────────┤ ~4GB VRAM + ~8GB RAM     │
│                            │  WAV data │ Turbo: 8-step inference   │
│                            │           └──────────────────────────┘
│  bark_engine.audio_io      │
│    master_to_mp3()         │   Mastering + MP3 encoding
│                            │
└────────────────────────────┘
```

## Generation Pipeline

```
1. songmaker generate <song>.md
         │
2. AceStepClient.generate(prompt, lyrics, bpm, duration, key)
         │  HTTP POST to localhost:8001
         │
3. ACE-Step server generates full song (vocals + instruments)
         │  Returns: 44100 Hz audio
         │
4. Master chain (multiband compression, LUFS, stereo) → MP3
```

## AceStepConfig (input)

```python
@dataclass(frozen=True)
class AceStepConfig:
    prompt: str              # Style description
    lyrics: str              # Lyrics with [verse]/[chorus] tags
    bpm: int = 120           # Tempo (0 = let model decide)
    duration: int = 60       # Seconds (10-600)
    key: str = "Am"          # Musical key
    time_signature: str = "4/4"
    vocal_language: str = "en"
    seed: int = -1           # -1 = random
    inference_steps: int = 8 # Turbo default
    guidance_scale: float = 0.0
    shift: float = 3.0
    think_mode: bool = False # CoT planning (false = more natural)
    lm_temperature: float = 0.85
    infer_method: str = "ode"
```

## Server Setup

```bash
# Start ACE-Step server
python scripts/start_acestep.py

# Health check
curl http://localhost:8001/health
```

## System Requirements

- **GPU**: 6GB VRAM minimum (GTX 1660 Ti works)
- **RAM**: 16GB recommended
- **Disk**: ~5GB for model checkpoints
- **Python**: 3.12

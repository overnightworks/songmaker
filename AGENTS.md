# Songmaker — Project Guide

## Overview

Song generation CLI that takes markdown files (lyrics + YAML config) and produces mastered MP3s via ACE-Step.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full pipeline diagram and mastering chain.

```
songmaker generate <song>.md
    → parse markdown → SongMeta → AceStepConfig
    → HTTP POST to ACE-Step server → poll for result
    → mastering chain → MP3 encoding (ffmpeg)
```

## Source Packages

### acestep_engine

HTTP client for the ACE-Step music generation server.

| File | Purpose |
|------|---------|
| `client.py` | Task submission, polling, health check |
| `models.py` | `AceStepConfig` and `AceStepResult` dataclasses |

### audio_engine

Audio I/O and mastering pipeline (numpy/scipy DSP).

| File | Purpose |
|------|---------|
| `audio_io.py` | WAV read/write, `master_to_mp3`, ffmpeg encoding |
| `mastering.py` | Multiband compression, LUFS normalization, stereo widening, soft clipping |
| `constants.py` | `TARGET_SAMPLE_RATE` (44100) |

### songmaker_cli

CLI entry point and song file handling.

| File | Purpose |
|------|---------|
| `main.py` | cyclopts commands: generate, check, player |
| `parser.py` | `SongMeta`, `AlbumMeta` (pydantic), markdown/YAML parsing |
| `config.py` | `OutputPaths`, versioned path resolution, `build_ace_config` |
| `constants.py` | `OUTPUT_ROOT`, `DEFAULT_ARTIST`, thresholds |
| `player.py` | HTML player generation |

## CLI Commands

```bash
# Generate a song
songmaker generate albums/<album>/lyrics/<NN>_<song>.md

# Override ACE-Step params from CLI
songmaker generate <song>.md --shift 1.0 --no-think-mode --seed 42

# Batch generate (auto-versioning: v1, v2, v3)
songmaker generate <song>.md --count 3

# Whisper accuracy check
songmaker check _output/<album>/<song>_v1.mp3

# Regenerate HTML player
songmaker player -o _output
```

## ACE-Step Tuning Notes

### Server Setup
```bash
python scripts/start_acestep.py --config acestep-v15-turbo --lm-model acestep-5Hz-lm-0.6B --lm-backend vllm
```

### Key Parameters

| Parameter | Default | Notes |
|-----------|---------|-------|
| `shift` | 3.0 | 1.0 = most natural/emotional, 3.0 = accurate lyrics |
| `think_mode` | true | false = more creative, true = more structured |
| `inference_steps` | 8 | Turbo default |
| `guidance_scale` | 0.0 | Turbo ignores CFG |
| `lm_temperature` | 0.85 | Higher (1.1-1.2) = more creative |
| `infer_method` | ode | sde = more textured/alive |
| `bpm` | 120 | 0 = let model decide freely |

### LM Model Selection

| Model | Effect |
|-------|--------|
| none | Raw/chaotic, most creative |
| 0.6B | Sweet spot — creative + structure |
| 4B | Over-planned, sterile — avoid |

## Mastering Chain

```
Input (mono WAV) → Stereo duplicate
  → Multiband Compression (3 bands: 20-250, 250-4k, 4k-20k Hz)
  → Stereo Widening (1.2x, mid-side)
  → LUFS Normalization (-14 LUFS, ITU-R BS.1770-4)
  → Soft Clipping (tanh, 0.98 ceiling)
  → MP3 (320 kbps, ffmpeg)
```

## Testing

See [docs/testing.md](docs/testing.md) for test structure, fixtures, and coverage targets.

```bash
pytest tests/
ruff check src/ tests/
```

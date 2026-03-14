# Songmaker — Project Guide

## Overview

AI-powered song generation engine by Flex0r.
Songs are generated from markdown files via ACE-Step.

**Creator**: Flex0r (the user)
**For**: MC Tobbisch (Tobias, the user's close friend)
**Purpose**: Generate complete songs from markdown lyrics files

## Quick Start

```bash
# Generate a song from markdown
songmaker generate albums/<album>/lyrics/<NN>_<song>.md

# Generate with specific seed
songmaker generate albums/<album>/lyrics/<NN>_<song>.md --seed 42

# Sync lyrics (transcribe, LRC, HTML player, ID3 tags)
songmaker sync _output/<album>/final/

# Open HTML player
songmaker player _output/
```

## Dependencies

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .
# ffmpeg must be on PATH (for MP3 encoding)
# ACE-Step server: python scripts/start_acestep.py
```

## Architecture

See [docs/architecture.md](docs/architecture.md) for system architecture details.

## Albums

### Album: Wake Up
| Track | File | Genre | BPM | Key |
|-------|------|-------|-----|-----|
| 01 Where Is the Love (2026) | albums/wake_up/lyrics/01_where_is_the_love.md | Hip-Hop / Conscious Rap | 95 | Am |

### Album: Download Days
| Track | File | Genre | BPM | Key |
|-------|------|-------|-----|-----|
| 01 Download Days | albums/download_days/tracks/01_download_days.py | Punk Rock | 175 | Em |

### Album: Midnight Frequency
| Track | File | Genre | BPM | Key |
|-------|------|-------|-----|-----|
| 01 Let Me Fall | albums/midnight_frequency/tracks/01_let_me_fall.py | Melodic House | 120 | Dm |

## Project Structure

```
songmaker/
├── AGENTS.md                          ← You are here
├── source_files/
│   ├── acestep_engine/                ← ACE-Step client (REST API to local server)
│   │   ├── client.py                  ← HTTP client, task submission, polling
│   │   ├── models.py                  ← AceStepConfig dataclass
│   │   └── __init__.py
│   │
│   ├── bark_engine/                   ← Audio I/O and mastering utilities
│   │   ├── audio_io.py                ← WAV read/write, mixing, MP3 mastering
│   │   ├── constants.py               ← SAMPLE_RATE constants
│   │   ├── models.py                  ← VocalLanguage, VocalStyle enums
│   │   └── __init__.py
│   │
│   ├── instrumental_engine/           ← DSP instrumental engine
│   │   ├── arrangement_engine.py      ← Orchestrator: renders Arrangement → audio
│   │   ├── models.py                  ← Arrangement, SongSection, Note, Chord, etc.
│   │   ├── constants.py               ← SAMPLE_RATE, midi_to_freq, note helpers
│   │   ├── synth_instruments.py       ← DSP synths (supersaw, pad, pluck, etc.)
│   │   ├── drum_machine.py            ← Drum synthesis + pattern library
│   │   ├── soundfont_engine.py        ← FluidSynth/SoundFont integration
│   │   ├── ducking.py                 ← Vocal-instrumental ducking
│   │   ├── effects.py                 ← Reverb, delay, chorus, sidechain
│   │   ├── mastering.py               ← Mastering chain (multiband/LUFS/stereo/clip)
│   │   └── mixer.py                   ← Stereo mixing, panning, WAV/MP3 export
│   │
│   └── songmaker_cli/                 ← CLI entry point
│       ├── main.py                    ← generate, sync, check, player commands
│       └── player.py                  ← HTML player generation
│
├── albums/
│   ├── <album>/lyrics/                ← Song markdown files (lyrics + config)
│   └── <album>/tracks/                ← Complex tracks (Python scripts)
├── _models/                           ← AI model weights (gitignored)
│   ├── soundfonts/                    ← SoundFont .sf2 files
│   └── acestep/                       ← ACE-Step repo + checkpoints
├── _cache/                            ← Temp/cached files (gitignored)
├── _output/                           ← Generated audio per album (gitignored)
├── scripts/                           ← Utilities (start_acestep.py, telegram_bot.py)
└── tests/                             ← Unit tests
```

## Core Rules

### 0. Lyrics-First Workflow
Every new song starts as a lyrics markdown file in `albums/<album>/lyrics/`.

**Workflow:**
1. Create `albums/<album>/lyrics/<NN>_<song_name>.md` with YAML frontmatter + lyrics
2. Review and iterate on lyrics until status is APPROVED
3. Generate with `songmaker generate`

### 1. One Song = One Markdown File
Each song is a `.md` file with YAML frontmatter (prompt, bpm, duration, key) + lyrics.

### 2. Engine Reuse
All engines live in `source_files/` — never duplicate engine code.

### 3. Commit Per Version
Every time lyrics change for a new generation, commit before generating.
Format: `feat(<album>): <song> v<N> — <style>`

## ACE-Step Generation — Tuning Notes (RTX 3090)

Discovered through extensive testing on RTX 3090 (March 2026). These are confirmed best settings.

### Optimal Server Setup
```bash
.venv/bin/python scripts/start_acestep.py --config acestep-v15-turbo --lm-model acestep-5Hz-lm-0.6B --lm-backend vllm
```

### LM Model Comparison
| LM Model | Effect | Verdict |
|----------|--------|---------|
| none | Raw/chaotic, most creative but unpredictable | OK for punk/chaos genres |
| 0.6B | **Sweet spot** — creative + some structure, feels natural | Best default |
| 1.7B | Not tested yet | — |
| 4B | Over-planned, sterile, too "correct" — kills the vibe | Avoid |

**Key insight**: On GTX 1660 (6GB VRAM) the 0.6B was the only LM that fit — this is why old results felt more alive. The 4B LM is too smart and kills creativity.

### Shift Parameter
| Shift | Effect |
|-------|--------|
| 0.0 | Not supported — rounds to 1.0 |
| 1.0 | **Most natural/emotional** — best for ballads, emotional songs |
| 3.0 | Default/recommended — accurate lyrics but slightly sterile |
| 5.0 | Over-structured, conservative |

**Key insight**: `shift: 1.0` with `0.6B LM` = the closest to the GTX 1660 "magic feel".

### Per-Song Recommendations
- **Emotional ballads** (slow songs): `shift: 1.0` + 0.6B LM
- **Punk/chaotic**: `shift: 1.0` + 0.6B LM (or no LM for extra chaos)
- **Structured pop**: `shift: 3.0` + 0.6B LM

### Other Parameters
- `inference_steps: 8` — turbo default, fast and good
- `guidance_scale: 0.0` — turbo ignores CFG, leave at 0.0
- `think_mode: false` — CoT planning. **false = more creative/feeling**, true = more structured
- `lm_temperature: 0.85` — LM sampling temperature. Try `1.1`-`1.2` for more creative outputs
- `infer_method: ode` — diffusion method. `sde` adds stochastic noise = more textured/alive
- `bpm: 0` — let model decide tempo freely (use when BPM feels forced)

## Instrumental Engine (instrumental_engine)

### Available Synth Instruments
| ID | Type | Best For |
|----|------|----------|
| `piano` | Struck-string model | Ballads, pop |
| `bright_piano` | Bright piano | Pop, dance |
| `strings` | Ensemble strings | Ballads, cinematic |
| `supersaw` | 7-voice detuned saw | EDM, trance drops |
| `pad` | Warm additive pad | Ambient, backgrounds |
| `pluck` | Karplus-Strong | Guitar-like arpeggios |
| `sub_bass` | Sine + saturation | Deep bass lines |
| `808_bass` | Heavy 808 | Hip-hop, trap |
| `distorted_guitar` | Distortion + harmonics | Rock, punk |
| `sf:*` | SoundFont (FluidSynth) | Any GM instrument |

### Drum Patterns (PATTERN_LIBRARY)
`basic_rock`, `four_on_floor`, `boom_bap`, `trap`, `reggaeton`, `ballad`, `schlager`, `synthwave`

## Professional Mastering Chain

All tracks use a professional mastering pipeline:

```
Input → Multiband Compression → Stereo Widening → LUFS Normalization → Soft Clipping → MP3
```

| Stage | Description | Key Parameters |
|-------|-------------|----------------|
| **Multiband Compression** | 3-band split, independent compression | 20–250, 250–4000, 4000–20000 Hz |
| **Stereo Widening** | Mid/side encoding, side boost | Width: 1.2× |
| **LUFS Normalization** | ITU-R BS.1770-4 measurement | Target: -14 LUFS |
| **Soft Clipping** | tanh saturation | Ceiling: 0.98 |

## Technical Notes

- **Sample rate**: 44100 Hz everywhere
- **Output format**: Stereo WAV → MP3 320kbps via ffmpeg
- **Python 3.12** (pinned — AI backends require <=3.12)
- **Dependencies**: torch, numpy, scipy, soundfile, librosa, pydantic

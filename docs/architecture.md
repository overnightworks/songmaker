# Songmaker Architecture

## Pipeline

```
songmaker generate <song>.md
    │
    ▼
┌────────────────────────────────────────────┐
│  SONGMAKER CLI (cyclopts)                  │
│  Parse markdown → SongMeta → AceStepConfig │
└────────────┬───────────────────────────────┘
             │
             ▼
┌────────────────────────┐     ┌──────────────────────────┐
│  ACE-Step Client       │────►│  ACE-Step API Server     │
│  acestep_engine/       │     │  (FastAPI, port 8001)    │
│  HTTP POST + polling   │◄────│  Turbo: 8-step inference │
└────────────┬───────────┘     └──────────────────────────┘
             │
             ▼
┌────────────────────────────────────────────┐
│  MASTERING (audio_engine/mastering.py)     │
│                                            │
│  Multiband Compression → Stereo Widening   │
│  → LUFS Normalization → Soft Clipping      │
│  → MP3 Encoding (ffmpeg, 320kbps)          │
└────────────────────────────────────────────┘
```

## File Map

```
src/
├── acestep_engine/
│   ├── client.py           HTTP client, task submission, polling
│   ├── models.py           AceStepConfig, AceStepResult
│   └── __init__.py
│
├── audio_engine/
│   ├── audio_io.py         WAV/MP3 I/O, master_to_mp3
│   ├── mastering.py        Multiband compression, LUFS, stereo, soft clip
│   ├── constants.py        DEFAULT_SAMPLE_RATE (44100)
│   └── __init__.py
│
└── songmaker_cli/
    ├── main.py             generate, check, player commands
    ├── config.py            OutputPaths, build_ace_config
    ├── constants.py         Non-model constants
    ├── parser.py            SongMeta, AlbumMeta, markdown/YAML parser
    └── player.py            HTML player generation
```

## Mastering Chain

```
Input (stereo from ACE-Step, native sample rate)
  │
  ▼
┌──────────────────────────────────────┐
│  MULTIBAND COMPRESSION               │
│  Bass 20-250 Hz   3.0:1             │
│  Mids 250-4k Hz   2.5:1             │
│  Treble 4k-20k Hz 2.0:1             │
└──────────────┬───────────────────────┘
               ▼
┌──────────────────────────────────────┐
│  STEREO WIDENING (1.2x)             │
│  Mid-Side processing                 │
└──────────────┬───────────────────────┘
               ▼
┌──────────────────────────────────────┐
│  LUFS NORMALIZATION                  │
│  Target: -14 LUFS (streaming)        │
│  ITU-R BS.1770-4                     │
└──────────────┬───────────────────────┘
               ▼
┌──────────────────────────────────────┐
│  SOFT CLIPPING                       │
│  tanh() at 0.98 ceiling              │
└──────────────┬───────────────────────┘
               ▼
         MP3 (320 kbps)
```

# Songmaker

AI-powered song generation engine that produces complete songs from markdown files via ACE-Step.

**Created by** Flex0r (Felix) **for** MC Tobbisch (Tobias)

## What It Does

Each song is a markdown file with lyrics and generation config. Run `songmaker generate` and get a mastered MP3.

```bash
songmaker generate albums/wake_up/lyrics/01_where_is_the_love.md
# -> _output/wake_up/01_where_is_the_love_v1.mp3
```

## Engines

| Engine | What it does | Technology |
|--------|-------------|------------|
| **ACE-Step** | Full song generation (vocals + music) | ACE-Step 1.5 (text-to-music AI) |
| **Instrumental** | Beats, bass, leads, pads | Pure DSP + SoundFont (FluidSynth) |

## Albums

| Album | Genre | Theme |
|-------|-------|-------|
| **Wake Up** | Hip-hop / conscious rap | Social commentary, protest |
| **Apologiez** | All genres | Personal album for MC Tobbisch |
| **Download Days** | Punk rock / boom-bap hip-hop | 90s Erlangen nostalgia |
| **Midnight Frequency** | Melodic house | Surrender and freedom |

## Setup

Requires **Python 3.12**, **ffmpeg** on PATH.

```bash
# Create venv and install
python3.12 -m venv .venv
source .venv/bin/activate       # Linux/Mac
pip install -e .

# GPU acceleration (recommended)
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121

# ACE-Step server (required for song generation)
python scripts/start_acestep.py   # Launch API server on port 8001
```

## Project Structure

```
songmaker/
├── source_files/                # Shared engines
│   ├── acestep_engine/          #   ACE-Step client (REST API)
│   ├── bark_engine/             #   Audio I/O, mastering utilities
│   ├── instrumental_engine/     #   DSP synths, drums, SoundFonts, mastering
│   └── songmaker_cli/           #   CLI entry point (generate, sync, player)
├── albums/
│   ├── <album>/lyrics/          # Markdown lyrics (draft -> approved)
│   └── <album>/tracks/          # Complex tracks (Python scripts)
├── _models/                     # AI model weights (gitignored)
│   ├── soundfonts/              #   SoundFont .sf2 files
│   └── acestep/                 #   ACE-Step repo + checkpoints
├── _cache/                      # Temp/cached files (gitignored)
├── _output/                     # Generated audio per album (gitignored)
├── scripts/                     # Utilities (setup, bot, ACE-Step server)
├── tests/                       # Unit tests (pytest)
└── pyproject.toml               # Dependencies, tool config
```

## Key Conventions

- **Sample rate**: 44100 Hz everywhere
- **Output**: Stereo WAV -> MP3 320kbps via ffmpeg
- **Mastering chain**: Multiband compression -> Stereo widening -> LUFS -14 -> Soft clipping
- **Lyrics-first workflow**: Write lyrics in markdown, get them approved, then generate

## Development

```bash
make test                        # Run pytest
ruff check source_files/ tests/  # Lint
vulture source_files/ scripts/ tests/ vulture_whitelist.py  # Dead code check
```

## License

MIT

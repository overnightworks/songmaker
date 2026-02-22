# Songmaker

AI-powered song generation engine that produces complete songs (vocals + instrumentals) from pure Python scripts.

**Created by** Flex0r (Felix) **for** MC Tobbisch (Tobias)

## What It Does

Each song is a single `.py` file that defines lyrics, melodies, chord progressions, drum patterns, and arrangement. Run the script and get a mastered MP3.

```bash
python albums/download_days/tracks/01_download_days.py
# -> _output/download_days/01_Download_Days.mp3
```

## Engines

| Engine | What it does | Technology |
|--------|-------------|------------|
| **ACE-Step** | High-quality singing vocals | ACE-Step 1.5 (text-to-music AI) |
| **Bark Vocal** | Singing + speech synthesis | Suno Bark AI |
| **Instrumental** | Beats, bass, leads, pads | Pure DSP + SoundFont (FluidSynth) |
| **RVC** | Voice conversion | Retrieval-based Voice Conversion |
| **XTTS** | Voice cloning | Coqui XTTS v2 |
| **MusicGen** | AI instrumental generation | Meta AudioCraft |
| **Demucs** | Stem separation | Meta Demucs |

## Albums

| Album | Genre | Theme |
|-------|-------|-------|
| **Download Days** | Punk rock / boom-bap hip-hop | 90s Erlangen nostalgia: MP3 downloads, LAN parties, biking |
| **Midnight Frequency** | Melodic house | Surrender and freedom |

## Setup

Requires **Python 3.12** (AI backends need <=3.12), **ffmpeg** on PATH.

```bash
# Create venv and install
py -3.12 -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e .

# Optional extras
pip install -e ".[xtts]"        # XTTS voice cloning
pip install -e ".[musicgen]"    # MusicGen AI instrumentals
pip install -e ".[demucs]"      # Demucs stem separation

# GPU acceleration (recommended, 10-25x faster)
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121

# Optional: download SoundFont files for realistic instruments
python scripts/download_soundfonts.py

# Optional: ACE-Step singing vocals (separate venv, ~5GB models)
python scripts/setup_acestep.py
python scripts/start_acestep.py   # Launch API server on port 8001
```

Or with [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv sync                         # Core deps
uv sync --extra xtts            # + XTTS
make sync                       # Core deps + fairseq patch
make sync-all                   # All extras + fairseq patch
```

## Project Structure

```
songmaker/
├── source_files/                # Shared engines
│   ├── acestep_engine/          #   ACE-Step singing vocals (REST API client)
│   ├── bark_engine/             #   Vocal synthesis (Bark AI)
│   ├── instrumental_engine/     #   DSP synths, drums, SoundFonts, mastering
│   ├── rvc_engine/              #   Voice conversion (optional)
│   ├── xtts_engine/             #   Voice cloning (optional)
│   ├── ai_engine/               #   MusicGen (optional)
│   └── stem_separator/          #   Demucs (optional)
├── albums/
│   ├── <album>/lyrics/          # Markdown lyrics (draft -> approved)
│   └── <album>/tracks/          # One .py per song
├── _models/                     # AI model weights (gitignored)
│   ├── diffsinger/              #   DiffSinger ONNX models + voicebanks
│   ├── rvc/                     #   RVC voice conversion models
│   ├── soundfonts/              #   SoundFont .sf2 files
│   ├── acestep/                 #   ACE-Step repo + checkpoints
│   └── voice_refs/              #   XTTS voice reference audio
├── _cache/                      # Temp/cached files (gitignored)
├── _output/                     # Generated audio per album (gitignored)
├── scripts/                     # Utilities (setup, download)
├── tests/                       # Unit tests (pytest)
├── docs/                        # Architecture docs
└── pyproject.toml               # Dependencies, tool config
```

## Key Conventions

- **Sample rate**: 44100 Hz everywhere
- **Output**: Stereo WAV -> MP3 192kbps via ffmpeg
- **Mastering chain**: Multiband compression -> Stereo widening -> LUFS -14 -> Soft clipping
- **Vocal ducking**: Instrumentals automatically reduce -3dB during vocals
- **Lyrics-first workflow**: Write lyrics in markdown, get them approved, then create track script

## Development

```bash
make test                        # Run pytest
ruff check source_files/ tests/  # Lint
vulture source_files/ scripts/ tests/ vulture_whitelist.py  # Dead code check
```

## License

MIT

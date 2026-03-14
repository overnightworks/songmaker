# Songmaker

AI-powered song generation CLI. Write lyrics in markdown, run one command, get a mastered MP3.

## How It Works

Each song is a markdown file with YAML frontmatter (style prompt, BPM, key, duration) and lyrics. The CLI sends it to an ACE-Step server for generation, then runs a mastering chain and encodes to MP3.

```bash
songmaker generate albums/my_album/lyrics/01_my_song.md

songmaker generate albums/my_album/lyrics/01_my_song.md --shift 1.0 --no-think-mode

songmaker generate albums/my_album/lyrics/01_my_song.md --count 3 --seed 42
```

## Setup

Requires **Python 3.12** and **ffmpeg** on PATH.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .

# Start the ACE-Step server (required for generation)
python scripts/start_acestep.py
```

## Song Format

```markdown
---
title: My Song
album: my_album
track: 1
prompt: >
  upbeat indie rock with driving guitars
bpm: 140
duration: 180
key: Em
language: en
---

## Lyrics

[verse]
First verse here...

[chorus]
Chorus here...
```

## Project Structure

```
songmaker/
├── src/
│   ├── acestep_engine/     ACE-Step HTTP client
│   ├── audio_engine/       Mastering, WAV/MP3 I/O
│   └── songmaker_cli/      CLI (generate, check, player)
├── albums/
│   └── <album>/lyrics/     Song markdown files
├── _output/                Generated audio (gitignored)
├── scripts/                Server setup/start
├── tests/                  pytest suite
└── docs/
    ├── architecture.md     System architecture and mastering chain
    └── testing.md          Test structure and conventions
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `songmaker generate <path>` | Generate a song from markdown |
| `songmaker check <mp3>` | Whisper transcription accuracy check |
| `songmaker player` | Generate HTML player for all albums |

Run `songmaker --help` for all options.

## Development

```bash
pytest tests/
ruff check src/ tests/
```

## Documentation

- [Architecture](docs/architecture.md) — pipeline, file map, mastering chain
- [Testing](docs/testing.md) — test structure, fixtures, coverage targets

## License

MIT

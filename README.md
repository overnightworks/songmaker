# Songmaker

AI-powered song generation platform. Web UI + REST API + CLI backed by [ACE-Step](https://github.com/ace-step/ACE-Step) for music generation, with automated quality scoring and a mastering chain.

## How It Works

Create albums and songs through the web UI or CLI. Each song has lyrics and a style prompt. Songmaker sends them to ACE-Step for generation, runs a multi-band mastering chain, encodes to MP3, and optionally scores the output (Whisper transcription accuracy, emotional dynamics, spectral quality, and more).

## Architecture

- **Frontend**: SvelteKit (static SPA) with audio player, version timeline, and Claude chat assistant
- **Backend**: FastAPI + SQLite (WAL mode), session-based auth, CSRF protection
- **Generation**: ACE-Step server (managed subprocess) on GPU
- **Scoring**: 7-scorer pipeline (Whisper, AudioBox, librosa-based metrics, Claude LLM)
- **CLI**: Thin HTTP client to the same REST API

See [docs/architecture.md](docs/architecture.md) for the full system design.

## Setup

Requires **Python 3.12**, **Node 22**, **pnpm**, and **ffmpeg** on PATH.

```bash
# Backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[server,scoring,whisper,dev]"

# Frontend
cd frontend && pnpm install && pnpm build && cd ..

# Run
songmaker server --port 8080
```

On first launch, the web UI prompts you to create an admin account.

## CLI

The CLI talks to the same API as the web UI:

```bash
songmaker server                           # Start the server
songmaker generate <song.md>               # Generate from markdown
songmaker generate <song.md> --count 3     # Multiple generations
```

Run `songmaker --help` for all options.

## Development

```bash
# Backend tests + lint
pytest tests/ -q --cov=songmaker_cli --cov=audio_engine --cov=acestep_engine --cov-report=term-missing
ruff check src/ tests/

# Frontend checks
cd frontend && pnpm check && pnpm lint && pnpm test
```

## Documentation

- [Architecture](docs/architecture.md) — system design, data flow, middleware stack
- [Testing](docs/testing.md) — test structure, fixtures, coverage targets
- [Security](docs/security.md) — auth, CSRF, rate limiting, headers
- [ACE-Step](docs/acestep.md) — generation server, model variants, parameters

## License

MIT

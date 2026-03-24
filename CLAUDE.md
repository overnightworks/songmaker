# Songmaker — Claude Code Config

## Project

AI-powered song generation and playback platform. A SvelteKit web app provides the UI for creating, generating, reviewing, and listening. All song data lives in SQLite. The CLI is a thin HTTP client that talks to the same API.

**Python**: 3.12 (pinned — AI backends require <=3.12)
**Venv**: `.venv/`
**Node**: 22 LTS
**Package manager**: pnpm
**Frontend**: SvelteKit + TypeScript (strict) in `frontend/`

## CLI (cyclopts + httpx)

The CLI requires the server to be running (`songmaker server`).

```bash
songmaker server [--port 8080] [--open] [-o output_dir] [--root project_root]

songmaker albums
songmaker songs [--album TITLE]
songmaker song <title>

songmaker generate <title> [-n COUNT]
songmaker score <title> [-g GENERATION_NUMBER]
songmaker edit <title> [--lyrics @file.txt] [--prompt STR] [--bpm N] [--duration N] [--key STR]
```

Global options: `--server URL` (default: http://localhost:8080), `-v`/`-q` for verbosity.

## Data Model

```
Song (identity: title + album)
  └── Version (content snapshot: lyrics, prompt, BPM, key, duration, generation_params)
        └── Generation (MP3 output: seed, scores, rating, whisper text)
```

All data in SQLite (`_output/songmaker.db`). Songs created/edited via web UI or CLI.

## Code Standards

### KISS
- Short, self-explanatory methods (~20 lines max)
- No inline comments — use descriptive names
- No God classes — one responsibility per class/module
- Flat over nested, three similar lines > one premature abstraction

### No Hardcoded Strings
- Constants for repeated values (paths, magic numbers)
- Config files or CLI options for user-facing settings

### Separation of Concerns
- Each module does one thing well
- I/O at the edges, pure logic in the middle
- No business logic in CLI handlers — delegate to engine modules

### Testing
- 100% coverage goal (achieved on all core modules)
- pytest fixtures, no test inheritance
- Mock external services (ACE-Step server, ffmpeg, Whisper)
- Unit tests must be fast (< 10 seconds)

### General (Python)
- Type hints on all function signatures
- Prefer dataclasses/pydantic/TypedDict over untyped dicts for structured data
- Functions return values, don't mutate arguments
- No dead parameters, no unused imports, no stale docstrings

### Frontend Code Standards (SvelteKit + TypeScript)
- Same KISS principles as Python — small components, single responsibility
- Components max ~80 lines of script — extract logic into `lib/` if larger
- No `any` — strict TypeScript, no escape hatches
- Props are typed interfaces, not inline types
- Reactive state via Svelte stores/runes, no global mutable variables
- No inline styles — use scoped CSS in `<style>` blocks
- Semantic HTML — use proper elements, not div soup

### Frontend Testing
- Vitest + @vitest/coverage-v8 for unit tests, Testing Library for components
- 100% statement coverage on lib/ (stores, API client, utils)
- Mock API calls, never hit real backend in tests

### Frontend Linting
- ESLint + eslint-plugin-svelte
- Prettier with svelte plugin
- `pnpm check` must pass before committing (svelte-check + tsc --noEmit)

## Key Rules

1. **Database is the source of truth**: All song data lives in SQLite, not in files.
2. **One code path**: CLI and web UI both use the same REST API.
3. **Engine reuse**: All engines live in `src/` — never duplicate engine code.
4. **Never commit secrets or API keys.**

## Project Structure

- `src/acestep_engine/` — ACE-Step HTTP client (with retry), config dataclass, response models
- `src/audio_engine/` — Mastering chain, WAV/MP3 I/O, LUFS measurement
- `src/songmaker_cli/` — CLI + server
  - `main.py` — CLI commands (thin HTTP client via httpx)
  - `cli_client.py` — HTTP helpers (api_get/post/put, resolve_song, poll_job)
  - `server.py` — FastAPI app setup, static files, startup
  - `api.py` — REST API endpoints (CRUD, generation, scoring, chat)
  - `jobs.py` — Background job runners (generation + scoring)
  - `gpu_queue.py` — GPU job queue with ACE-Step lifecycle management
  - `config.py` — ACE-Step config building, output path resolution, generation defaults
  - `generate.py` — Generation engine (decode, master, write MP3)
  - `parser.py` — Data models (SongMeta, AlbumMeta, GenerationParams)
  - `db/` — SQLAlchemy models, queries, engine
  - `scoring/` — Scoring pipeline with ScorerRegistry + individual scorers
  - `claude/` — Claude provider (API + CLI backends)
  - `constants.py` — Shared constants
  - `errors.py` — Error types
- `_output/` — Generated audio + SQLite DB (gitignored)
- `_models/` — AI model weights (gitignored)
- `scripts/` — Server setup/start
- `tests/` — pytest suite (382 tests)
- `frontend/` — SvelteKit frontend app (108 tests)
  - `src/routes/` — SvelteKit pages and layouts
  - `src/lib/components/` — Svelte components
  - `src/lib/stores/` — Svelte stores (player, editor, filter, jobs, settings)
  - `src/lib/api/` — Typed API client and shared types
  - `src/lib/utils/` — Diff, formatting utilities

## Setup

### Backend (Python)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[server,scoring,whisper,dev]"
# ffmpeg must be on PATH
```

### Frontend (SvelteKit)

```bash
cd frontend
pnpm install
pnpm dev              # dev server with HMR (proxies /api to FastAPI)
pnpm build            # production build
pnpm check            # svelte-check + tsc
pnpm lint             # eslint + prettier --check
pnpm test             # vitest
pnpm test:coverage    # vitest with v8 coverage
```

## Workflow

- **Commit before reviewing**: After completing a batch of changes, always commit first, then review.
- **Run tests before committing**: `pytest tests/ -q` must pass. Run `ruff check` on changed files.
- **Frontend changes**: `pnpm check` and `pnpm lint` must pass before committing. Run `pnpm test` for changed modules.

## API Contract

- Backend serves API at `/api/*`, frontend proxied in dev via Vite
- All API types defined in `frontend/src/lib/api/types.ts`
- Types must match Python pydantic models — keep in sync manually
- CLI uses the same `/api/*` endpoints via httpx

## Conventions

- Commit messages: conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`)
- Code and docs in English, lyrics can be any language
- Sample rate: native from ACE-Step (typically 48kHz), `FALLBACK_SAMPLE_RATE = 48000` in `audio_engine.constants`
- Output: Stereo WAV -> MP3 320kbps via ffmpeg
- Mastering: Multiband compression -> Stereo widening -> LUFS -14 -> Soft clipping

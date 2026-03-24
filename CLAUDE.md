# Songmaker — Claude Code Config

## Project

AI-powered song generation and playback platform. Markdown files with lyrics and YAML frontmatter go in, mastered MP3s come out. A SvelteKit web app provides the UI for creating, generating, reviewing, and listening.

**Python**: 3.12 (pinned — AI backends require <=3.12)
**Venv**: `.venv/`
**Node**: 22 LTS
**Package manager**: pnpm
**Frontend**: SvelteKit + TypeScript (strict) in `frontend/`

## CLI (cyclopts)

```bash
songmaker generate <path> [--seed N] [--count N] [--duration N] [--bpm N]
    [--key KEY] [--shift F] [--guidance-scale F] [--inference-steps N]
    [--lm-temperature F] [--infer-method STR] [--think-mode/--no-think-mode]

songmaker check <mp3> [--source <lyrics.md>] [--whisper-model STR]

songmaker score [<mp3>] [--source <lyrics.md>] [--scorers STR]
    [--whisper-model STR] [--all] [--force] [--device cpu|cuda]

songmaker archive [<mp3>] [--below THRESHOLD]

songmaker player [-o output_dir] [--root project_root]

songmaker server [--port 8080] [--open] [-o output_dir] [--root project_root]
```

## Song Format

```markdown
---
title: Song Title
album: album_name
track: 1
prompt: >
  style description for ACE-Step
bpm: 120
duration: 180
key: Am
language: de
---

## Lyrics

[verse]
Lyrics here...

[chorus]
Chorus here...
```

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
- 100% coverage goal
- pytest fixtures, no test inheritance
- Mock external services (ACE-Step server, ffmpeg, Whisper)
- Unit tests must be fast (< 10 seconds); integration tests with audio processing are slower

### General (Python)
- Type hints on all function signatures
- Prefer dataclasses/pydantic/TypedDict over untyped dicts for structured data
- Functions return values, don't mutate arguments
- No dead parameters, no unused imports, no stale docstrings — if you move or remove code, clean up all traces

### Frontend Code Standards (SvelteKit + TypeScript)
- Same KISS principles as Python — small components, single responsibility
- Components max ~80 lines of script — extract logic into `lib/` if larger
- No `any` — strict TypeScript, no escape hatches
- Props are typed interfaces, not inline types
- Reactive state via Svelte stores/runes, no global mutable variables
- No inline styles — use scoped CSS in `<style>` blocks
- Semantic HTML — use proper elements, not div soup
- Accessibility: all interactive elements keyboard-navigable, proper ARIA labels

### Frontend Testing
- Vitest for unit tests, Testing Library for component tests
- Test logic in `lib/` (stores, API client, utils) — high coverage
- Test components that contain logic (forms, player controls)
- Mock API calls, never hit real backend in tests

### Frontend Linting
- ESLint + eslint-plugin-svelte
- Prettier with svelte plugin
- `pnpm check` must pass before committing (svelte-check + tsc --noEmit)

## Key Rules

1. **Lyrics-first workflow**: Songs start as markdown in `albums/<album>/lyrics/`. Finalize lyrics before generating.
2. **One song = one markdown file**: YAML frontmatter + lyrics section.
3. **Engine reuse**: All engines live in `src/` — never duplicate engine code.
4. **Never commit secrets or API keys.**
5. **Commit per version**: Commit lyrics before each generation. Format: `feat(<album>): <song> v<N> — <style>`

## Project Structure

- `src/acestep_engine/` — ACE-Step HTTP client (with retry), config dataclass, response models
- `src/audio_engine/` — Mastering chain, WAV/MP3 I/O, LUFS measurement
- `src/songmaker_cli/` — CLI entrypoint and subcommands
  - `main.py` — Thin CLI adapter (cyclopts commands → engine modules, no business logic)
  - `generate.py` — Generation orchestration (generate, decode, master, score, rank)
  - `batch.py` — Batch scoring (score --all, score single MP3)
  - `archive.py` — Archive bad versions (move to _archive/, threshold filtering)
  - `parser.py` — Markdown + YAML parsing into pydantic models
  - `config.py` — Output path resolution, ACE-Step config building
  - `check.py` — Verbose lyrics check CLI (thin wrapper over scoring.text_accuracy)
  - `scanner.py` — Filesystem scanning, version deduplication
  - `manifest.py` — Player manifest data model + building
  - `player.py` — HTML player generation (thin orchestrator)
  - `server.py` — FastAPI backend for player UI (ratings, scoring, generation)
  - `snapshot.py` — Generation snapshot read/write (frontmatter, scores, generation info)
  - `scoring/` — Scoring pipeline with ScorerRegistry class + decorator registration
- `albums/<album>/lyrics/` — Song markdown files
- `albums/<album>/album.yaml` — Album metadata (title, artist, year)
- `_output/` — Generated audio (gitignored)
- `_models/` — AI model weights (gitignored)
- `scripts/` — Server setup/start
- `tests/` — pytest suite
- `docs/` — Architecture and testing docs
- `frontend/` — SvelteKit frontend app
  - `src/routes/` — SvelteKit pages and layouts
  - `src/lib/components/` — Svelte components
  - `src/lib/stores/` — Svelte stores (player state, WebSocket, jobs)
  - `src/lib/api/` — Typed API client and shared types
- `plans/` — Architecture plans and design docs

## Setup

### Backend (Python)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
# ffmpeg must be on PATH
# ACE-Step server: python scripts/start_acestep.py
```

### Frontend (SvelteKit)

```bash
cd player
pnpm install
pnpm dev          # dev server with HMR (proxies /api to FastAPI)
pnpm build        # production build
pnpm check        # svelte-check + tsc
pnpm lint         # eslint + prettier --check
pnpm test         # vitest
```

## Workflow

- **Commit before reviewing**: After completing a batch of changes, always commit first, then review. This ensures work is safe and reviewable as a clean diff.
- **Run tests before committing**: `pytest tests/ -q` must pass. Run `ruff check` on changed files.
- **Frontend changes**: `pnpm check` and `pnpm lint` must pass before committing. Run `pnpm test` for changed modules.

## API Contract

- Backend serves API at `/api/*`, frontend proxied in dev via Vite
- All API types defined in `frontend/src/lib/api/types.ts`
- Types must match Python pydantic models — keep in sync manually
- WebSocket at `/ws` for real-time generation/scoring progress

## Conventions

- Commit messages: conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`)
- Code and docs in English, lyrics can be any language
- Sample rate: native from ACE-Step (typically 48kHz), `FALLBACK_SAMPLE_RATE = 48000` in `audio_engine.constants`
- Output: Stereo WAV -> MP3 320kbps via ffmpeg
- Mastering: Multiband compression -> Stereo widening -> LUFS -14 -> Soft clipping

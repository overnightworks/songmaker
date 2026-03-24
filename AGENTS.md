# Songmaker — Project Guide

## Overview

Song generation platform: CLI + web app. Takes markdown files (lyrics + YAML config) and produces mastered MP3s via ACE-Step. SvelteKit frontend provides the UI for creating, generating, reviewing, and listening.

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

## Frontend (SvelteKit + TypeScript)

Located in `frontend/`. Communicates with FastAPI backend via REST + WebSocket.

### Source Structure

```
frontend/src/
  routes/                     Pages and layouts
    +layout.svelte            Persistent PlayerBar + nav
    +page.svelte              Dashboard (recent, in-progress)
    create/+page.svelte       Lyrics editor + generation form
    library/+page.svelte      All songs, filter/sort/search
    album/[id]/+page.svelte   Album view
    song/[id]/+page.svelte    Song detail, versions, scores

  lib/
    components/               Svelte components (PlayerBar, Lyrics, etc.)
    stores/                   Svelte stores (player, jobs, websocket)
    api/
      client.ts               Typed fetch wrapper for all endpoints
      types.ts                Shared types (must match Python pydantic models)
```

### Frontend Code Standards

- Same KISS principles as Python — small components, single responsibility
- Components max ~80 lines of script — extract logic into `lib/` if larger
- No `any` — strict TypeScript, no escape hatches
- Props are typed interfaces, not inline types
- Reactive state via Svelte stores/runes, no global mutable variables
- No inline styles — use scoped CSS in `<style>` blocks
- Semantic HTML, proper ARIA labels for accessibility

### API Endpoints

```
POST   /api/songs                Create song (lyrics + meta)
GET    /api/songs/:id            Song detail
PUT    /api/songs/:id            Update lyrics/meta
GET    /api/songs/:id/versions   List all versions
POST   /api/songs/:id/generate   Enqueue generation
POST   /api/versions/:id/rate    Rate a version
POST   /api/versions/:id/score   Trigger scoring
GET    /api/albums               List albums
GET    /api/library              Paginated, filtered, sorted
GET    /api/jobs                 Active jobs
WS     /ws                      Real-time generation/scoring progress
```

### Dev Commands

```bash
cd player
pnpm dev          # dev server (proxies /api to FastAPI)
pnpm build        # production build
pnpm check        # svelte-check + tsc
pnpm lint         # eslint + prettier --check
pnpm test         # vitest
```

## Self-Review (required for refactors and multi-file changes)

After completing a refactor, bug fix that touches multiple files, or any structural change, do a self-review before presenting the result:

1. **Re-read changed files in full** — not just the diff. Does each module still read as a coherent whole, or does it look like patches were bolted on? If a function was moved from A to B, did you remove all traces from A (dead parameters, unused imports, stale docstrings)?

2. **Question your own abstractions** — if you introduced a new type, interface, or pattern, can you explain it in one sentence? If not, simplify. Prefer typed structures (dataclass, TypedDict) over untyped dicts. Don't trade one code smell for a milder one — solve the actual design problem.

3. **Check for half-measures** — did you solve each issue in isolation, or did you step back and ask whether the overall result makes sense? Fixing a checklist of issues point-by-point without considering how the fixes interact is how you end up with incoherent code that satisfies every requirement but reads like patches.

4. **Run the tests** — `pytest tests/` must pass. For frontend: `pnpm test` must pass. If tests had to change, verify the new tests are testing behavior, not implementation details. If you changed a public interface, make sure tests cover the new contract.

5. **Verify no regressions** — `ruff check src/ tests/` must pass. For frontend: `pnpm check && pnpm lint` must pass. No new type: ignore or @ts-ignore annotations unless genuinely unavoidable.

Skip this for trivial single-file changes (typo fixes, adding a constant, etc.).

## Testing

See [docs/testing.md](docs/testing.md) for test structure, fixtures, and coverage targets.

```bash
# Backend
pytest tests/
ruff check src/ tests/

# Frontend
cd player
pnpm check
pnpm lint
pnpm test
```

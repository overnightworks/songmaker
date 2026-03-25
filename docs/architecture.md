# Songmaker Architecture

## Overview

```
┌──────────────────────────────────────┐
│   SvelteKit Frontend                 │
│   Song editor, player, Claude chat,  │
│   generation settings, filters       │
└───────────────┬──────────────────────┘
                │ REST API (JSON)
                ▼
┌──────────────────────────────────────┐
│   FastAPI Backend                    │
│   Auth middleware → API endpoints    │
│   Pydantic request/response models   │
└───┬──────────┬──────────┬────────────┘
    │          │          │
 SQLite    GPU Queue    External Services
 (all data)  (serial)   (ACE-Step, Claude, Whisper)
```

## Layers

### Frontend (`frontend/`)

SvelteKit single-page app. All state in Svelte stores.

| Layer | What | Key files |
|-------|------|-----------|
| Routes | Pages: main view, login, setup, settings | `src/routes/` |
| Components | SongEditor, PlayerBar, SongList, GenerationDetail, ClaudeChat, etc. | `src/lib/components/` |
| Stores | Reactive state: player, editor, filter, jobs, auth, settings, ui | `src/lib/stores/` |
| API client | Typed HTTP client, mirrors `api_models.py` | `src/lib/api/client.ts`, `types.ts` |

The API client and `types.ts` are the frontend's contract with the backend. When `api_models.py` changes, `types.ts` must match.

### Backend (`src/songmaker_cli/`)

| Layer | Responsibility | Key files |
|-------|---------------|-----------|
| HTTP | FastAPI app, CORS, security headers, body size limit, SPA fallback | `server.py` |
| Auth | Session middleware, login/setup/logout, password change, brute-force protection | `middleware.py`, `auth_api.py`, `auth.py` |
| API | REST endpoints split by domain: albums, songs, generations, chat | `api.py` (aggregator), `album_api.py`, `song_api.py`, `generation_api.py`, `chat_api.py`, `admin_api.py` |
| Helpers | Shared access checks, rate limiting, slug generation | `api_helpers.py` |
| Models | Pydantic request/response with `from_orm()` | `api_models.py` |
| Jobs | Background generation + scoring runners | `jobs.py` |
| GPU | Sequential job queue, ACE-Step lifecycle, VRAM management | `gpu_queue.py` |
| Generation | ACE-Step call → decode WAV → master → MP3 | `generate.py` |
| Config | ACE-Step config building (merges defaults + user + song params) | `config.py` |
| DB | SQLAlchemy ORM models, query functions, engine init | `db/` |
| Scoring | Fault-isolated pipeline: text accuracy, dynamics, BPM, silence, spectral, aesthetics, coherence | `scoring/` |
| Claude | API + CLI backends for chat and lyrical coherence | `claude/provider.py` |
| CLI | Thin HTTP client to the same API | `main.py`, `cli_client.py` |

### Engine packages (`src/`)

| Package | Purpose |
|---------|---------|
| `acestep_engine` | HTTP client for the ACE-Step server (generate, poll, model info) |
| `audio_engine` | Mastering chain (multiband compression, stereo widening, LUFS normalization, MP3 encoding), WAV I/O |

## Data Model

```
User (username, role: admin|user, bcrypt hash)
  ├── Album (title, artist — owned via created_by)
  │     └── Song (title, track_number)
  │           ├── Version (lyrics, prompt, BPM, key, duration, generation_params)
  │           └── Generation (MP3, seed, status, whisper_text)
  │                 ├── Score (scorer, value JSON)
  │                 └── Rating (0-100, notes)
  ├── Job (type, status, progress, error)
  └── AuditLog (action, resource_type, resource_id, detail)

Also: UserSession, LoginAttempt
```

SQLite with WAL mode. SQLAlchemy ORM. Alembic migrations. DB file permissions `600`.

## API Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/albums` | user | List albums (filtered by ownership) |
| POST | `/api/albums` | user | Create album |
| GET/PUT | `/api/songs/{id}` | user | Get/update song |
| POST | `/api/songs` | user | Create song in album |
| POST | `/api/songs/{id}/generate` | user | Submit generation job |
| POST | `/api/generations/{id}/score` | user | Submit scoring job |
| POST | `/api/generations/{id}/rate` | user | Rate a generation |
| POST | `/api/generations/{id}/pick` | user | Pick best generation |
| GET | `/api/jobs/{id}` | user | Poll job status |
| POST | `/api/chat` | user | Claude chat (rate-limited) |
| GET | `/api/capabilities` | user | Feature flags |
| * | `/api/admin/*` | admin | User CRUD, sessions, audit log, ACE-Step control |
| * | `/api/auth/*` | public | Login, logout, setup, password change |
| GET | `/audio/{album}/{file}` | user | Serve MP3 files (ownership-checked) |

## Generation Flow

```
POST /api/songs/{id}/generate
  → rate limit check (per-user)
  → ownership check
  → create Job record + audit log entry
  → submit to GpuQueue
  → GpuQueue._prepare_mode("generate")
    → clear scoring models from VRAM
    → start ACE-Step server if not running
  → run_generation_job()
    → build config (song params + admin defaults + model defaults)
    → ACE-Step HTTP API → WAV bytes
    → decode → master (multiband compress, LUFS normalize) → MP3
    → create Generation record in DB
  → Job status: completed
```

## Scoring Flow

```
POST /api/generations/{id}/score
  → rate limit check (per-user)
  → ownership check
  → create Job record + audit log entry
  → submit to GpuQueue
  → GpuQueue._prepare_mode("score")
    → stop ACE-Step server
    → free VRAM (gc + torch.cuda.empty_cache)
  → run_scoring_job()
    → run_scoring_pipeline() — each scorer fault-isolated:
      text_accuracy (Whisper), emotional_dynamics, bpm_accuracy,
      silence_detection, spectral_quality, audiobox_aesthetics,
      lyrical_coherence (Claude)
    → save scores + whisper text to DB
  → Job status: completed
```

## VRAM Management

Single RTX 3090 shared between generation and scoring. Only one mode active at a time.

```
generate mode: ACE-Step server (loads DiT + LM models)
score mode:    Whisper large-v3 + AudioBox (loaded on demand, cached)
```

Mode switching: stop ACE-Step → `gc.collect()` + `torch.cuda.empty_cache()` → verify VRAM freed → load scoring models. Reverse for generation.

## Key Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Single code path | CLI → API → DB | No duplication between CLI and web |
| Pydantic from_orm() | Response models serialize ORM objects | No manual dict layer to maintain |
| GPU queue | Single-threaded, in-process | One GPU, ACE-Step + scoring share VRAM |
| Scoring isolation | try/except per scorer | One crash doesn't block others |
| Session auth | Cookies, not JWT | Revocable, HttpOnly, simpler for monolith |
| Album ownership | `created_by` on Album | Songs inherit access, future-proof for sharing |
| SQLite + WAL | Single-server, no external deps | No Redis/Postgres overhead |
| ACE-Step as subprocess | Separate server, managed lifecycle | Clean VRAM release, independent restarts |
| Typed API contract | `api_models.py` ↔ `types.ts` | Backend and frontend stay in sync |

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
 PostgreSQL  Redis              External Services
 (all data)  (queue,RL,sessions) (ACE-Step, Claude, Whisper)
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
| Worker | arq-based job queue, ACE-Step lifecycle, VRAM management | `worker.py`, `acestep_manager.py`, `arq_pool.py` |
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
  ├── Album (title, artist, share_slug?, is_shared — owned via created_by)
  │     └── Song (title, track_number)
  │           ├── Version (lyrics, prompt, BPM, key, duration, generation_params)
  │           └── Generation (MP3, seed, status, whisper_text)
  │                 ├── Score (scorer, value JSON)
  │                 └── Rating (0-100, notes)
  ├── Job (type, status, progress, error)
  └── AuditLog (action, resource_type, resource_id, detail)

Also: UserSession, LoginAttempt
```

PostgreSQL with connection pooling. SQLAlchemy ORM. Alembic migrations. Redis is a required dependency — the server will refuse to start if Redis is unreachable.

## API Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/albums?offset=0&limit=50` | user | List albums with pagination (filtered by ownership) |
| POST | `/api/albums` | user | Create album |
| DELETE | `/api/albums/{id}` | user | Delete album (cascade: songs, generations, files) |
| GET/PUT | `/api/songs/{id}` | user | Get/update song |
| PUT | `/api/songs/{id}/album` | user | Move song to different album |
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
| GET | `/health` | public | Liveness/readiness probe (DB, GPU queue, ACE-Step, active model) |
| GET | `/metrics` | public | Job stats, HTTP request counters, VRAM usage |
| POST | `/api/albums/{id}/share` | user | Enable sharing, return secret link |
| DELETE | `/api/albums/{id}/share` | user | Revoke sharing |
| GET | `/shared/{slug}` | public | Read-only album view (no auth, rate-limited) |
| GET | `/shared/{slug}/audio/{file}` | public | Stream MP3 for shared album (no auth, rate-limited) |
| POST | `/api/songs/{id}/reimport` | user | Upload MP3/WAV to reimport into a song |
| GET | `/audio/{owner_id}/{file}` | user | Serve audio files (MP3/WAV, ownership-checked by user ID) |

## Generation Flow

```
POST /api/songs/{id}/generate  (optional: {"model": "sft"} for model validation)
  → rate limit check (per-user)
  → ownership check
  → model validation (if specified — reject 409 if active model doesn't match)
  → create Job record + audit log entry
  → enqueue to arq (Redis-backed)
  → arq worker: prepare_generate_mode()
    → ensure ACE-Step server is running (start if needed)
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
  → enqueue to arq (Redis-backed)
  → arq worker: run_scoring_job()
    → run_scoring_pipeline() with parallel CPU/GPU execution:
      GPU scorers (audiobox) run sequentially in main thread
      CPU scorers (text_accuracy via faster-whisper, emotional_dynamics,
        bpm_accuracy, silence_detection, spectral_quality) run concurrently
      Deferred CPU scorers (lyrical_coherence) wait for shared_data from GPU
      Each scorer fault-isolated: one failure does not block others
    → save scores + whisper text to DB
  → Job status: completed
```

## VRAM Management

Single RTX 3090 shared between generation and scoring. `max_jobs=1` serializes all GPU work.

```
ACE-Step server: ~18 GB VRAM (DiT + LM models, stays loaded as subprocess)
faster-whisper:  ~3 GB VRAM (int8_float16, CTranslate2 backend, loads on demand, cached)
AudioBox:        CPU only  (forced via CUDA_VISIBLE_DEVICES="" context manager)
```

Mode switching via `prepare_generate_mode()` / `prepare_score_mode()` in `acestep_manager.py`. Before generation, scoring model caches are cleared and VRAM release is verified. Per-job cleanup: `gc.collect()` + `torch.cuda.empty_cache()` in `finally` blocks.

VRAM verification uses pynvml (NVML) for system-wide GPU memory measurement with a delta-based check: snapshots VRAM before clearing scoring models, then polls until usage drops back to baseline + margin. Raises `RuntimeError` if not freed, failing the job cleanly instead of OOMing ACE-Step. Falls back gracefully if pynvml is unavailable.

## Key Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Single code path | CLI → API → DB | No duplication between CLI and web |
| Pydantic from_orm() | Response models serialize ORM objects | No manual dict layer to maintain |
| GPU queue | Single-threaded, in-process | One GPU, ACE-Step + scoring share VRAM |
| Scoring isolation | try/except per scorer | One crash doesn't block others |
| Session auth | Cookies + Redis cache | Revocable, HttpOnly, Redis-first reads. Redis TTL is authoritative for session expiry; DB synced every 5 min as backup |
| Redis required | Fail-fast at startup, fail-open rate limiting | Server won't start without Redis; if Redis drops mid-operation, rate limiting allows requests through |
| Album ownership | `created_by` on Album | Songs inherit access; sharing via secret UUID slug |
| PostgreSQL | Connection pooling, concurrent writes | Required alongside Redis |
| ACE-Step as subprocess | Separate server, managed lifecycle | Clean VRAM release, independent restarts |
| Typed API contract | `api_models.py` ↔ `types.ts` | Backend and frontend stay in sync |

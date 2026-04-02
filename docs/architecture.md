# Songmaker Architecture

## Overview

```
                    ┌─────────────────────────────────────┐
                    │        SvelteKit Frontend            │
                    │  Song editor, player, Claude chat,   │
                    │  generation settings, filters        │
                    └──────────────┬──────────────────────┘
                                  │ REST API (JSON)
                                  ▼
                    ┌─────────────────────────────────────┐
                    │        FastAPI Backend               │
                    │  Auth middleware → API endpoints     │
                    │  Pydantic request/response models    │
                    └──┬─────────┬──────────┬─────────────┘
                       │         │          │
                       ▼         ▼          ▼
                 PostgreSQL    Redis    Claude API
                 (all data)   (queues,  (chat, scoring)
                              sessions,
                              rate limits)
```

## Docker Compose Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│ Docker Compose                                                       │
│                                                                      │
│  ┌──────────────────┐   ┌────────────┐   ┌─────────────────────┐    │
│  │  songmaker-web    │   │  postgres   │   │  redis              │    │
│  │  FastAPI + Svelte │──▶│  all data   │◀──│  sessions, queues,  │    │
│  │  port 8080        │   │  port 5432  │   │  rate limits        │    │
│  └────────┬─────────┘   └────────────┘   └──────────┬──────────┘    │
│           │                                          │               │
│           │  enqueue jobs to named Redis queues       │               │
│           │                                          │               │
│           ▼                                          ▼               │
│  ┌────────────────────┐            ┌──────────────────────────────┐  │
│  │  music-worker       │            │  scoring-worker              │  │
│  │                     │            │                              │  │
│  │  GPU + ACE-Step     │            │  CPU (or GPU)                │  │
│  │  subprocess         │            │  Whisper + AudioBox          │  │
│  │                     │            │  subprocess                  │  │
│  │  queue: music       │            │  queue: scoring              │  │
│  │  max_jobs: 2        │            │  max_jobs: 1                 │  │
│  │  CUDA_VISIBLE_      │            │  SCORING_DEVICE=cpu|cuda     │  │
│  │  DEVICES=0          │            │                              │  │
│  └─────────────────────┘            └──────────────────────────────┘  │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐                                  │
│  │  prometheus   │  │  grafana     │                                  │
│  │  scrapes      │──│  dashboards  │                                  │
│  │  /metrics     │  │  port 3000   │                                  │
│  └──────────────┘  └──────────────┘                                  │
└──────────────────────────────────────────────────────────────────────┘
```

## Job Routing

```
User clicks "Generate"                    User clicks "Score"
        │                                         │
        ▼                                         ▼
  POST /songs/{id}/generate               POST /generations/{id}/score
        │                                         │
        ├── rate limit check                      ├── rate limit check
        ├── ownership check                       ├── ownership check
        ├── validate model (admin-enabled)        ├── create Job record
        ├── create Job record                     │
        │                                         ▼
        ▼                                   arq:queue:scoring
  arq:queue:music                          (Redis sorted set)
  (Redis sorted set)                              │
        │                                         ▼
        ▼                                   Scoring Worker
  Music Worker                             ├── spawn scorer subprocess
  ├── auto-switch model if needed          ├── Whisper transcription
  ├── prepare_generate_mode()              ├── AudioBox aesthetics
  ├── apply repaint/cover overrides        ├── BPM, dynamics, silence, spectral
  ├── ACE-Step HTTP → WAV                  ├── lyrical coherence (Claude)
  ├── master → MP3                         ├── save scores to DB
  ├── save Generation (model_mode) to DB   └── Job status: completed
  └── Job status: completed

  Repaint: POST /generations/{id}/repaint
  Cover:   POST /generations/{id}/cover
  Upload:  POST /api/audio/upload (reference audio)

  User clicks "Chat"
        │
        ▼
  POST /songs/{id}/chat
  (multi-turn: loads history from DB,
   sends full messages array to Claude,
   stores user + assistant messages)
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
| Worker | arq-based job queues (music + scoring), ACE-Step lifecycle | `music_worker.py`, `scoring_worker.py`, `worker_base.py`, `acestep_manager.py`, `arq_pool.py` |
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
  │           ├── Generation (MP3, seed, status, whisper_text, model_mode)
  │           │     ├── Score (scorer, value JSON)
  │           │     └── Rating (0-100, notes)
  │           └── ChatMessage (role, content — per-song conversation history)
  ├── Job (type, status, progress, error, queue_position)
  └── AuditLog (action, resource_type, resource_id, detail)

Also: UserSession, LoginAttempt, Playlist, PlaylistEntry,
      GenerationPreset, AvailableModel, RateLimitSetting
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
| POST | `/api/songs/{id}/generate` | user | Submit generation job (→ music queue) |
| POST | `/api/generations/{id}/score` | user | Submit scoring job (→ scoring queue) |
| POST | `/api/generations/{id}/rate` | user | Rate a generation |
| POST | `/api/generations/{id}/pick` | user | Pick best generation |
| GET | `/api/jobs/{id}` | user | Poll job status (includes queue_position) |
| POST | `/api/songs/{id}/chat` | user | Send chat message (multi-turn, rate-limited) |
| GET | `/api/songs/{id}/chat` | user | Load chat history |
| DELETE | `/api/songs/{id}/chat` | user | Clear chat history |
| GET | `/api/chat/recent` | user | Songs with active chats |
| GET | `/api/capabilities` | user | Feature flags |
| * | `/api/admin/*` | admin | User CRUD, sessions, audit log, ACE-Step control |
| * | `/api/auth/*` | public | Login, logout, setup, password change |
| GET | `/health` | public | Per-worker status, DB, Redis, ACE-Step, queue depths |
| GET | `/metrics` | public | Job stats, HTTP counters, VRAM usage (Prometheus) |
| POST | `/api/albums/{id}/share` | user | Enable sharing, return secret link |
| DELETE | `/api/albums/{id}/share` | user | Revoke sharing |
| GET | `/shared/{slug}` | public | Read-only album view (no auth, rate-limited) |
| GET | `/shared/{slug}/audio/{file}` | public | Stream MP3 for shared album (no auth, rate-limited) |
| POST | `/api/songs/{id}/reimport` | user | Upload MP3/WAV to reimport into a song |
| GET | `/audio/{owner_id}/{file}` | user | Serve audio files (MP3/WAV, ownership-checked by user ID) |

## Generation Flow

```
POST /api/songs/{id}/generate  (optional: {"model": "sft"} for model validation)
  → rate limit check (per-user, advisory lock)
  → ownership check
  → model validation (if specified — reject 409 if active model doesn't match)
  → create Job record + audit log entry
  → enqueue to arq (Redis-backed, music queue)
  → music worker: prepare_generate_mode()
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
  → rate limit check (per-user, advisory lock)
  → ownership check
  → create Job record + audit log entry
  → enqueue to arq (Redis-backed, scoring queue)
  → scoring worker: run_scoring_job(device=SCORING_DEVICE)
    → ScorerProcess.score() dispatches to a long-lived subprocess:
      Subprocess calls run_scoring_pipeline() with parallel execution:
        GPU scorers (audiobox) run sequentially
        CPU scorers (text_accuracy via faster-whisper, emotional_dynamics,
          bpm_accuracy, silence_detection, spectral_quality) run concurrently
        Deferred CPU scorers (lyrical_coherence) wait for shared_data from GPU
        Each scorer fault-isolated: one failure does not block others
      Parent kills subprocess on timeout (SIGKILL), freeing GPU memory
    → save scores + whisper text to DB
  → Job status: completed
```

## Worker Architecture

```
                         ┌─ arq:queue:music ──→ Music Worker(s)
  API ─→ route by type ──┤
                         └─ arq:queue:scoring → Scoring Worker(s)

  Chat runs inline in the API process (no arq queue).
```

**Music worker** (`music_worker.py`):
- Owns ACE-Step subprocess lifecycle (start, stop, health check, model switch)
- Handles `generate` and `reinitialize_acestep` tasks
- `max_jobs=2` (one active in ACE-Step, one pre-fetched and waiting)
- Cron: recovers stale generate jobs every 2 minutes, audits orphaned audio files
- Publishes active model and ACE-Step status to Redis

**Scoring worker** (`scoring_worker.py`):
- Owns scorer subprocess (Whisper, AudioBox, Claude coherence)
- Handles `score` tasks
- Device configurable via `SCORING_DEVICE` env var (`cpu` or `cuda`)
- `max_jobs=1` (default, configurable via `SCORING_MAX_JOBS`)
- Cron: recovers stale score jobs every 2 minutes

**Shared infrastructure** (`worker_base.py`):
- DB singleton with thread-safe initialization
- Path helpers (`_audio_dir`, `_data_dir`)
- Timeout constants, terminal status set
- Common startup (env loading, logging, Redis URL validation)
- Common shutdown (per-type stale recovery with Redis advisory lock, DB disposal)
- Orphaned file audit (`audit_orphaned_files()`) — logs disk files with no DB record

**Backwards-compatible shim** (`worker.py`):
- Imports tasks from music_worker and scoring_worker
- Runs both on the legacy `arq:queue` queue
- Logs a deprecation warning on startup

### Adding a new modality

1. Write task function (e.g. `generate_image()`)
2. Add queue constant (`ARQ_IMAGE_QUEUE_NAME`)
3. Add health check function (`is_image_worker_healthy()`)
4. Add API routing (`pool.enqueue_job("generate_image", ..., _queue_name=...)`)
5. Create worker module (`image_worker.py` with `ImageWorkerSettings`)
6. Add Docker Compose service

No existing code changes needed.

## VRAM Management

```
ACE-Step server: ~18 GB VRAM (DiT + LM models, stays loaded as subprocess)
faster-whisper:  ~3 GB VRAM on GPU, runs on CPU when SCORING_DEVICE=cpu
AudioBox:        ~1 GB VRAM on GPU, runs on CPU when SCORING_DEVICE=cpu
```

With separate workers, no VRAM coordination is needed at the application level. The operator configures each worker's device via env vars to match available hardware:

| Deployment | Music worker | Scoring worker | Notes |
|-----------|-------------|----------------|-------|
| Single GPU, 24 GB | GPU 0 | CPU | ACE-Step owns GPU exclusively |
| Single GPU, 48 GB+ | GPU 0 | GPU 0 | Both fit in VRAM |
| Two GPUs | GPU 0 | GPU 1 | Full parallel |

## Key Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Single code path | CLI → API → DB | No duplication between CLI and web |
| Pydantic from_orm() | Response models serialize ORM objects | No manual dict layer to maintain |
| Worker split | Separate arq queues per job type | Independent scaling, device config per worker |
| Scoring subprocess | Long-lived child process, killed on timeout | Real cleanup via SIGKILL, GPU memory freed immediately |
| Scoring isolation | try/except per scorer | One crash doesn't block others |
| Session auth | Cookies + Redis cache | Revocable, HttpOnly, Redis-first reads. Redis TTL is authoritative for session expiry; DB synced every 5 min as backup |
| Redis required | Fail-fast at startup, fail-closed rate limiting | Server won't start without Redis; if Redis drops mid-operation, IP rate limiting returns 503 |
| Album ownership | `created_by` on Album | Songs inherit access; sharing via secret UUID slug |
| PostgreSQL | Connection pooling, concurrent writes | Required alongside Redis |
| ACE-Step as subprocess | Separate server, managed lifecycle | Clean VRAM release, independent restarts |
| Typed API contract | `api_models.py` ↔ `types.ts` | Backend and frontend stay in sync |

## Monitoring

Prometheus + Grafana stack in `docker-compose.yml`. Prometheus scrapes `/metrics` every 15s. Grafana on port 3000 with a pre-provisioned dashboard.

Exported metrics: `songmaker_http_requests_total`, `songmaker_http_request_duration_milliseconds_total`, `songmaker_active_sessions`, `songmaker_jobs_total`, `songmaker_job_duration_seconds`, `songmaker_queue_depth`, `songmaker_gpu_vram_megabytes`.

Health endpoint at `/health` reports:
- `music_worker`: running/stopped
- `scoring_worker`: running/stopped
- `music_queue_depth`, `scoring_queue_depth`: jobs waiting per queue
- `db`, `redis`, `acestep`: component health
- `status`: "ok" or "degraded" (degraded if both workers down, DB down, or Redis down)

## Backup & Restore

`scripts/backup.sh` dumps PostgreSQL + copies the audio Docker volume to `BACKUP_DIR` (default `/mnt/backup/songmaker`). `scripts/restore.sh` restores both. `scripts/backup-list.sh` lists snapshots. See [scripts/BACKUP.md](../scripts/BACKUP.md) for setup instructions.

DB and audio must be backed up and restored together — one without the other leaves orphaned records or unreachable files.

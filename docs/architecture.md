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
│  │  port 8080        │   │  port 5432  │   │  rate limits,       │    │
│  │  + control plane  │   │             │   │  worker state (TTL) │    │
│  └────────┬─────────┘   └────────────┘   └──────────┬──────────┘    │
│           │                                          │               │
│           │  enqueue jobs to named Redis queues       │               │
│           ▼                                          ▼               │
│  ┌────────────────────┐            ┌──────────────────────────────┐  │
│  │  music-worker       │            │  scoring-worker              │  │
│  │  no GPU             │            │  CPU (or GPU)                │  │
│  │  scheduler dispatch │            │  Whisper + AudioBox          │  │
│  │  queue: music       │            │  queue: scoring              │  │
│  │  max_jobs: 2        │            │  max_jobs: 1                 │  │
│  └──────────┬──────────┘            └──────────────────────────────┘  │
│             │ HTTP /load_model, /generate, SSE                       │
│             ▼                                                        │
│  ┌──────────────────────┐  ┌──────────────────────┐                  │
│  │  acestep-worker-0    │  │  acestep-worker-1    │ ← future GPU      │
│  │  GPU + ACE-Step      │  │  (added later, no    │                   │
│  │  subprocess          │  │   code change)       │                   │
│  │  /load_model         │  └──────────────────────┘                   │
│  │  /generate → SSE     │                                             │
│  │  registers w/ web    │                                             │
│  └──────────────────────┘                                             │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐                                  │
│  │  prometheus   │  │  grafana     │                                  │
│  │  scrapes      │──│  dashboards  │                                  │
│  │  /metrics     │  │  port 3000   │                                  │
│  └──────────────┘  └──────────────┘                                  │
└──────────────────────────────────────────────────────────────────────┘
```

ACE-Step worker pool: each `acestep-worker-N` is a peer container with its
own GPU. Workers self-register with the web container at startup
(`POST /api/internal/workers/register`) and heartbeat ephemeral state to
Redis with a 15s TTL. The music-worker is now a thin orchestrator: its
arq `generate` job calls the scheduler (`scheduler.py`), which picks an
online worker, INCRs queue depth atomically, dispatches via HTTP, and
consumes the worker's task SSE stream until `done`. The music-worker then
post-processes the worker's WAV (decode → splice → master → MP3 → DB
insert) and the job completes. See [acestep.md](acestep.md) for the
worker API surface.

## Job Routing

```
User clicks "Generate"                    User clicks "Score"
        │                                         │
        ▼                                         ▼
  POST /songs/{id}/generate               POST /generations/{id}/score
        │                                         │
        ├── rate limit check                      ├── rate limit check
        ├── ownership check                       ├── ownership check
        ├── create Job record                     ├── create Job record
        │                                         │
        ▼                                         ▼
  arq:queue:music                          arq:queue:scoring
  (Redis sorted set)                       (Redis sorted set)
        │                                         │
        ▼                                         ▼
  Music Worker (orchestrator)              Scoring Worker
  ├── apply repaint/cover overrides        ├── spawn scorer subprocess
  ├── scheduler.dispatch_generation:       ├── Whisper transcription
  │   ├── pick acestep-worker              ├── AudioBox aesthetics
  │   ├── INCR queue_depth (Redis)         ├── BPM, dynamics, silence, spectral
  │   ├── /load_model + /generate (HTTP)   ├── lyrical coherence (Claude)
  │   ├── consume SSE → task done          ├── save scores to DB
  │   └── DECR queue_depth (finally)       └── Job status: completed
  ├── post_process_generation (to_thread):
  │   ├── read worker WAV from volume
  │   ├── decode + splice (if repaint)
  │   ├── master → MP3 + ID3 tags
  │   └── INSERT generation + `generation.created` event (one DB transaction)
  └── Job status: completed

  Repaint: POST /generations/{id}/repaint
  Cover:   POST /generations/{id}/cover
  Upload:  POST /api/audio/upload (reference audio)
  Art:     POST /api/albums/{id}/cover (album cover files on the audio volume)

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

The home library has two exclusive modes (Studio and Listen; internal section IDs
`albums` and `playlists`). Studio is albums and songs; Listen is playlists. Share
inventory is a complete server list of the current user's public slugs
(`GET /api/library/shares`), opened from `Shared · N` in the header — including
when mobile detail hides the library nav — not a third library tab. Membership is
public slug reachability (`is_shared` plus slug, not soft-deleted; archived takes
stay). `N` is the unfiltered server total; a type filter pages a subset without
changing `N`. Old `history.state.section === 'shared'` still opens that inventory.
Unshare stays the four resource DELETE endpoints. Studio browse is a wrapping
album-card grid (title, artist, song count, created age, and the cover image
when `cover` is present, otherwise `colors.primary` or title initials), not a
nested song tree; the album overview remains the track
list. Cards wrap with `minmax(0, …)` above 768px and stack at ≤768px
(`LIBRARY_NARROW_MEDIA`); keep-browse uses that same card grid, not a horizontal
shelf. Search still lists song hits under album context; album-only hits may use
card chrome. Desktop keeps compact Studio/Listen navigation in the sidebar.
Opening a Studio song on the detail surface keeps that card grid in a named
browse column beside song detail (`nav browse detail`); Listen playlist detail,
Create, and album overview hide browse. Shared still forces browse, so the
inventory never sits beside `SongDetailView`. On viewports ≤768px, any detail
hides browse and the song header offers album title plus previous/next track. Each mode keeps its
last visible browse/detail context (selection, query, sort, loaded page, scroll,
and song surface) in memory; switching Studio↔Listen replaces the current
history entry and restores that mode's surface. Library context is also stored
on `history.state` (`kind: 'songmaker'`) so browser-back and shell-back restore
the same view. Older history blobs without `detailTab` default to Takes.

| Layer | What | Key files |
|-------|------|-----------|
| Routes | Pages: main view, login, setup, settings | `src/routes/` |
| Components | SongEditor, PlayerBar, SongList, take inspector (`GenerationView`), CoWriterPanel, etc. | `src/lib/components/` |
| Stores | Reactive state: player, editor, filter, jobs, auth, settings, ui | `src/lib/stores/` |
| API client | Typed HTTP client, mirrors `songmaker_cli.api_models` | `src/lib/api/client.ts`, `types.ts` |

The API client and `types.ts` are the frontend's contract with the backend. When `src/songmaker_cli/api_models/` changes, `types.ts` must match.

Frequent studio actions (theme toggle, pick/keep, playlist reorder/remove, new song/playlist, playlist-picker add, account-menu trigger) share the `[data-hitbox='frequent']` primitive in `frontend/src/lib/styles/hitbox.ts`. The visible glyph or inset face stays compact; the control's hitbox is 24×24px on a fine pointer and 44×44px when any pointer is coarse (including hybrid mouse+touch devices). PlayerBar and SharedPlayer are out of this primitive's scope. On viewports ≤768px or any coarse pointer, the shell shows Brand/Back and one account overflow menu (theme, Voices, Settings, username, Logout) instead of inline header links; desktop keeps the same actions inline. Album, song, and playlist details use the app-shell back only — `goBack()` pops browser history when a Songmaker predecessor exists, otherwise restores library browse at `/`. A selected song stays on `SongDetailView` with two surfaces: Recipe (lyrics, prompt, params, Generate) and Takes (list plus in-song inspector). Selecting a take replaces the current history entry and does not push a page. List clicks and previous/next between songs also replace the current song history entry and keep Recipe/Takes; Back returns to the album overview or browse that opened the song, not through every neighbor. Go to song from Now Playing uses that same replace-or-stack rule, then opens Takes on the playing generation. Co-Writer is a Recipe drawer, not a peer tab. Desktop splits Recipe and Takes only when the panes box can give each column at least 360px after the split gap; otherwise the same Recipe | Takes switch as compact. Take rows wrap pick/keep onto their own row so seed text does not paint under the rating. The header is 46px so a 44px overflow-menu hitbox stays inside the 2px bottom border. Settings and Admin use that same compact media: a one-control section/tab selector and stacked action rows, so every control stays reachable at 320px without sideways scroll.

The compact player title is the single entry to Now Playing. That sheet shows the playing take’s song, album/artist, take number, and the lyrics of the version that produced that generation — never the song’s latest draft.

### Backend (`src/songmaker_cli/`)

| Layer | Responsibility | Key files |
|-------|---------------|-----------|
| HTTP | FastAPI app, CORS, security headers, body size limit, SPA fallback | `server.py` |
| Auth | Session dependencies, login/setup/logout, password change, brute-force protection | `middleware/auth.py`, `auth_api.py`, `auth.py` |
| API | REST endpoints split by domain: albums, songs, generations, playlists, library search/shares, LoRAs, chat, settings, admin | `api.py` (aggregator), `album_api.py`, `song_api.py`, `generation_api.py`, `playlist_api.py`, `library_api.py`, `lora_api.py`, `chat_api.py`, `settings_api.py`, `admin_api.py` |
| Helpers | Shared access checks, rate limiting, slug generation | `api_helpers.py` |
| Models | Pydantic request/response with `from_orm()` | `api_models/` |
| Jobs | Background generation + scoring runners | `jobs/` (package: `_runtime.py`, `generation.py`, `scoring.py`, `model_lifecycle.py`) |
| Worker | arq-based job queues (music + scoring), scheduler dispatch | `music_worker.py`, `scoring_worker.py`, `worker_base.py`, `scheduler.py`, `arq_pool.py` |
| ACE-Step worker pool | Peer containers serving ACE-Step over HTTP/SSE | `src/acestep_worker/` (top-level package, separate from `songmaker_cli`) |
| Generation post-process | Decode worker WAV → splice → master → MP3 | `generate.py`, `jobs/generation.py:post_process_generation` |
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
  │     └── Song (title, track_number, share_slug?, is_shared)
  │           ├── Version (lyrics, prompt, BPM, key, duration, generation_params)
  │           ├── Generation (MP3, seed, status, whisper_text, whisper_cues?, model_mode, share_slug?, is_shared)
  │           │     ├── Score (scorer, value JSON)
  │           │     └── Rating (0-100, notes)
  │           └── ChatMessage (role, content — per-song conversation history)
  ├── CowriterUserMemory (durable co-writer notes; survives new conversations)
  ├── ResourceEventCursor (per-user monotonic high-water mark)
  ├── ResourceEvent (30-day durable invalidation history; historical IDs, no resource FK)
  ├── Job (type, status, progress, error, queue_position)
  └── AuditLog (action, resource_type, resource_id, detail)

Also: UserSession, LoginAttempt, Playlist (share_slug?, is_shared), PlaylistEntry,
      GenerationPreset, AvailableModel, RateLimitSetting,
      Conversation / ConversationSummary / ChatMessage (global co-writer thread),
      CowriterSongMemory, CowriterAlbumMemory
```

PostgreSQL with connection pooling. SQLAlchemy ORM. Alembic migrations. Redis is a required dependency — the server will refuse to start if Redis is unreachable.

### Resource event ledger

Every successfully persisted generation from the generation job or reimport path
writes one `generation.created` row in the same transaction. A per-user cursor is
incremented with `UPDATE … RETURNING`, so PostgreSQL serializes concurrent writers
without a process-local lock. The event stores immutable song and generation IDs;
they deliberately are not foreign keys, so retained history survives later resource
deletion. User deletion cascades both cursor and events.

The web-server lifecycle owns a named hourly cleanup task. Events older than 30 days
are deleted while the cursor high-water mark remains intact, allowing the replay
transport to detect retention gaps. Redis is not an authority or publisher for this
ledger.

`GET /api/resource-events/stream` is the authenticated read side. Its auth check and
handshake use one function-local DB session that closes before the response begins;
polls use separate short sessions. A fresh stream sends `hello` with `id: H`. A
reconnect reasserts its existing cursor with `hello` and `id: L`, replays only
`L < sequence <= H`, then becomes
live. Missing retained history, an internal sequence hole, or `L > H` produces one
`resync` at `H`. Heartbeats are SSE comments. Every connection ends after at most 60
seconds so native EventSource reconnect rechecks the session. Sequence and high-water
JSON fields are decimal strings, matching SSE IDs without JavaScript precision loss.

The library page is the sole frontend owner of that stream. Each mount — including
return from settings — opens a native `EventSource`, waits for `hello`, and runs
history restore inside a new snapshot epoch. Events after the epoch watermark are
buffered until the snapshot merges, then the owner is `live`. Targeted
`generation.created` invalidations update the selected song, loaded browse songs,
and loaded search hits through explicit adapters; events for songs that are still
in flight stay queued until those songs enter the loaded set. Browse and album
list writes keep already-loaded takes when a later summary would otherwise wipe
them. History restore
awaits every expanded album before the snapshot is ready so those tracks are in
the loaded set for the buffer flush. Window `focus` and document `visibilitychange`
revalidate the selected song and any failed refresh, not the whole browse page —
a 200-song library would otherwise exceed the 120/min IP limiter. Missed takes for
other loaded songs arrive through EventSource replay. Song fetches run with bounded
concurrency. A 404 drops the song from the loaded set instead of retrying forever.
The open song editor reloads only when the selected song id changes or the user
explicitly applies a fresh song, including after deleting the version on screen.
A live refresh error stays visible across the 60-second reconnect and is retried
on the next `hello`; a later successful fetch clears Retry.
Generation jobs no longer fetch the song themselves. The job tab still shows its
success toast; other tabs update silently. Bootstrap failures retry a bounded
number of times, then surface one accessible Retry status rather than hanging on
`Loading...`. Unmount, logout, and 401/403 on `EventSource.onerror` close the
stream.

## API Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/albums?offset=0&limit=50` | user | List the caller's albums (`q` title contains, `sort=newest\|oldest\|title`). `has_more` is explicit. |
| GET | `/api/songs?offset=0&limit=50` | user | List the caller's songs (`album_id`, `q`, `sort`). `has_more` is explicit. |
| GET | `/api/library/search` | user | Keyset search of the caller's album and song titles. `q` required; `next_cursor` is null iff `has_more` is false. Invalid or mismatched cursors are 422. |
| GET | `/api/resource-events/stream` | user | User-exact `generation.created` SSE with fresh baseline, bounded replay, gap resync, comment heartbeats, and 60-second reauthentication boundary. |
| POST | `/api/albums` | user | Create album |
| GET/POST/DELETE | `/api/albums/{id}/cover` | user | Read, upload/replace, or remove the album cover (JPEG/PNG; ownership 404) |
| DELETE | `/api/albums/{id}` | user | Delete album (cascade: songs, generations, files) |
| GET/PUT | `/api/songs/{id}` | user | Get/update song |
| PUT | `/api/songs/{id}/album` | user | Move song to different album |
| POST | `/api/songs` | user | Create song in album |
| POST | `/api/songs/{id}/generate` | user | Submit generation job (→ music queue) |
| POST | `/api/generations/{id}/score` | user | Submit scoring job (→ scoring queue) |
| POST | `/api/generations/{id}/rate` | user | Rate a generation |
| POST | `/api/generations/{id}/pick` | user | Pick best generation |
| GET | `/api/jobs/{id}` | user | Poll job status (includes queue_position) |
| POST | `/api/jobs/{id}/cancel` | user | Cancel a queued or running job (409 if not active). Terminal; later progress/finalize cannot overwrite. Does not stop in-flight GPU inference. |
| POST | `/api/songs/{id}/chat` | user | Send chat message (multi-turn, rate-limited) |
| GET | `/api/songs/{id}/chat` | user | Load chat history |
| DELETE | `/api/songs/{id}/chat` | user | Clear chat history |
| GET | `/api/chat/recent` | user | Songs with active chats |
| POST | `/api/chat/turn` | user | Co-writer turn — SSE stream of assistant text, tool calls, and a final event with persisted messages. Injects current song, durable memory, server-resolved @-mentions, and the relevant take's whisper/pick/keep/scores (`current_generation_id`). Unknown mention or generation IDs 404; a take for the wrong song or a non-playable take is 422. Provider is the persisted studio setting (`claude`, `grok`, or `codex`); missing credentials fail that provider by name. |
| GET | `/api/settings/cowriter` | user | Co-writer provider, selected model, and live model catalogs from each provider or CLI |
| PUT | `/api/settings/cowriter` | admin | Persist co-writer provider and a model id that exists in that provider's live catalog |
| GET | `/api/memory` | user | Durable co-writer memory (`?song_id=` adds song + album scopes) |
| PUT | `/api/memory/user` | user | Replace user-scope co-writer memory |
| PUT | `/api/memory/songs/{id}` | user | Replace song-scope co-writer memory |
| PUT | `/api/memory/albums/{id}` | user | Replace album-scope co-writer notes |
| GET | `/api/capabilities` | user | Feature flags |
| * | `/api/admin/*` | admin | User CRUD, sessions, audit log, ACE-Step control |
| * | `/api/auth/*` | public | Login, logout, setup, password change |
| GET | `/health` | public | Per-worker status, DB, Redis, ACE-Step, queue depths |
| GET | `/metrics` | public | Job stats, HTTP counters, VRAM usage (Prometheus) |
| POST/DELETE | `/api/albums/{id}/share` | user | Enable/revoke album sharing |
| POST/DELETE | `/api/songs/{id}/share` | user | Enable/revoke song sharing |
| POST/DELETE | `/api/generations/{id}/share` | user | Enable/revoke generation sharing |
| POST/DELETE | `/api/playlists/{id}/share` | user | Enable/revoke playlist sharing |
| GET | `/shared/{slug}` | public | Read-only album JSON (no auth, rate-limited). `cover` is present only while shared and the file exists. |
| GET | `/shared/song/{slug}` | public | Read-only song JSON (no auth, rate-limited) |
| GET | `/shared/gen/{slug}` | public | Read-only generation JSON (no auth, rate-limited) |
| GET | `/shared/playlist/{slug}` | public | Read-only playlist JSON (no auth, rate-limited) |
| GET | `/shared/{slug}/cover` | public | Stream the shared album cover after the same share-slug gate as album JSON |
| GET | `/shared/{slug}/audio/{file}` | public | Stream shared album audio after filename allowlist validation |
| GET | `/shared/song/{slug}/audio/{file}` | public | Stream shared song audio after filename allowlist validation |
| GET | `/shared/gen/{slug}/audio/{file}` | public | Stream shared generation audio after filename allowlist validation |
| GET | `/shared/playlist/{slug}/audio/{file}` | public | Stream shared playlist audio after filename allowlist validation |
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
  → music worker: run_generation_job()
    → build config (model defaults + admin defaults + preset + song params)
    → scheduler.dispatch_generation()
      → pick an online acestep-worker
      → POST /load_model if the target mode is not loaded
      → POST /generate and consume /tasks/{id}/stream SSE until done
    → read worker WAV from the shared audio volume
    → persist Generation + per-user `generation.created` event atomically
    → decode → splice if repaint → master (multiband compress, LUFS normalize) → MP3
    → create Generation record in DB
  → Job status: completed

Cancel (POST /api/jobs/{id}/cancel) sets status=cancelled and completed_at.
`update_job_status` is a no-op once the job is already terminal, so progress
callbacks and finalize cannot revive a cancelled job. The generation runner
stops before setup, before each variant, after the worker returns, and before
persist. Queued cancelled jobs are skipped by `check_job_still_valid`.
In-flight ACE-Step GPU work is not interrupted (issue #30 Phase 2).
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
    → save scores + whisper_text + whisper_cues to DB
  → Job status: completed
```

`whisper_cues` is a JSON list of `{start, end, text}` from faster-whisper segments (start/end in seconds). `null` means never scored or a legacy row; a list (including `[]`) means text_accuracy ran and stored whatever usable cues it produced. `whisper_text` is the same cue texts joined with newlines. Missing timings are not invented.

## Worker Architecture

```
                         ┌─ arq:queue:music ──→ Music Worker(s)
  API ─→ route by type ──┤
                         └─ arq:queue:scoring → Scoring Worker(s)

  Chat runs inline in the API process (no arq queue).
```

**Music worker** (`music_worker.py`):
- Thin orchestrator — no GPU, no ACE-Step process. Dispatches generation jobs
  to acestep-worker peer containers via the scheduler (`scheduler.py`).
- Handles `generate` and `load_model_on_worker` tasks
- `max_jobs=2` (concurrent SSE consumers; the actual generation runs on the
  acestep-worker)
- Cron: recovers stale generate jobs every 2 minutes, audits orphaned audio files
- Post-processes worker WAV → mastered MP3 → DB row in `asyncio.to_thread`

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
- Common startup (logging configuration, stale-job recovery)
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
ACE-Step models:  ~6-12 GB VRAM each (varies by mode), live in acestep-worker containers
faster-whisper:   ~3 GB VRAM on GPU, runs on CPU when SCORING_DEVICE=cpu
AudioBox:         ~1 GB VRAM on GPU, runs on CPU when SCORING_DEVICE=cpu
```

ACE-Step VRAM is owned by `acestep-worker-N` containers, one per GPU. Each worker
holds an LRU cache of loaded models bounded by `VRAM_BUDGET_GB` and reports
its current usage via heartbeat. The music-worker has no GPU access at all.

| Deployment | acestep-worker | Scoring worker | Notes |
|-----------|---------------|----------------|-------|
| Single GPU, 24 GB | GPU 0 (1 container) | CPU | LRU cache holds 1-2 models |
| Single GPU, 48 GB+ | GPU 0 (1 container) | GPU 0 | Larger LRU cache + scoring on same GPU |
| Two GPUs | GPU 0 + GPU 1 (2 containers) | GPU 0 or CPU | Scheduler picks least-busy |

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
| Typed API contract | `api_models/` ↔ `types.ts` | Backend and frontend stay in sync |

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

Album covers live as files on that same audio volume (`covers/{album_id}/` for original plus card and detail derivatives). They are not stored as Base64 in PostgreSQL; the album row only stores `cover_key`. Backup/restore of the audio volume therefore includes covers with no extra volume.

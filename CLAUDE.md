# Songmaker — Claude Code Config

## Project

AI-powered song generation platform. SvelteKit web UI + FastAPI backend + PostgreSQL + Redis. Songs are created, generated via ACE-Step, scored, and reviewed. The CLI is a thin HTTP client to the same API.

**Python**: 3.12 | **Venv**: `.venv/` | **Node**: 22 LTS | **Package manager**: pnpm | **Frontend**: `frontend/`

Docs: [architecture](docs/architecture.md) | [testing](docs/testing.md) | [security](docs/security.md) | [ACE-Step](docs/acestep.md)

**Parallel agents**: If you're implementing a plan alongside other agents, read [plans/COORDINATION.md](plans/COORDINATION.md) before editing any files. It tracks file ownership to prevent merge conflicts.

## Product Context

A musician creates an **album** (a coherent collection of songs — an EP, LP, or concept album). Each **song** belongs to one album. **Playlists** let the user collect favorite songs across albums for listening.

The workflow for a song: write lyrics and a style prompt → **generate** audio via ACE-Step → listen → tweak lyrics/prompt/params → generate again. Each edit creates a **version** (an immutable snapshot of lyrics, prompt, and generation params). Each generation attempt produces a **generation** (an audio file tied to a specific version). One song can have many versions, each version can have many generations.

Two special flags on generations: **pick** marks "this is THE one for this song on the album" (one per song, replaces the previous pick). **Keep** marks "I like this, don't delete it" — survives cleanup but isn't the album pick.

**Scoring** is auto-rating: BPM accuracy, spectral quality, silence detection, emotional dynamics, text accuracy (Whisper transcription of what was actually sung vs the lyrics). Purely informational — helps the user decide which generation sounds best. The Whisper transcript also shows the user what the AI actually sang.

**Co-writer** is a Claude chat per song. The user discusses lyrics, brainstorming, and refinement. Claude can propose changes that the user applies to the current song's editor. Using @-mentions, the user can reference other songs or album context, and Claude can create entirely new songs.

**Seed pinning** lets the user reproduce a generation: pin a seed from a previous generation, regenerate with tweaked params, and get a comparable result (same random noise, different settings). This enables A/B testing of parameter changes.

## Setup & Run

```bash
# Backend (requires Redis + PostgreSQL)
uv sync --extra server --extra scoring --extra whisper --extra dev
uv run songmaker server --port 8080   # Reads DATABASE_URL + REDIS_URL from .server.env

# Frontend (dev mode)
cd frontend && pnpm install && pnpm dev
```

## Checks

During iteration, run **targeted tests** for the files you changed + the linter. Full suite once before committing or when asked.

```bash
# During iteration — fast feedback
ruff check src/ tests/
pytest tests/test_foo.py -q              # just the relevant test file(s)

# Before committing — full parallel suite + coverage
pytest tests/ -n auto -q --cov=songmaker_cli --cov=audio_engine --cov=acestep_engine --cov-report=term-missing

# Frontend
cd frontend && pnpm check && pnpm lint && pnpm test
```

- CI enforces 90% overall coverage; scoring modules excluded from CI (require GPU extras). Locally, aim for 100% on non-scoring modules (exclude `main.py` CLI entrypoint).
- Docs (`docs/`) must stay accurate after changes

## Schema Changes

```bash
alembic revision --autogenerate -m "description"
alembic upgrade head
```

## Where Things Go

| Adding a... | Files to touch | Exemplar |
|---|---|---|
| API endpoint | `api_models.py` → `db/queries/{domain}.py` → `{domain}_api.py` → run `python scripts/generate_types.py` | `album_api.py` |
| Scorer | `scoring/{name}.py` → `scoring/models.py` → `pipeline.py` count → `api_models.py` names | `scoring/silence_detection.py` |
| DB model | `db/models.py` → `db/queries/{domain}.py` → Alembic migration | `db/models.py:Song` |
| Frontend component | `lib/components/` → `lib/stores/` if stateful → `lib/api/client.ts` if new API | `SongList.svelte` |

## Code Patterns (codebase-specific)

These are conventions that aren't obvious from reading a single file:

- **Query functions `flush()`, endpoints `commit()`.** `get_db_session` does NOT auto-commit. Forgetting `session.commit()` in an endpoint = silent data loss. Exception: "commit then raise" in `auth_api.py` login (must persist failed attempt before returning 401).
- **`from_orm()` classmethods on response models.** Never hand-build response dicts. Add a `from_orm()` to the Pydantic model.
- **Engine packages are independent.** `acestep_engine` and `audio_engine` must never import from `songmaker_cli`. Dependency flows one way.
- **Ownership checks on every resource endpoint.** Use `check_song_access()`, `check_album_access()`, `check_generation_access()` from `api_helpers.py`. Never skip, even for GET.
- **Middleware order is security-critical.** See comment block in `server.py`. Do not reorder.
- **DB queries split by domain.** `db/queries/songs.py`, `db/queries/auth.py`, `db/queries/jobs.py`. New queries go in the matching file, re-exported from `db/queries/__init__.py`.
- **No inline comments.** Use descriptive names. Comments in code are a smell — if you need to explain what code does, rename things until you don't.
- **No hardcoded strings.** Use constants in `constants.py` or `Final` module-level variables. Exception: one-off error messages, log messages, and exception descriptions are fine inline — only extract strings that are reused or configure behavior.
- **Pydantic for structured data, not dicts.** Any function returning or accepting a dict with a known schema should use a Pydantic model (or dataclass for internal-only data). Plain dicts are fine for generic key-value stores, `**kwargs`, or serialization helpers — not for domain objects, API responses, or cross-module contracts.

## Key Rules

1. **Database is source of truth** — all data in PostgreSQL, not files
2. **One code path** — CLI and web UI use the same REST API (exception: `reset-password` and `list-users` are local DB escape hatches)
3. **Pydantic models define the API contract** — `api_models.py` → `types.ts` (generated via `python scripts/generate_types.py`)
4. **Never commit secrets** — `.server.env` is gitignored
5. **Commit messages**: conventional commits (`feat:`, `fix:`, `refactor:`, `test:`)

## Known Technical Debt

- **`main.py` escape hatches**: `reset-password` and `list-users` bypass the API. Intentional for emergency recovery.
- **Claude CLI bind mounts in `docker-compose.yml`** are a temporary workaround for using a Max subscription instead of an API key. Three mounts (`~/.local/bin/claude`, `~/.claude`, `~/.claude.json`) give the container access to the host's CLI binary and credentials. When switching to `ANTHROPIC_API_KEY`, remove all three mounts — the provider auto-prefers the API key over CLI.
- **`WorkerSettings.redis_settings` is resolved at import time** from `REDIS_URL`. The env var must be set in the process environment _before_ `arq` imports the module. `.server.env` loading in `on_startup` is too late for this setting — it covers other vars (DB, secrets). The worker now logs a warning on startup if the import-time and post-load values differ.
- **`CLAUDE_CHAT_MODEL` and `CLAUDE_SCORING_MODEL` are resolved at import time** in `constants.py` via `os.environ.get()`. Same constraint as `REDIS_URL` — set these in the process environment (e.g. `docker-compose.yml` `environment:`) before startup, not in `.server.env`.
- **Redis is authoritative for session expiry.** The session sync loop in `lifecycle.py` syncs Redis TTL → DB `expires_at` every 5 minutes. This is intentional — Redis-first reads avoid DB writes on every request. The DB copy is a backup for audit/recovery, not the source of truth.
- **Scorer model caches are module-level globals** (`_whisper_model` in `text_accuracy.py`, `_predictor` in `audiobox_aesthetics.py`). These live in the scorer subprocess, so leaks are contained and cleaned up on subprocess kill. `pytest-xdist` runs each worker in a separate process, so parallel execution is safe.
- **`create_job_with_rate_limit()` and `unique_album_id()` commit the current transaction** before acquiring an exclusive lock. Auth-layer mutations (session renewal, audit records) are committed even on rejection. Callers must not have uncommitted business mutations before calling these functions.
- **VRAM verification** uses delta-based NVML checks (system-wide GPU memory via `pynvml`). Falls back to proceed-with-warning if pynvml is unavailable. Raises `RuntimeError` if scoring models aren't freed, failing the job cleanly instead of OOMing.
- **`slugify()` uses `python-slugify`.** Transliterates Unicode to ASCII (CJK, emoji, accented characters all produce meaningful slugs). The `"untitled"` fallback covers edge cases where transliteration yields an empty string.
- **Backup/restore requires both DB and audio files.** `scripts/backup.sh` dumps PostgreSQL + copies the audio volume to `BACKUP_DIR`. `scripts/restore.sh` restores both atomically. The two must stay in sync — restoring one without the other leaves orphaned records or unreachable files.
- **Trust boundaries: subprocesses share OS user.** ACE-Step and scorer subprocesses run as the same `songmaker` user in Docker with `cap_drop: ALL`. Compromised model weights or ACE-Step code get full user-level disk access. Container-level isolation mitigates this; OS user separation would require separate containers for marginal benefit. Accepted risk for a single-user deployment.
- **Seed reproducibility requires `use_random_seed: false`.** ACE-Step's API ignores the `seed` field unless `use_random_seed` is explicitly `false`. The client sets this automatically based on `config.seed`: `-1` means random, any non-negative value means fixed. The DB stores the seed from the server's response (`seed_value`), not the requested seed.

## Docker

Always use `--wait` with `docker compose up -d` but wrap it in `timeout` to prevent hanging after healthchecks pass (known Docker Compose bug): `timeout 120 docker compose up -d --build --wait`. If timeout fires, check `docker compose ps` — containers are likely already healthy.

## Workflow — Speed

- **Batch changes, test once.** All edits first, suite once at the end.
- **Parallel edits.** Signature change across N files → edit all in parallel.
- **Don't re-read files** you just read in the same conversation.
- **Trust the linter.** Don't run the full suite for trivial changes.
- **One coverage check per task.** `--cov` once at the end.

## Self-Review (multi-file changes)

1. Re-read changed files in full — coherent whole, no dead traces?
2. Question abstractions — explainable in one sentence?
3. Update `docs/` if the change affects architecture, security, API endpoints, or test structure
4. Run checks (above)

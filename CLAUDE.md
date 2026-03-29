# Songmaker — Claude Code Config

## Project

AI-powered song generation platform. SvelteKit web UI + FastAPI backend + PostgreSQL + Redis. Songs are created, generated via ACE-Step, scored, and reviewed. The CLI is a thin HTTP client to the same API.

**Python**: 3.12 | **Venv**: `.venv/` | **Node**: 22 LTS | **Package manager**: pnpm | **Frontend**: `frontend/`

Docs: [architecture](docs/architecture.md) | [testing](docs/testing.md) | [security](docs/security.md) | [ACE-Step](docs/acestep.md)

**Parallel agents**: If you're implementing a plan alongside other agents, read [plans/COORDINATION.md](plans/COORDINATION.md) before editing any files. It tracks file ownership to prevent merge conflicts.

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

# Before committing — full suite + coverage
pytest tests/ -q --cov=songmaker_cli --cov=audio_engine --cov=acestep_engine --cov-report=term-missing

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
- **No hardcoded strings.** Use constants in `constants.py` or `Final` module-level variables.
- **Pydantic for structured data, not dicts.** Any function returning or accepting a dict with a known schema should use a Pydantic model (or dataclass for internal-only data). Plain dicts are fine for generic key-value stores, `**kwargs`, or serialization helpers — not for domain objects, API responses, or cross-module contracts.

## Key Rules

1. **Database is source of truth** — all data in PostgreSQL, not files
2. **One code path** — CLI and web UI use the same REST API (exception: `reset-password` and `list-users` are local DB escape hatches)
3. **Pydantic models define the API contract** — `api_models.py` → `types.ts` (generated via `python scripts/generate_types.py`)
4. **Never commit secrets** — `.server.env` is gitignored
5. **Commit messages**: conventional commits (`feat:`, `fix:`, `refactor:`, `test:`)

## Known Technical Debt

- **`main.py` escape hatches**: `reset-password` and `list-users` bypass the API. Intentional for emergency recovery.
- **`WorkerSettings.redis_settings` is resolved at import time** from `REDIS_URL`. The env var must be set in the process environment _before_ `arq` imports the module. `.server.env` loading in `on_startup` is too late for this setting — it covers other vars (DB, secrets). The worker now logs a warning on startup if the import-time and post-load values differ.
- **Redis is authoritative for session expiry.** The session sync loop in `lifecycle.py` syncs Redis TTL → DB `expires_at` every 5 minutes. This is intentional — Redis-first reads avoid DB writes on every request. The DB copy is a backup for audit/recovery, not the source of truth.
- **Frontend stores Claude API key in localStorage.** The direct-to-Anthropic chat path lets users bring their own key without server config. XSS could expose it, but CSP mitigates this. Documented as a known limitation in `docs/security.md`.
- **`SessionCache.update_ip_ua()` uses a Lua script for atomic read-modify-write.** GET+TTL+SET in a single Redis eval to prevent TOCTOU races on IP/UA updates.
- **Scorer model caches are module-level globals** (`_whisper_model` in `text_accuracy.py`, `_predictor` in `audiobox_aesthetics.py`). These now live in the scorer subprocess, so leaks are contained and cleaned up on subprocess kill. Still prevents `pytest-xdist` parallel execution for scoring tests.
- **`create_job_with_rate_limit()` and `unique_album_id()` commit the current transaction** before acquiring an exclusive lock. Auth-layer mutations (session renewal, audit records) are committed even on rejection. Callers must not have uncommitted business mutations before calling these functions.
- **VRAM verification** uses delta-based NVML checks (system-wide GPU memory via `pynvml`). Falls back to proceed-with-warning if pynvml is unavailable. Raises `RuntimeError` if scoring models aren't freed, failing the job cleanly instead of OOMing.
- **`slugify()` uses `python-slugify`.** Transliterates Unicode to ASCII (CJK, emoji, accented characters all produce meaningful slugs). The `"untitled"` fallback covers edge cases where transliteration yields an empty string.
- **No backup/restore strategy.** Audio files live in `data/audio/`, DB records reference them by relative path. Restoring the DB without the audio directory leaves orphaned records (404 on playback). Restoring audio without the DB leaves unreachable files. Both must be backed up together. Not documented in ops runbooks.
- **Dependencies have upper bounds** in `pyproject.toml` (e.g. `>=2.0,<3`). The `uv.lock` file pins exact versions for reproducible installs. Upper bounds prevent silent breakage on major version bumps for users installing without the lock file.
- **Trust boundaries: subprocesses share OS user.** ACE-Step and scorer subprocesses run as the same `songmaker` user in Docker with `cap_drop: ALL`. Compromised model weights or ACE-Step code get full user-level disk access. Container-level isolation mitigates this; OS user separation would require separate containers for marginal benefit. Accepted risk for a single-user deployment.

## Docker

Always use `--wait` with `docker compose up -d` (e.g. `docker compose up -d --build --wait`). Without it, the command can hang indefinitely after containers are already running, blocking the calling process.

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

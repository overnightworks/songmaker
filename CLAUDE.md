# Songmaker — Claude Code Config

## Project

AI-powered song generation platform. SvelteKit web UI + FastAPI backend + SQLite. Songs are created, generated via ACE-Step, scored, and reviewed. The CLI is a thin HTTP client to the same API.

**Python**: 3.12 | **Venv**: `.venv/` | **Node**: 22 LTS | **Package manager**: pnpm | **Frontend**: `frontend/`

Docs: [architecture](docs/architecture.md) | [testing](docs/testing.md) | [security](docs/security.md) | [ACE-Step](docs/acestep.md)

**Parallel agents**: If you're implementing a plan alongside other agents, read [plans/COORDINATION.md](plans/COORDINATION.md) before editing any files. It tracks file ownership to prevent merge conflicts.

## Setup & Run

```bash
# Backend (requires Redis — `docker run -d redis` or install locally)
source .venv/bin/activate
pip install -e ".[server,scoring,whisper,dev]"
songmaker server --port 8080   # REDIS_URL defaults to redis://localhost:6379/0

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

- Coverage on core modules must stay at 100% (exclude `main.py` CLI entrypoint)
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

## Key Rules

1. **Database is source of truth** — all data in SQLite, not files
2. **One code path** — CLI and web UI use the same REST API (exception: `reset-password` and `list-users` are local DB escape hatches)
3. **Pydantic models define the API contract** — `api_models.py` → `types.ts` (generated via `python scripts/generate_types.py`)
4. **Never commit secrets** — `.server.env` is gitignored
5. **Commit messages**: conventional commits (`feat:`, `fix:`, `refactor:`, `test:`)

## Known Technical Debt

- **`main.py` escape hatches**: `reset-password` and `list-users` bypass the API. Intentional for emergency recovery.

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

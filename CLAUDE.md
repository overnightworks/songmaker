# Songmaker — Claude Code Config

## Project

AI-powered song generation platform. SvelteKit web UI + FastAPI backend + SQLite. Songs are created, generated via ACE-Step, scored, and reviewed. The CLI is a thin HTTP client to the same API.

**Python**: 3.12 | **Venv**: `.venv/` | **Node**: 22 LTS | **Package manager**: pnpm | **Frontend**: `frontend/`

Docs: [architecture](docs/architecture.md) | [testing](docs/testing.md) | [security](docs/security.md) | [ACE-Step](docs/acestep.md)

## Setup & Run

```bash
# Backend
source .venv/bin/activate
pip install -e ".[server,scoring,whisper,dev]"
songmaker server --port 8080

# Frontend (dev mode)
cd frontend && pnpm install && pnpm dev
```

## Checks

Run after every change. After refactors, also check coverage.

```bash
# Backend
pytest tests/ -q
ruff check src/ tests/
# + coverage after refactors:
pytest tests/ -q --cov=songmaker_cli --cov-report=term-missing

# Frontend
cd frontend
pnpm check && pnpm lint && pnpm test
```

- Coverage on core modules must stay at 100% (exclude `main.py` CLI entrypoint)
- Docs (`docs/`) must stay accurate after changes

## Schema Changes

```bash
alembic revision --autogenerate -m "description"
alembic upgrade head
```

## Code Standards

### Python
- KISS: ~20 line methods, no God classes, flat over nested
- Type hints everywhere, Pydantic/dataclass for structured data
- No inline comments — use descriptive names
- No hardcoded strings — use constants
- 100% test coverage on core modules (pytest, mock external services)
- Pydantic response models with `from_orm()` — no manual dict serialization

### Frontend (SvelteKit + TypeScript)
- Same KISS — small components, single responsibility
- No `any` — strict TypeScript
- Svelte stores/runes for state, scoped CSS, semantic HTML
- 100% statement coverage on `lib/` (Vitest + @vitest/coverage-v8)

## Key Rules

1. **Database is source of truth** — all data in SQLite, not files
2. **One code path** — CLI and web UI use the same REST API
3. **Pydantic models define the API contract** — `api_models.py` (Python) ↔ `types.ts` (frontend)
4. **Never commit secrets** — `.server.env` is gitignored
5. **Commit messages**: conventional commits (`feat:`, `fix:`, `refactor:`, `test:`)

## Self-Review (multi-file changes)

1. Re-read changed files in full — coherent whole, no dead traces?
2. Question abstractions — explainable in one sentence?
3. Run checks (above)

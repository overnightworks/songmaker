# Songmaker — Claude Code Config

## Project

AI-powered song generation platform. SvelteKit web UI + FastAPI backend + SQLite. Songs are created, generated via ACE-Step, scored, and reviewed. The CLI is a thin HTTP client to the same API.

**Python**: 3.12 | **Venv**: `.venv/` | **Node**: 22 LTS | **Package manager**: pnpm | **Frontend**: `frontend/`

Architecture: [docs/architecture.md](docs/architecture.md) | Testing: [docs/testing.md](docs/testing.md)

## Setup & Run

```bash
# Backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[server,scoring,whisper,dev]"
songmaker server --port 8080    # starts FastAPI + serves frontend build

# Frontend (dev mode with HMR)
cd frontend && pnpm install && pnpm dev

# CLI (requires server running)
songmaker albums
songmaker songs [--album TITLE]
songmaker generate <title> [-n COUNT]
songmaker score <title> [-g NUM]
songmaker edit <title> [--lyrics @file.txt] [--bpm N] [--key STR]
```

## Checks Before Committing

```bash
# Backend
pytest tests/ -q
ruff check src/ tests/

# Frontend
cd frontend
pnpm check        # svelte-check + tsc
pnpm lint         # eslint + prettier
pnpm test         # vitest
```

## Schema Changes

```bash
# After modifying db/models.py:
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

## Self-Review (for multi-file changes)

1. Re-read changed files in full — coherent whole, no dead traces?
2. Question abstractions — explainable in one sentence?
3. Run tests + lint (both backend and frontend)

## Auth System

- Session-based auth (bcrypt, HttpOnly cookies, brute-force protection)
- Roles: `admin` (sees all) + `user` (sees own albums only)
- Albums have `created_by` → User (ownership)
- CLI: `songmaker list-users`, `songmaker reset-password`, `songmaker reinit-acestep`
- Requires `SESSION_SECRET` env var (generate with `openssl rand -hex 32`)

## Current State

- **Branch**: `feat/auth-system`
- **Tests**: 484 Python + 131 frontend, all passing
- **Next**: Step 10 — Album ownership (see `plans/auth-system.md`)
- **Deferred**: B6 (pagination), B8 (client caching), B9 (E2E tests), Playwright
- **Plans**: `plans/acestep-modes.md` (cover, repaint, reference audio)

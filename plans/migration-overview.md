# Migration Overview: Single-User → Multi-User Platform

> **Status: PLANNING** — all individual plans written, none started.

## Execution Order

```
Phase 0: Feature Flags         (prerequisite — wires env var detection into engine/server)
Phase 1: Redis + PostgreSQL    (parallel — no dependencies on each other)
Phase 2: Celery                (depends on: Redis)
Phase 3: Object Storage        (optional, only for multi-machine — depends on Celery)
         Sessions/Auth         (optional, deferred — depends on Redis + PostgreSQL)
```

## Phase 0: Feature Flag Infrastructure

Before any migration can start, the codebase needs env-var-based backend selection. Currently hardcoded to SQLite + in-memory state.

### What to build

**`engine.py` — Database URL detection** (currently hardcodes SQLite at line 54-70):
- Read `DATABASE_URL` env var (fall back to `sqlite:///{output_dir}/songmaker.db`)
- If URL starts with `postgresql://`: use `QueuePool` (pool_size=5, max_overflow=10, pool_pre_ping=True)
- If URL starts with `sqlite://`: keep current PRAGMAs, connect_args, file permissions
- Skip `_restrict_permissions()` (line 84-90) for non-SQLite
- Skip PRAGMA event listeners (line 20-26) for non-SQLite
- Skip `connect_args={"timeout": 30}` (line 64) for non-SQLite
- Update `alembic/env.py` (at `src/songmaker_cli/db/migrations/env.py`) to use same `DATABASE_URL` detection — currently has its own fallback at line 22-33 via `SONGMAKER_DB_URL`; unify to `DATABASE_URL`

**`server.py` — Redis detection** (new):
- Read `REDIS_URL` env var (default: None)
- If set: create Redis connection pool, pass to rate limiters and metrics
- If unset: use current in-memory classes unchanged
- Remove `UVICORN_WORKERS > 1` guard (line 742-747) when both Redis AND non-SQLite DB are configured

**`server.py` — Celery detection** (new):
- Read `USE_CELERY` env var
- If set: skip `GpuQueue` creation (line 414) and startup (line 425)
- If unset: current behavior

**`app_context.py` — Extend AppContext** (line 17-25):
- Add `redis: Redis | None = None` field
- Add `use_celery: bool = False` field

### Files to change
- `src/songmaker_cli/db/engine.py` — dialect detection, conditional PRAGMAs/pool
- `src/songmaker_cli/db/migrations/env.py` — unify to `DATABASE_URL`
- `src/songmaker_cli/server.py` — Redis/Celery env var reads, conditional startup
- `src/songmaker_cli/app_context.py` — new fields

### Tests
- `test_engine.py` — test SQLite path unchanged, test PostgreSQL pool config (mock)
- `test_server.py` — test with/without REDIS_URL, with/without USE_CELERY

### Why this is Phase 0
Every migration plan references feature flags (`REDIS_URL`, `DATABASE_URL`, `USE_CELERY`) that don't exist yet. Without Phase 0, agents implementing Redis or PostgreSQL have no hook point.

---

## Plans

| # | Plan | What it solves | Effort | Agent-parallelizable? |
|---|------|---------------|--------|----------------------|
| 0 | Phase 0 (above) | Feature flag infrastructure | Small | No — must be first |
| 1 | [migration-redis.md](migration-redis.md) | In-memory state lost on restart, blocks multi-process | Medium | Yes (parallel with #2) |
| 2 | [migration-postgresql.md](migration-postgresql.md) | Write serialization, SQLite-specific hacks | Medium | Yes (parallel with #1) |
| 3 | [migration-celery.md](migration-celery.md) | Zombie threads, job durability, multi-GPU | Large | No — sequential after #1 |
| 4 | [migration-object-storage.md](migration-object-storage.md) | File sharing across machines | Small (deferred) | Yes (independent) |
| 5 | [migration-sessions-auth.md](migration-sessions-auth.md) | Per-request DB writes, OAuth/MFA | Medium (deferred) | Yes (independent) |

## What Each Migration Unblocks

| Capability | Phase 0 | Redis | PostgreSQL | Celery | Obj Storage | Auth |
|------------|---------|-------|------------|--------|-------------|------|
| Multiple uvicorn workers | x | x | | | | |
| Concurrent DB writes | x | | x | | | |
| Durable job queue | | x | | x | | |
| Kill stuck GPU jobs | | | | x | | |
| Multiple GPUs | | | | x | | |
| Multi-machine deployment | | x | x | x | x | |
| OAuth/SSO login | | | x | | | x |
| Survives restart cleanly | | x | | x | | |

## Agent Execution Strategy

```
Human:   Implements Phase 0 (small, touches plumbing everywhere)
Agent A: Redis migration        ← starts after Phase 0 merges
Agent B: PostgreSQL migration   ← starts after Phase 0 merges (parallel with A)
Human:   Celery migration       ← after Redis, too complex for unsupervised agent
Agent C: Object Storage         ← after Celery (deferred, clean interface)
Agent D: Sessions/Auth          ← after Redis + PostgreSQL (deferred)
```

Celery is human-driven because ACE-Step subprocess lifecycle, VRAM management, and job idempotency require judgment calls that agents will get wrong without supervision.

## Docker Compose Target

After Phase 0 through Celery, the deployment looks like:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    volumes: [postgres-data:/var/lib/postgresql/data]
    environment:
      POSTGRES_DB: songmaker
      POSTGRES_USER: songmaker
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
  redis:
    image: redis:7-alpine
    volumes: [redis-data:/data]
  api:
    build: .
    command: songmaker server --port 8080
    environment:
      DATABASE_URL: postgresql://songmaker:password@postgres:5432/songmaker
      REDIS_URL: redis://redis:6379/0
      USE_CELERY: "1"
  worker:
    build: .
    command: celery -A songmaker_cli.celery_app worker --concurrency=1
    environment:
      DATABASE_URL: postgresql://songmaker:password@postgres:5432/songmaker
      REDIS_URL: redis://redis:6379/0
    deploy:
      resources:
        reservations:
          devices: [{capabilities: [gpu]}]
  beat:
    build: .
    command: celery -A songmaker_cli.celery_app beat
    environment:
      REDIS_URL: redis://redis:6379/0
```

## Backwards Compatibility

Every migration is behind an env var:
- `DATABASE_URL` unset or starts with `sqlite://` → SQLite mode (current)
- `REDIS_URL` unset → in-memory fallback (current)
- `USE_CELERY` unset → in-process GPU queue (current)
- `STORAGE_URL` unset → local filesystem (current)

The single-user `songmaker server` command continues to work without any infrastructure dependencies.

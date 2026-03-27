# Agent Coordination

Agents working on plans in parallel MUST read this file before starting and update their status as they work.

## Rules

1. **Read this file first** — check if any files you need are owned by another agent
2. **Claim your files** — add your plan name to the "Active Work" table before editing anything
3. **Update status** — mark phases as you complete them (queued → active → done)
4. **Release files** — remove your entry when done, commit the update

## File Ownership Map

Files that multiple plans touch. If another agent owns a file, DO NOT edit it — wait or coordinate.

| File | Redis | PostgreSQL | Celery | Notes |
|------|-------|------------|--------|-------|
| `engine.py` | | owns | | Dialect detection, pool config |
| `server.py` lines 130-156 (HttpMetrics) | owns | | | Metrics class |
| `server.py` lines 290-315 (IpRateLimit) | owns | | | Rate limiter middleware |
| `server.py` lines 487-531 (metrics cache) | owns | | | Cache + lock |
| `server.py` lines 594-609 (shared limiter) | owns | | | Shared album rate limit |
| `server.py` lines 376-425 (lifespan/startup) | | | owns | GPU queue startup |
| `server.py` lines 439-444 (middleware order) | | | | DO NOT TOUCH |
| `server.py` lines 491-531 (metrics endpoint) | owns | | | Reads from metrics |
| `server.py` lines 742-747 (workers guard) | | owns | | UVICORN_WORKERS check |
| `middleware.py` lines 110-146 (IpRateLimiter) | owns | | | Class definition |
| `api_helpers.py` lines 43-81 | | owns | | BEGIN IMMEDIATE |
| `api_helpers.py` lines 99-108 | | owns | | unique_album_id |
| `app_context.py` | shared | shared | shared | Add fields — coordinate! |
| `db/migrations/env.py` | | owns | | DATABASE_URL |
| `db/queries/jobs.py` lines 141-158 | | owns | | julianday |
| `gpu_queue.py` | | | owns | Entire file |
| `generation_api.py` lines 96-107, 118-130 | | | owns | submit() calls |
| `jobs.py` | | | owns | Task extraction |

### Shared files (multiple agents need to edit)

**`app_context.py`**: Redis adds `redis` field, Celery adds `use_celery` field. Agents must ADD fields, never remove or rename existing ones. Merge is safe if both just append.

**`server.py`**: Split by line ranges above. Each agent owns specific sections. Do not edit outside your owned ranges.

**`pyproject.toml`**: Redis adds `redis[hiredis]`, PostgreSQL adds `psycopg[binary]`, Celery adds `celery[redis]`. All are additive to the `[server]` extras list. Safe to merge.

## Active Work

| Plan | Agent | Status | Branch | Started |
|------|-------|--------|--------|---------|
| | | | | |

<!-- Agents: fill in your row when you start, update status as you go -->
<!-- Status values: queued | active | phase-N | done -->
<!-- Branch: the git branch you're working on -->

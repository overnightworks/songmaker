# Agent Coordination

Agents working on plans in parallel MUST coordinate file ownership to prevent merge conflicts.

## How it works

A SQLite database at `~/.claude/songmaker-coordination.db` (outside the repo) tracks which agent owns which files. All agents — including those in git worktrees — share this database.

## Commands

```bash
# Before starting: claim the files your plan needs
python scripts/coordinate.py claim migration-redis "middleware.py,server.py:130-156,server.py:290-315,server.py:487-531,server.py:594-609"

# Check if a file is available before editing
python scripts/coordinate.py check middleware.py

# See all active work
python scripts/coordinate.py status

# When done: release all claims
python scripts/coordinate.py done migration-redis
```

## Agent workflow

1. Read your plan file
2. Run `python scripts/coordinate.py status` to see what's in progress
3. Run `python scripts/coordinate.py claim <plan> <files>` — if it prints CONFLICT, stop and ask the user
4. Work on a git branch `feat/migration-{plan-name}`
5. If a file you need is claimed by another agent, leave a `# TODO(migration-X): ...` at the call site
6. When done, run `python scripts/coordinate.py done <plan>`

## File ownership reference

See each migration plan for its exact file:line ownership. Summary:

**Redis**: `middleware.py`, `server.py:130-156`, `server.py:290-315`, `server.py:487-531`, `server.py:594-609`
**PostgreSQL**: `engine.py`, `api_helpers.py`, `db/migrations/env.py`, `db/queries/jobs.py:141-158`, `server.py:742-747`
**Celery**: `gpu_queue.py`, `generation_api.py:96-130`, `jobs.py`, `server.py:376-425`

**Shared (additive only)**: `app_context.py` (append fields), `pyproject.toml` (append deps)
**Never touch**: `server.py:439-444` (middleware order is security-critical)

# songmaker

## Commands

- `bash scripts/static_checks.sh`: every static check CI runs, before reporting a tip; needs `.venv` and `frontend/node_modules`.
- `pytest -q <files>`: targeted Python tests that need no database.
- `scripts/test_postgresql.sh <files>`: targeted tests against a throwaway PostgreSQL container.
- `pnpm exec vitest run <file>`: one frontend test file, from `frontend/`.
- `python scripts/generate_types.py`: regenerates the frontend's API types from `api_models/` after a model change.

## Rules

- The live app runs only in Docker, started by the systemd units; `.venv` serves tests and type checking.
- A deploy's `docker compose up --build --wait` never runs inside `timeout`: SIGTERM leaves a partial deploy.
- Query functions `flush()`, endpoints `commit()`. The exceptions commit before an exclusive lock, so their callers hold no uncommitted write: `end_read_transaction_before_lock()` of `api_helpers.py` (used by `create_job_with_rate_limit()` and the slug finders such as `unique_album_id()`), and the sign-in store of `auth_stores.py`, which commits admission and session together.
- Response models are built with `from_orm()`, never as hand-built dicts.
- Every resource endpoint, GET included, checks ownership through a `check_*_access()` of `api_helpers.py`.
- The middleware order in `server.py` is security-critical.
- Sharing goes through `enable_sharing()` and `disable_sharing()` of `db/queries/sharing.py`; side effects live in the domain wrapper.
- ACE-Step's parameter names come from the HTTP API code of `vendor/acestep`, our fork.
- A reproducible seed needs `use_random_seed: false`; ACE-Step ignores `seed` otherwise.
- Each pytest worker process keeps its own numba cache (`tests/conftest.py`); a scorer-test segfault in numba's compiled code means several processes filled one cache.
- Test albums carry a recognizable title prefix and are archived, never deleted.

## Owners

- Deployment is agreed with platform's head.
- The GPU is shared with speech-runtime; its use is agreed with speech-runtime's head.

## Documents

- `README.md`: read when installing, starting or backing up the live app.
- `docs/VISION.md`: read when deciding what the product does.
- `docs/architecture.md`: read when changing structure, routes or the co-writer turn.
- `docs/catalog.md`, `docs/generation.md`, `docs/library.md`, `docs/navigation.md`, `docs/sharing.md`, `docs/co-writer.md`: read when changing a ruled behaviour of that area.
- `docs/security.md`: read when touching sign-in, tokens, sharing, the agent front or the trust model.
- `docs/acestep.md`: read when touching ACE-Step, its fork's pin and patches, or the workers.
- `docs/testing.md`: read when adding tests, or changing CI, coverage floors or the quality gate.

# songmaker

## Commands

- `bash scripts/static_checks.sh`: every static check CI runs, before reporting a tip; needs `.venv` and `frontend/node_modules`.
- `pytest -q <files>`: targeted Python tests that need no database and no Redis server.
- `scripts/test_postgresql.sh <files>`: targeted tests against throwaway PostgreSQL and Redis containers (the database tests and the Redis wire tests).
- `pnpm exec vitest run <file>`: one frontend test file, from `frontend/`.
- `python scripts/generate_types.py`: regenerates the frontend's API types from `src/songmaker_cli/api_models/` after a model change.
- `design-catalogs`: regenerates `frontend/src/lib/words/` from `frontend/src/lib/catalogs/` after a catalog change; `--check` runs in the static checks.

## Rules

- The platform serves the live app; `docker/docker-compose.test.yml` is the test stack for CI's e2e boot, the probes and local runs, and `.venv` serves tests and type checking.
- Every Compose call runs from the repository root as `docker compose --project-directory . -f docker/docker-compose.test.yml ...`, which keeps the per-worktree project name and the root `.env`.
- PostgreSQL is the source of truth, not files.
- One code path: the web UI, a person's token and their agent's marked `/mcp` routes all reach the same API; the CLI only starts the server.
- Functions in `src/songmaker_cli/db/queries/` `flush()` and never `commit()`; the code that owns the transaction commits. A helper that calls `end_read_transaction_before_lock()` commits first, so its caller must hold no uncommitted change.
- Response models are built with `from_orm()`, never as hand-built dicts.
- Every resource endpoint, GET included, checks ownership through a `check_*_access()` of `src/songmaker_cli/api_helpers.py` or a query keyed by the owner.
- The middleware order in `src/songmaker_cli/server.py` is security-critical.
- Sharing goes through `enable_sharing()` and `disable_sharing()` of `src/songmaker_cli/db/queries/sharing.py`; side effects live in the domain wrapper.
- ACE-Step's parameter names come from the HTTP API code of `vendor/acestep`, our fork.
- A reproducible seed needs `use_random_seed: false`; ACE-Step ignores `seed` otherwise.
- A test that needs a real `ffmpeg` requests `locked_ffmpeg` (`tests/support/ffmpeg_binary.py`): the `dev` extra's locked `imageio-ffmpeg` is the only ffmpeg tests run, never the machine's.
- Each pytest worker process keeps its own numba cache (`tests/conftest.py`); a scorer-test segfault in numba's compiled code means several processes filled one cache.
- An interface text of a surface that reads `frontend/src/lib/utils/page-words.ts` is a key in `frontend/src/lib/catalogs/en.po`; any other new interface text goes into its surface's `frontend/src/lib/constants/` file, never as a literal in markup.
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
- design's [language standard](https://github.com/overnightworks/design/blob/main/docs/languages.md): read when adding or moving an interface text.
- `docs/testing.md`: read when adding tests, or changing CI, coverage floors or the quality gate.

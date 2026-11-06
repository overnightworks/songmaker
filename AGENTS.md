# Songmaker

Repository facts only.

SvelteKit UI (`frontend/`, pnpm), FastAPI backend (`src/songmaker_cli/`), PostgreSQL, Redis, ACE-Step workers.

## Product context

An **album** holds **songs**; **playlists** collect songs across albums. Saving rewrites a song's latest **version** until a take is queued or rendering for it, or until it has a take and lyrics, prompt, BPM, key or length change; then it makes a new version. Each attempt is a **generation** (audio tied to one version). **Pick** is the one generation per song on the album; **keep** only protects from cleanup.

The **co-writer** is one conversation per musician, not per song, only via `POST /chat/turn`; it runs `agents/cowriter.md` through the LiteLLM gateway, with no local provider fallback ([architecture](docs/architecture.md)). Its expansion is frozen until needed.

## Setup and run

The live app is Docker-only; `.venv` is for tests and type checking. Settings and not-yet-moved secrets live in one gitignored `.env` in the deploy checkout `~/srv/songmaker`; the other secrets are files in `~/.secrets/songmaker/`. Only systemd units start the stack. Install and first start are in the README.

A deploy's `docker compose up --build --wait` never runs in a `timeout` (a cold rebuild takes 8-15 minutes; a SIGTERM leaves a partial one). After changing a Dockerfile under `docker/base/`, run `scripts/build_images.sh` first.

## Checks

CI runs the pinned quality gate; floors: [testing](docs/testing.md#static-analysis-sonarcloud). Run targeted: `pytest -q <files>`, `scripts/test_postgresql.sh <files>` for database tests, `pnpm exec vitest run <file>`. Before reporting a tip run `bash scripts/static_checks.sh`. Schema changes: `alembic revision --autogenerate`.

## Code patterns

- **Query functions `flush()`, endpoints `commit()`**. Exceptions: the sign-in callback in `auth_api.py` commits admission and session together; `create_job_with_rate_limit()` and `unique_album_id()` commit before an exclusive lock, so callers hold no uncommitted mutation.
- **Response models use `from_orm()`**, not hand-built dicts.
- **Engine packages are independent**: `acestep_engine`, `audio_engine`, `acestep_worker` never import `songmaker_cli` (the worker image lacks it); `.importlinter` owns this.
- **Ownership checks on every resource endpoint**, GET included: `check_*_access()` in `api_helpers.py`.
- **Middleware order in `server.py` is security-critical.**
- **DB queries split by domain** (`db/queries/`); callers import the domain module.
- **Sharing** (Album, Song, Generation, Playlist): `enable_sharing()`/`disable_sharing()` from `db/queries/sharing.py`.
- **Required configuration has no silent default**: raise or 422, or use a NAMED constant; never `next(iter(d))` or insertion order. `scripts/check_no_silent_fallbacks.py` enforces it.

## Key rules

1. PostgreSQL is the source of truth, not files.
2. One code path: the web UI is the only API client; the CLI only starts the server. Sign-in is Keycloak: accounts keyed by its subject, membership and admin from groups `/apps/songmaker` and `/apps/songmaker/admin` at each sign-in.
3. `api_models/` Pydantic models are the API contract; `python scripts/generate_types.py` generates `types.ts`.
4. Test albums get a recognizable name prefix and are archived, not deleted.

## Constraints

- No co-writer turn or cover runs on a Claude CLI, so no song content reaches one; agent-CLI mounts never expose an operator profile.
- The DB owns session validity (`touch()` returns a real `bool`); removing someone ends no session early ([revocation](docs/security.md#revocation)).
- Trust model: [security](docs/security.md#ace-step-worker-pool-trust-boundary).
- Only `songmaker-acestep-worker-N` has a GPU; nothing arbitrates VRAM.
- `vendor/acestep` is our fork; its HTTP API code is the source of truth for param names; pin and patches in [ACE-Step](docs/acestep.md).
- Seed reproducibility needs `use_random_seed: false` (ACE-Step ignores `seed` otherwise).
- Backup and restore need both DB and audio files (`scripts/backup.sh`).

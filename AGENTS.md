# Songmaker

## Product context

An **album** holds **songs**; **playlists** collect songs across albums. Saving rewrites a song's latest **version** until a take is queued or rendering for it, or until it has a take and lyrics, prompt, BPM, key or length change; then it makes a new version. Each attempt is a **generation**; scoring is purely informational. **Pick** is the one generation per song on the album; **keep** only protects from cleanup.

The **co-writer** is one conversation per musician, not per song, only via `POST /chat/turn`; it runs `agents/cowriter.md` through the LiteLLM gateway, no local fallback; expansion is frozen until needed.

## Setup and run

The live app is Docker-only; `.venv` is for tests and type checking. Settings and some secrets live in the ignored `.env` of the deploy checkout `~/srv/songmaker`, the others in `~/.secrets/songmaker/`; only systemd units start the stack.

A deploy's `docker compose up --build --wait` never runs in a `timeout` (SIGTERM leaves a partial deploy).

## Checks

CI runs the pinned quality gate; floors in [testing](docs/testing.md#static-analysis-sonarcloud). Targeted runs: `pytest -q <files>`, `scripts/test_postgresql.sh <files>` for DB tests, `pnpm exec vitest run <file>`. Before reporting a tip: `bash scripts/static_checks.sh`.

## Code patterns

- **Query functions `flush()`, endpoints `commit()`**. Exceptions: the sign-in callback in `auth_api.py` commits admission and session together; `create_job_with_rate_limit()` and `unique_album_id()` commit before an exclusive lock, so callers hold no uncommitted mutation.
- **Response models use `from_orm()`**, not hand-built dicts.
- **Engine packages are independent**: `acestep_engine`, `audio_engine`, `acestep_worker` never import `songmaker_cli`; `.importlinter` owns it.
- **Ownership checks on every resource endpoint**, GET included: `check_*_access()` in `api_helpers.py`.
- **Middleware order in `server.py` is security-critical.**
- **DB queries split by domain** (`db/queries/`); callers import the domain module.
- **Sharing**: `enable_sharing()`/`disable_sharing()` from `db/queries/sharing.py`; side effects in the domain wrapper.
- **Constants:** reused or behaviour-configuring strings go in `constants.py` or a `Final`; one-off messages stay inline.
- **Required configuration has no silent default**: raise or 422, or use a NAMED constant; never `next(iter(d))` or insertion order. `scripts/check_no_silent_fallbacks.py` enforces it.

## Key rules

1. PostgreSQL is the source of truth, not files.
2. One code path: the web UI is the API's one client of songmaker's own; a person's hal token reaches the same API as that person, and a member's own agent reaches the routes of it marked as its tools over `/mcp` as that person, never as an admin; the CLI only starts the server; no passwords, admin bootstrap or local account commands. Sign-in is Keycloak: accounts keyed by its subject, membership and admin from groups `/apps/songmaker` and `/apps/songmaker/admin` at each sign-in.
3. `api_models/` Pydantic models are the API contract; `python scripts/generate_types.py` generates `types.ts`.
4. Test albums get a recognizable name prefix and are archived, not deleted.

## Constraints

- No co-writer turn or cover runs on a Claude CLI, so no song content reaches one; agent-CLI mounts never expose an operator profile. A member's own agent over `/mcp` reaches song content, with its provider, only at that person's request ([security](docs/security.md#mcp-endpoint-for-a-persons-own-agent)).
- The DB owns session validity (`touch()` returns a real `bool`); removing someone ends no session early ([revocation](docs/security.md#revocation)).
- Only `songmaker-acestep-worker-N` has a GPU; nothing arbitrates VRAM.
- Trust model (shared OS user, one worker token, single node), accepted for one user: [security](docs/security.md#ace-step-worker-pool-trust-boundary).
- `vendor/acestep` is our fork; its HTTP API code is the source of truth for param names; pin and patches in [ACE-Step](docs/acestep.md).
- Seed reproducibility needs `use_random_seed: false` (ACE-Step ignores `seed` otherwise).
- Backup and restore need both DB and audio files.
- Parallel pytest workers share no numba cache (`tests/conftest.py` gives each process its own `NUMBA_CACHE_DIR`); a scorer-test segfault in numba's compiled code means several processes populated one cache.

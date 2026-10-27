# Songmaker

Repository facts only. The global contract owns coordination, claims, worktrees, review and code policy; `CLAUDE.md` is exactly `@AGENTS.md`.

AI-powered song generation platform: SvelteKit web UI (`frontend/`, pnpm, Node 22 LTS), FastAPI backend, PostgreSQL, Redis. Songs are created, generated via ACE-Step, scored and reviewed. The CLI only starts the server. Python 3.12, venv `.venv/`.

The README indexes the docs.

## Product Context

A musician creates an **album** (EP, LP or concept album) holding **songs**; each song belongs to one album. **Playlists** collect favourite songs across albums.

Song workflow: write lyrics and a style prompt, **generate** audio via ACE-Step, listen, tweak, generate again. Each edit creates an immutable **version** (lyrics, prompt, generation params); each attempt produces a **generation** (an audio file tied to one version). A song has many versions, a version many generations.

Two flags on generations: **pick** is THE one for this song on the album (one per song, replaces the previous pick); **keep** means "don't delete it" and survives cleanup but is not the album pick.

**Scoring** is purely informational auto-rating: BPM accuracy, spectral quality, silence, emotional dynamics, text accuracy (Whisper transcript of what was sung vs the lyrics, which the user also sees).

**Co-writer** is one active multi-turn conversation per musician, not per song (`chat_messages`, scoped via `conversations`); each turn is one run of `agents/cowriter.md` at the agent service (the model songmaker sends, `claude/opus` by default) that reads and writes songs through the tools songmaker serves at `/mcp`, with no local provider fallback. Memory, tools and @-mentions: [architecture](docs/architecture.md). Co-writer expansion (more memory or mention features) is frozen until organically needed (operator ruling 2026-08-24). There is no per-song chat; the co-writer runs only through `POST /chat/turn` in `conversation_api.py`.

**Seed pinning** reproduces a generation (pin a previous seed, regenerate with tweaked params).

## Setup and run

The live app is Docker-only; there is no local server path. `.venv` is for tests, type checking and IDE only. Application secrets and settings live in one gitignored `.env` at the root of the deploy checkout `~/srv/songmaker`; only its systemd units start the live stack, and a work clone has no `.env`. The non-secret `SONGMAKER_CLAUDE_CLI`, `SONGMAKER_GROK_CLI` and `SONGMAKER_CODEX_CLI` overrides are the exception: the preflight reads only their exported deployment environment values. Install, first start and model download (`scripts/download_models.sh`, needs `HF_TOKEN` in `.env`) are in the README; `pnpm dev` runs the frontend alone. The external network `hal_backchannel_songmaker` is edge's: edge's `hal apply` creates it, and CI's `e2e.yml` creates its own.

**Docker:** never wrap `docker compose up --build --wait` in `timeout`. A cold-cache rebuild of all 5 images takes 8-15 minutes (the acestep-worker alone is 8.84 GB); a shorter timeout SIGTERMs mid-build silently and leaves a partial deploy. After changing a Dockerfile under `docker/base/`, run `scripts/build_images.sh` first, or compose fails with `manifest unknown` for `songmaker/acestep-base:latest`.

## Checks

CI runs the pinned reusable quality gate (`quality / verdict`, mandatory jobs in `quality/config.toml`); coverage floors, Sonar and transport are in [testing](docs/testing.md#static-analysis-sonarcloud).

Local runs are targeted: `pytest -q` on the named files, `pnpm exec vitest run` on the named frontend file.

Before reporting a tip, run `bash scripts/static_checks.sh`: it runs CI's static gates (ruff, import contracts, the repository scripts, svelte-check, eslint, prettier, quality hygiene at CI's pin) and stops at the first red one, naming it. It needs `.venv` and `frontend/node_modules`; the script lists the gates.

Schema changes: `alembic revision --autogenerate -m "..."`, then `alembic upgrade head`.

## Code patterns

- **Query functions `flush()`, endpoints `commit()`.** Backend paths are under `src/songmaker_cli/`. `get_db_session` does not auto-commit; a missing `session.commit()` in an endpoint is silent data loss. Exception: the sign-in callback in `auth_api.py` commits the admission and the new session together, before it issues the cookies. `create_job_with_rate_limit()` and `unique_album_id()` commit the current transaction before taking an exclusive lock, so callers must hold no uncommitted business mutation.
- **`from_orm()` classmethods on response models**; never hand-build response dicts.
- **Engine packages are independent.** `acestep_engine`, `audio_engine` and `acestep_worker` never import `songmaker_cli`; the acestep-worker image does not install it and would crash at startup. `acestep_engine` and `acestep_worker` each own a `settings.py`. `.importlinter` (judged by quality's `import-contract` rule in CI) owns the boundary. `agent_providers` and `webauth` are installed release wheels from their own repositories; `lint-imports` does not scan their internals, so a chain reaching the application through a wheel is not caught. Neither imports `songmaker_cli` today.
- **Ownership checks on every resource endpoint**, GET included: `check_song_access()`, `check_album_access()`, `check_generation_access()` from `api_helpers.py`.
- **Middleware order in `server.py` is security-critical.** Do not reorder.
- **DB queries split by domain** (`db/queries/songs.py`, `auth.py`, `jobs.py`); new ones go in the matching file, and callers import that domain module directly.
- **Sharing via `ShareMixin`** (Album, Song, Generation, Playlist): use `enable_sharing()`/`disable_sharing()` from `db/queries/sharing.py`; entity side effects go in the domain wrapper.
- **Constants:** reused or behaviour-configuring strings live in `constants.py` or as `Final` module-level values; one-off error, log and exception messages stay inline.
- **Required configuration has no silent default.** Reject missing input (raise or 422) or use a NAMED constant; never fall through to `next(iter(some_dict))` or insertion order. Origin: 2026-04-08, a truncated `available_models` table made `resolve_model_mode(None)` return `'turbo'` for every generation. `scripts/check_no_silent_fallbacks.py` enforces it in CI.

## Key rules

1. The database is the source of truth: all data in PostgreSQL, not files.
2. One code path: the web UI is the REST API's only client, and the CLI only starts the server (`songmaker server`). People sign in through Keycloak (`GET /login/oidc`, `GET /auth/callback`, `POST /auth/logout`); the app holds no passwords, no admin bootstrap and no local account commands. Accounts are keyed by the Keycloak subject; membership and the admin role come from the groups `/apps/songmaker` and `/apps/songmaker/admin` at each sign-in.
3. Pydantic models in `api_models/` define the API contract; `python scripts/generate_types.py` generates `types.ts`.
4. Test albums (verify, proof, throwaway, QA runs) get a recognizable name prefix and are archived, not deleted, once verified.

## Constraints and known debt

- **Claude CLI call paths carry song content only through the tool-surface gate** (`verify_cli_tool_surface()` and `verify_no_builtin_cli_tools()` in `agent_providers/claude/provider.py`; the co-writer expects exactly the twelve tools in `MCP_TOOL_NAMES`, `cowriter/mcp_spec.py`). A drifted surface refuses the call, never server startup; `GET /health` reports `ok`/`drift`/`unverified`. Mechanics, caches and single-flight: [Claude Chat Security](docs/security.md#claude-chat-security).
- **Agent-CLI bind mounts** never expose an operator profile; `ANTHROPIC_API_KEY` serves the API routes (judge, catalog) but does not replace the mounted CLI the CLI routes (judge, cover) need: [Agent-CLI Mounts](docs/security.md#agent-cli-mounts).
- **The DB owns session validity** (`touch()` must return a real `bool`). `get_current_user` commits renewal in its own short transaction; stores never commit endpoint writes; stream callers commit before streaming. Keycloak group changes apply only at the next sign-in, so removing someone ends nothing until their sessions expire: revoke as described in [Authentication](docs/security.md#revocation).
- **Trust model** (subprocesses share the OS user, one shared worker token, single-node): accepted for a single-user deployment; rationale and limits in [Worker Pool Trust Boundary](docs/security.md#ace-step-worker-pool-trust-boundary).
- **GPU isolation is by container.** Only `songmaker-acestep-worker-N` has a GPU; `songmaker-scoring-worker` runs `SCORING_DEVICE=cpu`, so nothing arbitrates VRAM. NVML and worker health: [ACE-Step](docs/acestep.md#operating-the-worker-pool).
- **ACE-Step submodule:** `vendor/acestep` is our fork [FlexOr2/ACE-Step-1.5](https://github.com/FlexOr2/ACE-Step-1.5); upstream remote `upstream`. The fork carries patches not yet upstream (see [ACE-Step](docs/acestep.md) for the pin and patch list). The fork's HTTP API code (`vendor/acestep/acestep/api/http/`) is the source of truth for param names. Check upstream PR status live: `gh pr list --repo ACE-Step/ACE-Step-1.5 --author FlexOr2 --state open`.
- **Seed reproducibility needs `use_random_seed: false`**: ACE-Step ignores `seed` otherwise. The client sets it from `config.seed` (`-1` random, non-negative fixed); the DB stores the response's `seed_value`.
- **Scoring modules in `.github/workflows/coveragerc-ci` `omit` are excluded from CI coverage** (the CI image lacks their model weights); local runs include them. Scorer model caches are module-level globals in the scorer subprocess, so leaks die with it.
- **Stale numba cache segfaults scorer tests after `uv sync`** (librosa's `.nbc`/`.nbi` files under `librosa/__pycache__/`). Fix: `find .venv/lib/python*/site-packages/librosa \( -name "*.nbc" -o -name "*.nbi" \) -delete`.
- **Backup and restore need both** DB and audio files (`scripts/backup.sh`, `scripts/restore.sh`); restoring one leaves orphaned records or unreachable files.
- **`slugify()` uses `python-slugify`**; the `"untitled"` fallback covers an empty transliteration.

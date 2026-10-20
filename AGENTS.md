# Songmaker

Repository facts only. The global contract owns coordination, claims, worktrees, review and code policy; `CLAUDE.md` is exactly `@AGENTS.md`.

AI-powered song generation platform: SvelteKit web UI (`frontend/`, pnpm, Node 22 LTS), FastAPI backend, PostgreSQL, Redis. Songs are created, generated via ACE-Step, scored and reviewed. The CLI is a thin HTTP client to the same API. Python 3.12, venv `.venv/`.

Docs: [architecture](docs/architecture.md) | [testing](docs/testing.md) | [security](docs/security.md) | [ACE-Step](docs/acestep.md) | [vision](docs/VISION.md) | [requirements](docs/requirements/README.md).

## Product Context

A musician creates an **album** (EP, LP or concept album) holding **songs**; each song belongs to one album. **Playlists** collect favourite songs across albums.

Song workflow: write lyrics and a style prompt, **generate** audio via ACE-Step, listen, tweak, generate again. Each edit creates an immutable **version** (lyrics, prompt, generation params); each attempt produces a **generation** (an audio file tied to one version). A song has many versions, a version many generations.

Two flags on generations: **pick** is THE one for this song on the album (one per song, replaces the previous pick); **keep** means "don't delete it" and survives cleanup but is not the album pick.

**Scoring** is purely informational auto-rating: BPM accuracy, spectral quality, silence, emotional dynamics, text accuracy (Whisper transcript of what was sung vs the lyrics, which the user also sees).

**Co-writer** is one active multi-turn conversation per musician, not per song (`chat_messages`, scoped via `conversations`), with a chosen provider (Claude, Grok or Codex) sharing the same song read/write capabilities. History goes verbatim while it fits the token-bounded tail; beyond it a rolling summary plus that tail. The model can persist an owned song's lyrics, style prompt, title, BPM, key or duration and create new songs. @-mentions are resolved from the DB server-side. Co-writer expansion (more memory or mention features) is frozen until organically needed (operator ruling 2026-08-24). The per-song legacy chat is gone (#1190); the co-writer runs only through `POST /chat/turn` in `conversation_api.py`.

**Seed pinning** reproduces a generation (pin a previous seed, regenerate with tweaked params). Whether to keep, surface or remove it is open (#230).

## Setup and run

The live app is Docker-only; there is no local server path. `.venv` is for tests, type checking and IDE only. Application secrets and settings live in one gitignored `.env` at the root. The non-secret `SONGMAKER_CLAUDE_CLI`, `SONGMAKER_GROK_CLI` and `SONGMAKER_CODEX_CLI` overrides are the exception: the preflight reads only their exported deployment environment values.

```bash
uv sync --extra server --extra scoring --extra whisper --extra mcp --extra image --extra dev
docker compose up -d --build --wait     # agents: run in the background
cd frontend && pnpm install && pnpm dev
bash scripts/download_models.sh         # model weights, needs HF_TOKEN in .env
```

**Docker:** never wrap `docker compose up --build --wait` in `timeout`. A cold-cache rebuild of all 5 images takes 8-15 minutes (the acestep-worker alone is 8.84 GB); a shorter timeout SIGTERMs mid-build silently and leaves a partial deploy. After changing a Dockerfile under `docker/base/`, run `scripts/build_images.sh` first, or compose fails with `manifest unknown` for `songmaker/acestep-base:latest`.

## Checks

CI runs the pinned reusable quality gate (`quality / verdict`, mandatory jobs in `quality/config.toml`); coverage floors, Sonar and transport are in [testing](docs/testing.md#static-analysis-sonarcloud).

Targeted local runs:

```bash
ruff check src/songmaker_cli/foo.py tests/test_foo.py
pytest tests/test_foo.py -q --tb=short
cd frontend && pnpm exec vitest run src/lib/stores/player.test.ts
```

Cheap and path-triggered: `python scripts/check_no_silent_fallbacks.py src/` when touching `src/`; `python scripts/generate_types.py --check` when touching API models; `python scripts/check_root_layout.py` when adding or moving a root-level file (it owns the root allowlist).

Schema changes: `alembic revision --autogenerate -m "..."`, then `alembic upgrade head`.

## Where things go

| Adding a... | Files to touch | Exemplar |
|---|---|---|
| API endpoint | `api_models/{domain}.py` → `db/queries/{domain}.py` → `{domain}_api.py` → `python scripts/generate_types.py` | `album_api.py` |
| Scorer | `scoring/{name}.py` → `scoring/models.py` → `pipeline.py` count → `api_models/` names | `scoring/silence_detection.py` |
| DB model | `db/models.py` → `db/queries/{domain}.py` → Alembic migration | `Song` in `db/models.py` |
| Frontend component | `lib/components/` → `lib/stores/` if stateful → `lib/api/client.ts` if new API | `AlbumMetaEditor.svelte` |

Backend paths are under `src/songmaker_cli/`. `plans/` holds temporary live-coordination notes for in-flight multi-session work; delete a plan once its issue closes.

## Code patterns

- **Query functions `flush()`, endpoints `commit()`.** `get_db_session` does not auto-commit; a missing `session.commit()` in an endpoint is silent data loss. Exception: login in `auth_api.py` commits then raises, to persist the failed attempt before the 401. `create_job_with_rate_limit()` and `unique_album_id()` commit the current transaction before taking an exclusive lock, so callers must hold no uncommitted business mutation.
- **`from_orm()` classmethods on response models**; never hand-build response dicts.
- **Engine packages are independent.** `acestep_engine`, `audio_engine` and `acestep_worker` never import `songmaker_cli`; the acestep-worker image does not install it and would crash at startup. `acestep_engine` and `acestep_worker` each own a `settings.py`. `.importlinter` (run by `lint-imports` in CI) owns the boundary. `agent_providers` (`overnightworks-agent-providers` v0.1.3) and `webauth` (`overnightworks-webauth` v0.14.0) are installed release wheels from their own repositories (#886, #879); `lint-imports` does not scan their internals, so a chain reaching the application through a wheel is not caught (#1207). Neither imports `songmaker_cli` today.
- **Ownership checks on every resource endpoint**, GET included: `check_song_access()`, `check_album_access()`, `check_generation_access()` from `api_helpers.py`.
- **Middleware order in `server.py` is security-critical.** Do not reorder.
- **DB queries split by domain** (`db/queries/songs.py`, `auth.py`, `jobs.py`); new ones go in the matching file, re-exported from `db/queries/__init__.py`.
- **Sharing via `ShareMixin`** (Album, Song, Generation, Playlist): use `enable_sharing()`/`disable_sharing()` from `db/queries/sharing.py`; entity side effects go in the domain wrapper.
- **Constants:** reused or behaviour-configuring strings live in `constants.py` or as `Final` module-level values; one-off error, log and exception messages stay inline.
- **Required configuration has no silent default.** Reject missing input (raise or 422) or use a NAMED constant; never fall through to `next(iter(some_dict))` or insertion order. Origin: 2026-04-08, a truncated `available_models` table made `resolve_model_mode(None)` return `'turbo'` for every generation. `scripts/check_no_silent_fallbacks.py` enforces it in CI.

## Key rules

1. The database is the source of truth: all data in PostgreSQL, not files.
2. One code path: CLI and web UI use the same REST API. Exceptions: `reset-password` and `list-users` are local escape hatches that need only the DB. `songmaker reset-password <username>` asks twice at a hidden prompt (no argv password; a mismatch changes nothing), changes the password and deletes the account's DB sessions in one transaction, and needs no Redis. `songmaker login <username>` asks once, hidden.
3. Pydantic models in `api_models/` define the API contract; `python scripts/generate_types.py` generates `types.ts`.
4. Test albums (verify, proof, throwaway, QA runs) get a recognizable name prefix and are archived, not deleted, once verified.

## Constraints and known debt

- **Claude CLI call paths carry song content only through the tool-surface gate** (`verify_cli_tool_surface()` and `verify_no_builtin_cli_tools()` in `agent_providers/claude/provider.py`; the co-writer expects exactly the twelve tools in `MCP_TOOL_NAMES`, `cowriter/mcp_spec.py`). A drifted surface refuses the call, never server startup; `GET /health` reports `ok`/`drift`/`unverified`. Mechanics, caches and single-flight: [Claude Chat Security](docs/security.md#claude-chat-security).
- **Agent-CLI bind mounts** never expose an operator profile; `ANTHROPIC_API_KEY` serves the API routes (judge, catalog, API co-writer) but does not replace the mounted CLI the CLI co-writer route needs: [Agent-CLI Mounts](docs/security.md#agent-cli-mounts).
- **The DB owns session validity** (stored expiry, absolute age, active account on every request; `touch()` must return a real `bool`). `get_current_user` commits renewal and audit in its own short transaction; stores never commit endpoint writes; stream callers commit before streaming: [Authentication](docs/security.md#authentication).
- **Trust model** (subprocesses share the OS user, one shared worker token, single-node): accepted for a single-user deployment; rationale and limits in [Worker Pool Trust Boundary](docs/security.md#ace-step-worker-pool-trust-boundary).
- **GPU isolation is by container.** Only `songmaker-acestep-worker-N` has a GPU; `songmaker-scoring-worker` runs `SCORING_DEVICE=cpu`, so nothing arbitrates VRAM. NVML (`pynvml`) lives only in `src/acestep_worker/gpu_util.py`: the worker reports VRAM in its heartbeat (republished on `/metrics`), and `check_gpu_health()` makes the worker's `/health` answer 503 when `pynvml` is present but the device cannot be opened; a missing `pynvml` is not broken and never blocks a job. `SCORING_DEVICE=cuda` would need a release/verify protocol (#161, #182).
- **ACE-Step submodule:** `vendor/acestep` is our fork [FlexOr2/ACE-Step-1.5](https://github.com/FlexOr2/ACE-Step-1.5); upstream remote `upstream`. The fork carries patches not yet upstream (see [ACE-Step](docs/acestep.md) for the pin and patch list). The fork's HTTP API code (`vendor/acestep/acestep/api/http/`) is the source of truth for param names. Check upstream PR status live: `gh pr list --repo ACE-Step/ACE-Step-1.5 --author FlexOr2 --state open`.
- **Seed reproducibility needs `use_random_seed: false`**: ACE-Step ignores `seed` otherwise. The client sets it from `config.seed` (`-1` random, non-negative fixed); the DB stores the response's `seed_value`.
- **Scoring modules in `.github/workflows/coveragerc-ci` `omit` are excluded from CI coverage** (the CI image lacks their model weights); local runs include them. Scorer model caches are module-level globals in the scorer subprocess, so leaks die with it.
- **Stale numba cache segfaults scorer tests after `uv sync`** (librosa's `.nbc`/`.nbi` files under `librosa/__pycache__/`). Fix: `find .venv/lib/python*/site-packages/librosa \( -name "*.nbc" -o -name "*.nbi" \) -delete`.
- **Backup and restore need both** DB and audio files (`scripts/backup.sh`, `scripts/restore.sh`); restoring one leaves orphaned records or unreachable files.
- **`slugify()` uses `python-slugify`**; the `"untitled"` fallback covers an empty transliteration.

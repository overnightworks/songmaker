# Songmaker — Claude Code Config

## Project

AI-powered song generation platform. SvelteKit web UI + FastAPI backend + PostgreSQL + Redis. Songs are created, generated via ACE-Step, scored, and reviewed. The CLI is a thin HTTP client to the same API.

**Python**: 3.12 | **Venv**: `.venv/` | **Node**: 22 LTS | **Package manager**: pnpm | **Frontend**: `frontend/`

Docs: [architecture](docs/architecture.md) | [testing](docs/testing.md) | [security](docs/security.md) | [ACE-Step](docs/acestep.md)

**Backlog:** [BACKLOG.md](BACKLOG.md) at the repo root. Always consult it when the user asks "what should we do next?", "what's on the roadmap?", or "anything in the queue?" — don't assume the `plans/` directory is the full picture. BACKLOG.md holds feature-level concept notes; `plans/` holds per-task concept notes only while work is in flight.

**ACE-Step submodule:** `vendor/acestep` → [FlexOr2/ACE-Step-1.5](https://github.com/FlexOr2/ACE-Step-1.5) (our fork). The fork carries patches not yet upstream, especially HTTP API param exposure; the old VRAM preflight skip is not currently applied in the vendored file (see `docs/acestep.md`). Upstream remote is `upstream` inside the submodule. Sync periodically with `cd vendor/acestep && git fetch upstream && git merge upstream/main`. When adding or modifying ACE-Step params, read the fork's HTTP API code directly (`vendor/acestep/acestep/api/http/`) — it's the source of truth for available params and their names. **For PR status questions** ("what's open upstream?", "are my PRs merged?", "anything blocked?") always query GitHub live with `gh pr list --repo ACE-Step/ACE-Step-1.5 --author FlexOr2 --state open --json number,title,isDraft,mergeStateStatus,reviewDecision,updatedAt` — don't trust memory snapshots, they go stale within days.

## Product Context

A musician creates an **album** (a coherent collection of songs — an EP, LP, or concept album). Each **song** belongs to one album. **Playlists** let the user collect favorite songs across albums for listening.

The workflow for a song: write lyrics and a style prompt → **generate** audio via ACE-Step → listen → tweak lyrics/prompt/params → generate again. Each edit creates a **version** (an immutable snapshot of lyrics, prompt, and generation params). Each generation attempt produces a **generation** (an audio file tied to a specific version). One song can have many versions, each version can have many generations.

Two special flags on generations: **pick** marks "this is THE one for this song on the album" (one per song, replaces the previous pick). **Keep** marks "I like this, don't delete it" — survives cleanup but isn't the album pick.

**Scoring** is auto-rating: BPM accuracy, spectral quality, silence detection, emotional dynamics, text accuracy (Whisper transcription of what was actually sung vs the lyrics). Purely informational — helps the user decide which generation sounds best. The Whisper transcript also shows the user what the AI actually sang.

**Co-writer** is a multi-turn Claude conversation per song, stored in PostgreSQL (`chat_messages` table). The user discusses lyrics, brainstorming, and refinement. Full conversation history is sent to the Claude API on each turn. Claude can propose changes via `songmaker` blocks that the user applies to the current song's editor. Using @-mentions, the user can reference other songs or album context — the backend resolves mentions from the DB and builds context server-side. Claude can also create entirely new songs.

**Seed pinning** lets the user reproduce a generation: pin a seed from a previous generation, regenerate with tweaked params, and get a comparable result (same random noise, different settings). This enables A/B testing of parameter changes.

## Setup & Run

The live app is **Docker-only** — there is no `uv run songmaker server`
local-dev path. The local `.venv` is for tests, type checking, and IDE
autocomplete only. All secrets and config live in a single `.env` file
at the project root (gitignored).

```bash
# Local toolchain (tests, lint, IDE)
uv sync --extra server --extra scoring --extra whisper --extra dev

# Run the live stack — agents: ALWAYS run this in the background
# (Bash tool: run_in_background=true). Cold-cache rebuilds take 8-15 minutes
# and any wrapping `timeout` will SIGTERM mid-build. See "Docker" section.
docker compose up -d --build --wait

# Frontend (dev mode)
cd frontend && pnpm install && pnpm dev

# Download ACE-Step model weights (requires HF_TOKEN in .env)
bash scripts/download_models.sh       # Downloads all model variants to vendor/acestep/checkpoints/
```

## Checks

During iteration, run **targeted tests** for the files you changed + the linter. Full suite once before committing or when asked.

```bash
# During iteration — fast feedback
ruff check src/ tests/
pytest tests/test_foo.py -q              # just the relevant test file(s)

# Before committing — full parallel suite + coverage
pytest tests/ -n auto -q --cov=songmaker_cli --cov=audio_engine --cov=acestep_engine --cov-report=term-missing

# Frontend
cd frontend && pnpm check && pnpm lint && pnpm test
```

- CI enforces 90% overall coverage; scoring modules excluded from CI (require GPU extras). Locally, aim for 100% on non-scoring modules (exclude `main.py` CLI entrypoint).
- Docs (`docs/`) must stay accurate after changes

## Schema Changes

```bash
alembic revision --autogenerate -m "description"
alembic upgrade head
```

## Where Things Go

| Adding a... | Files to touch | Exemplar |
|---|---|---|
| API endpoint | `api_models/{domain}.py` → `db/queries/{domain}.py` → `{domain}_api.py` → run `python scripts/generate_types.py` | `album_api.py` |
| Scorer | `scoring/{name}.py` → `scoring/models.py` → `pipeline.py` count → `api_models/` names | `scoring/silence_detection.py` |
| DB model | `db/models.py` → `db/queries/{domain}.py` → Alembic migration | `db/models.py:Song` |
| Frontend component | `lib/components/` → `lib/stores/` if stateful → `lib/api/client.ts` if new API | `SongList.svelte` |
| Plan / design doc | `plans/{name}.md` — **concept only** (goal, locked-in decisions, hard constraints, "first step: read the live code"). See "Plan-writing convention" below. Add `**Status:** Proposed\|In progress\|Done\|Abandoned` and `**Date:** YYYY-MM-DD` headers. Delete `Done`/`Abandoned` plans — git history keeps them recoverable. | `plans/jobs-module-split.md` |

## Plan-writing convention

Detailed implementation plans rot. Symbol lists, line counts, and step-by-step move orders become wrong as soon as the underlying code changes. **Plan files in `plans/` must capture the concept, not the implementation.** Three tiers:

| Task size | Artifact |
|---|---|
| **Small** (< 30 min — rename a function, add an index, fix a typo) | No plan. Execute directly. |
| **Medium / future work** (hours, has decisions worth capturing) | Concept note in `plans/{name}.md`, ~10–30 lines: **goal** (1–2 sentences), **locked-in decisions** (bullets — things the user already answered), **hard constraints** (bullets — things the executor cannot violate), **first step** (always "read the live code, design + execute"). The executing agent generates their own implementation plan in-session if they want one — don't pre-write it. |
| **Live multi-session execution** (multi-agent or multi-day work in flight) | A detailed plan IS appropriate as a live coordination doc, but treat it as **temporary**. Delete once execution finishes — git history keeps it if needed. Don't keep refreshing it after the work is done. |

**Why:** detailed plans for future work pretend to know things only the executor can know. The agent is closer to the truth at execution time than the plan ever can be. Pre-written symbol lists, file structures, and step orders bias the executor toward the planner's pre-conception and need maintenance every time the code changes underneath. Concept notes survive code changes because they don't depend on details.

**Don't** include in a concept note: symbol inventories, line counts, file-by-file diff sketches, step-by-step ordering, "risks" that are generic engineering concerns, verification commands beyond the standard `ruff check && pytest && docker compose up -d --build --wait`. The agent runs `grep` and `wc -l` themselves in 1 second when needed.

**Do** include: the goal, the decisions that came from prior conversations (so the agent doesn't re-prompt), and the constraints that aren't obvious from the code. Anything else is rot waiting to happen.

## Code Patterns (codebase-specific)

These are conventions that aren't obvious from reading a single file:

- **Query functions `flush()`, endpoints `commit()`.** `get_db_session` does NOT auto-commit. Forgetting `session.commit()` in an endpoint = silent data loss. Exception: "commit then raise" in `auth_api.py` login (must persist failed attempt before returning 401).
- **`from_orm()` classmethods on response models.** Never hand-build response dicts. Add a `from_orm()` to the Pydantic model.
- **Engine packages are independent.** `acestep_engine`, `audio_engine`, AND `acestep_worker` must never import from `songmaker_cli`. Dependency flows one way. The acestep-worker container is a slim image that does NOT install `songmaker_cli` — any import from `songmaker_cli` in `acestep_worker/` will crash the container at startup with `ModuleNotFoundError: No module named 'songmaker_cli'`. Each engine package owns its own `settings.py` (`acestep_engine/settings.py`, `acestep_worker/settings.py`). Verify with `grep -rn "from songmaker_cli\|import songmaker_cli" src/acestep_engine/ src/audio_engine/ src/acestep_worker/` — must return empty.
- **Ownership checks on every resource endpoint.** Use `check_song_access()`, `check_album_access()`, `check_generation_access()` from `api_helpers.py`. Never skip, even for GET.
- **Middleware order is security-critical.** See comment block in `server.py`. Do not reorder.
- **DB queries split by domain.** `db/queries/songs.py`, `db/queries/auth.py`, `db/queries/jobs.py`. New queries go in the matching file, re-exported from `db/queries/__init__.py`.
- **Sharing via `ShareMixin`.** Album, Song, Generation, Playlist inherit `ShareMixin` for `share_slug` + `is_shared`. Use `enable_sharing()` / `disable_sharing()` from `db/queries/sharing.py`. Entity-specific side effects (e.g. marking picked generation as kept) go in the domain wrapper.
- **No inline comments.** Use descriptive names. Comments in code are a smell — if you need to explain what code does, rename things until you don't.
- **No hardcoded strings.** Use constants in `constants.py` or `Final` module-level variables. Exception: one-off error messages, log messages, and exception descriptions are fine inline — only extract strings that are reused or configure behavior.
- **Pydantic for structured data, not dicts.** Any function returning or accepting a dict with a known schema should use a Pydantic model (or dataclass for internal-only data). Plain dicts are fine for generic key-value stores, `**kwargs`, or serialization helpers — not for domain objects, API responses, or cross-module contracts.
- **Validate at boundaries. No silent defaults for required configuration.** If a value is required for a downstream operation, the layer that accepts it from outside (HTTP request, env var, CLI arg, DB seed) must either reject missing input (raise / 422) or use a NAMED constant as the default. Never fall through to `next(iter(some_dict))`, "the first thing in the list", or dict-insertion-order. Those are silent corruption disguised as resilience. Discovered the hard way 2026-04-08 when the `available_models` table got TRUNCATEd and `resolve_model_mode(None)` silently returned `'turbo'` for every generation regardless of which model was actually loaded. The full cleanup shipped on 2026-04-09 across W1–W5 of the no-silent-fallbacks branch — see commit messages on `main` for the audit trail. CI enforces the rule via `scripts/check_no_silent_fallbacks.py`.

## Key Rules

1. **Database is source of truth** — all data in PostgreSQL, not files
2. **One code path** — CLI and web UI use the same REST API (exception: `reset-password` and `list-users` are local DB escape hatches)
3. **Pydantic models define the API contract** — `src/songmaker_cli/api_models/` → `types.ts` (generated via `python scripts/generate_types.py`)
4. **Never commit secrets** — `.env` is gitignored
5. **Commit messages**: conventional commits (`feat:`, `fix:`, `refactor:`, `test:`)

## Known Technical Debt

- **`main.py` escape hatches**: `reset-password` and `list-users` bypass the API. Intentional for emergency recovery.
- **Scoring modules excluded from CI coverage.** All seven scorers in `scoring/` are listed in `.coveragerc-ci` `omit`. Reason: the CI image doesn't ship faster-whisper / audiobox-aesthetics / librosa model weights, and adding them blows up image size and runtime for a single-developer project. Local coverage runs include them.
- **Stale numba JIT cache in librosa segfaults scorer tests after `uv sync`.** librosa caches compiled gufuncs as `.nbc`/`.nbi` files inside `librosa/__pycache__/` (NOT `~/.numba_cache`). When `uv sync` upgrades numba, numpy, or librosa, the old cache files survive and the new numba runtime segfaults trying to load them. Symptom: `pytest tests/test_scorers.py` crashes with "Fatal Python error: Segmentation fault" deep inside `numba/np/ufunc/gufunc.py` called from `librosa.pyin`. Fix: `find .venv/lib/python*/site-packages/librosa \( -name "*.nbc" -o -name "*.nbi" \) -delete`. Numba rebuilds the cache on first call (~1s extra on the first scorer test). Run after any dependency upgrade that touches the librosa/numba/numpy stack.
- **Claude CLI bind mounts in `docker-compose.yml`** are a temporary workaround for using a Max subscription instead of an API key. Three mounts (`~/.local/bin/claude`, `~/.claude`, `~/.claude.json`) give the container access to the host's CLI binary and credentials. When switching to `ANTHROPIC_API_KEY`, remove all three mounts — the provider auto-prefers the API key over CLI.
- **Redis is authoritative for session expiry.** The session sync loop in `lifecycle.py` syncs Redis TTL → DB `expires_at` every 5 minutes. This is intentional — Redis-first reads avoid DB writes on every request. The DB copy is a backup for audit/recovery, not the source of truth.
- **Scorer model caches are module-level globals** (`_whisper_model` in `text_accuracy.py`, `_predictor` in `audiobox_aesthetics.py`). These live in the scorer subprocess, so leaks are contained and cleaned up on subprocess kill. `pytest-xdist` runs each worker in a separate process, so parallel execution is safe.
- **`create_job_with_rate_limit()` and `unique_album_id()` commit the current transaction** before acquiring an exclusive lock. Auth-layer mutations (session renewal, audit records) are committed even on rejection. Callers must not have uncommitted business mutations before calling these functions.
- **VRAM verification** uses delta-based NVML checks (system-wide GPU memory via `pynvml`). Falls back to proceed-with-warning if pynvml is unavailable. Raises `RuntimeError` if scoring models aren't freed, failing the job cleanly instead of OOMing.
- **`slugify()` uses `python-slugify`.** Transliterates Unicode to ASCII (CJK, emoji, accented characters all produce meaningful slugs). The `"untitled"` fallback covers edge cases where transliteration yields an empty string.
- **Backup/restore requires both DB and audio files.** `scripts/backup.sh` dumps PostgreSQL + copies the audio volume to `BACKUP_DIR`. `scripts/restore.sh` restores both atomically. The two must stay in sync — restoring one without the other leaves orphaned records or unreachable files.
- **Trust boundaries: subprocesses share OS user.** ACE-Step and scorer subprocesses run as the same `songmaker` user in Docker with `cap_drop: ALL`. Compromised model weights or ACE-Step code get full user-level disk access. Container-level isolation mitigates this; OS user separation would require separate containers for marginal benefit. Accepted risk for a single-user deployment.
- **Seed reproducibility requires `use_random_seed: false`.** ACE-Step's API ignores the `seed` field unless `use_random_seed` is explicitly `false`. The client sets this automatically based on `config.seed`: `-1` means random, any non-negative value means fixed. The DB stores the seed from the server's response (`seed_value`), not the requested seed.
- **Claude CLI `_DISALLOWED_TOOLS` is a denylist** in `claude/provider.py`. It blocks all known tools, but fails open — new tools added to future Claude Code versions are implicitly allowed. Accepted risk for an invite-only platform. When going public, switch to `ANTHROPIC_API_KEY` (which uses the SDK, not the CLI) and this issue disappears.
- **Shared-secret internal token for worker↔control-plane auth.** The acestep-worker and music-worker authenticate to the web container's internal API using a single shared `SONGMAKER_INTERNAL_TOKEN` env var. All workers hold the same secret. Compromise of any one worker grants full internal-API access. Acceptable for a single-node deployment where workers share the same trust domain as the web container. Multi-node deployments should move to per-worker tokens or mTLS — see `docs/security.md` for the trust model.
- **Single-node ACE-Step worker pool.** The worker pool architecture (scheduler → control plane → acestep-worker) is designed to support multiple GPU workers, but today we run exactly one acestep-worker per GPU on a single host, with the ACE-Step HTTP subprocess living inside that worker's container. Multi-node distribution (workers on separate hosts, shared model storage, cross-host Redis heartbeats) is untested. The image/packaging refactor that would precede any multi-node move (decoupling the ACE-Step subprocess image from the worker image) has not been written.

## Docker

**Never wrap `docker compose up --build --wait` in `timeout`.** Use `--wait` (it exits cleanly when all containers are healthy) but no surrounding timeout. A cold-cache rebuild of all 5 service images takes 8-15 minutes — the acestep-worker alone is 8.84 GB of PyTorch + CUDA. Any timeout shorter than ~20 minutes will SIGTERM the build mid-way through, leaving you with a partial deploy (some images rebuilt, others stale, containers still running the old code). Discovered the hard way 2026-04-09 after a `docker builder prune` cleared the cache and the next deploy with `timeout 600` killed itself just after the acestep-worker finished, before the other 4 service images rebuilt. The bug looked like "stuck" because the SIGTERM is silent.

```bash
# Correct
docker compose up -d --build --wait

# Wrong — silently kills the build at 600s
timeout 600 docker compose up -d --build --wait
```

**Agents: always run `docker compose up --build` in the background** (Bash tool `run_in_background=true`). The command takes 8-15 minutes on cold cache and there's no reason to block the agent loop while it runs. Poll the background output instead, or check `docker compose ps` later. The `--wait` flag means the command will exit on its own when containers are healthy — you're not babysitting an indefinite hang.

If you've changed any Dockerfile under `docker/base/`, run `scripts/build_images.sh` first to rebuild the base images. Otherwise compose will fail with `manifest unknown` for `FROM songmaker/acestep-base:latest`.

## Workflow — Speed

- **Batch changes, test once.** All edits first, suite once at the end.
- **Parallel edits.** Signature change across N files → edit all in parallel.
- **Don't re-read files** you just read in the same conversation.
- **Trust the linter.** Don't run the full suite for trivial changes.
- **One coverage check per task.** `--cov` once at the end.

## Self-Review (multi-file changes)

1. Re-read changed files in full — coherent whole, no dead traces?
2. Question abstractions — explainable in one sentence?
3. Update `docs/` if the change affects architecture, security, API endpoints, or test structure
4. Run checks (above)

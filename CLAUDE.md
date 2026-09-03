# Songmaker — Claude Code Config

## Project

AI-powered song generation platform. SvelteKit web UI + FastAPI backend + PostgreSQL + Redis. Songs are created, generated via ACE-Step, scored, and reviewed. The CLI is a thin HTTP client to the same API.

**Python**: 3.12 | **Venv**: `.venv/` | **Node**: 22 LTS | **Package manager**: pnpm | **Frontend**: `frontend/`

Docs: [architecture](docs/architecture.md) | [testing](docs/testing.md) | [security](docs/security.md) | [ACE-Step](docs/acestep.md)

**Backlog:** GitHub Issues + Milestones at [FlexOr2/songmaker](https://github.com/FlexOr2/songmaker/issues). Always query live (`gh issue list --repo FlexOr2/songmaker --state open --json number,title,milestone,labels`) when the user asks "what should we do next?", "what's on the roadmap?", or "anything in the queue?" — don't assume `plans/` is the full picture. New work is filed as a GitHub issue **with a milestone** before it is built. `plans/` holds per-task concept notes only while work is in flight.

**Agent policy:** [AGENTS.md](AGENTS.md) is the provider-neutral entrypoint. Use the globally installed `agent-claim` CLI for repository claims; it owns the coordination protocol.

**ACE-Step submodule:** `vendor/acestep` → [FlexOr2/ACE-Step-1.5](https://github.com/FlexOr2/ACE-Step-1.5) (our fork). The fork carries patches not yet upstream, especially HTTP API param exposure; the old VRAM preflight skip is not currently applied in the vendored file (see `docs/acestep.md`). Upstream remote is `upstream` inside the submodule. Sync periodically with `cd vendor/acestep && git fetch upstream && git merge upstream/main`. When adding or modifying ACE-Step params, read the fork's HTTP API code directly (`vendor/acestep/acestep/api/http/`) — it's the source of truth for available params and their names. **For PR status questions** ("what's open upstream?", "are my PRs merged?", "anything blocked?") always query GitHub live with `gh pr list --repo ACE-Step/ACE-Step-1.5 --author FlexOr2 --state open --json number,title,isDraft,mergeStateStatus,reviewDecision,updatedAt` — don't trust memory snapshots, they go stale within days.

## Product Context

A musician creates an **album** (a coherent collection of songs — an EP, LP, or concept album). Each **song** belongs to one album. **Playlists** let the user collect favorite songs across albums for listening.

The workflow for a song: write lyrics and a style prompt → **generate** audio via ACE-Step → listen → tweak lyrics/prompt/params → generate again. Each edit creates a **version** (an immutable snapshot of lyrics, prompt, and generation params). Each generation attempt produces a **generation** (an audio file tied to a specific version). One song can have many versions, each version can have many generations.

Two special flags on generations: **pick** marks "this is THE one for this song on the album" (one per song, replaces the previous pick). **Keep** marks "I like this, don't delete it" — survives cleanup but isn't the album pick.

**Scoring** is auto-rating: BPM accuracy, spectral quality, silence detection, emotional dynamics, text accuracy (Whisper transcription of what was actually sung vs the lyrics). Purely informational — helps the user decide which generation sounds best. The Whisper transcript also shows the user what the AI actually sang.

**Co-writer** is one active multi-turn conversation per musician, not per song, stored in PostgreSQL (`chat_messages` table, scoped via `conversations`). The user discusses lyrics, brainstorming, and refinement with a chosen provider — Claude, Grok, or Codex — which share the same song read/write capabilities. When history fits the token-bounded tail it goes verbatim; over budget, a rolling summary plus that tail take its place. The model can persist an owned song's lyrics, style prompt, title, BPM, key, or duration directly, and can create entirely new songs. Using @-mentions, the user can reference other songs or album context — the backend resolves mentions from the DB and builds context server-side. Co-writer expansion (further memory or mention features) is frozen until organically needed (operator ruling 2026-08-24).

**Seed pinning** lets the user reproduce a generation: pin a seed from a previous generation and regenerate with tweaked params for a comparable result (same random noise, different settings). The capability exists in the code; whether to keep, surface, or remove it is an open decision (#230).

## Setup & Run

The live app is **Docker-only** — there is no `uv run songmaker server`
local-dev path. The local `.venv` is for tests, type checking, and IDE
autocomplete only. Application secrets and settings live in a single `.env`
file at the project root (gitignored). The non-secret
`SONGMAKER_CLAUDE_CLI`, `SONGMAKER_GROK_CLI`, and `SONGMAKER_CODEX_CLI` path
overrides are an exception: the preflight reads only their exported deployment
environment values.

```bash
# Local toolchain (tests, lint, IDE)
uv sync --extra server --extra scoring --extra whisper --extra mcp --extra dev

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

**Agents and subagents never run the full suite on this machine.** The operator
sits here; a `pytest tests/ -n auto` or `pnpm test` (all files) plus coverage
blocks the desktop. Same rule as atelier-2: the land gate is GitHub CI.

Local, always **targeted**:

```bash
# Python — only the files that prove THIS change
ruff check src/songmaker_cli/foo.py tests/test_foo.py
pytest tests/test_foo.py tests/test_bar.py -q --tb=short

# Frontend — only the matching test files
cd frontend && pnpm exec vitest run src/lib/stores/player.test.ts src/lib/services/offline.test.ts
```

`python scripts/check_no_silent_fallbacks.py src/` is cheap; run it when
touching `src/`. `python scripts/generate_types.py --check` when touching
API models.

**Full suite is CI only** (or when the operator explicitly asks):

```bash
pytest tests/ -n auto -q --cov=songmaker_cli --cov=audio_engine --cov=acestep_engine --cov=acestep_worker --cov-report=term-missing --cov-fail-under=90 --cov-config=.coveragerc-ci
python scripts/generate_types.py --check
cd frontend && pnpm check && pnpm lint && pnpm test:coverage && pnpm build
```

- CI enforces 90% backend coverage (`songmaker_cli` + engines + `acestep_worker`; scoring modules excluded — require GPU extras) and a 70% frontend `lib/` floor plus `pnpm build`. Locally, aim for 100% on non-scoring Python modules (exclude `main.py` CLI entrypoint).
- Docs (`docs/`) must stay accurate after changes
- Open work lives in GitHub Issues with a milestone. Do not add items to a markdown backlog.

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
| Work item | GitHub issue **with a milestone** (`gh issue create --milestone …`). Concept notes for in-flight work may live in `plans/{name}.md` until the issue closes, then delete the plan. | [issues](https://github.com/FlexOr2/songmaker/issues) |

## Plan-writing convention

Detailed implementation plans rot. Symbol lists, line counts, and step-by-step move orders become wrong as soon as the underlying code changes. **Plan files in `plans/` must capture the concept, not the implementation.** Three tiers:

| Task size | Artifact |
|---|---|
| **Small** (< 30 min — rename a function, add an index, fix a typo) | No issue, no plan. Execute directly. |
| **Medium / future work** (hours, has decisions worth capturing) | GitHub issue **with a milestone**. Body is a concept note: **goal** (1–2 sentences), **locked-in decisions**, **hard constraints**, **first step** ("read the live code, design + execute"). No `plans/` file. |
| **Live multi-session execution** (multi-agent or multi-day work in flight) | GitHub issue + a temporary `plans/{name}.md` as a live coordination doc. Delete the plan once the issue closes. |

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
- **Claude CLI bind mounts in `docker-compose.yml`** never expose an operator profile. The web container and scoring worker each own a writable `.claude` profile and mount only the Claude CLI binary and redacted credential mirror read-only with `create_host_path: false`; Grok and Codex use their HTTP APIs and have no mount. Claude creates `~/.claude.json` in its own profile when needed. `ANTHROPIC_API_KEY` enables Claude's judge and catalog SDK path, but not the co-writer, which needs the CLI with Songmaker's MCP tools; retain the web Claude CLI mirror for co-writer turns. See `docs/security.md`, "Agent-CLI Mounts".
- **Redis is authoritative for session expiry.** The session sync loop in `lifecycle.py` syncs Redis TTL → DB `expires_at` every 5 minutes. This is intentional — Redis-first reads avoid DB writes on every request. The DB copy is a backup for audit/recovery, not the source of truth.
- **Scorer model caches are module-level globals** (`_whisper_model` in `text_accuracy.py`, `_predictor` in `audiobox_aesthetics.py`). These live in the scorer subprocess, so leaks are contained and cleaned up on subprocess kill. `pytest-xdist` runs each worker in a separate process, so parallel execution is safe.
- **`create_job_with_rate_limit()` and `unique_album_id()` commit the current transaction** before acquiring an exclusive lock. Auth-layer mutations (session renewal, audit records) are committed even on rejection. Callers must not have uncommitted business mutations before calling these functions.
- **GPU isolation is by container, not by handshake.** `songmaker-acestep-worker-N` is the only container with a GPU; `songmaker-scoring-worker` gets no GPU device and runs `SCORING_DEVICE=cpu`, so nothing arbitrates VRAM between scoring and generation because nothing has to. NVML (`pynvml`) is used for *reporting* only and lives in exactly one place, `acestep_worker/gpu_util.py`: the worker reads its own VRAM into its heartbeat, and `songmaker-web` republishes those numbers on `/metrics` as `songmaker_acestep_worker_vram_used_gigabytes` / `_total_gigabytes`. `songmaker-web` has no GPU and no NVML of its own. The reader returns `None` when pynvml is missing and never blocks a job. Switching to `SCORING_DEVICE=cuda` would need a real release/verify protocol between the two containers — that work is issues #161 and #182, not something the code does today.
- **`slugify()` uses `python-slugify`.** Transliterates Unicode to ASCII (CJK, emoji, accented characters all produce meaningful slugs). The `"untitled"` fallback covers edge cases where transliteration yields an empty string.
- **Backup/restore requires both DB and audio files.** `scripts/backup.sh` dumps PostgreSQL + copies the audio volume to `BACKUP_DIR`. `scripts/restore.sh` restores both atomically. The two must stay in sync — restoring one without the other leaves orphaned records or unreachable files.
- **Trust boundaries: subprocesses share OS user.** ACE-Step and scorer subprocesses run as the same `songmaker` user in Docker with `cap_drop: ALL`. Compromised model weights or ACE-Step code get full user-level disk access. Container-level isolation mitigates this; OS user separation would require separate containers for marginal benefit. Accepted risk for a single-user deployment.
- **Seed reproducibility requires `use_random_seed: false`.** ACE-Step's API ignores the `seed` field unless `use_random_seed` is explicitly `false`. The client sets this automatically based on `config.seed`: `-1` means random, any non-negative value means fixed. The DB stores the seed from the server's response (`seed_value`), not the requested seed.
- **No Claude CLI call carrying song content runs unverified — the gate sits in the call paths, not in each caller, and not in the command builders themselves (the builders just format flags; they check nothing).** `_build_cli_cmd()` (tool-free: the legacy `/songs/{id}/chat` endpoint and the lyrical-coherence judge) is reached only through `_call_cli()`/`_acall_cli()` in `claude/provider.py`, and those two call `verify_no_builtin_cli_tools()`/`averify_no_builtin_cli_tools()` themselves before building anything — so a future caller of `call_claude()`/`acall_claude()` inherits the gate automatically instead of needing to remember it. `_build_mcp_cli_cmd()` (the co-writer, MCP tools attached) is reached only through the two MCP entry points (`acall_claude_with_mcp`/`acall_claude_with_mcp_stream`), which call `verify_cli_tool_surface()` themselves the same way — a separate gate, not routed through `_call_cli()`/`_acall_cli()`. Both command lines apply `--tools ""`, `--setting-sources ""`, `--strict-mcp-config`, and `--disable-slash-commands` (removing the CLI's built-ins, any profile `~/.claude/settings.json`, foreign MCP servers, and slash-command/skill dispatch respectively). `--permission-mode bypassPermissions` is gone from both.
  The two gates read the tool list the CLI itself reports on startup (`--output-format stream-json --verbose`, first init-event line, `subtype` checked too) on a cache **miss** only — a cache hit returns the remembered verdict without starting a CLI session at all. The co-writer's MCP-attached probe expects **exactly** the eleven `mcp__songmaker__*` tools — a hand-maintained literal tuple in `provider.py` (not imported from `mcp_server/server.py`, to avoid pulling the `mcp` package into the scoring-worker container), kept honest by a dedicated test that compares it against that module's real registration; set equality, not a prefix check, so a tool going missing is caught the same as an extra one — but an unexpected tool or a reachable slash command is *always* a permanent mismatch, regardless of whether the MCP connection itself came up; only a clean absence genuinely explainable by that connection never establishing is short-lived (a CLI reporting `tools=["Bash"]` while its MCP connection also happens to be down is not "unverifiable", it is confirmed dangerous). The no-MCP probe, used by every tool-free call, expects **no tool at all**, since that call line never attaches ours either — and never attaches `--mcp-config`, so it needs neither a reachable database (registering and listing MCP tools touches no DB — only a tool *call* does) nor the `mcp` extra. Only the second one is the scoring-worker container's real gap: it has a reachable database (it writes scores back to it), just not the `mcp` extra — which is why the no-MCP probe, specifically, is the one that stays importable there (`tests/test_packaging_boundary.py`). Both also require the reported slash-command list to be empty.
  A verdict — a real answer about this exact binary build's tool surface, mismatch or clean — is cached per resolved build with no expiry, because it does not change until the build does (a self-update is a different build, re-probed). A probe **failure** — anything that kept the answer from being trustworthy: a timed-out probe, unparseable output, the songmaker MCP server failing to connect (co-writer path; reports the same empty tool list a clean, genuinely tool-free CLI would) — is cached separately, for only `CLAUDE_CLI_TOOL_SURFACE_FAILURE_CACHE_SECONDS`. A process that outlives SIGKILL is its own third case, checked before parsing, the MCP check, or the verdict ever run — a clean read followed by a zombie is not trusted either: not a verdict about the build (the build is fine; this one instance of it is stuck), and not an ordinary failure either — ten more seconds will not make it healthy, so it gets the much longer `CLAUDE_CLI_ZOMBIE_FAILURE_CACHE_SECONDS` instead, so retrying on the ordinary schedule cannot spawn a fresh zombie every ten seconds.

  Single-flight is a *published future*, never a held lock — rounds 3 and 4 held a per-key mutex across the whole probe and spent two rounds finding a new unbounded wait inside it, so round 5 changed the shape instead of patching another hole. The dict lock now only ever guards a lookup/insert. The first cold caller for a key publishes an `asyncio.Future` (async gates) or `concurrent.futures.Future` (`_call_cli`'s sync gate) under that lock, releases it immediately, and probes with nothing held at all; every later caller for that key finds the published future and awaits it, each with its own timeout — so a leader that somehow never resolves it degrades every later caller to "wait, then give up" rather than a permanent block, and a resolution always happens (success, probe failure, or an unexpected bug in evaluating the result) so the dict entry is never left dangling. A leader whose own task gets cancelled hands followers a normal `UnavailableError`, never its literal `CancelledError` — an unrelated follower's own task must not look cancelled just because the leader's was. Sync and async callers for the *same* key still do not exclude each other (a thread future cannot be awaited without blocking the loop, an asyncio future cannot be waited on from a thread without one) — an accepted, narrow gap given the only key both domains ever share is the no-MCP one.

  The probe itself runs under one overall deadline covering process start, stdin write, and stdout read together — not a separate timeout per step that can add up to an unknown total (spawn and the pipe write used to have none at all). The async gate does not spawn via `asyncio.create_subprocess_exec` directly: that still runs the underlying `fork()`/`exec()` synchronously on whichever thread calls it, including the event loop's own, so a stuck spawn could keep the loop from ever running the timer meant to enforce the deadline. Both gates instead run the one real probe body (`_probe_cli_surface_sync`) on a worker thread via `asyncio.to_thread`, so a hung `Popen()` only blocks its own thread, never the caller waiting on it with a real deadline. Only cleanup (SIGTERM grace, then the post-SIGKILL wait) has its own small, separate bound, `CLAUDE_CLI_ZOMBIE_REAP_TIMEOUT_SECONDS`: cleanup must always be attempted regardless of how much of the answer budget is left. The caller can therefore observe the probe timeout plus that cleanup margin after its answer budget expires. Probes and real turns share one Claude CLI process pool, capped at `CLAUDE_CLI_MAX_CONCURRENT_PROCESSES` (one pool per Python process: the web container's process and one for each scorer subprocess). Every spawn takes a reservation, and it is released only after confirmed death or when a background reaper ends. A zombie storm therefore deliberately fails closed by refusing another process rather than growing without bound. The app's shutdown (`server.py`'s lifespan) cancels every outstanding background async reaper the same way it already cancels its other background loops.

  The gate resolves the CLI's symlink once and runs that literal path for both the probe and the real turn, so what was checked is what executes even if the mounted `claude` binary self-updates in between. The probe cannot guarantee zero API cost: the CLI's own `--max-budget-usd` was checked live and only aborts a session after a call completes, not before one starts.
  Replaced the former hand-maintained denylist, which was already missing eight tools (`Task`, `DesignSync`, `ListAgents`, `Monitor`, `PushNotification`, `ReportFindings`, `ScheduleWakeup`, `Workflow`) against the installed 2.1.257 CLI's 26.
  **A drifted tool surface never fails server startup** (operator ruling, round 6): #351 literally asked for an unknown tool to fail the boot, but once the gate itself was confirmed to cover every call path with untrusted content, a server that refuses to serve albums and playback over a co-writer problem is a worse outage than the co-writer being unavailable. `lifecycle.report_claude_cli_tool_surface()` still probes at boot and logs the result, but now also returns one of three states — `"ok"` (verified, clean), `"drift"` (verified, a real mismatch), or `"unverified"` (the probe itself could not reach a verdict — no CLI mounted, a timeout, a zombie, MCP never connecting; never silently reported as `"ok"`) — a live value in `claude/provider.py` (`claude_cli_tool_surface_health()`), updated by every `verify_cli_tool_surface()` call — cache hit or fresh probe alike — not a value captured once at boot, so a later verdict (a real co-writer turn, once the CLI becomes reachable, say) overrides an earlier one instead of staying stuck at whatever booted — and surfaced as that same field on `GET /health`, so the state is visible to monitoring and the operator, not only the first musician who opens a chat and finds it broken. Nothing polls in the background: the value only changes when the gate itself runs again, so if the CLI disappears without a fresh probe following it, `/health` keeps reporting the last verdict until the next call to the gate. `tests/test_lifecycle_claude_tool_surface.py` and `tests/test_health_api.py` pin the boot report and the live `/health` field across all three states; that a co-writer turn is actually refused on drift is proven separately, in `tests/test_claude_provider.py`'s `test_cowriter_turn_refuses_a_cli_with_an_unverified_tool_surface` and `test_cowriter_non_stream_turn_refuses_a_cli_with_an_unverified_tool_surface`.
  `POST /api/songs/{id}/chat` (`chat_api.py`) is dead legacy — no frontend, CLI, or test-outside-its-own-suite calls it; the live co-writer chat is `POST /chat/turn` in `conversation_api.py`. It is still gated the same as every other tool-free call, but removing the endpoint outright (rather than guarding it) is the cleaner fix once the operator signs off — it is a public endpoint, so that is not a call this file makes on its own.
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

- **Batch changes, targeted tests once.** All edits first, then only the tests that prove those files.
- **Parallel edits.** Signature change across N files → edit all in parallel.
- **Don't re-read files** you just read in the same conversation.
- **Trust the linter.** Don't run the full suite locally.
- **Coverage is CI.** Do not run `--cov` or `pnpm test:coverage` on this machine unless the operator asks.

## Self-Review (multi-file changes)

1. Re-read changed files in full — coherent whole, no dead traces?
2. Question abstractions — explainable in one sentence?
3. Update `docs/` if the change affects architecture, security, API endpoints, or test structure
4. Run checks (above)

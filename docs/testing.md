# Testing Guide

## Running Tests

Agents and subagents run **only the tests that prove the change**. The full
suite belongs to GitHub CI so it does not saturate this machine (atelier-2
rule: local = targeted, land gate = CI).

```bash
# Backend — targeted (local / agents)
pytest tests/test_api.py -q --tb=short
pytest tests/test_queue_streams.py tests/test_playlists.py -q

# Frontend — targeted (local / agents)
cd frontend && pnpm exec vitest run src/lib/stores/player.test.ts
cd frontend && pnpm exec vitest run src/lib/services/offline.test.ts

# Full suite — CI only, or when the operator asks
pytest tests/ -n auto -q --cov=songmaker_cli --cov=audio_engine --cov=acestep_engine --cov=acestep_worker --cov-report=term-missing --cov-fail-under=90 --cov-config=.coveragerc-ci
cd frontend && pnpm check && pnpm lint && pnpm test:coverage && pnpm build
```

### Parallel Execution

Tests run in parallel via `pytest-xdist` (`-n auto` uses all CPU cores). All tests are isolated:
- Each test gets its own `tmp_path` and SQLite database
- `mock_arq_pool` fixture (conftest.py) isolates the arq connection pool
- `_reset_settings_cache` and `_reset_worker_singletons` autouse fixtures clear `Settings`/`WorkerBase` per-test state
- Settings/worker singletons are reset by fixtures; scorer model caches live in subprocesses
- Scorer tests run on CPU but are excluded from CI coverage because the CI image doesn't ship faster-whisper / audiobox-aesthetics / librosa model weights (see `.coveragerc-ci`)

## Coverage Targets

- **CI backend**: 90% overall across `songmaker_cli` + `audio_engine` + `acestep_engine` + `acestep_worker` (scoring modules excluded — require GPU extras not installed in CI, see `.coveragerc-ci`). CI also installs the `mcp` extra so `tests/test_mcp_server.py` collects.
- **Local**: aim for 100% on non-scoring core modules (exclude `main.py` CLI entrypoint)
- **CI frontend**: `pnpm test:coverage` (70% statement/line floor on `src/lib/**/*.ts`, generated `types.ts` excluded) plus `pnpm build`. 100% on `lib/` remains a local aspiration, not a CI gate.
- **CI PostgreSQL contract**: `tests/test_postgresql.py` runs serially (`-n 0`) against PostgreSQL 16. It is the mandatory proof for migrations, concurrent per-user event-sequence allocation, transactional rollback, and retention gaps; SQLite tests do not stand in for these guarantees.
- **Resource-event transport**: `tests/test_resource_event_api.py` proves the full auth/session boundary, fresh/replay/gap/ahead protocol, paged retention races, exact user isolation, BIGINT-safe wire values, final production headers, 60-second termination (including a blocked outer ASGI send), Redis leases, and fail-closed limits. Protocol-generator tests remain deterministic and route tests use the real app/middleware stack.

GitHub workflows (`.github/workflows/ci.yml`, `e2e.yml`, `security.yml`,
`requirements.yml`, and `requirement-witnesses.yml`) run on push/PR to `main`.
Security and live requirement-witness verification also run weekly. The
requirement workflows are separate visible checks, not enforced merge gates
while issue #31 remains open. The live checks are:

| Job | What |
|---|---|
| Backend | `ruff check src/ tests/` · `scripts/check_no_silent_fallbacks.py src/` · `scripts/generate_types.py --check` · pytest + 90% coverage |
| PostgreSQL contract | Serial PostgreSQL 16 tests for dialect-specific migrations, concurrency, rollback, and event retention gaps |
| Frontend | `pnpm check` · `pnpm lint` · `pnpm test:coverage` · `pnpm build` |
| E2E | Boots the CI stack (`docker-compose.ci.yml`), curl-smokes it, then drives the desktop library flow in Chromium against it |
| Security | bandit (`pyproject.toml`: skip B101/B110/B310/B404/B603, exclude tests; B104/B105/B608 nosec only on known false positives) · pip-audit · `pnpm audit --prod` |
| Requirements | strict offline requirement/acceptance schema · exact bytes and linear history · exact PR/push base · derived PRODUCT view |
| Requirement witnesses | fixed GitHub repo/issue/comment re-fetch · exact identity, URL, author, timestamp, and approval-body match |
| Acceptance evidence | #42-A1 runs the marked Pick-replacement API test and retains its commit-bound JSON report for 30 days |

### No-silent-fallbacks check

`scripts/check_no_silent_fallbacks.py src/` has no exemption list. A reported
line is a defect to fix, and a legitimate exception is expressed in the code
instead:

- **Env reads** belong to the settings module of the package that needs them.
  All read forms count, including the ones carrying a fallback:
  `os.environ.get` / `.pop` / `.setdefault`, `os.getenv`, and `os.environ[K]`.
  Writes, `del`, augmented assignment, and `os.environ.copy()` are process
  state, not configuration, and are not reported. Three roles are out of
  scope, matched by path rather than by file name (so `api_models/settings.py`
  is still judged): `src/<package>/settings.py`, the Alembic migration
  `db/migrations/env.py` (it runs before Settings exists), and
  `src/songmaker_cli/env_override.py`, which owns `temporary_env_override()`
  — the single save-and-restore idiom for a library that reads a variable
  like `CUDA_VISIBLE_DEVICES` on its own.
- **A nullable timestamp** that the response computes is declared as
  `ComputedTimestamp` (`api_models/fields.py`). Plain `datetime | None` on a
  timestamp field still fails, because that is how a NOT NULL column gets
  misdescribed.

`tests/test_check_no_silent_fallbacks.py` runs the checker over the real
`src/` tree, over a table of read and write statements that pins that
boundary, and over seeded files at every path that used to be exempt.

### Acceptance evidence pilot

#42-A1 is one Pytest integration proof for `ACC-CURATION-02` →
`REQ-CURATION-02`. It exercises the FastAPI router and SQLite persistence through
the test client with its test-auth override. It does not prove session/login,
PostgreSQL, a separate server, browser, UI, accessibility, or E2E behavior.
`scripts/acceptance_evidence.py` accepts only one literal direct marker per
top-level test, rejects unknown or orphaned critical integration claims, runs the
claimed tests serially, and writes a point-in-time report containing the checked
out commit, command, exit status, and result. The CI job uploads that report even
when the test fails; its visible result is not a required merge gate until branch
protection is configured.

The witness test suite uses injected fake GitHub clients and transports; local
tests never need a token or make network calls. It covers strict witness parsing,
the empty no-network path, resource and time limits including the outer watchdog,
fixed routes, fork-PR token isolation, pathological JSON, and mismatches at each
link of the repository→issue→comment identity
chain. A green live check proves only what GitHub returned during that run; the
edited/deleted event hooks and weekly schedule reduce, but cannot eliminate, the
time between a later invalidation and detection.

The local binder is covered separately by
`tests/test_requirement_binder.py` and `tests/test_bind_requirement_revision.py`.
Those tests use temporary Git repositories and fake GitHub clients. They cover
Genesis/successor lineage, canonical witness bytes, exact Git/index states,
token isolation from Git, live-capture TOCTOU, process locking and wall timeout,
no-clobber collisions, permission preservation, full planned-contract checks,
same-byte foreign ownership, bounded ignored-directory scans, the final expected
delta, and rollback/manual-recovery behavior at every write boundary. They never
create a real approval or make a network request.

## End-to-end flows

`frontend/e2e/` drives the real stack — Postgres, Redis, migrations and the web
container from `docker-compose.ci.yml` — through the click paths an operator
walks by hand. Unit tests keep missing those: every operator bug from
2026-08-23 (dead picker, ▶ after an album switch, shuffle, 429 storm) passed
them.

Two Chromium projects walk the same flow: `desktop` at 1440×900 and `mobile` at
390×844 with touch input. The steps the two shells share are written once; the
mobile project adds what the compact shell does differently — the rail as a
drawer, the editor opening on Write, Now Playing's judging panel as a sheet,
the one 64px transport row with a thumb-sized play control — plus a 320-wide
check that the album header still reads as a title over its breadcrumb.

What a flow proves that a unit test cannot: the album pick really plays (the
transport offers Pause, not Retry), Now Playing opens on the judged take, a
take reaches a playlist and can be reordered and pruned there, shuffle toggles,
and a share link serves the album to a logged-out visitor. Any 429 or 5xx
response, failed request, browser console error or uncaught page exception
fails the flow, and each flow holds a named `/api` request budget per shell.

- **Projects run serially** (`fullyParallel: false`, one worker). Both shells
  share one stack behind one IP rate-limit window, so their cost is additive and
  measurable instead of a burst. Measured on the first green run: 26 `/api`
  requests per shell, budget 32 each.
- **One login per run.** Global setup authenticates once, seeds an album, songs,
  takes, a pick and a share link through the public API, and hands its session
  to every attempt as storage state. Mutable fixtures (the playlist) are seeded
  per attempt so a retry starts clean.
- **Selectors are roles and accessible names** from `frontend/src/lib/constants.ts`.
  No `data-testid`. A row that cannot be found by its accessible name is an
  accessibility defect, not a selector problem.
- **Locally, never point them at port 8080** — that is the operator's stack.
  Boot the CI stack on its own port and project (`WEB_PORT=18080`), run
  `E2E_BASE_URL=http://localhost:18080 pnpm test:e2e`, then `down -v`.
- Re-running against a warm stack trips the app's IP rate limit (120 requests
  per window) and the flow reports 429s. That is the guard working, not
  flakiness — reset the stack or wait out the window.

`frontend/e2e/README.md` has the exact commands, the audio fixture, and the
budget rule.

## Test Structure

```
tests/
├── conftest.py                    Shared fixtures (DB, WAV/audio factories, arq mocks)
├── test_*_api.py                  Domain API coverage: admin, auth, conversation, generation,
│                                  internal, LoRA, playlist, reimport, sharing, server
├── test_*_queries.py              DB query coverage for workers and LoRAs
├── test_jobs*.py                  Generation, scoring, model lifecycle, LoRA training jobs
├── test_*worker*.py               Music/scoring worker classes and ACE-Step worker package tests
├── test_scoring*.py               Scorer registry, pipeline, subprocess, and scorer modules
├── test_*client*.py               CLI client, ACE-Step client, and training client tests
├── test_auth*.py                  Auth utilities and auth endpoints
├── test_config.py                 ACE-Step config building, defaults, path resolution
├── test_db.py / test_postgresql.py Database models, migrations, PostgreSQL concurrency
├── test_resource_events.py         Durable event sequencing, atomicity, retention, lifecycle
├── test_resource_event_api.py      Authenticated SSE replay, gaps, limits, headers, isolation
├── test_generation*.py            Generation params, retention, LoRA integration
└── test_*                         Audio I/O, lifecycle, middleware, parser, Redis, scheduler,
                                   soft delete, constants, MCP server, mastering

tests/acestep_worker/
├── test_downloads.py
├── test_heartbeat.py
├── test_main.py
├── test_model_cache.py
├── test_progress.py
├── test_registry_client.py
├── test_subprocess_runner.py
├── test_task_store.py
└── test_wrapper.py

frontend/src/
├── lib/api/*.test.ts              API client modules: admin, client, fetch, LoRA,
│                                  resource-event decimal SSE payloads
├── lib/components/*.test.ts       Component tests: library, share status, frequent-action hitboxes,
│                                  components/share/share-import-boundary.test.ts (grep gate: nothing
│                                  under lib/share or components/share runtime-imports
│                                  stores/player|navigation|editor|takeActions|auth)
├── lib/stores/*.test.ts           Store coverage: admin polling, auth, editor, filter,
│                                  health, jobs, library search/context, resource sync
│                                  (hello/snapshot interleavings, replay, stale fetch,
│                                  bootstrap disconnect, resync, focus, retry, cleanup),
│                                  navigation, LoRA, player, playlists, toast
├── lib/services/*.test.ts         Audio player service tests (incl. swapCallbacks/restoreCallbacks,
│                                  loadUrl, unload)
├── lib/share/*.test.ts            Pure sharedCollection adapters; SharePlayback's classic/stream
│                                  dispatch, shuffle, and callback ownership
├── lib/utils/*.test.ts            Chat context, contrast, diff, and format helpers
└── routes/share/**/page.test.ts   Album/playlist/song/take share pages through their real
                                   +page.svelte entry points (loading/error/retry, stream vs
                                   classic playback, windowed-stream stop, Now Playing)
```

```
frontend/e2e/
├── global-setup.ts                One login per run, seeds the library, saves the storage state
├── seed.ts                        Public-API seeding: per-run library, per-attempt playlist
├── helpers.ts                     Guards, shell facts, /api budgets, name matchers
├── library.spec.ts                Library flow, driven in both the desktop and the mobile shell
└── fixtures/take.mp3              3-second tone imported as a real take
```

## Testing Patterns

### Python

- **Real SQLite** for DB tests (`tmp_path` per test, `seeded_db` fixture in `conftest.py`)
- **Synthesized audio** for mastering/scoring tests (sine waves via numpy)
- **Mock external services**: scheduler dispatch, Whisper model, Claude API, ffmpeg
- **Patch at the import location**, not the source: `patch("songmaker_cli.jobs.dispatch_generation")`
- **Factory fixtures** in conftest.py for WAV bytes, stereo audio, song files
- **`Settings` constructed with explicit kwargs** in tests; no monkeypatching of `os.environ` for the fields. Use `monkeypatch.setenv` only for the import-time env vars set in `conftest.py` (`DATABASE_URL`, `REDIS_URL`, `SESSION_SECRET`, `SONGMAKER_INTERNAL_TOKEN`, `WORKER_ID`)

### Frontend

- **jsdom** environment for all tests
- **Mock fetch** globally for API client tests
- **Mock stores** for component isolation
- **`vi.useFakeTimers()`** for job polling tests
- **Svelte store tests** use `get()` to read reactive values

## Adding Tests for New Features

1. Add unit tests for new functions/modules
2. Add API tests if new endpoints are added (use `TestClient` fixture in test_api.py)
3. Run `pytest --cov` to verify no gaps in new code
4. Frontend: add store tests for new state, component tests for new UI logic

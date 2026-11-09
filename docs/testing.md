# Testing Guide

## Running Tests

GitHub CI explicitly sets `-n auto` for parallel test runs and owns the full suite.

The auto-deploy subprocess tests fake Docker and GitHub: they prove that a
changed `vendor/acestep` pin is fetched and checked out before Compose builds.

```bash
# Backend — targeted (local / agents)
pytest tests/songmaker_cli/db -q --tb=short
pytest tests/songmaker_cli/test_queue_streams.py tests/songmaker_cli/test_playlist_api.py -q
# PostgreSQL tests — a disposable server per run, -n auto
scripts/test_postgresql.sh tests/songmaker_cli/test_db_postgresql.py -q

# Frontend — targeted (local / agents)
cd frontend && pnpm exec vitest run src/lib/stores/player.test.ts

# Full suite — CI only, or when the operator asks
pytest tests/ -n auto -q --cov=songmaker_cli --cov=audio_engine --cov=acestep_engine --cov=acestep_worker --cov-report=term-missing --cov-report=xml:reports/coverage.xml --cov-config=.github/workflows/coveragerc-ci.ini
cd frontend && pnpm check && pnpm lint && pnpm test:coverage && pnpm build
```

## Static analysis (SonarCloud)

GitHub CI calls the SHA-pinned `overnightworks/quality` v0.10.0 reusable gate from `.github/workflows/ci.yml`. Its `quality / verdict` check combines `quality check`, Sonar findings and the mandatory job names in [`quality/config.toml`](../quality/config.toml). Failed or skipped dependencies still reach the verdict; cancelled runs do not start the caller. There are no actor or fork exclusions: missing `SONAR_TOKEN` fails closed, including tokenless forks. Dependabot needs the separately configured Dependabot secret.

The backend and frontend producers retain their separate coverage artifacts. The `coverage` assembly job downloads both, requires nonempty XML and LCOV reports, and uploads exactly those files as `coverage`, replacing the artifact on reruns. The gate restores it into the checkout; [`sonar-project.properties`](../sonar-project.properties) therefore names `coverage.xml` and `frontend-coverage/lcov.info`. The [SonarCloud project page](https://sonarcloud.io/project/overview?id=overnightworks_songmaker) shows the resulting analysis and coverage.

Findings from the run's own analysis block the verdict, including accepted and false-positive findings; the required bar is zero. The gate owns scan waiting and findings evaluation, so the properties file has no wait override or rule exemptions. On pull requests, existing default-branch Sonar findings are reported by default; `quality check` findings still block. This verdict does not replace SonarCloud's native coverage-on-new-code or hotspot-review gate: verify its actual check/rules status and keep it green wherever required.

Adoption is complete only after authenticated enforcement checks and the post-merge main run prove the verdict and both reports. The operator enables `quality_gate=true` after a green verdict and verifies the required context is exactly `quality / verdict`; older open PRs must merge main to supply that check. Automatic analysis must be off. Red main blocks deployment; retain the last green deployment and forward-fix. Any temporary enforcement rollback requires an explicit operator ruling.

The scope covers `src`, `frontend/src` and `scripts`. Backend `tests`, frontend unit tests, and frontend E2E tests are test scope. It excludes the vendored ACE-Step fork (`vendor/**`, maintained in its own repository), design mockups (`docs/mockups/**`), generated test artifacts (`frontend/e2e/test-results/**` and `frontend/playwright-report/**`), planning material (`plans/**`), dependencies (`**/node_modules/**`), SvelteKit output (`**/.svelte-kit/**`), and frontend build output (`frontend/build/**`). These are not product code and would distort the analysis.

Coverage exclusions are intentionally narrower and identical in `.github/workflows/coveragerc-ci.ini` and `sonar-project.properties`, except `scripts/**`, which only the Sonar side names because pytest `--cov` never measures `scripts` and its lines would otherwise read as 0 % new code: `src/songmaker_cli/main.py` (CLI entry point and local recovery commands); `src/songmaker_cli/scoring/audiobox_aesthetics.py` and `src/songmaker_cli/scoring/emotional_dynamics.py` (heavy model runtime absent from CI); `src/songmaker_cli/scoring/text_accuracy.py` (Whisper model absent from CI); `src/songmaker_cli/db/migrations/versions/**` (historical Alembic/PostgreSQL deployment artifacts); and `frontend/src/service-worker.ts` (browser/build runtime proven outside Vitest coverage). Testable scorers remain measured.

### Parallel Execution

CI runs tests in parallel via `pytest-xdist` (`-n auto` uses all CPU cores). All tests are isolated:
- Each test gets its own `tmp_path` for files
- A database test gets its worker's own PostgreSQL database, reset to its migrated state after the test (see [Database Tests](#database-tests))
- `mock_arq_pool` fixture (conftest.py) isolates the arq connection pool
- `_reset_settings_cache` and `_reset_worker_singletons` autouse fixtures clear `Settings`/`WorkerBase` per-test state
- Settings/worker singletons are reset by fixtures; scorer model caches live in subprocesses
- Heavy scorer tests are excluded from CI coverage because the CI image doesn't ship the Whisper/provider model runtimes; the BPM, silence, and spectral scorers are measured because CI installs the `signal` extra (see `.github/workflows/coveragerc-ci.ini`)

### Database Tests

Every database test runs on a real PostgreSQL; no test uses another database engine.

**Running.** `scripts/test_postgresql.sh <files and pytest arguments>` starts a disposable container of Compose's PostgreSQL image, runs pytest against it and removes it. It needs Docker and `.venv`, refuses to start under high machine load, caps the run and the container's lifetime, and takes no probe-stack lock. Its header owns the limits and their values.

**Writing.** A test needs no marker: the case record (see CI PostgreSQL tests) decides from the fixture closure that it is a database test. Pick the fixture by what the test needs:
- `pg_factory`: a session factory on this worker's migrated database; the fixture disposes its engine before the reset.
- `db_factory` and `seeded_db` (`tests/support/generation_job_world.py`): `pg_factory` together with `fresh_settings`, and on it a seeded user, album and song.
- `extra_pg_factory`: builds further migrated databases for a test that needs more than one; each is dropped afterwards.
- `empty_postgresql_url`: an empty database for a test that migrates it itself.
- `postgresql_url` and `postgresql_databases`: the worker's database URL and its owner, for a test that connects itself.

A test that takes `pg_factory` and `fresh_settings` lists `pg_factory` first, because `pg_factory` reads and caches the settings. A test closes every connection and disposes every engine it opens itself: a connection left open fails the test's teardown.

**Reset.** `tests/support/postgresql.py` owns the databases. Each run and xdist worker gets one database, named with the run and worker id and migrated through production `init_db()`. After every test that used it, the owner locks every table under a lock and statement timeout, checks that the schemas and columns are those recorded after migration and the revision is at head, then empties every application table except `alembic_version` and restores the rows the migration seeded. Drift, or a check that cannot read the tables, fails that test before anything is removed, and the database is recreated; if that fails, or the first migration fails, every later database fixture of the worker errors with the original cause. A connection the test left open fails its teardown: one in a transaction makes the reset wait past its lock timeout, and every other client connected to the worker database while the reset holds its locks is found and ended before it can write, while one that connects only after the reset commits is the next reset's to find. The owner reports the open backends of that database (no SQL text) and terminates only those, before it restores a row. The administration URL names its database in its path; a query option that selects a database is refused. The owner never migrates, empties or drops the server's administration database, and it drops its own at the end of the run, also after an interrupt. `tests/test_postgresql_databases.py` proves these rules.

## Coverage Targets

- **CI backend**: two separate floors, one on statement lines and one on branches, judged by the "Coverage summary and floors" step of the `backend-coverage` job in `.github/workflows/ci.yml`. That job turns the raw coverage data of the `backend` job (`coverage combine`) into the one `reports/coverage.xml` that Sonar reads. The step reads the two measured percentages from that report, owns the floor values in its own environment and prints both in the step summary (coverage.py's `fail_under` would judge both combined, so it is not used). The `backend` job measures with `.github/workflows/coveragerc-ci.ini`, which turns branch measurement on and records relative paths. It covers `songmaker_cli` + `audio_engine` + `acestep_engine` + `acestep_worker` (the three heavy scoring modules are excluded; lightweight scoring modules remain measured, see `.github/workflows/coveragerc-ci.ini`). `backend-coverage` is a mandatory job in `quality/config.toml`, so a red floor turns `quality / verdict` red.
- **CI frontend**: `pnpm test:coverage` plus `pnpm build`. Vitest measures every `.ts` and `.svelte` file under `frontend/src/`, loaded by a test or not, except the test files and the test setup file (which Vitest leaves out itself; other test support under `src/tests/` is measured). The config excludes the generated `src/lib/api/types.ts`, the re-export barrel `src/lib/index.ts` and `src/service-worker.ts` (browser/build runtime proven outside Vitest). Floors for statements, lines and branches on that set, and the preserved statement and line floors on `src/lib/**/*.ts`, live in `frontend/vitest.config.ts`, which owns the values.
- **CI PostgreSQL tests**: the `backend` job (`.github/workflows/ci.yml`) runs every test, the database tests included, against its own PostgreSQL 16 service (`TEST_DATABASE_URL`); a step before the tests turns off the service's `fsync`, `synchronous_commit` and `full_page_writes` and checks they took effect. It is the mandatory proof for migrations, concurrent writes and the locks that order them, transactional rollback, retention gaps and accounting; no other database stands in for these guarantees. `tests/support/database_case_record.py` decides which collected cases are database cases, by each case's fixture closure (it includes `postgresql_databases`, however a support helper reaches it), and records that as a `database_case` property in the junit report. A Backend step reads only that record and fails the build when no database case ran, when any recorded database case skipped, or when no reference quota case ran, and prints the case count of every module with one. A module skipped whole at collection has no cases to record, so the record cannot name it. One fixture in `tests/conftest.py` reads `TEST_DATABASE_URL`; a missing, malformed or unreachable server fails every database test, none skips. `tests/test_postgresql_url_owner.py` rejects a string or bytes constant containing `TEST_DATABASE_URL` in code anywhere under `tests/` but `conftest.py` and the check file itself, which has to name it; docstrings and comments are exempt, so any literal spelling of an environment read is caught. A computed environment key or a loop over `os.environ` gets past that check; only deliberate obfuscation does. The write-lock modules share `tests/support/postgres_lock_harness.py` (hold one writer at its commit, start the second, require through `pg_blocking_pids` that it waits behind the first). Component tables preserve draft references on the exact 409; desktop and 390px browser proof remains a separate landing requirement.
- **Resource-event transport**: `tests/songmaker_cli/test_resource_event_api.py` proves the full auth/session boundary, fresh/replay/gap/ahead protocol, paged retention races, exact user isolation, BIGINT-safe wire values, final production headers, 60-second termination (including a blocked outer ASGI send), Redis leases, and fail-closed limits. Protocol-generator tests remain deterministic and route tests use the real app/middleware stack.
- **Not measured**: Playwright E2E, because `e2e.yml` drives a plain, uninstrumented build of the CI stack and collects no coverage, so the browser flows add nothing to the Sonar reports; and `scripts/`, because the backend `--cov` flags name only `songmaker_cli`, `audio_engine`, `acestep_engine` and `acestep_worker`, so `scripts/` stays outside the coverage reports (Sonar scopes it but excludes it from coverage).

GitHub workflows (`.github/workflows/ci.yml`, `e2e.yml` and `code-scanning.yml`) run on push/PR to `main`.
Code scanning also runs weekly. The live checks are:

| Job | What |
|---|---|
| Backend | `ruff check src/ tests/` · `scripts/check_no_silent_fallbacks.py src/` · `scripts/check_requirement_citations.py` (every `REQ-` heading in `docs/*.md` is cited by a test, and no test cites an undefined one) · `scripts/generate_types.py --check` · pytest against a PostgreSQL 16 service (one database per xdist worker: dialect-specific migrations, concurrency, rollback, event retention gaps) collecting coverage data, judged in Combine backend coverage |
| Combine backend coverage | Combines the Backend coverage data and judges the line and branch floors (see Coverage Targets) |
| Quality | `quality / verdict`: `quality check`, Sonar findings, mandatory jobs and both coverage reports |
| Frontend | `pnpm check` · `pnpm lint` · `pnpm test:coverage` · `pnpm build` |
| E2E | Boots the CI stack (`docker/docker-compose.ci.yml`: Postgres, Redis, web and the music worker; web migrates at start, and the boot is two `up --wait` steps, the stores first, so a worker image that cannot start fails the boot), curl-smokes it, then drives the library flows in Chromium against it, one job per Playwright project (`desktop`, `mobile`), each with its own runner and stack |
| Security | runs inside `quality / verdict`: quality's `python-security` rule (ruff's `S` rules; known false positives carry a `# noqa: S…` with its reason) · Python lockfiles are covered by quality's advisory rule (the frontend has only devDependencies, so no production audit applies, and its `pnpm-lock.yaml` is not audited until quality's advisory rule reads it) |

### No-silent-fallbacks check

`scripts/check_no_silent_fallbacks.py src/` has no per-violation allowlist. A
reported hit is a defect to fix, and a legitimate exception is expressed in
the code instead, as a narrow, documented role exemption tied to a specific
file's job:

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
- **`cowriter/tools.py`** is exempt from the `dict[str, Any]`-in-signature
  rule: `execute_cowriter_tool` dispatches raw tool-call JSON across the
  heterogeneous handlers whose only shared shape is each tool's own JSON
  Schema (`CowriterTool.parameters`). Collapsing that into named per-tool
  argument models is a multi-file rework, tracked as a follow-up (#332,
  finding F15), not something this checker fixes by itself.

`tests/scripts/test_check_no_silent_fallbacks.py` runs the checker over the real
`src/` tree, over a table of read and write statements that pins that
boundary, and over seeded files at every path that used to be exempt.

### API type contract

`scripts/generate_types.py --check` derives the browser contract from the
registered `api`, `audio_api`, `health_api`, and `sharing_api` routers without starting the
application lifecycle. It follows every route's `response_model` and body
parameter through nested Pydantic annotations, then supplements that set with
exported `api_models` and checks that each discovered model has a TypeScript
interface in `frontend/src/lib/api/types.ts`. The output always states `Checked
N API models`. The only route role excluded is
`/api/internal/`: worker registration is a
backend-to-backend protocol rather than a browser surface.

Run `python scripts/generate_types.py` after changing a routed model, then
`python scripts/generate_types.py --check`. `tests/scripts/test_generate_types.py`
plants routed response, body, and nested models to prove a stale type file
fails with the missing model name and a regenerated file passes. A routed model
declared outside `songmaker_cli.api_models` that no named exemption in the
script holds makes both modes exit 1, naming the model and its module, before
anything is written.

### Alert rules (promtool)

`monitoring/rules/alert.rules.yml` is Prometheus' own schema, so Prometheus' own
tool checks and unit-tests it rather than pytest.
`monitoring/alert.rules.test.yml` feeds the real rule file synthetic series
and asserts which alerts fire — in particular that a job failure is caught
both when Prometheus watched the metric across it and when its very first
sample of the series already carries it (issue #333). CI runs this as the
`alert-rules` job; locally:

```bash
docker run --rm -v "$PWD/monitoring:/monitoring:ro" -w /monitoring \
  --entrypoint promtool prom/prometheus:v3.15.1@sha256:fa3302279710be2f21a8301ec17a8b4f2301fd829bd113839b3b6b02b6f191a2 test rules alert.rules.test.yml
```

## End-to-end flows

`frontend/e2e/` drives the real stack — Postgres, Redis and the web
container from `docker/docker-compose.ci.yml` — through the click paths an operator
walks by hand. Unit tests keep missing those: every operator bug from
2026-08-23 (dead picker, ▶ after an album switch, shuffle, 429 storm) passed
them.

A test stack stays on this machine and dies with it. It publishes the web port
on loopback only (`127.0.0.1:${WEB_PORT}`), like the live stack, because a
Docker-published port bypasses ufw and an all-interface binding reaches the LAN.
Every service runs with `restart: "no"`, so a stack nobody tore down does not
come back after a reboot. `tests/test_packaging_boundary.py` renders the CI
stack, with and without the Voices overlay, through `docker compose config` and
pins both.

Two Chromium projects walk the same flow: `desktop` at 1440×900 and `mobile` at
390×844 with touch input. The steps the two shells share are written once; the
mobile project adds what the compact shell does differently — bottom tabs (`phone-tabs.spec.ts`),
the editor opening on Edit, Now Playing's judging panel as a sheet,
the one 64px transport row with a thumb-sized play control — plus a 320-wide
check that the album header still reads as a title over its song count.
Which project runs a test is decided by its shell tag in
`frontend/playwright.config.ts`, never by a `test.skip` inside the test: a
test, or a describe whose every test belongs to one shell, carries
`ONLY_IN_SHELL.desktop` or `ONLY_IN_SHELL.mobile` from
`frontend/e2e/helpers.ts`, and the other shell's project leaves it out.

What a flow proves that a unit test cannot: the album pick really plays (the
transport offers Pause, not Retry), Now Playing opens on the judged take, a
take reaches a playlist and can be reordered and pruned there, a playlist row
plays and judges its take the same way an editor take row does — docked beside
the playlist on desktop, as a sheet on mobile — shuffle toggles, and a share
link serves the album to a logged-out visitor. A second `library.spec.ts` test
proves the rail itself the same way (issue #326): a collapsed row's songs are
provably invisible and an expanded row's provably not — `grid-template-rows:
0fr` + `overflow: hidden` collapses to zero height only in a real layout
engine, which jsdom never runs — the rail's one-open-album rule holds as that
same real visibility, and Settings stays in view after the rail's own list is
scrolled. Any 429 or 5xx response, failed request, browser console error or
uncaught page exception fails the flow, and each flow holds a named `/api`
request budget per shell.

- **Projects run serially** (`fullyParallel: false`, one worker). In CI each
  project has its own job, stack and IP rate-limit window; locally both shells
  run one after the other in one stack behind one window, so their cost is
  additive and measurable instead of a burst. Each flow's measured count and budget are
  a code comment on its constant (`LIBRARY_FLOW_API_REQUEST_BUDGET`,
  `RAIL_FLOW_API_REQUEST_BUDGET` in `frontend/e2e/helpers.ts`) — that is the
  one place the number is written down, so it cannot drift out of sync with
  this doc the way it did before issue #326.
- **One seeded session per run.** There is no Keycloak in the CI stack, so no
  flow types a password. `frontend/e2e/support/seed_sessions.py` runs inside the
  web container and opens database sessions whose cookie the pinned library
  signs, and it creates the e2e admin (`E2E_ADMIN_USERNAME`) because the stack
  has no admin bootstrap. Global setup seeds an album, songs, takes, a pick and
  a share link through the public API with that admin's session and hands it to
  every attempt as storage state. Mutable fixtures (the playlist) are seeded
  per attempt so a retry starts clean. `queue-continuity.spec.ts` seeds a
  flow-owned account once per project, gives it an album with three songs and
  no pick, and deletes the account afterwards: a library with nothing picked
  cannot be reached from the shared admin library. `auth-flows.spec.ts`
  starts from an explicitly empty storage state and proves what runs without
  Keycloak: the start redirect to the issuer, the signed-out, no-access and
  failed pages, and logout. The identity provider is a stub
  (`stubIdentityProvider`), and a real login is proven live, not in CI. The
  stack's `OIDC_ISSUER` names an issuer that never answers and its client secret
  is a throwaway file (`KEYCLOAK_CLIENT_SECRET_FILE`), as is the gateway key
  (`GATEWAY_KEY_FILE`); web boots without reaching the issuer. The spec's numbers live in `frontend/e2e/README.md`.
- **Sign-in routes run against a fake issuer.** `tests/songmaker_cli/test_auth_api_sign_in.py`
  drives `/login/oidc`, `/auth/callback` and `/auth/logout` (webauth's routes) through the real
  relying party; only the token request and the key set come from
  `tests/support/fake_oidc_issuer.py`, which signs ID tokens with a test RSA key, so
  every token is verified as in production.
- **Selectors are roles and accessible names** from `frontend/src/lib/constants.ts`.
  No `data-testid`. A row that cannot be found by its accessible name is an
  accessibility defect, not a selector problem.
- **Locally, never point them at port 8080** — that is the operator's stack.
  Boot the CI stack on its own port and project (`WEB_PORT=18080`), run
  `E2E_BASE_URL=http://localhost:18080 pnpm test:e2e`, then `down -v --remove-orphans --rmi local`.
- Re-running against a warm stack trips the app's IP rate limit (120 requests
  per window) and the flow reports 429s. That is the guard working, not
  flakiness — reset the stack or wait out the window.
- The CI stack allows 200 resource-event stream opens per user. In the
  2026-09-05 CI run, 30 opens succeeded and the 31st returned 429.
- **`setOffline` does not cut an open event stream.** Chromium's offline
  emulation flips `navigator.onLine` and fires `offline`, but an SSE
  connection the page already holds keeps delivering, and nothing tells the
  page it dropped (checked 27.09.2026 against a plain `EventSource`). A flow
  that loses the network uses `loseNetwork` / `regainNetwork` from
  `frontend/e2e/helpers.ts`: it also stops the page's open loads
  (`window.stop()`, which ends the stream with an `error` the way a dropped
  network does) and refuses every reopen of the resource stream until the
  network returns. `loseNetwork(page, context, { keepOpenStreams: true })`
  skips the `window.stop()`: the streams already open keep delivering and only
  new requests are refused, the moment a stream's last event (a job's end) is
  already on its way when the network goes. Such a flow builds its `FlowGuard` with
  `losesNetworkOnPurpose`, so that guard does not count a request failed with
  `net::ERR_INTERNET_DISCONNECTED`, nor a load `window.stop()` ended in flight
  (`net::ERR_ABORTED` while the network is away); every other flow still fails
  on one.

`frontend/e2e/README.md` has the exact commands, the audio fixture, and the
budget rule.

### Voices E2E worker

The Voices browser flow adds `docker/docker-compose.e2e-voices.yml` to the normal CI
stack. It starts the test-only worker at
`tests/support/fake_training_worker.py`; the Library E2E continues to use
only `docker/docker-compose.ci.yml`.

Run the proof as one capped command under the probe lock; the script starts the
isolated stack, runs `e2e/voices.spec.ts` against it and tears the stack down:

```bash
flock -o -w 3600 /tmp/probe-stack.lock setpriv --pdeathsig TERM timeout -k 120 1700 scripts/voices_e2e_probe.sh
```

The fake worker uses the same internal worker registration, Redis heartbeat,
GPU-hold, task-SSE, and adapter-result contracts as the ACE-Step worker. It
only replaces model training and generation output; ARQ, job, and database
handling remain in the application. The two S5 occupancy jobs target one
dedicated song/version whose existing prompt exactly equals
`FAKE_GENERATION_OCCUPANCY_PROMPT`; no generation request carries a prompt.
All other fake generations produce a deterministic 1-second mono WAV from the
exact tuple `(prompt, seed, adapter path)`. The browser proof trains its voices
through the normal lifecycle, then proves the ready-mode chip, a foreign-mode
picker option named `not available for this model`, distinct WAV bytes with and
without the adapter, and that deleting the used voice leaves a playable take
named `voice deleted` after reload. It does not seed a ready status or adapter
storage path.

## Test Structure

New and moved backend tests mirror the code they test: a test for `src/songmaker_cli/db/queries/loras.py` lives in `tests/songmaker_cli/db/queries/` and is named for it, and the engine packages mirror under `tests/acestep_engine/`, `tests/audio_engine/` and `tests/acestep_worker/`. `tests/conftest.py` holds the shared fixtures, and `tests/support/` the helpers and pytest plugins that tests import as `support.<module>`, never from `conftest`.

```
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
│                                  loadUrl, unload); lyrics alignment transport (latest take wins,
│                                  synchronous fallback where the platform has no Worker)
├── lib/share/*.test.ts            Pure sharedCollection adapters; SharePlayback's classic/stream
│                                  dispatch, shuffle, and callback ownership
├── lib/utils/*.test.ts            Chat context, contrast, diff, and format helpers
└── routes/share/**/page.test.ts   Album/playlist/song/take share pages through their real
                                   +page.svelte entry points (loading/error/retry, stream vs
                                   classic playback, windowed-stream stop, Now Playing)
```

```
frontend/e2e/
├── global-setup.ts                One seeded admin session per run, seeds the library, saves the storage state
├── seed.ts                        Public-API seeding: per-run library, per-attempt playlist
├── helpers.ts                     Guards, shell facts, /api budgets, name matchers
├── library.spec.ts                Library flow and the rail's own disclosure/pin promises (#326),
│                                  both driven in the desktop and the mobile shell
└── fixtures/take.mp3              3-second tone imported as a real take
```

The auth library's own tests are not in this repository. They moved with
`webauth` to [overnightworks/webauth](https://github.com/overnightworks/webauth)
in #879 and run in that repository's CI; songmaker installs its pinned git tag
and proves the auth surface it builds on it through `test_auth_api_sign_in.py`,
`test_auth_api.py`, `test_auth_dependencies.py`, `test_server_middleware.py`, and `e2e/auth-flows.spec.ts`.

## Testing Patterns

The frontend CI job runs `python3 ../scripts/check_style_literals.py` (from
`frontend/`) against `.svelte`, `.ts`, and `.css` files in `frontend/src`,
excluding `app.css` and comments. Test files (`*.test.ts` and `*.spec.ts`) are
excluded so issue references in test names are not counted as hex colors.
It counts hex and rgb/hsl colors, pixel `border-radius` declarations (including
longhands), `font-size` literals outside the
22/15/13/12/11/10 px scale (including equivalent rem values at a 16 px root),
and literal `box-shadow` declarations. A shadow containing a color counts in
both categories. `scripts/style-literals.txt` lists one `path count` line per
file (relative to `frontend/src`, sorted) with its current count. A file whose
count grows, or a new file with literals, fails and prints the stored and
current count with that file's literal locations. A file whose count fell, or
that is gone or has none, fails as stale until `--update` writes the smaller
baseline. `--update` never raises or adds an entry; ordinary checks never
rewrite the file. The same check also fails on any `var(--x)` in `frontend/src`
(`app.css` included, test files excluded) whose name no declaration defines,
and prints each as `path:line --x`; a fallback does not excuse an undefined
token, and there is no baseline. Declarations come from `frontend/src` (a
`--x:` in CSS, `<style>` blocks and inline `style` attributes, `style:--x`, and
any quoted `'--x'` string in script code, which is how `setProperty` receives its
name, directly or through a named constant; comments define nothing) and from
the installed appkit stylesheet under `frontend/node_modules`, which is
required: without it the check fails and names the path. The file fixtures in
`tests/scripts/test_check_style_literals.py` prove detection and ratchet behavior.

`scripts/test_helper_ratchet.sh` holds each helper name defined in more than one
test module: module-level private Python functions in `tests/`, and
top-level named functions, `const` function expressions, or `const` object literals in
`frontend/src/**/*.test.ts`.
Calls and repeated definitions within one file do not count.
`scripts/test_helper_ratchet.txt` lists one `tree name modules` line per
duplicated name (`backend` or `frontend`, sorted) with the number of test modules
that define it. A new duplicated name or a name in more modules fails, and one in
fewer modules or no longer duplicated fails as stale, each naming the stored and
current count. After consolidation, run `scripts/test_helper_ratchet.sh --update`
to commit the smaller baseline; it never raises or adds an entry, and normal
checks never rewrite it. Router-only API tests use `make_router_ctx` from
`tests/support/web_app.py` to prepare a context with an optional database and seed callback,
then `make_router_app(ctx, user=...)` to mount the router. `make_authenticated_user` (`tests/support/web_app.py`)
builds active users with an explicit ID and optional role and username. Full
middleware and lifecycle tests continue to use `make_test_app`.

### Python

- **Real PostgreSQL** for DB tests: `seeded_db` (`tests/support/generation_job_world.py`) or `pg_factory` on the worker's database (see [Database Tests](#database-tests))
- **Synthesized audio** for mastering/scoring tests (sine waves via numpy)
- **Mock external services**: scheduler dispatch, Whisper model, Claude API, ffmpeg
- **Patch at the import location**, not the source: `patch("songmaker_cli.jobs.dispatch_generation_on_worker")`
- **Factory fixtures** in conftest.py for WAV bytes and stereo audio
- **`Settings` constructed with explicit kwargs** in tests; no monkeypatching of `os.environ` for the fields. Use `monkeypatch.setenv` only for the import-time env vars set in `conftest.py` (`DATABASE_URL`, which names no usable database so an engine built from settings fails at once, `REDIS_URL`, `SESSION_SECRET`, `SONGMAKER_INTERNAL_TOKEN`, `WORKER_ID`, `PUBLIC_BASE_URL`). A compose stack gets the four songmaker secrets as files: the CI e2e workflow and `scripts/voices_e2e_probe.sh` write throwaway ones into a temporary directory and set `SONGMAKER_SECRETS_DIR`, and `tests/scripts/test_secret_files_compose.py` renders the real compose to prove no service receives one as an environment variable

### Frontend

- **jsdom** environment for all tests
- **Mock fetch** globally for API client tests
- **Mock stores** for component isolation
- **`vi.useFakeTimers()`** for job polling tests
- **Svelte store tests** use `get()` to read reactive values
- **jsdom ships no `Worker`**, so `alignInWorker` runs the same pure alignment synchronously there.
  A test that needs to see the state *before* the answer arrives (`NowPlayingLyrics.test.ts`) stubs
  `Worker` with a fake that runs the real pure function and delivers it when the test says so. Every
  such fake `postMessage` **structured-clones its request**, so a take that could not really cross
  the worker boundary — reactive `$state` cues from a share page — fails in the test too
- **Runes need a `.svelte.ts` module**: `src/tests/reactive-fixtures.svelte.ts` hands a plain
  `.test.ts` a real `$state` proxy or props a mounted component follows when the test changes them
- **Hitbox floor tests measure the real cascade, not the hitbox sheet alone.** Vitest never extracts
  a mounted component's scoped `<style>` into the document, so a test that only injects the global
  hitbox sheet (`test-utils/hitbox.ts`) cannot see a component's own rule outrank it — that is exactly
  how the Breadcrumb link shrank to 0px and stayed unclickable (#185) while its hitbox test stayed
  green. `test-utils/component-styles.ts` recompiles a component's own source and injects its `<style>`
  pinned to the scope class already on the mounted DOM, so `frequent-hitbox.test.ts`'s inventory
  measures every target against hitbox sheet + component sheet together. It asserts the floor twice:
  once with `setPointer()` unset, at the exact specificity `[data-hitbox='frequent']` and its
  `@media (any-pointer: coarse)` variant ship at in production (jsdom cannot match `any-pointer`
  itself, hence `setPointer()`'s `html[data-pointer]` selectors exist at all — but that override is
  more specific than a two-class scoped selector, so it would mask the exact regression this exists
  to catch), and again through `setPointer('fine'|'coarse')` for the pixel values themselves.

## Adding Tests for New Features

1. Add unit tests for new functions/modules
2. Add API tests if new endpoints are added (use `TestClient` fixture in test_api.py)
3. Run `pytest --cov` to verify no gaps in new code
4. Frontend: add store tests for new state, component tests for new UI logic

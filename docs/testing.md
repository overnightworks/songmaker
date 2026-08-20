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

GitHub workflows (`.github/workflows/ci.yml`, `security.yml`) run on push/PR to `main`. Security also runs weekly. The live checks are:

| Job | What |
|---|---|
| Backend | `ruff check src/ tests/` · `scripts/check_no_silent_fallbacks.py src/` · `scripts/generate_types.py --check` · pytest + 90% coverage |
| Frontend | `pnpm check` · `pnpm lint` · `pnpm test:coverage` · `pnpm build` |
| Security | bandit (`pyproject.toml`: skip B101/B110/B310/B404/B603, exclude tests; B104/B105/B608 nosec only on known false positives) · pip-audit · `pnpm audit --prod` |

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
├── test_db.py / test_postgresql.py Database models, migrations, concurrency
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
├── lib/api/*.test.ts              API client modules: admin, client, fetch, LoRA
├── lib/stores/*.test.ts           Store coverage: admin polling, auth, editor, filter,
│                                  health, jobs, LoRA, player, toast
├── lib/services/*.test.ts         Audio player service tests
└── lib/utils/*.test.ts            Chat context, contrast, diff, and format helpers
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

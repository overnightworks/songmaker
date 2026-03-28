# Testing Guide

## Running Tests

```bash
# Backend (from project root)
pytest tests/ -q                    # all tests
pytest tests/ -q --tb=short         # with short tracebacks
pytest tests/test_api.py -v         # single file, verbose
pytest tests/ --cov=songmaker_cli --cov-report=term-missing  # coverage

# Frontend (from frontend/)
pnpm test                           # all tests
pnpm test:coverage                  # with v8 coverage report
```

## Coverage Targets

- **CI**: 90% overall (scoring modules excluded — require GPU extras not installed in CI, see `.coveragerc-ci`)
- **Local**: aim for 100% on non-scoring core modules (exclude `main.py` CLI entrypoint)
- **Frontend**: 100% statement coverage on `lib/` (`pnpm test` to see current count)

## Test Structure

```
tests/
├── conftest.py              Shared fixtures (WAV generators, song file factory)
├── test_admin_api.py        Admin endpoints (user CRUD, sessions, login attempts)
├── test_api.py              API endpoint tests (FastAPI TestClient)
├── test_auth_api.py         Auth endpoints (login, setup, password)
├── test_auth.py             Auth utilities (bcrypt, session config)
├── test_cli.py              CLI helper function tests (generate, decode, write)
├── test_cli_client.py       HTTP client tests (resolve_song, api_get/post/put)
├── test_client.py           ACE-Step HTTP client tests
├── test_claude_provider.py  Claude API/CLI backend tests
├── test_config.py           ACE-Step config building, path resolution
├── test_db.py               DB models, queries, engine, migrations
├── test_acestep_manager.py   ACE-Step lifecycle, VRAM management
├── test_arq_pool.py         arq connection pool, Redis health queries
├── test_worker.py           arq worker tasks, idempotency, startup/shutdown
├── test_jobs.py             Background generation + scoring job runners
├── test_mastering.py        Mastering chain (compression, LUFS, clipping)
├── test_middleware.py       Auth middleware and FastAPI dependencies
├── test_parser.py           SongMeta/AlbumMeta data model tests
├── test_audio_io.py         WAV read/write, MP3 encoding
├── test_rate_limit.py       Rate limiting (generation, scoring, queue depth)
├── test_scorers.py          Silence, BPM, dynamics scorers
├── test_scorers_extended.py Spectral, audiobox, text accuracy, coherence
├── test_scoring_pipeline.py Pipeline registry, runner, type validation
├── test_sharing.py          Album sharing (share/unshare, shared view, rate limit)
└── test_server.py           Server app creation, static files, audio routes

frontend/src/
├── lib/api/client.test.ts          API client (all endpoints, error handling)
├── lib/stores/auth.test.ts         Auth store (login, logout, role checks)
├── lib/stores/editor.test.ts       Editor store (dirty tracking, save, diff)
├── lib/stores/filter.test.ts       Filter store (metrics, add/remove, apply)
├── lib/stores/jobs.test.ts         Job polling, completion, error retry
├── lib/stores/player.test.ts       Browsing, playback, score updates
├── lib/stores/settings.test.ts     Claude key persistence
├── lib/utils/diff.test.ts          LCS diff algorithm
└── lib/utils/format.test.ts        Number/time formatting
```

## Testing Patterns

### Python

- **Real SQLite** for DB tests (`tmp_path` per test, `reset_engine()` in fixtures)
- **Synthesized audio** for mastering/scoring tests (sine waves via numpy)
- **Mock external services**: ACE-Step client, Whisper model, Claude API, ffmpeg
- **Patch at the import location**, not the source: `patch("songmaker_cli.jobs.AceStepClient")`
- **Factory fixtures** in conftest.py for WAV bytes, stereo audio, song files

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

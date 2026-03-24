# Songmaker Architecture

## Overview

AI-powered song generation platform. Songs are created, generated, scored, and reviewed through a web UI. All data lives in SQLite. The CLI is a thin HTTP client to the same API.

```
┌─────────────────────────────────┐
│   SvelteKit Frontend            │
│   Single-page app: editor,      │
│   player, Claude chat, filters  │
└──────────────┬──────────────────┘
               │ REST API
               ▼
┌─────────────────────────────────┐
│   FastAPI Backend               │
│   api.py → api_models.py        │
│   Pydantic request/response     │
└───┬──────────┬──────────┬───────┘
    │          │          │
 SQLite    GPU Queue    External
 (data)    (jobs.py)    (ACE-Step, Claude, Whisper)
```

## Data Model

```
Song (title + album)
  └── Version (lyrics, prompt, BPM, key, duration, generation_params)
        └── Generation (MP3, seed, scores, rating, whisper text)
```

All in SQLite with SQLAlchemy ORM. Alembic for migrations.

## Package Structure

```
src/
├── acestep_engine/     ACE-Step HTTP client (retry, polling, models)
├── audio_engine/       Mastering chain, WAV/MP3 I/O, LUFS
└── songmaker_cli/
    ├── main.py          CLI (httpx HTTP client)
    ├── cli_client.py    HTTP helpers (resolve_song, poll_job)
    ├── server.py        FastAPI app, static files, startup
    ├── api.py           REST endpoints
    ├── api_models.py    Pydantic models with from_orm()
    ├── jobs.py          Background generation + scoring
    ├── gpu_queue.py     GPU job queue, ACE-Step lifecycle
    ├── config.py        ACE-Step config, path resolution
    ├── generate.py      Generation engine (decode, master, MP3)
    ├── parser.py        Data models (SongMeta, AlbumMeta)
    ├── db/
    │   ├── models.py    SQLAlchemy ORM models
    │   ├── queries.py   DB query functions
    │   ├── engine.py    DB init, WAL mode, session factory
    │   └── migrations/  Alembic migrations
    ├── scoring/
    │   ├── pipeline.py  ScorerRegistry, fault-isolated runner
    │   ├── text_accuracy.py      Whisper transcription comparison
    │   ├── emotional_dynamics.py  Pitch/RMS/onset analysis
    │   ├── bpm_accuracy.py       BPM detection vs intended
    │   ├── silence_detection.py   Gap detection
    │   ├── spectral_quality.py    Noise artifact detection
    │   ├── audiobox_aesthetics.py Meta AudioBox model
    │   └── lyrical_coherence.py   Claude-judged coherence
    └── claude/
        └── provider.py  Claude API + CLI backends

frontend/               SvelteKit + TypeScript
├── src/routes/         Pages (single-page app)
├── src/lib/stores/     Svelte stores (player, editor, filter, jobs)
├── src/lib/api/        Typed API client + types
├── src/lib/components/ UI components
└── src/lib/utils/      Diff, formatting

tests/                  377 Python tests
```

## Key Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Single code path | CLI → API → DB | No duplication between CLI and web |
| Pydantic from_orm() | Response models serialize ORM objects | No manual dict layer to maintain |
| GPU queue | Single-threaded, in-process | One GPU (3090), ACE-Step + scoring share VRAM |
| Scoring isolation | One crash doesn't block others | try/except per scorer in pipeline |
| Session auth (planned) | Cookies, not JWT | Revocable, HttpOnly, simpler for monolith |
| SQLite + WAL | Good enough for single-server | No Redis/Postgres overhead |
| Alembic | Schema migrations tracked | Safe schema evolution |

## Generation Flow

```
POST /api/songs/{id}/generate
  → create Job record
  → submit to GpuQueue
  → GpuQueue._prepare_mode("generate")
    → clear scoring models from VRAM
    → start ACE-Step server if needed
  → run_generation_job()
    → _build_generation_context() (DB lookup + config)
    → generate_single() (ACE-Step → decode → master → MP3)
    → create Generation record in DB
  → Job status: completed
```

## Scoring Flow

```
POST /api/generations/{id}/score
  → create Job record
  → submit to GpuQueue
  → GpuQueue._prepare_mode("score")
    → stop ACE-Step server
    → free VRAM
  → run_scoring_job()
    → run_scoring_pipeline() (all scorers, fault-isolated)
    → save scores + whisper text to DB
  → Job status: completed
```

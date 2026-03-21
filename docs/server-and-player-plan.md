# Songmaker Server & Player — Implementation Plan

## Goal

Turn the static HTML player into a live web UI backed by a tiny FastAPI
server. Enable rating persistence, auto-refresh, batch scoring, and
generation triggers from the browser.

## Architecture

```
songmaker (CLI tool, unchanged)
    ↓ subprocess / direct import
songmaker-server (FastAPI, ~200 lines)
    ↓ serves
player.html (enhanced, talks to server)
    ↓ loads
manifest.json + MP3s from _output/
```

No database — snapshots `.md` are the persistence layer.
No auth — single-user local tool.
No frontend framework — vanilla JS in the existing player.

## Phases

### Phase 1 — songmaker-server

**Create:** `src/songmaker_cli/server.py`

Endpoints:
- `GET /manifest.json` — serve manifest
- `GET /audio/{album}/{file}` — serve MP3 files from _output/
- `POST /rate/{album}/{version}` — save 1-5 star rating to snapshot .md
- `POST /score/{album}/{version}` — trigger scoring for one MP3
- `POST /score-all` — trigger batch scoring of all MP3s
- `POST /generate` — trigger generation in background (params in body)
- `GET /status` — generation/scoring progress
- `WebSocket /ws` — live progress updates (generation logs, scoring results)

CLI: `songmaker server [--port 8080] [--open]`

**Dependencies:** `fastapi`, `uvicorn` (add to optional deps)

**Commit:** `feat: songmaker-server — FastAPI backend for player`

---

### Phase 2 — Player upgrade

**Modify:** `templates/player.html`

- Fetch manifest from server (`http://localhost:8080/manifest.json`)
- Auto-refresh: poll manifest every 5s, re-render on change
- Rating widget: POST to `/rate/{album}/{version}` on star click
- Load ratings from manifest (read from snapshot scores)
- Score display: show all scorer results per track
- Text diff view: side-by-side intended vs transcribed lyrics
- Generation trigger: "Generate" button that POSTs to `/generate`

**Commit:** `feat: player — auto-refresh, ratings, text diff, generate button`

---

### Phase 3 — Batch scoring CLI

**Modify:** `src/songmaker_cli/main.py`

Add `--all` flag to `score` command:
```bash
songmaker score --all [--scorers silence,dynamics] [--whisper-model medium]
```

Scans `_output/` for all MP3s, finds matching lyrics, scores each,
writes to snapshot. Skips already-scored versions (unless `--force`).

**Commit:** `feat: songmaker score --all — batch scoring`

---

### Phase 4 — Archive command

**Create logic in:** `src/songmaker_cli/generate.py` or new `archive.py`

```bash
songmaker archive <mp3>           # move to _archive/
songmaker archive --below 30      # archive all with dynamics < 30
```

Moves MP3 + snapshot .md to `_archive/{album}/`. Preserves data for
future preference model training. Rebuilds manifest after archive.

**Commit:** `feat: songmaker archive — move bad versions, don't delete`

---

### Phase 5 — Spectral artifact detection

**Create:** `src/songmaker_cli/scoring/spectral_quality.py`

- Sliding window spectral flatness analysis
- Flag windows with abnormally high flatness (noise) vs song median
- Detects: white noise tails, mid-song glitches, distortion
- Registered as scorer `spectral_quality` in pipeline

**Commit:** `feat(scoring): spectral quality scorer — artifact detection`

---

### Phase 6 — GPU scoring option

**Modify:** `PipelineConfig`, `text_accuracy.py`, `audiobox_aesthetics.py`

Add `--device` flag to score command:
```bash
songmaker score --all --device cuda   # use GPU when ACE-Step server is off
```

AudioBox and Whisper load on specified device. Default remains CPU
for compatibility when ACE-Step server is running.

**Commit:** `feat: --device flag for GPU-accelerated scoring`

---

### Phase 7 — Preference model (future)

**Prerequisites:** 100+ rated songs via player

1. CLAP embedding extraction per MP3, cached as .npy
2. `songmaker train-preference` — MLP on embeddings + scores → rating
3. `PreferenceScorer` predicts user rating for new generations
4. Recalibrate scoring thresholds from rated data

**Hardware:** RTX 3090, training takes seconds
**Data:** Rate everything, keep all files (use archive, don't delete)

---

## Review process

After each phase:
1. Self-review for code smells, missing tests, dead code
2. Run full test suite
3. Commit with descriptive message
4. Brief review before moving to next phase

## Key decisions

- **No database** — snapshot .md files are the persistence layer
- **No frontend framework** — vanilla JS, keep it simple
- **No auth** — single-user local tool
- **Server is optional** — CLI works without it, server enhances the workflow
- **Albums are directories** — no separate repos needed, `--root` flag suffices

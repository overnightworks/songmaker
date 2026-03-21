# Scoring Pipeline — Implementation Plan

## Goal

Automated quality scoring for generated songs. Generate 20 versions, auto-rank them, listen to the top 3 instead of all 20.

## Architecture

Chainable scorers — each is an independent function that takes an MP3 + metadata and returns a typed score. A pipeline runner calls all enabled scorers and aggregates results into `SongScores`.

```
src/songmaker_cli/scoring/
    __init__.py              # Public API: run_scoring_pipeline, SongScores
    models.py                # Score dataclasses
    pipeline.py              # Registry + runner
    emotional_dynamics.py    # Novel — pitch/RMS/onset variance per section
    text_accuracy.py         # Refactored from check.py
    audiobox_aesthetics.py   # Meta AudioBox wrapper
    bpm_accuracy.py          # librosa beat detection vs requested BPM
    silence_detection.py     # Gap detection
```

## CLI

```bash
songmaker score <mp3> [--source <lyrics.md>] [--scorers all|text,bpm,silence,dynamics,audiobox]
songmaker generate <path> --score   # runs scoring after generation
```

## Phases

### Phase 1a — Foundation (dataclasses + pipeline runner)

**Create:**
- `scoring/models.py` — all score dataclasses (TextAccuracyScore, EmotionalDynamicsScore, AudioBoxScore, BpmAccuracyScore, SilenceScore, SongScores)
- `scoring/pipeline.py` — scorer registry, runner (catches per-scorer exceptions, aggregates results)
- `scoring/__init__.py` — re-exports
- `main.py` — add `score` CLI command (skeleton)
- `tests/test_scoring_pipeline.py` — test runner with mock scorers

**Review:** verify dataclass design, pipeline error handling, CLI wiring
**Commit:** `feat(scoring): pipeline foundation — models, runner, CLI skeleton`

---

### Phase 1b — Silence + BPM + Emotional Dynamics scorers

**Create:**
- `scoring/silence_detection.py` — RMS thresholding, gap detection, ignore intro/outro
- `scoring/bpm_accuracy.py` — librosa beat_track, octave error handling
- `scoring/emotional_dynamics.py` — per-section pitch variance (pyin), RMS contrast, onset rate changes
- `tests/test_silence_detection.py`
- `tests/test_bpm_accuracy.py`
- `tests/test_emotional_dynamics.py`

**Dependencies:** librosa, numpy (already installed)

**Review:** validate scoring logic against real MP3s from _output/, tune thresholds
**Commit:** `feat(scoring): silence, BPM, and emotional dynamics scorers`

---

### Phase 1c — Refactor check.py → text accuracy scorer

**Modify:**
- `check.py` — extract core SequenceMatcher logic into `scoring/text_accuracy.py`, keep check.py as thin CLI wrapper
- `scoring/text_accuracy.py` — Whisper transcribe + compare, returns TextAccuracyScore

**Create:**
- `tests/test_text_accuracy_scorer.py`

**Review:** verify backward compatibility of `songmaker check` command
**Commit:** `refactor(scoring): extract text accuracy scorer from check.py`

---

### Phase 1d — AudioBox Aesthetics integration

**Create:**
- `scoring/audiobox_aesthetics.py` — lazy import, model cached, wraps predict()

**Modify:**
- `pyproject.toml` — add `scoring` optional deps group

**Create:**
- `tests/test_audiobox_scorer.py` (mocked)

**Review:** verify Python 3.12 compatibility, check VRAM usage alongside ACE-Step
**Commit:** `feat(scoring): AudioBox Aesthetics integration`

---

### Phase 1e — Snapshot + player integration

**Modify:**
- `snapshot.py` — add `append_scores_section(path, scores)`
- `manifest.py` — read `## Scores` from snapshots, add to TrackInfo
- `main.py` — wire `--score` flag on generate command
- `templates/player.html` — display scores in generation info panel

**Review:** verify end-to-end: generate → score → snapshot → player shows scores
**Commit:** `feat(scoring): snapshot persistence + player display`

---

### Phase 2 — Preference Model (future side project)

**Prerequisites:** 100+ user-rated songs via player

1. Add 1-5 star rating persistence in player → snapshot .md files
2. **Important: don't delete bad songs — rate them low instead.** Bad examples
   are as valuable as good ones. Binary kept/deleted loses nuance.
   ~40 currently kept songs are NOT all good — they need proper 1-5 ratings.
3. Extract CLAP embeddings per MP3, cache as .npy
4. `songmaker train-preference` — trains MLP on CLAP embeddings + scoring
   features → user rating (1-5 regression, not binary classification)
5. `PreferenceScorer` predicts user rating for new generations
6. Recalibrate scoring thresholds based on rated data

**Hardware:** RTX 3090 (24GB) — overkill for this, training takes seconds
**Approach:** Linear probe on frozen CLAP embeddings (laion/larger_clap_music, 512-dim)
**Data note:** ~100 songs were deleted before this system existed. Lost data.
Going forward, rate everything and keep all files.

---

## Scorer Details

### Emotional Dynamics (novel)

Divides audio into N equal segments (default 6). Per segment:
- Pitch via `librosa.pyin()` → coefficient of variation across segments
- RMS energy → contrast ratio (max/min section RMS)
- Onset density → coefficient of variation

Score = weighted: pitch_cv (0.4) + rms_contrast (0.3) + onset_cv (0.3)
High variance = expressive = good. Monotone = low score.

### BPM Accuracy

- `librosa.beat.beat_track()` → detected BPM
- Compare to requested BPM, check half/double for octave errors
- Score = `max(0, 100 - deviation_percent * 5)`

### Silence Detection

- Frame-level RMS with ~50ms window
- Frames below -40dB relative to max = silent
- Group consecutive silent frames into gaps
- Ignore first/last 2 seconds
- Penalize gaps > 2 seconds

### AudioBox Aesthetics

- Content Enjoyment (1-10)
- Content Understanding (1-10)
- Production Complexity (1-10)
- Production Quality (1-10)
- Summary = mean scaled to 0-100

### Text Accuracy

- Whisper large-v3 transcription
- SequenceMatcher ratio vs intended lyrics
- Already exists, just needs structured return type

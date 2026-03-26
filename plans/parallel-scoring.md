# Parallel Scoring Pipeline

## Problem

Scorers run sequentially in a `for` loop ([pipeline.py:210](src/songmaker_cli/scoring/pipeline.py#L210)). Each gets its own `ThreadPoolExecutor(max_workers=1)` just for timeout enforcement. With 7 scorers, wall-clock time is the sum of all scorer durations instead of the max.

## Approach

Run all scorers concurrently in a shared `ThreadPoolExecutor`, with GPU scorers serialized to avoid VRAM contention.

### Scorer Classification

| Scorer | Type | Typical Duration | Notes |
|--------|------|-----------------|-------|
| silence_detection | CPU | <1s | NumPy only |
| bpm_accuracy | CPU | 2-5s | librosa beat tracking |
| spectral_quality | CPU | 1-3s | scipy FFT |
| emotional_dynamics | CPU | 2-4s | librosa + numpy |
| lyrical_coherence | CPU | <1s | text-only, no audio |
| text_accuracy | GPU | 15-60s | Whisper inference |
| audiobox_aesthetics | GPU | 5-15s | AudioBox model |

### Design

1. Split scorers into `cpu_scorers` and `gpu_scorers` based on existing `needs_audio` flag — but that's not the right split (BPM needs audio but is CPU). Add a `device` flag to registration instead:

```python
@register("silence", device="cpu")
def score_silence(...): ...

@register("text_accuracy", device="gpu")
def score_text_accuracy(...): ...
```

2. Run CPU scorers concurrently in `ThreadPoolExecutor(max_workers=len(cpu_scorers))`.
3. Run GPU scorers sequentially (they already hold module-level locks for model access).
4. Both groups can overlap — CPU scorers don't compete with GPU scorers for resources.

### Implementation

**Files to change:**
- `scoring/pipeline.py` — `ScorerRegistry.register()` gains `device` param, `run_scoring_pipeline()` uses concurrent execution
- `scoring/*.py` — add `device="cpu"` or `device="gpu"` to each `@register` call (6 files, 1-line each)

**Concrete change to `run_scoring_pipeline()`:**

```python
def run_scoring_pipeline(...) -> SongScores:
    # ... existing setup ...

    cpu_names = [n for n in scorers if not reg.scorer_uses_gpu(n)]
    gpu_names = [n for n in scorers if reg.scorer_uses_gpu(n)]

    results: dict[str, object] = {}
    shared_data: dict = {}

    with ThreadPoolExecutor(max_workers=max(len(cpu_names), 1)) as pool:
        futures = {
            pool.submit(_run_scorer, name, ...): name
            for name in cpu_names
        }
        # GPU scorers run sequentially in the main thread
        for name in gpu_names:
            _run_scorer_into(results, name, ...)

        for future in as_completed(futures, timeout=config.scorer_timeout):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception:
                log.exception("Scorer '%s' failed", name)

    return _build_song_scores(results)
```

### Expected Improvement

- Current: ~30-80s serial (sum of all scorers)
- After: ~20-65s (bounded by slowest GPU scorer + overhead)
- CPU scorers complete in parallel during GPU inference

### Risks

- `shared_data` dict is currently passed mutably between scorers. Need to verify no scorer writes to it that another reads. If so, split into per-scorer dicts or use a lock.
- Thread count: 5 CPU threads + 1 main thread for GPU is fine for typical hardware.

### Test Changes

- Existing tests pass a custom `ScorerRegistry` — no change needed for unit tests.
- Add one test verifying concurrent execution (mock scorers with `time.sleep`, assert total time < sum).

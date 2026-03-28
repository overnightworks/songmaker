# Fix VRAM Mode-Switching Verification

> **Status: NOT STARTED**

## Context

The architecture review found that `verify_vram_freed()` in `acestep_manager.py` uses `torch.cuda.memory_allocated()` — which only measures PyTorch-managed memory in the current process. This misses:
- **CTranslate2 memory** (Whisper uses CTranslate2, which has its own CUDA allocator outside PyTorch)
- **ACE-Step subprocess memory** (separate CUDA context, ~18GB)

Today this works because `max_jobs=1` serializes everything and the dict-clear usually works. But if Whisper cleanup fails silently (dangling reference), `verify_vram_freed()` reports success (PyTorch sees 0), while CTranslate2 still holds ~3GB, and ACE-Step OOMs.

The `/metrics` endpoint has the same blind spot — reports PyTorch memory only.

## Approach: Delta-Based NVML Verification

A flat system-wide threshold doesn't work because ACE-Step holds ~18GB at baseline. Instead, use a **delta check**:

1. Snapshot system-wide VRAM **before** clearing scoring models
2. Clear models with explicit cleanup (not just dict.clear())
3. Poll system-wide VRAM until it drops by at least the expected amount
4. Fail the job if VRAM doesn't drop (instead of current silent warning)

### Why delta, not absolute threshold?

| State | System-wide VRAM | PyTorch (worker) |
|-------|-----------------|------------------|
| Idle (ACE-Step loaded) | ~18GB | 0 |
| After scoring (Whisper loaded) | ~21GB | ~0 (CTranslate2 is outside PyTorch!) |
| After clearing models | ~18GB | 0 |

PyTorch always reads ~0 in the worker because Whisper uses CTranslate2, not PyTorch tensors. The only reliable signal is the system-wide delta.

## File Changes

### 1. Add `nvidia-ml-py3` dependency

**File: `pyproject.toml`** — add to `scoring` extras (it's already on any NVIDIA GPU system):

```
"nvidia-ml-py3>=7.352",
```

### 2. New utility: `src/songmaker_cli/gpu_util.py` (~25 lines)

```python
def get_gpu_memory_used_mb(device_index: int = 0) -> float | None:
    """System-wide GPU memory via NVML. Returns None if unavailable."""
```

- Init/shutdown NVML per call (fast, no leaked state)
- Graceful `None` on ImportError or NVMLError

### 3. Fix `verify_vram_freed()` in `src/songmaker_cli/acestep_manager.py`

**Current** (line 194): polls `torch.cuda.memory_allocated()`, warns if not freed, continues anyway.

**New**: Takes a `baseline_mb` parameter (measured before clearing):
- Polls `get_gpu_memory_used_mb()` until system-wide VRAM drops to within `baseline_mb + margin`
- Margin: `_VRAM_MARGIN_MB = 200` (configurable via `SONGMAKER_VRAM_MARGIN_MB`)
- **Raises RuntimeError** if not freed in time — propagates to job failure handler
- Falls back to old behavior (proceed with warning) if pynvml unavailable

**Update `prepare_generate_mode()`** (line 148):
```python
def prepare_generate_mode(self) -> None:
    if self._current_mode != "generate":
        baseline = get_gpu_memory_used_mb()  # snapshot before clearing
        clear_scoring_models()
        verify_vram_freed(baseline_mb=baseline)
    self.ensure()
    self.refresh_cached_model()
    self._current_mode = "generate"
```

When `_current_mode` is already `"generate"`, no scoring models are loaded, so skip entirely.

### 4. Explicit model cleanup in scoring cache clears

**`src/songmaker_cli/scoring/text_accuracy.py`** — `clear_cache()`:
- Iterate + `del model` before `dict.clear()` (ensures CTranslate2 `__del__` fires)
- Add `gc.collect()` after clearing (force CTranslate2 finalizers)

**`src/songmaker_cli/scoring/audiobox_aesthetics.py`** — `clear_cache()`:
- Same pattern (though AudioBox runs on CPU via `CUDA_VISIBLE_DEVICES=""`, so this is defensive)

### 5. Fix `/metrics` GPU reporting in `src/songmaker_cli/health_api.py`

Replace `_get_gpu_vram_mb()` (line 16): delegate to `gpu_util.get_gpu_memory_used_mb()`. Drop-in replacement, returns `None` on failure (already handled).

### 6. Tests

**`tests/test_gpu_util.py`** (new, ~40 lines):
- `test_no_pynvml` — ImportError → returns None
- `test_nvml_error` — NVMLError → returns None
- `test_success` — mock returning memory info → correct MB value
- `test_shutdown_always_called` — verify cleanup even on error

**`tests/test_acestep_manager.py`** (update existing):
- `test_verify_vram_freed_delta` — baseline 18000, after clearing 18100 → success
- `test_verify_vram_freed_not_freed` — baseline 18000, stays 21000 → **RuntimeError**
- `test_verify_vram_freed_no_pynvml` — returns None → proceed with warning
- `test_verify_vram_freed_gradual` — drops over 3 polls → success on 3rd
- `test_prepare_generate_mode_vram_failure` — verify RuntimeError propagates

## Risk

- **Low**: pynvml is a thin NVML wrapper, always present with NVIDIA drivers
- **Behavior change**: Failed VRAM verification now fails the job instead of silently proceeding to OOM. This is strictly better.
- **Threshold tuning**: 200MB margin should cover measurement jitter. Configurable via env var if needed.
- **Fallback**: If pynvml is missing, old behavior (proceed with warning) is preserved

## Verification

1. `ruff check src/ tests/`
2. `pytest tests/test_gpu_util.py tests/test_acestep_manager.py tests/test_server.py -q`
3. Full suite: `pytest tests/ -q --cov=songmaker_cli --cov=audio_engine --cov=acestep_engine --cov-report=term-missing`

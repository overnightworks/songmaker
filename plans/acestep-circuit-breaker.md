# ACE-Step Circuit Breaker / Timeout Protection

## Problem

Two timeout vulnerabilities:

1. **`_download_audio` can hang**: `resp.read()` after connection has no wall-clock deadline — data trickling in slowly bypasses the socket timeout.
2. **Worker thread blocks indefinitely**: If `job.fn()` hangs, the GPU queue is dead. The stale job cleanup marks the DB record as failed, but the worker thread stays blocked.

## Design Decisions

- **Socket timeouts already exist** on poll (10s), submit (30s), download (60s), health (5s). The gap is `resp.read()` post-connection.
- **Job-level timeout by type**: generation 300s (5 min), scoring 120s (2 min). Typical generation takes under a minute; these are generous safety margins. Configurable via env vars.
- **Cancellation**: No cancel API on ACE-Step server. On timeout, restart the subprocess via `_stop_acestep()`.
- **Restart blocks the queue**: `_handle_stuck_job` must complete (stop + cleanup) before the worker dequeues the next job. The next generation job's `_ensure_acestep()` handles the restart (~120s). During this window the queue is blocked — acceptable, since we just recovered from a hang.
- **Stale recovery** remains as safety net for edge cases.

## Implementation

### Phase 1: Chunked download with wall-clock deadline

**File: `src/acestep_engine/client.py`**

Replace `resp.read()` in `_download_audio` with chunked read that checks `time.monotonic()`:

```python
DOWNLOAD_DEADLINE_SECONDS: Final[float] = 60.0

def _download_audio(self, task_id, ...):
    # ... existing urlopen with timeout=60 ...
    start = time.monotonic()
    chunks = []
    while True:
        if time.monotonic() - start > DOWNLOAD_DEADLINE_SECONDS:
            raise AudioDownloadError("Audio download exceeded time limit")
        chunk = resp.read(65536)
        if not chunk:
            break
        chunks.append(chunk)
    wav_bytes = b"".join(chunks)
```

### Phase 2: Job-level watchdog in GpuQueue

**File: `src/songmaker_cli/gpu_queue.py`**

Add per-type timeout constants:

```python
GENERATE_TIMEOUT_SECONDS: Final[int] = int(os.environ.get("GENERATE_TIMEOUT_SECONDS", "300"))
SCORE_TIMEOUT_SECONDS: Final[int] = int(os.environ.get("SCORE_TIMEOUT_SECONDS", "120"))
```

Run `job.fn()` in a sub-thread with join timeout:

```python
def _execute(self, job):
    # ... existing mode preparation ...
    timeout = GENERATE_TIMEOUT_SECONDS if job.job_type == "generate" else SCORE_TIMEOUT_SECONDS
    worker = threading.Thread(target=self._run_job, args=(job,), daemon=True)
    worker.start()
    worker.join(timeout=timeout)
    if worker.is_alive():
        self._fail_job(job.job_id, f"Job timed out after {timeout}s")
        self._handle_stuck_job(job)  # blocks until cleanup completes

def _handle_stuck_job(self, job):
    if job.job_type == "generate":
        self._stop_acestep()       # synchronous: SIGTERM → wait → kill → wait
        self._current_mode = None  # force re-preparation on next job
    # scoring: daemon thread leaks but holds no subprocess — tolerable
```

Key ordering guarantee: `_handle_stuck_job` runs synchronously on the worker thread. The worker does not dequeue the next job until `_stop_acestep()` returns. The next generation job's `_ensure_acestep()` cold-starts the subprocess.

### Phase 3: Tests

- `test_execute_times_out_stuck_generation` — mock fn to sleep(forever), verify fail + `_stop_acestep` called
- `test_execute_times_out_stuck_scoring` — mock fn to sleep(forever), verify fail + `_stop_acestep` NOT called
- `test_execute_normal_job_within_timeout` — verify normal flow unaffected
- `test_download_audio_deadline_exceeded` — mock slow chunked read, verify `AudioDownloadError`

## Risks

- **Daemon thread leak**: Abandoned generation thread holds resources until ACE-Step subprocess is killed (socket errors propagate, thread exits). Abandoned scoring thread leaks until model call returns or process exits — tolerable since scoring models are small.
- **Double failure marking**: Both watchdog and job may call `_fail_job`. Idempotent — harmless.
- **Thread safety of `_stop_acestep`**: Abandoned thread gets `ConnectionRefusedError` on next call — safe.
- **Queue blocked during restart**: Up to `ACESTEP_STARTUP_TIMEOUT` (120s) for the next generation job to cold-start the subprocess. Acceptable — recovering from a hang.

# ACE-Step Circuit Breaker / Timeout Protection

## Problem

Two timeout vulnerabilities:

1. **`_download_audio` can hang**: `resp.read()` after connection has no wall-clock deadline — data trickling in slowly bypasses the socket timeout.
2. **Worker thread blocks indefinitely**: If `job.fn()` hangs, the GPU queue is dead. The stale job cleanup marks the DB record as failed, but the worker thread stays blocked.

## Design Decisions

- **Socket timeouts already exist** on poll (10s), submit (30s), download (60s), health (5s). The gap is `resp.read()` post-connection.
- **Job-level timeout**: 1200s (20 min), shorter than `POLL_TIMEOUT` (1800s). Configurable via `JOB_TIMEOUT_SECONDS` env var.
- **Cancellation**: No cancel API on ACE-Step server. On timeout, restart the subprocess via `_stop_acestep()`.
- **Stale recovery** remains as safety net for edge cases.

## Implementation

### Phase 1: Chunked download with wall-clock deadline

**File: `src/acestep_engine/client.py`**

Replace `resp.read()` in `_download_audio` with chunked read that checks `time.monotonic()`:

```python
DOWNLOAD_DEADLINE_SECONDS: Final[float] = 120.0

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

Run `job.fn()` in a sub-thread with join timeout:

```python
JOB_TIMEOUT_SECONDS = int(os.environ.get("JOB_TIMEOUT_SECONDS", 1200))

def _execute(self, job):
    # ... existing mode preparation ...
    worker = threading.Thread(target=self._run_job, args=(job,), daemon=True)
    worker.start()
    worker.join(timeout=JOB_TIMEOUT_SECONDS)
    if worker.is_alive():
        self._fail_job(job.job_id, f"Job timed out after {JOB_TIMEOUT_SECONDS}s")
        self._handle_stuck_job(job)

def _handle_stuck_job(self, job):
    if job.job_type == "generate":
        self._stop_acestep()
        self._current_mode = None  # force re-preparation
```

### Phase 3: Tests

- `test_execute_times_out_stuck_job` — mock fn to sleep, verify fail + restart
- `test_execute_timeout_no_restart_for_score` — verify no subprocess restart
- `test_execute_normal_job_within_timeout` — verify normal flow unaffected
- `test_download_audio_deadline_exceeded` — mock slow chunked read

## Risks

- **Daemon thread leak**: Abandoned thread holds resources until ACE-Step subprocess is killed (socket errors propagate).
- **Double failure marking**: Both watchdog and job may call `_fail_job`. Idempotent — harmless.
- **Thread safety of `_stop_acestep`**: Abandoned thread gets `ConnectionRefusedError` on next call — safe.

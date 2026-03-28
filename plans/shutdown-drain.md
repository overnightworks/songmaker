# Graceful Shutdown Drain for arq Worker

> **Status: NOT STARTED**

## Problem

When the arq worker receives SIGTERM (e.g., during deploy), it cancels running jobs immediately. The job stays in `running` status in the DB until the stale cron picks it up — which currently runs every 15 minutes with an 1800s threshold. This means a user can stare at a "running" spinner for up to 30 minutes after a restart.

## Solution

Two complementary changes:

1. **Worker-side drain**: Use arq's built-in `job_completion_wait` to let running jobs finish before exit, and mark any that don't finish as failed with a `shutdown` error type.
2. **Reduce stale timeout**: Shrink the cron interval and threshold so ungraceful crashes (OOM, power loss) are detected faster.
3. **Frontend (optional)**: Show a friendlier message for `shutdown` error type.

---

## Part 1: Worker-Side Drain

arq already supports graceful shutdown via `job_completion_wait` (integer, seconds). When set:
- On SIGTERM/SIGINT, arq calls `handle_sig_wait_for_completion` instead of `handle_sig`
- Sets `allow_pick_jobs = False` (stops accepting new jobs)
- Waits up to `job_completion_wait` seconds for running tasks to complete
- After timeout, cancels remaining tasks and shuts down
- `on_shutdown` callback is called after all tasks are done/cancelled

### File: `src/songmaker_cli/worker.py`

**Add constant** (line ~27):

```python
DRAIN_TIMEOUT_SECONDS = int(os.environ.get("ARQ_DRAIN_TIMEOUT", "300"))
```

Move to `constants.py` if preferred, but this is arq-worker-specific so `worker.py` is fine.

**Add `job_completion_wait` to `WorkerSettings`** (line ~140):

```python
class WorkerSettings:
    functions = [generate, score]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    )
    max_jobs = 1
    job_timeout = JOB_TIMEOUT_SECONDS
    job_completion_wait = DRAIN_TIMEOUT_SECONDS       # <-- NEW
    health_check_interval = HEALTH_CHECK_INTERVAL_SECONDS
    cron_jobs = [
        cron(cleanup_stale, hour=None, minute=None, second={0}, run_at_startup=True),
    ]
```

This is the entire change needed for the drain itself. arq handles the signal routing, the "stop picking jobs" flag, and the timeout + cancel automatically.

**Update `on_shutdown`** to mark any still-running jobs as failed (line ~135):

When `on_shutdown` fires after a drain timeout, arq has already cancelled the tasks. But `CancelledError` in the job functions may not reach the `_update_job` call. So `on_shutdown` should sweep for orphaned running jobs — exactly what `recover_stale_jobs` already does.

```python
async def on_shutdown(ctx):
    db_factory = _get_db_factory()
    with db_factory() as session:
        recovered = recover_stale_jobs(session)
        if recovered:
            log.warning("Shutdown: marked %d in-progress jobs as failed", recovered)
        session.commit()

    if _acestep_manager:
        _acestep_manager.stop()
```

The existing `recover_stale_jobs` already sets `error_type="server_restart"` and a user-friendly error message, which is exactly right for this case.

### File: `src/songmaker_cli/db/queries/jobs.py`

No changes needed. `recover_stale_jobs` (line 79) already marks all running/queued jobs as failed with `error_type="server_restart"`. This covers both:
- Jobs that were cancelled by the drain timeout
- Jobs that were queued but never picked up

---

## Part 2: Reduce Stale Timeout

For ungraceful crashes where `on_shutdown` never runs (OOM kill, hardware failure), the cron-based recovery is the safety net.

### File: `src/songmaker_cli/worker.py`

**Change cron schedule** from 15-minute intervals to every 2 minutes (line ~150-152):

```python
cron_jobs = [
    cron(cleanup_stale, minute=None, second={0}),
]
```

`minute=None` means "every minute". Combined with `second={0}`, this runs at the top of every minute. But since we only want every 2 minutes, use:

```python
cron_jobs = [
    cron(cleanup_stale, minute={i for i in range(0, 60, 2)}, second={0}),
]
```

### File: `src/songmaker_cli/db/queries/jobs.py`

**Reduce default threshold** from 1800s to 600s (line 98-100):

```python
STALE_JOB_THRESHOLD_SECONDS = int(
    os.environ.get("STALE_JOB_THRESHOLD_SECONDS", 600),
)
```

600s (10 minutes) is well above the normal job timeout of 300s, so it won't false-positive on legitimate long-running jobs. The env var override remains for safety.

---

## Part 3: Frontend (Optional)

The frontend already shows `updated.error` for failed jobs in `frontend/src/lib/stores/jobs.ts` (line 52). The error message from `recover_stale_jobs` is already user-friendly: `"Server restarted while job was in progress"`.

If we want to distinguish the toast style:

### File: `frontend/src/lib/stores/jobs.ts`

**Change the failure toast** (line ~44-52) to detect shutdown errors:

```typescript
} else {
    const isRestart = updated.error_type === 'server_restart';
    addToast(
        isRestart
            ? 'Server restarted — please retry'
            : (updated.error || `${updated.type} failed`),
        isRestart ? 'info' : 'error'
    );
}
```

This shows an `info` toast instead of `error` for restarts, since the user didn't do anything wrong.

---

## Tests

### File: `tests/test_worker.py`

- Test that `WorkerSettings.job_completion_wait` equals `DRAIN_TIMEOUT_SECONDS`
- Test that `on_shutdown` calls `recover_stale_jobs` and commits
- Update existing `test_on_startup_recovers_stale_jobs` if the mock setup changes

### File: `tests/test_db.py`

- Existing tests for `recover_stale_jobs` and `recover_stale_jobs_by_age` already cover the query logic
- Add a test for `recover_stale_jobs_by_age` with the new 600s default (or just verify the constant)

---

## Summary of Changes

| File | Change |
|---|---|
| `src/songmaker_cli/worker.py` | Add `DRAIN_TIMEOUT_SECONDS`, set `job_completion_wait` on `WorkerSettings`, update `on_shutdown` to recover stale jobs, update cron to 2-minute intervals |
| `src/songmaker_cli/db/queries/jobs.py` | Change `STALE_JOB_THRESHOLD_SECONDS` default from 1800 to 600 |
| `frontend/src/lib/stores/jobs.ts` | (Optional) Show `info` toast for `server_restart` error type |
| `tests/test_worker.py` | Test drain config and shutdown recovery |

## Risk

- **Low**: `job_completion_wait` is a well-documented arq feature. With `max_jobs=1`, there is at most one task to wait for.
- **Cron frequency**: Running every 2 minutes instead of 15 is negligible overhead (single DB query).
- **600s threshold**: Still 2x the default job timeout. No false positives unless someone sets `ARQ_JOB_TIMEOUT` above 600 — document in `.server.env.example` if one exists.

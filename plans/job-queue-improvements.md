# Job Queue Improvements

> **Status: PROBLEM 2 DONE** — Stale jobs auto-cleared on submission + cron catches queued jobs. Problems 1 and 3 remain.

## Problem 1: Scoring blocks generation

When a score job is running, the user gets "already has an active job" error when trying to generate. Scoring (CPU/Whisper) and generating (GPU/ACE-Step) use completely different resources and should run in parallel.

### Root Cause

`create_job_with_rate_limit()` in `api_helpers.py` checks for ANY active job regardless of type:

```python
active = count_active_jobs(session, user.id)  # counts ALL types
if active >= 1:
    raise HTTPException(409, "Already has an active job")
```

### Fix

Change the active job check to be **per job type** — a running `score` job should not block a `generate` job and vice versa.

- `count_active_jobs()` should accept a `job_type` filter
- Or split into `count_active_generation_jobs()` and `count_active_score_jobs()`
- Chat jobs should also be independent

## Problem 2: Stale jobs block new submissions

If a job crashes or the worker restarts, jobs can get stuck in `running` or `queued` status forever. The user then can't submit new jobs.

### Root Cause

The `cleanup_stale` cron exists but may not catch all edge cases (e.g., the permission error crash left a stale `chat` job in `queued` status).

### Fix

- Review `cleanup_stale` logic — ensure it catches jobs stuck in `running` for longer than a reasonable timeout (e.g., 30min for generate, 15min for score)
- On job submission, if there's a stale job older than the timeout, auto-clear it instead of rejecting the new submission
- Consider adding a "Cancel" button in the UI for stuck jobs

## Problem 3: Job queue visibility

Users don't see queued jobs or understand why their request was rejected.

### Fix

- When a job is rejected due to rate limit or active job, return a clear message with what's running and estimated time
- Show all active/queued jobs in the UI (not just current song's jobs)
- Consider actually queuing jobs instead of rejecting — let the worker process them in order

## Files to Touch

| File | Change |
|------|--------|
| `api_helpers.py` | Per-type active job check |
| `db/queries/jobs.py` | Add `job_type` filter to `count_active_jobs()` |
| `worker.py` | Review cleanup_stale timeout logic |
| Frontend: `+page.svelte` | Show global job status, not just per-song |

## Priority

Problem 1 (scoring blocks generation) → Problem 2 (stale jobs) → Problem 3 (visibility)

## Constraints

- The `create_job_with_rate_limit` function commits the transaction before acquiring the lock — see known tech debt in CLAUDE.md. Be careful with transaction ordering.
- Rate limits per type are already separate (`GENERATION_RATE_LIMIT_USER`, `SCORING_RATE_LIMIT_USER`, etc.) — the issue is only the active job count check.
- Don't change the arq worker architecture — just fix the API-side gating logic.

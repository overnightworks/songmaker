# Job Queue Improvements

> **Status: IN PROGRESS** — Problem 2 done. Problem 0 up next, then Problem 1.

## Problem 0: Chat jobs never finalize (BUG)

`chat_api.py` creates a job via `create_job_with_rate_limit()` and commits, but never sets the job to `completed` or `failed`. If the Claude call is slow or errors out, the job stays `queued` forever — blocking the user from submitting new jobs.

This is what blocked Julia on 2026-03-29.

### Root Cause

```python
create_job_with_rate_limit(session, user, "chat")
session.commit()
# ... call Claude ...
# job never finalized
```

### Fix

Wrap the Claude call in `try/finally`. Set job status to `completed` on success, `failed` on error. Use `update_job_status()` from `db.queries`.

### Files to Touch

| File | Change |
|------|--------|
| `chat_api.py` | Finalize chat job status after Claude call |
| `tests/test_chat_api.py` or relevant test | Verify job reaches terminal status |

---

## Problem 1: Active job check ignores job type

`count_user_active_jobs()` counts ALL active jobs regardless of type. A running score job blocks a new generate request, even though they use different resources (CPU/GPU). Chat jobs also block generate/score.

### Root Cause

`db/queries/jobs.py:count_user_active_jobs()` filters only by user and status, not by job type.

### Fix

- Add `job_type: str` parameter to `count_user_active_jobs()`
- Pass `job_type` from `create_job_with_rate_limit()` in `api_helpers.py`
- Raise `MAX_USER_ACTIVE_JOBS` default from 1 to 10 (jobs queue in arq anyway)
- Raise `MAX_QUEUE_DEPTH` default from 10 to 100

### Files to Touch

| File | Change |
|------|--------|
| `db/queries/jobs.py` | Add `job_type` param to `count_user_active_jobs()` |
| `api_helpers.py` | Pass `job_type` through to the check |
| `auth.py` | Update default constants |
| `tests/test_db.py` | Update test for new signature |
| `tests/test_rate_limit.py` | Verify cross-type jobs don't block each other |

---

## Problem 2: Stale jobs block new submissions (DONE)

Stale job recovery works via:
- `clear_stale_user_jobs()` called on every job submission (`api_helpers.py`)
- `cleanup_stale` cron runs every 2 minutes (`worker.py`)
- Configurable threshold via `STALE_JOB_THRESHOLD_SECONDS` (default 360s)

---

## Problem 3: Job cancellation

Users should be able to cancel queued jobs. The worker already skips jobs with terminal status, so cancellation is just a DB status update.

### Fix

- Add `"cancelled"` to `TERMINAL_STATUSES` in `worker.py`
- Add `POST /api/jobs/{id}/cancel` endpoint with ownership check
- Frontend: show job queue with cancel buttons (separate PR)

### Files to Touch

| File | Change |
|------|--------|
| `worker.py` | Add `"cancelled"` to `TERMINAL_STATUSES` |
| New: `job_api.py` or in existing API | Cancel endpoint |
| `api_helpers.py` | Ownership check helper |
| Frontend (later PR) | Job queue UI with cancel |

---

## Problem 4: Job queue visibility (future)

- Show all active/queued jobs in the UI (not just per-song)
- Show queue position and estimated wait time
- This depends on Problem 3 (cancel) being done first

---

## Priority

Problem 0 (chat finalization) → Problem 1 (per-type active check) → Problem 3 (cancel) → Problem 4 (visibility)

## Constraints

- `create_job_with_rate_limit()` commits before acquiring the lock — see CLAUDE.md known tech debt
- Rate limits per type are already separate — only the active job count check is wrong
- Don't change the arq worker architecture — fix API-side gating only
- `max_jobs=1` on the worker serializes execution — the API should allow queueing

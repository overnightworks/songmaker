**Status:** Proposed
**Date:** 2026-04-18

# Generation Retention & Cleanup

## Goal

Auto-reap exploratory generations so the audio volume and DB don't balloon with throwaways. Preserve anything the user explicitly marked (picked, kept) or that anchors reproducibility (seed-pin / src_generation).

## Locked-in decisions

- **Rule:** generation eligible for soft-delete when `is_picked = false` AND `is_kept = false` AND `age > GENERATION_RETENTION_DAYS`.
- **Two-stage delete.** Soft-delete first (`is_archived = true`, files kept). Hard-delete (files + row) after `GENERATION_HARD_DELETE_DAYS` additional days archived.
- **Defaults:** `GENERATION_RETENTION_DAYS = 7`, `GENERATION_HARD_DELETE_DAYS = 30`. Configured via `.env` (no admin-settings page — single-admin scale).
- **Never delete anchors.** Skip any generation referenced by another non-expired generation's `src_generation_id` or by a pinned seed still in use.
- **Daily scheduled job** does the actual work. Admin UI also exposes a "Run cleanup now" button with dry-run + execute modes.
- **UX — calm-most, loud-late.** No per-row badge when expiry > 3 days out. Warning badge only in final 3 days. Dashboard/song digest banner: *"N generations expire in M days — review"* with bulk "keep all" action. Detail view always shows full expiry info.
- **Archived gens hidden** from normal lists by default; a "show archived" toggle reveals them for recovery (user can un-archive → flips `is_archived = false`, resets clock).

## Hard constraints

- Files deleted by hard-delete stage must not orphan DB rows — commit in a transaction with file removal protected by idempotent logic (re-delete on retry = noop).
- The cleanup job must not block generation/playback queues. Run in the existing jobs/scheduler system, not inline with requests.
- Admin "Run cleanup now" requires admin role; not exposed to regular users.
- Dry-run output must be exact — show the IDs that *would* be deleted, not just counts.
- Un-archive must restore visibility without re-materializing files (files weren't deleted at soft-delete stage).

## First step

Read the live code: `db/models.py` (Generation.is_archived semantics), `db/queries/` (existing delete paths), `api_helpers.py` (admin-role check), the scheduler (how daily jobs are registered), `SongDetailView.svelte` + generation list components (where badges/banner render). Then design + execute.

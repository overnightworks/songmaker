# Admin User Management — Reset Password, Hard Delete

## Context

Admin panel at Settings > Users already supports: create user, toggle role, disable/enable.
Missing: reset password button, hard delete (account + all data).

Backend API already supports password reset via `PUT /api/admin/users/{id}` with `{password: "..."}`.
Hard delete is new — current `DELETE /api/admin/users/{id}` only soft-deletes (deactivates).

## Three-Tier User Actions (escalating severity)

| Action | Reversible | Effect |
|---|---|---|
| Disable | Yes | Lock out, keep all data |
| Reset Password | Partially | New password, sessions invalidated |
| Delete Account | No | Hard delete user + all their songs, albums, generations, sessions |

## Admin Account Protection

- Any admin can be hard-deleted, **except the last active admin** (existing `ensure_not_last_admin` guard)
- Self-deletion blocked — cannot delete your own account
- No demote-first requirement — a compromised admin can trivially script demote+delete anyway, so it's just UX friction without real security benefit
- The real protection remains: `ensure_not_last_admin` guarantees at least one admin always exists for recovery

## Audit Log Preservation

- `AuditLog.user_id` FK already has `ondelete="SET NULL"` — deleting a user automatically NULLs the reference
- Record a final audit entry BEFORE deletion with `detail="username=<name>, albums=N, songs=N, generations=N"` so the deletion is traceable even after `user_id` becomes NULL
- No schema change needed — existing `detail` field captures the context

## Plan

### Phase 1: Backend — Hard Delete Endpoint

**File: `src/songmaker_cli/db/queries/auth.py`**
- Add `hard_delete_user(session, user_id)`:
  - Collect all audio file paths from user's generations (via albums → songs → generations, same pattern as `delete_album()`)
  - Delete all user sessions (`cascade="all, delete-orphan"` on User.sessions handles this automatically)
  - Delete all albums owned by user — cascades to songs → generations (via existing SA cascade)
  - Delete the user record
  - `session.flush()`
  - Return list of relative audio file paths for cleanup

**File: `src/songmaker_cli/admin_api.py`**
- Add `DELETE /api/admin/users/{user_id}/permanent` endpoint:
  - `require_admin` dependency
  - Reject if target is self → 400
  - Reject if target is admin and last admin → 400 (reuse `ensure_not_last_admin`)
  - Record audit entry BEFORE deletion: `record_audit(admin.id, "hard_delete", "user", user_id, detail=f"username={user.username}, albums=N, songs=N, gens=N")`
  - Call `hard_delete_user()` → `session.commit()`
  - Delete audio files AFTER commit using existing `cleanup_generation_files()` pattern
  - Clear Redis session cache for deleted user
  - Return `StatusResponse(status="ok")`

**File: `src/songmaker_cli/api_models/auth.py`**
- No new models needed — uses existing `StatusResponse`

### Phase 2: Frontend — Reset Password + Delete Button

**File: `frontend/src/lib/api/client.ts`**
- Add `hardDeleteUser(userId: string): Promise<void>` → `DELETE /api/admin/users/{userId}/permanent`

**File: `frontend/src/routes/settings/users/+page.svelte`**
- Add per-user actions (for non-self users):
  - **Disable/Enable** (existing)
  - **Reset Password** — small button that reveals inline password input + save, calls `updateUser(id, {password})`
  - **Delete** — danger-styled button, shows confirmation: "This will permanently delete USERNAME and all their songs, albums, and generations. Type the username to confirm." Confirm button disabled until typed username matches.

### Phase 3: Tests

- Backend tests in `tests/test_admin_api.py`:
  - Hard delete cascades correctly: user, albums, songs, generations, sessions all gone from DB
  - Audit log entry survives with `user_id=NULL` and detail containing username
  - Rejects self-deletion → 400
  - Rejects deleting last admin → 400
  - Allows deleting non-last admin directly (no demote needed)
  - User with no data deletes cleanly
  - Audio file paths returned for cleanup
- Frontend: `pnpm check && pnpm lint`

## Audio File Cleanup Strategy

Existing pattern (used by `delete_album`, `delete_generation`, `delete_song`):
1. Collect relative file paths from generation records BEFORE deleting DB rows
2. Commit DB transaction
3. Call `cleanup_generation_files(audio_dir, paths)` AFTER commit
4. `cleanup_generation_files` logs warnings for files that fail to delete (missing, permissions)

This means: if commit succeeds but file deletion fails → orphaned files on disk (detectable, not data loss).
If commit fails → no files deleted, consistent state.
Same tradeoff as every other deletion in the app. No special handling needed.

Files live at `{AUDIO_ROOT}/{user_id}/{generation_id}.{mp3,wav,md,whisper}`. After deleting all a user's generations, the `{AUDIO_ROOT}/{user_id}/` directory will be empty — clean it up too.

## Files Touched

| File | Change |
|---|---|
| `db/queries/auth.py` | Add `hard_delete_user()` |
| `admin_api.py` | Add `DELETE /users/{id}/permanent` |
| `frontend/src/lib/api/client.ts` | Add `hardDeleteUser()` |
| `frontend/src/routes/settings/users/+page.svelte` | Reset password UI + delete with username confirmation |
| `tests/test_admin_api.py` | Tests for hard delete |

## Edge Cases

- User has no albums/songs/generations — delete is a no-op cascade, still works
- Audio files already missing from disk — `cleanup_generation_files` logs warning, doesn't fail
- Empty user directory after cleanup — rmdir it (new: add to cleanup step)
- Concurrent requests deleting same user — first wins, second gets 404
- User currently logged in — session deletion + Redis cache clear (existing pattern from deactivate endpoint)
- Rate limit overrides for deleted user — `user_rate_limits` table needs FK cascade or explicit deletion

# Admin-Configurable Rate Limits

> **Status: NOT STARTED**

## Problem

Rate limits are hardcoded in env vars (`GENERATION_RATE_LIMIT_USER`, etc.). Changing them requires editing `.env` and redeploying containers. There's no way to set per-user overrides — all users share the same limits.

## Goal

Admin can manage rate limits from the settings panel:
1. **Global defaults** — editable in the UI, stored in DB, no redeploy needed
2. **Per-user overrides** — give specific users higher/lower limits

Resolution order: per-user override → global DB default → env var fallback.

## Scope

Only **business/operational settings** are editable. Security settings stay in env vars:

| Editable (admin panel) | Stays in env (not editable) |
|---|---|
| `generation_rate_limit` | `ALLOWED_HOSTS` |
| `scoring_rate_limit` | `CORS_ORIGIN` |
| `chat_rate_limit` | `TRUSTED_PROXIES` |
| `max_queue_depth` | `DATABASE_URL`, `REDIS_URL` |
| `max_user_active_jobs` | `SECRET_KEY` |

## Data Model

### New table: `rate_limit_settings`

| Column | Type | Notes |
|---|---|---|
| id | varchar(36) PK | UUID |
| user_id | varchar(36) FK nullable | NULL = global default, set = per-user override |
| setting_key | varchar(50) | e.g. `generation_rate_limit` |
| value | integer | The limit value |
| updated_at | timestamptz | Last modified |

Unique constraint on `(user_id, setting_key)` — one value per setting per user (or global).

### Setting keys (constants)

```
SETTING_GENERATION_RATE_LIMIT = "generation_rate_limit"
SETTING_SCORING_RATE_LIMIT = "scoring_rate_limit"
SETTING_CHAT_RATE_LIMIT = "chat_rate_limit"
SETTING_MAX_QUEUE_DEPTH = "max_queue_depth"
SETTING_MAX_USER_ACTIVE_JOBS = "max_user_active_jobs"
```

## Resolution Logic

```
def resolve_rate_limit(session, user_id, setting_key, env_fallback):
    # 1. Per-user override
    override = get_rate_limit(session, user_id, setting_key)
    if override is not None:
        return override.value
    # 2. Global DB default
    global_default = get_rate_limit(session, None, setting_key)
    if global_default is not None:
        return global_default.value
    # 3. Env var fallback
    return env_fallback
```

## Files to Touch

| File | Change |
|---|---|
| `db/models.py` | Add `RateLimitSetting` model |
| `db/queries/settings.py` | CRUD for rate limit settings + resolve function |
| `db/queries/__init__.py` | Re-export new functions |
| `api_helpers.py` | Replace hardcoded constants with `resolve_rate_limit()` calls |
| `api_models.py` | Request/response models for rate limit endpoints |
| `settings_api.py` | New admin endpoints: GET/PUT global limits, GET/PUT per-user limits |
| `constants.py` | Setting key constants |
| Alembic migration | Create `rate_limit_settings` table |
| `scripts/generate_types.py` | Run to generate frontend types |
| Frontend: `settings/users/+page.svelte` | Per-user rate limit overrides in user management |
| Frontend: new `settings/rate-limits/+page.svelte` | Global rate limit defaults page |
| Frontend: `lib/api/client.ts` | API client functions for rate limit endpoints |

## API Endpoints

```
GET  /settings/rate-limits              → global defaults (admin only)
PUT  /settings/rate-limits              → update global defaults (admin only)
GET  /settings/rate-limits/user/{id}    → per-user overrides (admin only)
PUT  /settings/rate-limits/user/{id}    → set per-user overrides (admin only)
DELETE /settings/rate-limits/user/{id}  → clear per-user overrides (back to global)
```

## Frontend

### Global defaults page (`settings/rate-limits/+page.svelte`)
- Table of setting keys with current values
- Inline edit, save button
- Shows env fallback value as placeholder

### Per-user overrides (in `settings/users/+page.svelte`)
- Expand a user row → see their effective limits
- Override individual settings or clear to use global default
- Visual indicator when a user has custom limits

## Constraints

- Admin-only — all endpoints use `require_admin`
- Audit logged — all changes recorded via `record_audit()`
- Resolution must not add a DB query per request — cache in memory with short TTL or resolve at job creation time (already inside a transaction in `create_job_with_rate_limit`)
- Env vars remain as ultimate fallback — if the DB table is empty, behavior is identical to today
- No migration of existing env values into DB — they coexist

## Migration Path

1. Deploy with new table (empty) — behavior unchanged, env vars still control everything
2. Admin sets global defaults via UI — DB values now override env vars
3. Admin sets per-user overrides as needed

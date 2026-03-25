# Security Hardening Plan

Fixes from the Iron Guard security audit + hardening for public exposure.

## Phase 1: Audit Fixes (Critical) — DONE

### 1.1 Defense-in-depth auth on API endpoints
- [x] Replaced `_get_optional_user` with `Depends(get_current_user)` on all endpoints
- [x] Removed `None` guards in access check functions — user is always present
- [x] Audio endpoint now requires authentication independently of middleware

### 1.2 Sanitize job error messages
- [x] `_sanitize_error()` maps exception types to user-friendly messages
- [x] Raw exceptions logged server-side only
- [x] Claude `UnavailableError` returns generic "Claude is currently unavailable"

### 1.3 Constant-time login (prevent username enumeration)
- [x] `verify_password_constant_time()` always runs bcrypt against dummy hash when user not found

## Phase 2: Request Hardening — DONE

### 2.1 Request body size limit
- [x] `BodySizeLimitMiddleware` rejects requests > 1 MB (413)
- [x] Configurable via `MAX_REQUEST_BODY_BYTES` env var

## Phase 3: Rate Limit Overhaul — DONE

### 3.1 Per-user rate limits (replace per-IP)
- [x] All rate limits keyed by `user.id` via `count_user_jobs_in_window`
- [x] Works correctly behind reverse proxies

### 3.2 Admin rate limits (higher, not unlimited)
- [x] Admins get 10x user limits (configurable: `*_RATE_LIMIT_ADMIN` env vars)
- [x] `_RATE_LIMITS` dict maps job types to `(user_limit, admin_limit)` tuples
- [x] Queue depth and active job checks still apply to non-admins

### 3.3 Claude chat rate limit
- [x] Per-user hourly cap (default: 30/hr user, 300/hr admin)
- [x] Tracked as `type="chat"` jobs in the jobs table
- [x] Env vars: `CHAT_RATE_LIMIT_USER`, `CHAT_RATE_LIMIT_ADMIN`

## Phase 4: Audit Trail — DONE

### 4.1 AuditLog model
- [x] `audit_log` table: `id, user_id, action, resource_type, resource_id, detail, created_at`
- [x] Indexed on `user_id`, `action`, `created_at`
- [x] Alembic migration: `cb9d08c092f1`

### 4.2 Audit helper + endpoint
- [x] `record_audit()` called on: create album/song, update song, delete version/generation, generate, score, cleanup
- [x] `GET /api/admin/audit-log` endpoint for admins

## Phase 5: Infrastructure (manual / deploy-time)

### 5.1 HTTPS via Caddy reverse proxy
- Caddyfile: `yourdomain.com { reverse_proxy localhost:8080 }`
- Auto-TLS via Let's Encrypt
- Set `CORS_ORIGIN=https://yourdomain.com` in `.server.env`

### 5.2 Caddy body size limit
- Add `request_body { max_size 1MB }` to Caddyfile (defense-in-depth alongside app middleware)

## Future: MFA (deferred)

Not needed for current threat model (small user base, invite-only). Revisit if:
- Open registration is added
- Multiple untrusted users share the instance
- Compliance requirements change

Implementation notes for when needed:
- TOTP (Google Authenticator / Authy)
- New table: `user_mfa(user_id, secret, backup_codes, enabled_at)`
- Setup flow: generate secret → show QR → verify first code → enable
- Login flow: password OK → if MFA enabled → require TOTP code
- Recovery: 10 single-use backup codes generated at setup

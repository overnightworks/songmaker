# Songmaker Security

## Authentication

Session-based auth with bcrypt password hashing (12 rounds).

- **Session tokens**: `secrets.token_urlsafe(32)` — 256-bit entropy, stored in both DB and Redis
- **Redis session cache**: Session validation reads from Redis first (no DB hit on cache hit). DB is the durable store, synced every 5 minutes via a background task. Redis failure degrades gracefully to DB-only mode. Session TTL in Redis replaces per-request DB writes for sliding window renewal.
- **HMAC-signed cookies**: Session cookies are `{session_id}.{hmac_sha256}` signed with a server-side secret. A DB or Redis leak does not yield usable cookies. The secret comes from the `SESSION_SECRET` env var (min 32 chars) and is required at startup — Settings raises `ValidationError` if missing. There is no auto-generation fallback (was removed in the W1 no-silent-fallbacks cleanup; the old fallback masked deployment misconfigurations).
- **Cookie flags**: `HttpOnly`, `SameSite=Strict`, `Secure` (auto-detected; `X-Forwarded-Proto` only honored when the direct peer is in `TRUSTED_PROXIES`)
- **Session lifetime**: 30-day sliding window (via Redis TTL), 90-day absolute max (checked from cached `created_at`)
- **Session fixation**: All old sessions deleted from both DB and Redis on login, password change, and admin password reset
- **Logout**: `DELETE /session` invalidates the session in both DB and Redis (not just the cookie). The session ID is passed via `request.state` from the auth dependency.
- **Session anomaly detection**: IP and user-agent changes are logged to the audit trail (even on Redis cache hits)
- **User deactivation**: All sessions immediately deleted from both DB and Redis. A `user_sessions:{user_id}` Redis set tracks all active session IDs per user for efficient bulk deletion.
- **Brute-force protection**: 5 failed attempts per 5 minutes, per IP + per username. Also applies to password change endpoint.
- **Account lockout**: After 15 failed attempts per username within 1 hour, the account is temporarily locked (returns 429 with Retry-After). This catches patient attackers who stay under the per-window rate limit. Configurable via `LOGIN_LOCKOUT_THRESHOLD` and `LOGIN_LOCKOUT_WINDOW`.
- **Constant-time verification**: bcrypt always runs against a dummy hash when the user doesn't exist (login) or on password change, preventing timing-based enumeration
- **Login attempt cleanup**: Records older than 90 days are pruned at startup
- **Password strength**: Common passwords (~200 entries including seasonal/year variants) and low-entropy passwords (< 4 unique chars) are rejected on setup, user creation, and password change

## Authorization

Two-layer defense:

1. **Dependency-based auth** (`middleware/auth.py`): `get_current_user` is a FastAPI dependency that validates the session cookie, checks expiry/lifetime/active status, and renews the session. On Redis cache hit, validation uses cached data and TTL refresh replaces the DB write. On Redis miss or failure, falls back to the DB path and populates the Redis cache for subsequent requests.
2. **Endpoint** (`api.py`): Authenticated resource endpoints use `Depends(get_current_user)` and return 401 if unauthenticated. Public auth/setup endpoints are deliberately unauthenticated; worker control-plane routes under `/api/internal/*` use the internal token instead of sessions. Ownership checks enforce default-deny: access is blocked unless the resource belongs to the user (or the user is admin). Missing resources are denied.

Roles: `Literal["admin", "user"]` — validated at the Pydantic schema level. No other role values are accepted by the API. Demotion or deactivation of the last active admin is blocked to prevent lockout. When a user is deactivated or their role is changed, all their sessions are immediately invalidated.

## CSRF Protection

Four-layer defense:

1. **`SameSite=Strict` cookies**: Prevents cross-site cookie transmission in modern browsers
2. **Session-bound CSRF token**: Login and setup set a `csrf_token` cookie (non-HttpOnly, `SameSite=Strict`) whose value is `HMAC-SHA256(session_secret, "csrf:" + session_id)`. All mutating `/api/` requests (except login/setup) must include an `X-CSRF-Token` header. The server verifies the token by recomputing the HMAC from the current session — it does not trust the cookie value. This prevents subdomain cookie injection attacks (where a sibling subdomain sets a forged cookie).
3. **Origin verification**: Mutating requests to `/api/` with an `Origin`/`Referer` header that doesn't match `ALLOWED_HOSTS` (or localhost by default) are rejected (403). Uses a server-side allowlist instead of the request's `Host` header to prevent header-spoofing bypasses.
4. **Form-submit blocking**: Mutating requests without `Origin`/`Referer` are rejected if their `Content-Type` is a form type (`application/x-www-form-urlencoded`, `multipart/form-data`, `text/plain`). This blocks HTML form CSRF in browsers that don't enforce SameSite, while allowing JSON API clients (CLI, fetch).

## Rate Limiting

### Per-user (API endpoints)

| Resource     | User limit        | Admin limit       | Scope    |
|-------------|-------------------|-------------------|----------|
| Login        | 5 / 5 min         | 5 / 5 min         | Per IP + per username |
| Generation   | 3 / hour          | 30 / hour         | Per user |
| Scoring      | 10 / hour         | 100 / hour        | Per user |
| Chat (Claude)| 30 / hour         | 300 / hour        | Per user |
| Queue depth  | 100 total         | 100 total         | Global   |
| Active jobs  | 1 concurrent      | 1 concurrent      | Per user (non-admin) |

Rate limit checks and job creation are atomic (`BEGIN IMMEDIATE`) to prevent TOCTOU races where concurrent requests bypass limits.

### Shared endpoints (public, no auth)

Album, song, generation, and playlist shares expose public read-only endpoints with a dedicated per-IP rate limiter (default: 60 requests/minute, configurable via `SHARED_RATE_LIMIT`):

| Resource | JSON endpoint | Audio endpoint |
|----------|---------------|----------------|
| Album | `/shared/{slug}` | `/shared/{slug}/audio/{file}` |
| Song | `/shared/song/{slug}` | `/shared/song/{slug}/audio/{file}` |
| Generation | `/shared/gen/{slug}` | `/shared/gen/{slug}/audio/{file}` |
| Playlist | `/shared/playlist/{slug}` | `/shared/playlist/{slug}/audio/{file}` |

Album and song shares serve the picked unarchived generation when one exists, otherwise the latest unarchived generation. Generation shares serve the shared generation. Playlist shares serve playlist entry generations. Public JSON responses omit scores and edit history; audio URLs include the exact stored relative audio path needed by the filename allowlist. Share slugs are UUID v4 values (122 bits of entropy, unguessable). Sharing is revocable by the resource owner.

### Per-IP (global middleware)

All requests are subject to a global per-IP rate limit (default: 120 requests/minute). This prevents multi-account abuse and unauthenticated request floods. The rate limiter is memory-bounded (max 10k tracked IPs with automatic eviction of stale entries). Configurable via `IP_RATE_LIMIT` env var. When `TRUSTED_PROXIES` is configured, the rate limiter uses the real client IP from `X-Forwarded-For` (rightmost untrusted entry), matching the login rate limiter's behavior. If Redis is unavailable, the rate limiter fails closed (returns 503 with `Retry-After: 5`) rather than allowing all requests through.

Configure via env vars: `LOGIN_RATE_LIMIT`, `LOGIN_LOCKOUT_THRESHOLD`, `LOGIN_LOCKOUT_WINDOW`, `GENERATION_RATE_LIMIT_USER`, `GENERATION_RATE_LIMIT_ADMIN`, `SCORING_RATE_LIMIT_USER`, `SCORING_RATE_LIMIT_ADMIN`, `CHAT_RATE_LIMIT_USER`, `CHAT_RATE_LIMIT_ADMIN`, `MAX_QUEUE_DEPTH`, `IP_RATE_LIMIT`.

## Security Headers

All responses include:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; connect-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self' https://fonts.gstatic.com; frame-ancestors 'none'`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains` (HTTPS only; `X-Forwarded-Proto` only honored from `TRUSTED_PROXIES`)
- `Cache-Control: no-store` (API responses only — prevents caching of authenticated data)

## CORS

- **Methods**: `GET`, `POST`, `PUT`, `DELETE` (no wildcard)
- **Headers**: `Content-Type`, `Cookie`, `X-CSRF-Token` (no wildcard)
- **Credentials**: Allowed
- **Origins**: Configurable via `CORS_ORIGIN`. Wildcard origins must be `*.domain.tld` format (e.g., `*.trycloudflare.com`) — bare TLDs like `*.com` are rejected at startup. Defaults to `localhost`/`127.0.0.1` on ports 8080 and 5173 only for dev (not any arbitrary port).

## Error Handling

- **Job errors**: Sanitized before storing in DB. Internal exception details logged server-side only; clients see generic messages like "Internal error during processing".
- **API errors**: All `HTTPException` messages are human-readable strings with no internal paths or stack traces. User input is never reflected in error messages.
- **Validation errors**: Custom `RequestValidationError` handler returns only affected field names, not full Pydantic error details (constraints, expected types, internal schema).
- **ACE-Step errors**: Raw responses logged server-side; clients see "ACE-Step returned an error".
- **Claude CLI errors**: stderr is logged server-side; clients see "Claude is currently unavailable".
- **OpenAPI/docs**: Disabled (`docs_url=None, redoc_url=None, openapi_url=None`).

## Request Size Limits

`BodySizeLimitMiddleware` (raw ASGI) first checks `Content-Length` for fast rejection, then wraps the receive channel to count bytes as they stream in — aborting with 413 once the limit is exceeded without buffering the entire body. Requests > 1 MB are rejected (HTTP 413). Configurable via `MAX_REQUEST_BODY_BYTES` env var. The reimport endpoint (`/reimport`) and audio upload (`/audio/upload`) have a higher limit (50 MB, configurable via `MAX_UPLOAD_BODY_BYTES`) to allow audio file uploads.

### Reference audio upload

`POST /api/audio/upload` accepts audio files (.mp3, .wav, .flac, .ogg) up to 50 MB. Files are stored in `{audio_dir}/{user_id}/refs/{uuid}.{ext}` — the UUID filename prevents name collisions and path injection. The `reference_audio_path` field on `GenerationParams` is validated at two levels:

1. **API validation**: Pydantic validator rejects any value containing `..`
2. **Job execution**: The path is resolved to absolute and verified to stay inside `audio_dir` before being passed to ACE-Step

**Note**: For production deployments exposed to the internet, use a reverse proxy (e.g., nginx `client_max_body_size 1m`) to reject oversized requests at the network edge before they reach the application.

## Request Timeout

Uvicorn's `timeout-keep-alive` is set to `REQUEST_TIMEOUT` (default 30s). Idle connections exceeding this are closed. For production, use a reverse proxy timeout (e.g., nginx `proxy_read_timeout`) for full request-level timeout enforcement.

## Claude Chat Security

- **System prompt**: Hardcoded server-side (`SYSTEM_PROMPT` in `chat_api.py`). Clients cannot override it. Song context is wrapped in `<song_context>` XML tags with an untrusted-data notice instructing Claude to ignore instructions inside tags.
- **Multi-turn history**: Stored in `chat_messages` table, scoped to song. Ownership enforced via `check_song_access()` on every endpoint. Max 50 messages per song.
- **Context built server-side**: Mentioned song/version IDs are sent by the frontend, but the backend resolves them from the DB — the client never sends raw context. Each mentioned song is ownership-checked.
- **CLI backend**: All known tools disabled via `--disallowedTools` denylist. Note: `--tools ""` and `--allowedTools ""` do not reliably block tools in current Claude CLI versions, so a comprehensive denylist is used instead. This list must be updated when new tools are added to Claude Code.
- **API backend**: Uses the Anthropic Python SDK with `max_tokens=1024` to limit response cost.

## Admin Session Management

The admin sessions endpoint (`GET /api/admin/sessions`) returns SHA256 hashes of session tokens, not the raw tokens. This prevents session hijacking via the admin panel. Force-logout (`DELETE /api/admin/sessions/{hash}`) looks up sessions by hash.

## ACE-Step Worker Pool Trust Boundary

The ACE-Step worker pool runs each model-serving worker as a separate peer container. Workers self-register with the web container at startup and heartbeat ephemeral state to Redis. The control plane (web container) and the workers communicate over an **internal HTTP API** mounted under `/api/internal/*`.

### Internal token

- **Env var**: `SONGMAKER_INTERNAL_TOKEN` — a shared secret that must be set on both the web container and every worker container before startup.
- **Header**: Workers send `X-Internal-Token: <token>` on every internal call. The web container does the same when the music-worker scheduler proxies `/load_model` / `/evict_model` to a worker.
- **Verification**: `internal_api.verify_internal_token` is mounted as a router-level dependency, so every endpoint under `/api/internal/*` automatically requires the header. Comparison uses `hmac.compare_digest` for timing safety.
- **Failure modes**: Missing env var → 503 ("Internal API not configured"). Wrong/missing token → 401. The 503 vs 401 split tells the operator whether the issue is config or credentials.
- **CSRF**: `/api/internal/*` is exempt from the CSRF middleware. Workers do not have sessions; the internal token is the only credential that matters.

### Reverse proxy responsibility

The reverse proxy (nginx/caddy/cloudflare) **must not expose `/api/internal/*` to the public internet**. The internal API trusts any caller that knows the token, and the token lives in container env vars — there is no per-user authorization on these endpoints. Example nginx block:

```nginx
location /api/internal/ {
    deny all;
    return 404;
}
```

This is the same hardening principle as `/metrics`: an unauthenticated-but-internal endpoint that's safe behind the proxy and unsafe in front of it.

### Token rotation

1. Generate a new token (e.g. `openssl rand -hex 32`).
2. Update `SONGMAKER_INTERNAL_TOKEN` in the web container env and every worker container env.
3. Restart all containers. There is no DB state to update — registration is idempotent and the next worker startup re-registers with the new token.

There is no graceful "two valid tokens" overlap. Restarting workers in sequence is acceptable because the music-worker scheduler tolerates worker outages (it routes to surviving workers).

### Trust scope of a compromised worker

A compromised acestep-worker container has:

- The shared internal token (it needs it to register and to receive scheduler calls).
- The model-weights volume mount (read/write, but only its own checkpoints directory).
- Network access to the web container, music-worker container, and Redis.

It does **not** have:

- Database credentials (the worker has no `DATABASE_URL`; it only calls `/api/internal/workers/register`, which writes a single identity row).
- Auth tables, user data, or audio files (no DB connection, no audio volume).
- The session secret (only the web container has it).

The most a compromised worker can do is publish bogus state to Redis, register with a wrong host/port, or refuse to load models. None of these affect user data integrity. The blast radius is "denial of generation," not data exfiltration.

### Future hardening

If exposure to untrusted traffic becomes a concern, the next step is to bind `/api/internal/*` to a separate port (and bind it to the docker network, not `0.0.0.0`). The current single-port design is acceptable for self-hosted single-tenant deployments behind a reverse proxy that filters paths.

## Audit Trail

All mutating operations are logged to the `audit_log` table:

- **Actions tracked**: `create`, `update`, `delete`, `generate`, `score`, `cleanup`, `share`, `unshare`, `deactivate`, `session_ip_change`, `session_ua_change`
- **Fields**: `user_id`, `action`, `resource_type`, `resource_id`, `detail`, `created_at`
- **Admin access**: `GET /api/admin/audit-log?limit=100`

## Production Deployment

### Recommended

| Setting | How |
|---------|-----|
| HTTPS termination | Reverse proxy (nginx/caddy) with TLS. Set `X-Forwarded-Proto: https` so `Secure` cookie flag and HSTS header activate. |
| Session secret | Set `SESSION_SECRET` env var (min 32 chars). Required — startup fails with `ValidationError` if missing. Stable across restarts. Generate with `python3 -c "import secrets; print(secrets.token_hex(32))"`. |
| CORS origin | Set `CORS_ORIGIN=https://yourdomain.com` or `CORS_ORIGIN=*.yourdomain.com`. Wildcard must include a registrable domain (e.g., `*.trycloudflare.com`). Bare TLDs rejected. |
| Trusted proxies | Set `TRUSTED_PROXIES=10.0.0.1` (comma-separated). Only these IPs are trusted for `X-Forwarded-For`. Uses the rightmost untrusted entry to prevent spoofing. Without this, the client's direct IP is always used for rate limiting. |
| Allowed hosts | Set `ALLOWED_HOSTS=yourdomain.com,yourdomain.com:443` (comma-separated). Used by CSRF origin verification. Defaults to `localhost`/`127.0.0.1` regex for dev. |
| Host binding | Default is `127.0.0.1` (localhost only). Set `HOST=0.0.0.0` to listen on all interfaces (only behind a reverse proxy). |
| Workers | Production runs in Docker only. The web container uses a single uvicorn process; concurrency comes from arq worker containers (`MUSIC_MAX_JOBS`, `SCORING_MAX_JOBS`). PostgreSQL is the only supported production DB — SQLite is test-only. |
| Request body limit | App-level: `MAX_REQUEST_BODY_BYTES` (default 1 MB). Also set in reverse proxy for defense-in-depth. |
| IP rate limit | `IP_RATE_LIMIT` (default 120/min). Adjust based on expected traffic. |
| Request timeout | `REQUEST_TIMEOUT` (default 30s). Increase if generation/scoring endpoints are called synchronously. |

### Secrets

- `SESSION_SECRET`: HMAC signing key for session cookies. Required at startup (Settings raises ValidationError if missing).
- `ANTHROPIC_API_KEY`: Optional (for server-side Claude chat). Never logged or returned in responses.
- `.env`: Gitignored. Never committed. Single source for all Docker Compose substitutions and pydantic Settings.

## Input Validation

All request models use Pydantic with strict constraints:

- String fields: `max_length` enforced (lyrics: 50k, prompts: 5k, titles: 200)
- Numeric fields: `ge`/`le` bounds (BPM, duration, rating)
- Generation params: Typed `GenerationParams` model with `extra="forbid"`, range-validated fields, and enum-validated string values
- Role fields: `Literal["admin", "user"]` — no arbitrary role injection
- Password strength: Common password blocklist + minimum unique character count
- No raw SQL — 100% SQLAlchemy ORM with parameterized queries
- No `eval`, `exec`, `pickle`, `shell=True`, or `yaml.load` anywhere

## Path Traversal Protection

Audio file serving uses `.resolve()` + `.is_relative_to()` to prevent directory traversal. The authenticated audio endpoint (`/audio/{owner_id}/{filename}`) checks that the requesting user owns the files (or is admin) — no DB lookup needed since the path is keyed by user ID. Shared audio endpoints first resolve the slug to a shared album, song, generation, or playlist, then validate the requested filename against that resource's allowed generation paths before reading from disk.

## GPU Resource Safety

- **Per-job cleanup**: Both generation and scoring jobs call `gc.collect()` + `torch.cuda.empty_cache()` in a `finally` block, ensuring VRAM is released even on failure.
- **Mode-switch cleanup**: The GPU queue clears scoring models before generation and vice versa, with VRAM verification (waits up to 10s for release).
- **ACE-Step lifecycle**: The acestep-worker container manages the ACE-Step HTTP subprocess, sending SIGTERM (with SIGKILL fallback) on model switch, worker restart, or shutdown. See `docs/acestep.md` for the worker pool architecture.

## Known Limitations

- **Claude CLI tool denylist**: Uses `--disallowedTools` (denylist, not allowlist) because `--tools ""` doesn't reliably block tools. New Claude Code tools require updating the list in `provider.py`.
- **No IP binding on sessions**: A stolen session cookie works from any IP. IP/UA changes are logged to the audit trail but not blocked, to avoid breaking mobile users who switch networks.
- **No MFA**: Single-factor auth only. Acceptable for invite-only deployments.
- **Redis session staleness**: If Redis delete fails during user deactivation, the cached session remains valid until the next background sync (up to 5 minutes) or Redis TTL expiry. The background sync detects and cleans up orphaned/deactivated sessions.
- **Worker control endpoints have no cooldown**: `POST /api/admin/workers/{id}/restart`, `POST /api/admin/workers/{id}/pin_model`, and `POST /api/admin/registry/{mode}/download` are not rate-limited. Repeated calls by a compromised admin could disrupt GPU workers or exhaust download bandwidth. Admin-only auth is the only gate.
- **`/metrics` endpoint is unauthenticated**: Exposes Prometheus metrics (request counts, latencies, queue depth, VRAM usage) without auth. When deployed behind Cloudflare Tunnel or a reverse proxy, the proxy should block `/metrics` from public access. This is sufficient for single-user / friends-only deployments. If exposing to untrusted traffic, add `require_auth` or bind metrics to a separate internal port.

## Hardening Roadmap (for public internet exposure)

The application-layer security (auth, CSRF, IDOR, injection, error sanitization) is solid for a self-hosted tool behind a reverse proxy. The gaps below are infrastructure-level and would need addressing before exposing the app to untrusted public traffic at scale.

### ~~1. Replace SQLite with PostgreSQL~~ (Done)
PostgreSQL is now required for production. SQLite is used only in tests (`init_test_db()`).

### ~~2. Persistent rate limiting (Redis)~~ (Done)
Redis-backed sliding-window rate limiting is now the only implementation. Rate limit state survives restarts and is shared across workers.

### ~~3. Account lockout / progressive delays~~ (Done)
Implemented: 15 failed attempts per username within 1 hour triggers account lockout (429). Configurable via `LOGIN_LOCKOUT_THRESHOLD` and `LOGIN_LOCKOUT_WINDOW`.

### 4. Multi-worker architecture
**Priority: Medium** — PostgreSQL and Redis are in place. Multiple uvicorn workers can be added via `--workers N`. The arq worker already runs as a separate process.

### 5. Content Security Policy — remove `'unsafe-inline'` from `style-src`
**Priority: Low** — CSP now enforces `script-src 'self'` and `default-src 'none'`. The `style-src 'unsafe-inline'` directive is needed for SvelteKit dev mode but could be tightened in production. Consider nonce-based inline styles if a stricter policy is desired.

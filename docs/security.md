# Songmaker Security

## Authentication

Session-based auth with bcrypt password hashing (12 rounds).

- **Session tokens**: `secrets.token_urlsafe(32)` — 256-bit entropy, stored in SQLite
- **Cookie flags**: `HttpOnly`, `SameSite=Strict`, `Secure` (auto-detected via `X-Forwarded-Proto`)
- **Session lifetime**: 30-day sliding window, 90-day absolute max
- **Session fixation**: All old sessions deleted on login and password change
- **Brute-force protection**: 5 failed attempts per 5 minutes, per IP + per username
- **Constant-time login**: bcrypt always runs against a dummy hash when the user doesn't exist, preventing timing-based username enumeration

## Authorization

Two-layer defense:

1. **Middleware** (`middleware.py`): Blocks unauthenticated requests to all non-public paths. Returns 401 before reaching any endpoint.
2. **Endpoint** (`api.py`): Every endpoint uses `Depends(get_current_user)` — returns 401 independently of middleware. Ownership checks enforce `album.created_by == user.id` on every resource access.

Roles: `admin` (sees all resources, higher rate limits) and `user` (sees own albums only).

## Rate Limiting

| Resource     | User limit        | Admin limit       | Scope    |
|-------------|-------------------|-------------------|----------|
| Login        | 5 / 5 min         | 5 / 5 min         | Per IP + per username |
| Generation   | 3 / hour          | 30 / hour         | Per user |
| Scoring      | 10 / hour         | 100 / hour        | Per user |
| Chat (Claude)| 30 / hour         | 300 / hour        | Per user |
| Queue depth  | 10 total          | 10 total          | Global   |
| Active jobs  | 1 concurrent      | 1 concurrent      | Per user (non-admin) |

Configure via env vars: `LOGIN_RATE_LIMIT`, `GENERATION_RATE_LIMIT_USER`, `GENERATION_RATE_LIMIT_ADMIN`, `SCORING_RATE_LIMIT_USER`, `SCORING_RATE_LIMIT_ADMIN`, `CHAT_RATE_LIMIT_USER`, `CHAT_RATE_LIMIT_ADMIN`, `MAX_QUEUE_DEPTH`.

## Security Headers

All responses include:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Content-Security-Policy: frame-ancestors 'none'`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`

## Error Handling

- **Job errors**: Sanitized before storing in DB. Internal exception details logged server-side only; clients see generic messages like "Internal error during processing".
- **API errors**: All `HTTPException` messages are human-readable strings with no internal paths or stack traces.
- **Claude CLI errors**: stderr is logged server-side; clients see "Claude is currently unavailable".
- **OpenAPI/docs**: Disabled (`docs_url=None, redoc_url=None, openapi_url=None`).

## Request Size Limits

`BodySizeLimitMiddleware` rejects requests with `Content-Length` > 1 MB (HTTP 413). Configurable via `MAX_REQUEST_BODY_BYTES` env var. This is defense-in-depth alongside reverse proxy limits.

## Audit Trail

All mutating operations are logged to the `audit_log` table:

- **Actions tracked**: `create`, `update`, `delete`, `generate`, `score`, `cleanup`
- **Fields**: `user_id`, `action`, `resource_type`, `resource_id`, `detail`, `created_at`
- **Admin access**: `GET /api/admin/audit-log?limit=100`

## Production Deployment

### Required

| Env var | Purpose | Generate with |
|---------|---------|---------------|
| `SESSION_SECRET` | Required at startup (reserved for future session signing) | `openssl rand -hex 32` |

### Recommended

| Setting | How |
|---------|-----|
| HTTPS termination | Reverse proxy (nginx/caddy) with TLS. Set `X-Forwarded-Proto: https` so `Secure` cookie flag activates. |
| CORS origin | Set `CORS_ORIGIN=https://yourdomain.com`. Defaults to `localhost` regex for dev. |
| Proxy IP forwarding | Set `X-Forwarded-For` header in your reverse proxy. The rate limiter reads the first entry as the client IP. Only enable this behind a trusted proxy — without one, clients can spoof the header. |
| Request body limit | App-level: `MAX_REQUEST_BODY_BYTES` (default 1 MB). Also set in reverse proxy (e.g., `client_max_body_size 10m` in nginx) for defense-in-depth. |
| DB file permissions | Automatically set to `600` (owner read/write only). |

### Secrets

- `SESSION_SECRET`: Required, never logged.
- `ANTHROPIC_API_KEY`: Optional (for server-side Claude chat). Never logged or returned in responses.
- `.server.env`: Gitignored. Never committed.

## Input Validation

All request models use Pydantic with strict constraints:

- String fields: `max_length` enforced (lyrics: 50k, prompts: 5k, titles: 200)
- Numeric fields: `ge`/`le` bounds (BPM, duration, rating)
- Generation params: Whitelist of allowed keys, type-checked values, range-validated
- Generation defaults (admin): Max 50 keys per dict (field validator)
- No raw SQL — 100% SQLAlchemy ORM with parameterized queries
- No `eval`, `exec`, `pickle`, `shell=True`, or `yaml.load` anywhere

## Path Traversal Protection

Audio file serving uses `.resolve()` + `.is_relative_to()` to prevent directory traversal. Slug generation strips all non-alphanumeric characters.

## Known Limitations

- **No CSRF tokens**: Mitigated by `SameSite=Strict` cookies. If SameSite policy is relaxed, CSRF tokens would be needed.
- **No IP binding on sessions**: A stolen session cookie works from any IP. This is intentional — IP binding breaks mobile users who switch networks.
- **No MFA**: Single-factor auth only. Acceptable for invite-only deployments. See `plans/security-hardening.md` for future TOTP plan.
- **ACE-Step reinitialize**: No cooldown on `POST /api/admin/acestep/reinitialize`. Repeated calls by a compromised admin could cause GPU disruption.

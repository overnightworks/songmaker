# Songmaker Security

## Authentication

Session-based auth with bcrypt password hashing (12 rounds).

- **Session tokens**: `secrets.token_urlsafe(32)` — 256-bit entropy, stored in SQLite
- **HMAC-signed cookies**: Session cookies are `{session_id}.{hmac_sha256}` signed with a server-side secret. A DB leak does not yield usable cookies. The secret is auto-generated and stored in `<output_dir>/.session_secret` (mode 0600), or provided via `SESSION_SECRET` env var (min 32 chars).
- **Cookie flags**: `HttpOnly`, `SameSite=Strict`, `Secure` (auto-detected via `X-Forwarded-Proto`)
- **Session lifetime**: 30-day sliding window, 90-day absolute max
- **Session fixation**: All old sessions deleted on login and password change
- **Session anomaly detection**: IP and user-agent changes are logged to the audit trail
- **Brute-force protection**: 5 failed attempts per 5 minutes, per IP + per username
- **Constant-time login**: bcrypt always runs against a dummy hash when the user doesn't exist, preventing timing-based username enumeration
- **Login attempt cleanup**: Records older than 90 days are pruned at startup
- **Password strength**: Common passwords (top ~50 list) and low-entropy passwords (< 4 unique chars) are rejected on setup, user creation, and password change

## Authorization

Two-layer defense:

1. **Middleware** (`middleware.py`): Blocks unauthenticated requests to all non-public paths. Returns 401 before reaching any endpoint.
2. **Endpoint** (`api.py`): Every endpoint uses `Depends(get_current_user)` — returns 401 independently of middleware. Ownership checks enforce default-deny: access is blocked unless `album.created_by == user.id` (or user is admin). Missing album → denied.

Roles: `Literal["admin", "user"]` — validated at the Pydantic schema level. No other role values are accepted by the API.

## CSRF Protection

Three-layer defense:

1. **`SameSite=Strict` cookies**: Prevents cross-site cookie transmission in modern browsers
2. **Origin verification**: Mutating requests to `/api/` with an `Origin`/`Referer` header that doesn't match `Host` are rejected (403)
3. **Form-submit blocking**: Mutating requests without `Origin`/`Referer` are rejected if their `Content-Type` is a form type (`application/x-www-form-urlencoded`, `multipart/form-data`, `text/plain`). This blocks HTML form CSRF in browsers that don't enforce SameSite, while allowing JSON API clients (CLI, fetch).

## Rate Limiting

### Per-user (API endpoints)

| Resource     | User limit        | Admin limit       | Scope    |
|-------------|-------------------|-------------------|----------|
| Login        | 5 / 5 min         | 5 / 5 min         | Per IP + per username |
| Generation   | 3 / hour          | 30 / hour         | Per user |
| Scoring      | 10 / hour         | 100 / hour        | Per user |
| Chat (Claude)| 30 / hour         | 300 / hour        | Per user |
| Queue depth  | 10 total          | 10 total          | Global   |
| Active jobs  | 1 concurrent      | 1 concurrent      | Per user (non-admin) |

### Per-IP (global middleware)

All requests are subject to a global per-IP rate limit (default: 120 requests/minute). This prevents multi-account abuse and unauthenticated request floods. Configurable via `IP_RATE_LIMIT` env var.

Configure via env vars: `LOGIN_RATE_LIMIT`, `GENERATION_RATE_LIMIT_USER`, `GENERATION_RATE_LIMIT_ADMIN`, `SCORING_RATE_LIMIT_USER`, `SCORING_RATE_LIMIT_ADMIN`, `CHAT_RATE_LIMIT_USER`, `CHAT_RATE_LIMIT_ADMIN`, `MAX_QUEUE_DEPTH`, `IP_RATE_LIMIT`.

## Security Headers

All responses include:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Content-Security-Policy: frame-ancestors 'none'`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains` (HTTPS only)

## CORS

- **Methods**: `GET`, `POST`, `PUT`, `DELETE` (no wildcard)
- **Headers**: `Content-Type`, `Cookie` (no wildcard)
- **Credentials**: Allowed
- **Origins**: Configurable via `CORS_ORIGIN`. Defaults to `localhost`/`127.0.0.1` regex for dev.

## Error Handling

- **Job errors**: Sanitized before storing in DB. Internal exception details logged server-side only; clients see generic messages like "Internal error during processing".
- **API errors**: All `HTTPException` messages are human-readable strings with no internal paths or stack traces.
- **ACE-Step errors**: Raw responses logged server-side; clients see "ACE-Step returned an error".
- **Claude CLI errors**: stderr is logged server-side; clients see "Claude is currently unavailable".
- **OpenAPI/docs**: Disabled (`docs_url=None, redoc_url=None, openapi_url=None`).

## Request Size Limits

`BodySizeLimitMiddleware` first checks the `Content-Length` header for fast rejection, then reads and verifies the actual body size. Requests > 1 MB are rejected (HTTP 413). Configurable via `MAX_REQUEST_BODY_BYTES` env var.

**Note**: For production deployments exposed to the internet, use a reverse proxy (e.g., nginx `client_max_body_size 1m`) to reject oversized requests at the network edge before they reach the application.

## Claude Chat Security

- **System prompt**: Hardcoded server-side (`_CHAT_SYSTEM_PROMPT` in `api.py`). Clients cannot override it.
- **CLI backend**: All known tools disabled via `--disallowedTools` denylist. Note: `--tools ""` and `--allowedTools ""` do not reliably block tools in current Claude CLI versions, so a comprehensive denylist is used instead. This list must be updated when new tools are added to Claude Code.
- **API backend**: Uses the Anthropic Python SDK with `max_tokens=1024` to limit response cost.

## Admin Session Management

The admin sessions endpoint (`GET /api/admin/sessions`) returns SHA256 hashes of session tokens, not the raw tokens. This prevents session hijacking via the admin panel. Force-logout (`DELETE /api/admin/sessions/{hash}`) looks up sessions by hash.

## Audit Trail

All mutating operations are logged to the `audit_log` table:

- **Actions tracked**: `create`, `update`, `delete`, `generate`, `score`, `cleanup`, `deactivate`, `session_ip_change`, `session_ua_change`
- **Fields**: `user_id`, `action`, `resource_type`, `resource_id`, `detail`, `created_at`
- **Admin access**: `GET /api/admin/audit-log?limit=100`

## Production Deployment

### Recommended

| Setting | How |
|---------|-----|
| HTTPS termination | Reverse proxy (nginx/caddy) with TLS. Set `X-Forwarded-Proto: https` so `Secure` cookie flag and HSTS header activate. |
| Session secret | Set `SESSION_SECRET` env var (min 32 chars) for stable HMAC signing across restarts. If not set, auto-generated and stored in `<output_dir>/.session_secret`. |
| CORS origin | Set `CORS_ORIGIN=https://yourdomain.com`. Defaults to `localhost` regex for dev. |
| Trusted proxies | Set `TRUSTED_PROXIES=10.0.0.1` (comma-separated). Only these IPs are trusted for `X-Forwarded-For`. Without this, the client's direct IP is always used for rate limiting. |
| Host binding | Default is `127.0.0.1` (localhost only). Set `HOST=0.0.0.0` to listen on all interfaces (only behind a reverse proxy). |
| Request body limit | App-level: `MAX_REQUEST_BODY_BYTES` (default 1 MB). Also set in reverse proxy for defense-in-depth. |
| IP rate limit | `IP_RATE_LIMIT` (default 120/min). Adjust based on expected traffic. |
| DB file permissions | Automatically set to `600` (owner read/write only). |

### Secrets

- `SESSION_SECRET`: HMAC signing key for session cookies. Auto-generated if not set.
- `ANTHROPIC_API_KEY`: Optional (for server-side Claude chat). Never logged or returned in responses.
- `.server.env`: Gitignored. Never committed.

## Input Validation

All request models use Pydantic with strict constraints:

- String fields: `max_length` enforced (lyrics: 50k, prompts: 5k, titles: 200)
- Numeric fields: `ge`/`le` bounds (BPM, duration, rating)
- Generation params: Typed `GenerationParams` model with `extra="forbid"`, range-validated fields, and enum-validated string values
- Role fields: `Literal["admin", "user"]` — no arbitrary role injection
- Password strength: Common password blocklist + minimum unique character count
- Path parameters: `..` and `/` rejected in rate-by-path endpoint
- No raw SQL — 100% SQLAlchemy ORM with parameterized queries
- No `eval`, `exec`, `pickle`, `shell=True`, or `yaml.load` anywhere

## Path Traversal Protection

Audio file serving uses `.resolve()` + `.is_relative_to()` to prevent directory traversal. Slug generation strips all non-alphanumeric characters. The rate-by-path endpoint validates that album and generation name parameters contain no `..` or `/`.

## Known Limitations

- **Claude CLI tool denylist**: Uses `--disallowedTools` (denylist, not allowlist) because `--tools ""` doesn't reliably block tools. New Claude Code tools require updating the list in `provider.py`.
- **Frontend API key in localStorage**: When users provide their own Anthropic API key (BYOK), it's stored in `localStorage`. This is readable by any JavaScript on the same origin. CSP headers mitigate XSS risk, but browser extensions could potentially access it. The key is sent directly to Anthropic's API, never to the songmaker server.
- **No IP binding on sessions**: A stolen session cookie works from any IP. IP/UA changes are logged to the audit trail but not blocked, to avoid breaking mobile users who switch networks.
- **No MFA**: Single-factor auth only. Acceptable for invite-only deployments.
- **Body size buffering**: The body size middleware reads the full body into memory after the Content-Length pre-check passes. A reverse proxy should enforce limits at the network edge for internet-facing deployments.
- **ACE-Step reinitialize**: No cooldown on `POST /api/admin/acestep/reinitialize`. Repeated calls by a compromised admin could cause GPU disruption.

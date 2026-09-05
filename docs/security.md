# Songmaker Security

## Authentication

Session-based auth with bcrypt password hashing (12 rounds).

- **Session tokens**: `secrets.token_urlsafe(32)` — 256-bit entropy, stored in both DB and Redis
- **Redis session cache**: Session validation reads from Redis first (no DB hit on cache hit). DB is the durable store, synced every 5 minutes via a background task. Redis failure degrades gracefully to DB-only mode. Session TTL in Redis replaces per-request DB writes for sliding window renewal. Login writes the new session to Redis before the DB transaction commits (and deletes that key if commit fails) so a concurrent prune cannot be overwritten by a late cache `SET`.
- **HMAC-signed cookies**: Session cookies are `{session_id}.{hmac_sha256}` signed with a server-side secret. A DB or Redis leak does not yield usable cookies. The secret comes from the `SESSION_SECRET` env var (min 32 chars) and is required at startup — Settings raises `ValidationError` if missing. There is no auto-generation fallback (was removed in the W1 no-silent-fallbacks cleanup; the old fallback masked deployment misconfigurations).
- **Cookie flags**: `HttpOnly`, `SameSite=Strict`, `Secure` (auto-detected; `X-Forwarded-Proto` only honored when the direct peer's address falls inside a `TRUSTED_PROXIES` network — see "Proxy trust")
- **Session lifetime**: 30-day sliding window (via Redis TTL), 90-day absolute max (checked from cached `created_at`)
- **Session fixation**: Login adds an independent session and prunes only the oldest overflow once the per-user cap (`MAX_CONCURRENT_SESSIONS_PER_USER`, default 10) is exceeded. Expired sessions do not consume the cap. Password change and admin password reset still delete all sessions from both DB and Redis
- **Logout**: `DELETE /session` invalidates the session in both DB and Redis (not just the cookie). The session ID is passed via `request.state` from the auth dependency.
- **Session anomaly detection**: IP and user-agent changes are logged to the audit trail (even on Redis cache hits)
- **User deactivation**: All sessions immediately deleted from both DB and Redis. A `user_sessions:{user_id}` Redis set tracks all active session IDs per user for efficient bulk deletion.
- **Brute-force protection**: 5 failed attempts per 5 minutes, per IP + per username. Also applies to password change endpoint.
- **Account lockout**: After 15 failed attempts per username within 1 hour, the account is temporarily locked (returns 429 with Retry-After). This catches patient attackers who stay under the per-window rate limit. Configurable via `LOGIN_LOCKOUT_THRESHOLD` and `LOGIN_LOCKOUT_WINDOW`.
- **Constant-time verification**: bcrypt always runs against a dummy hash when the user doesn't exist (login) or on password change, preventing timing-based enumeration
- **Login attempt cleanup**: Records older than 90 days are pruned at startup
- **Password strength**: Common passwords (~200 entries including seasonal/year variants) and low-entropy passwords (< 4 unique chars) are rejected on setup, user creation, and password change
- **Frontend auth-check classification**: The SPA's startup `GET /api/auth/me` (`checkAuth()` in `frontend/src/lib/stores/auth.ts`) treats a 401 or 403 as "not logged in" and redirects to `/login` — 403 covers `get_current_user` returning "Account disabled" for a deactivated account, which is a permanent revocation, not a transient failure. A 429 (e.g. from the per-IP rate limiter below), a 5xx, or a network error is transient: the known session state is kept and the layout shows a retry-able error instead of forcing a logout. This prevents a fast-reloading browser or test harness from being logged out purely because it tripped the IP rate limit. Matches `probeResourceAuth` in `frontend/src/lib/stores/resourceSync.ts`, which already treats 401/403 alike.

## Authorization

Two-layer defense:

1. **Dependency-based auth** (`middleware/auth.py`): `get_current_user` is a FastAPI dependency that validates the session cookie, checks expiry/lifetime/active status, and renews the session. On Redis cache hit, validation uses cached data and TTL refresh replaces the DB write. On Redis miss or failure, falls back to the DB path (`SELECT ... FOR UPDATE` so an in-flight prune is not resurrected) and populates the Redis cache for subsequent requests.
2. **Endpoint** (`api.py`): Authenticated resource endpoints use `Depends(get_current_user)` and return 401 if unauthenticated. Public auth/setup endpoints are deliberately unauthenticated; worker control-plane routes under `/api/internal/*` use the internal token instead of sessions. Ownership checks enforce default-deny: access is blocked unless the resource belongs to the user (or the user is admin). Missing resources are denied.

Roles: `Literal["admin", "user"]` — validated at the Pydantic schema level. No other role values are accepted by the API. Demotion or deactivation of the last active admin is blocked to prevent lockout. When a user is deactivated or their role is changed, all their sessions are immediately invalidated.

Generation invalidation history is partitioned by `user_id` in PostgreSQL. Its
monotonic sequence allocator and event row participate in the same transaction as
the generation, with unique constraints on `(user_id, sequence)` and
`(kind, generation_id)`. Cursor and event rows cascade only with their owning user;
historical song/generation identifiers are intentionally not foreign keys. The
authenticated SSE endpoint reads only the exact authenticated user partition; admin
role does not bypass this filter and frames contain no user ID. Authentication and
the initial cursor reads finish in a function-local DB session before streaming
begins. Polls use independent short sessions, and every connection ends after at
most 60 seconds so deactivation or session expiry is enforced on reconnect.

## Proxy trust

`TRUSTED_PROXIES` is a comma-separated list of IP addresses and CIDR networks
(default: empty — no peer is trusted; the Docker deployment sets
`172.16.0.0/12`, the bridge-network range the tunnel's container gateway sits
in). `parse_trusted_proxies()` turns each entry into an `ip_network` at
startup, and a peer is trusted when its address falls inside one of them — so
`172.16.0.0/12` covers the gateway address `172.18.0.1`, and a bare
`10.0.0.1` covers only itself. An entry that is not a valid address or
network (including one with host bits set, like `10.0.0.1/24`) raises at
startup rather than being carried along as a rule that can never match. An
entry carrying an interface zone (`fe80::1%eth0`) is rejected too: a zone is
local to one host and is dropped when an address is matched against a network,
so the entry would silently widen to every interface.

Three behaviours hang off that decision, and all three are off when the peer
is not trusted:

- `X-Forwarded-For` is read for the real client IP (rightmost untrusted
  entry). Every per-IP budget, the login/lockout counters, the access log,
  and the session's bound IP key on that address; from an untrusted peer the
  header is ignored and the direct peer address is used.
- `X-Forwarded-Proto: https` marks the request as HTTPS, which is what sets
  `Secure` on the session and CSRF cookies.
- The same signal emits `Strict-Transport-Security`.

`auth.resolve_client_ip()` and `auth.request_is_https()` own both decisions;
no endpoint or middleware reads those headers itself. The chain is read from
the right, where our own proxies appended, and only what it says there can
become an identity:

- Every `X-Forwarded-For` header field belongs to one ordered list, so the
  fields are walked back to front too — reading only one of them would let a
  client hide hops in another.
- Starting at the newest hop, each entry a trusted proxy vouches for is
  stepped over; the first entry that is not trusted is the client. Entries
  further left are never read, so a client cannot change the answer by
  prepending its own: `garbage, 203.0.113.7` from the address `203.0.113.7`
  still keys on `203.0.113.7`. Reading left to right instead would let that
  client void the chain and spend the gateway's shared budget rather than its
  own.
- An entry that is not a plain IP address, right of the client, names nobody:
  `203.0.113.7, garbage` keys on the direct peer, because an empty string or a
  word like `garbage` must never become an identity that binds a session and
  buys a rate-limit budget.
- At most `MAX_FORWARDED_FOR_HOPS` (16) entries are read; a real chain here is
  three. Only the hops our own proxies appended are ever examined, so the
  public client cannot reach that bound — everything it writes lands left of
  the hop that decides. There is no bound on the chain's total length, because
  rejecting a long chain would hand a client exactly the peer-key escape that
  reading from the right removes.
- A long chain is cheap rather than forbidden: entries are cut out of the
  header field by index from the right, so a field carrying thousands of
  separators costs only the entries actually read, and text longer than
  `MAX_ADDRESS_CHARS` (45, the longest an address can be written) is refused
  without being handed to the address parser. Neither rule can change an
  identity — nothing they skip could have parsed as an address.
- Both fallbacks to the peer are logged at `WARNING`. They pool unrelated
  visitors into one budget, so they are a proxy misconfiguration to see rather
  than a silent default. The public client cannot trigger either one: behind
  Cloudflare → cloudflared → Docker the rightmost entry is always the one our
  own tunnel appended. A caller on the host itself can, because it reaches the
  server through the bridge gateway, which is a trusted pass-through hop and
  forwards the caller's own chain unchanged — so a line there means either a
  misconfigured proxy or a local caller, not a visitor from the internet.
- Addresses are canonicalized: `::ffff:203.0.113.9` and `203.0.113.9` are one
  identity, so nobody multiplies a budget by switching notation. An address
  carrying an interface zone is treated as no address at all.
- `X-Forwarded-Proto` is read by the same scan: only the rightmost value
  counts, so a client that prepends its own cannot outvote the proxy behind it,
  and a huge field costs no more than that one value.

`run_server()` passes `proxy_headers=False` to uvicorn. Uvicorn's own
forwarded-header handling would rewrite the peer address and the scheme before
any application code runs, from any peer unless its separate
`forwarded_allow_ips` is kept in sync with `TRUSTED_PROXIES` — two sources of
truth for one decision. `TrustedProxies` is the only owner. Uvicorn's default
`forwarded_allow_ips` is `127.0.0.1`, so this changes nothing for the Docker
deployment (the peer is the bridge gateway, `172.18.0.1`); a proxy that ever
reaches the server over loopback must be named in `TRUSTED_PROXIES` instead.

One consequence (#339): with proxy header rewriting off, `scope["scheme"]` —
and therefore Starlette's `request.base_url` — stays `http` for the whole
life of the Docker deployment, because the literal connection into the
container is never TLS; only `auth.request_is_https()` resolves the real
(proxy-forwarded) scheme, by reading the same trusted, verified
`X-Forwarded-Proto` this section describes. The four share endpoints
(album/song/generation/playlist) do not read either signal at request time:
building a public URL from a request is redundant when the public address is
a deployment-time fact, so they call `api_helpers.resolve_public_base_url()`
instead, backed by the validated `PUBLIC_BASE_URL` setting — see "Production
Deployment" below.

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
| Album | `/shared/{slug}` | `/shared/{slug}/audio/{file}`, `/shared/{slug}/cover` |
| Song | `/shared/song/{slug}` | `/shared/song/{slug}/audio/{file}`, `/shared/song/{slug}/cover`, `/shared/song/{slug}/album-cover` |
| Generation | `/shared/gen/{slug}` | `/shared/gen/{slug}/audio/{file}`, `/shared/gen/{slug}/album-cover` |
| Playlist | `/shared/playlist/{slug}` | `/shared/playlist/{slug}/audio/{file}` |

Album and song shares serve the picked unarchived generation when one exists, otherwise the latest unarchived generation. Generation shares serve the shared generation. Playlist shares expose audio only for playable entry generations. Shared stream manifests likewise contain only playable takes, so every listed audio URL is authorized to return bytes. `create_generation()` canonicalizes every non-empty MP3 path at the single write boundary and rejects a path that would leave the audio root; WAV-only takes retain their empty MP3 sentinel. Public JSON assembly builds URLs from those canonical stored paths without filesystem resolution. Operators must run `scripts/audit_generation_audio_paths.py` once before deploying this boundary to identify legacy rows. The audit never changes rows: each reported ID must be reimported when its source is known, or archived until its file identity can be established, because blindly normalizing an old filename can attach a take to the wrong recording. Public JSON responses omit scores and edit history; an audio URL is present only when its stored relative path is already canonical and remains below the audio root. A noncanonical stored path is a data defect: it is not silently repaired, is omitted from the response, and is logged at `WARNING`. Album JSON includes `cover` only while the album is shared and the cover file exists. Song JSON includes `cover` only while the song is shared and the **song** cover file exists. Song and generation JSON include `album_cover` only while their own share remains public and the parent album cover file exists. Public cover bytes are served through the matching album, song, or generation share slug — never a client-supplied path on `/audio/{owner_id}/{filename}`. Unshare, replace, or delete 404s the previous public cover URL. Share slugs are UUID v4 values (122 bits of entropy, unguessable). Sharing is revocable by the resource owner.

`audio_paths` owns stored-audio path resolution: queue-stream assembly uses
`resolve_audio_path()`, while the album, song, and playlist shared-audio
handlers validate the requested canonical filename and make their allowlist
decision with a scalar query before delivering bytes. A missing file, a
noncanonical filename, and a path that would escape the audio root (including
through a symlink) all return the indistinguishable visitor response `404 Not
Found`. Traversal rejection is logged at `WARNING` without the caller-supplied
path.

### Per-IP (global middleware)

Every request is subject to a global per-IP rate limit, split into three budget
classes (issue #257) so that one traffic pattern cannot exhaust the budget
another pattern from the same IP needs. `_classify_path` in
`middleware/rate_limit.py` is the single place that maps a path to a class;
every request gets exactly one class, and an unrecognized path falls back to
the API class — fail closed, not fail open. Each class is a Redis
sliding-window counter (`RedisRateLimiter`) over its own 60-second window and
its own key prefix, so exhausting one class's counter never touches another's.

| Class  | Paths | Default | Why |
|--------|-------|---------|-----|
| API    | Everything not matched below (including `/health` and unrecognized paths) | 120/min | Unchanged from the original single budget. `/health` is deliberately **not** exempt: it is the most expensive anonymous endpoint (a DB query plus roughly six Redis round trips for worker/queue state) and the only caller is the browser's 15s poll (~4/min) — exempting it would let an anonymous caller hammer the priciest endpoint for free. |
| Media  | `/audio/*`; `/api/queue-streams/{id}/audio`; every `/shared/**/audio/*` and `/shared/queue-streams/{id}/audio` route | 600/min | Range-request media playback is normal use, not abuse: a single MP3 played with normal seeking is **estimated** at roughly 40 range requests (order-of-magnitude from typical browser Range-chunking, not measured), and comparing takes can move through several songs a minute (40 × 5 = 200/min in ordinary use). 600 leaves headroom for aggressive seeking while still bounding an IP's disk I/O — not unlimited. All of these paths serve a `FileResponse` (Range-capable) — the public share audio routes carry the same seek/scrub pattern as the owner's own player, just from a stranger listening to a public share, so they get the same class. `_classify_path` matches each share-audio route with a regex anchored on the literal `audio` segment at the position that route defines, so a slug that literally reads `audio` cannot pass as one by shape alone. The metadata routes on the same slug — `/shared/{slug}`, `/shared/song/{slug}`, `/shared/gen/{slug}`, `/shared/playlist/{slug}`, every one of their `/cover` routes (song and album cover are both API, deliberately, not just the album one), and the `/stream` manifest POSTs — are deliberately excluded and stay API: only the byte-serving audio routes are Range-served. |
| Stream | `/api/resource-events/stream`, `/api/jobs/*/stream` | 45/min | SSE connection *opens*, not per-message traffic, sized between the legitimate worst case and the observed storm rate. Legitimate worst case: a normal page load opens one resource-events stream plus one job stream per active job; at the `max_user_active_jobs` default (10) that's 11 opens/load, and 3 page loads within a minute (full queue, operator reloads) is 33. Storm rate: the operator incident's reconnect storm ran at roughly 80 opens/min. It self-terminates, but not via a backoff -- there isn't one yet (that is the still-open #257 frontend slice); `MAX_POLL_ERRORS` (`frontend/src/lib/stores/jobs.ts`) is a plain error counter with no delay that closes the `EventSource` after 10 failures, and a 429 response to an `EventSource` is fatal per spec (no browser auto-reconnect), so the burst is short-lived either way. 45 sits clearly above 33 and clearly below 80 — there is no live dependency on `max_user_active_jobs`; raising that setting should prompt re-checking this math, not a settings cross-reference. The resource-events endpoint additionally enforces its own tighter per-user open limit (`RESOURCE_EVENT_STREAM_OPEN_LIMIT`, see below). |

Before this split, all three traffic patterns shared one 120/min bucket:
a player streaming range requests plus a few reconnecting SSE streams could
exhaust it in seconds, after which *every* request from that IP was rejected
— including the audio that was already playing (issue #257: 5035 rejected
responses in one operator session). The same bucket also gated a stranger
listening to a public share: a share page is the operator's public face, so
a listener range-requesting a shared album must not be locked out by
unrelated API traffic from the same IP either.

The public share audio routes are Media-classed at the *global* per-IP
layer, but the dedicated shared-endpoint limiter described above
(`SHARING_RATE_LIMIT`, 60/min) still runs *inside* the same endpoint handlers
and is the one that fires in practice, since it is far tighter than the
600/min Media budget. The two layers are not redundant: the global Media
class exists so a share listener isn't punished for unrelated traffic
sharing their IP (the regression this section fixes), while
`SHARING_RATE_LIMIT` remains the actual anti-abuse ceiling on anonymous share
traffic, unchanged by this split.

Static `_app/` build assets and the static PWA root assets (`/manifest.webmanifest`, `/robots.txt`, `/favicon.svg`, `/icon-192.png`, `/icon-512.png`, `/service-worker.js`) are exempt from all three budgets — they're fetched by the browser and the service worker outside of user-driven navigation and would otherwise crowd out real calls from the same IP.

When the request arrives from a peer inside a `TRUSTED_PROXIES` network, the rate limiter uses the real client IP from `X-Forwarded-For` (rightmost untrusted entry), matching the login rate limiter's behavior — see "Proxy trust". Without it every visitor behind the same proxy shares one budget. If Redis is unavailable, the rate limiter fails closed (returns 503 with `Retry-After: 5`) rather than allowing all requests through.

Configure via env vars: `LOGIN_RATE_LIMIT`, `LOGIN_LOCKOUT_THRESHOLD`, `LOGIN_LOCKOUT_WINDOW`, `GENERATION_RATE_LIMIT_USER`, `GENERATION_RATE_LIMIT_ADMIN`, `SCORING_RATE_LIMIT_USER`, `SCORING_RATE_LIMIT_ADMIN`, `CHAT_RATE_LIMIT_USER`, `CHAT_RATE_LIMIT_ADMIN`, `MAX_QUEUE_DEPTH`, `IP_RATE_LIMIT`, `MEDIA_RATE_LIMIT`, `STREAM_RATE_LIMIT`, `RESOURCE_EVENT_STREAM_OPEN_LIMIT`.

### Resource-event streams

The global IP limit is supplemented by a fail-closed per-user opening limit,
`RESOURCE_EVENT_STREAM_OPEN_LIMIT` (default 12 streams per minute, unchanged
in production); rejected attempts are not retained in the bounded Redis
window. CI overrides it to 200 in `docker-compose.ci.yml`, the same shape as
`IP_RATE_LIMIT`'s own override — the e2e suite reuses one seeded user across
every browser context, so its stream opens are additive against this one
per-user budget in a way real production traffic across many users never is.
Redis leases cap live streams at six per user and at most 12
globally, reduced automatically when the configured DB pool has less spare capacity.
If reserving one non-stream DB slot leaves no capacity, stream admission returns 503.
Acquire is one Lua operation across user and global sorted sets; UUID lease members
carry absolute expiry scores and release targets that exact token on disconnect. A
crashed process cannot retain a slot beyond 65 seconds. Lease release runs off the async loop; the
Redis client bounds connect and socket waits to two seconds, with expiry as the final
fallback. Redis failure returns 503 rather than opening an unbounded poller.

### Job streams

`GET /api/jobs/{id}/stream` polls a job's status once per second. It used
to do that with blocking psycopg2 calls directly on the event loop — one
waiting generation meant one blocking round trip per second on the loop,
and an exhausted DB pool could stall it for up to 30 seconds. The poll now
runs through `asyncio.to_thread()`, bounded by `asyncio.wait_for()` to the
stream's remaining lifetime so a poll cannot itself outrun the deadline by
waiting on an exhausted pool, matching the resource-event stream's
`_read_event_page_before` pattern exactly.

The endpoint also takes **no request-scoped `Depends()` at all** — matching
`api_stream_resource_events` exactly, not just in spirit. A first attempt
(review 2026-09-01) only dropped `Depends(get_db_session)` from the
endpoint's own signature but kept `Depends(get_current_user)`; a second,
independent review (2026-09-02) found that `get_current_user` itself takes
`Depends(get_db_session)`, and FastAPI keeps a yield dependency open until
the whole *response* finishes — for a `StreamingResponse` that's the full
stream lifetime, so the connection was still pinned one level up (measured:
`enter=1, exit=0` after the first body chunk, `exit=1` only once the stream
closed). `api_stream_job` is now a plain (non-`async`) `def`, so FastAPI
thread-offloads the whole handler body, exactly like
`api_stream_resource_events`; auth (`get_current_user(request, session)`)
and the access check run as plain function calls against one short-lived
`ctx.db()` session that closes before the lease is acquired or the
`StreamingResponse` is even constructed, and every poll opens and closes
its own short-lived session the same way. No open job stream pins a pool
connection for longer than one query, at any point in the request.

The stream has the same kind of bounded lifetime as the resource-event
stream: a 60-second wall (`JOB_STREAM_CONNECTION_SECONDS`) after which it
closes; the frontend's `EventSource` reconnect with backoff (`jobs.ts`)
already handles the drop and resets its retry count on the next message. A
Redis lease (`RedisConcurrentLeaseLimiter`, the same class the
resource-event stream uses) caps concurrent job streams per user
(`job_stream_lease_max_per_user`, default 10 — matches
`max_user_active_jobs`) and globally (`job_stream_lease_max_global`,
default 40). Unlike the resource-event lease, this one is not sized against
spare DB pool capacity — precisely because no job stream holds a pool
connection for its lifetime, there is no pool share to compute. It is a
flat, hard concurrency cap against a runaway client opening far more
streams than any real page load does. Redis failure fails closed (503),
matching the resource-event lease.

## Security Headers

All responses include:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; connect-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self' https://fonts.gstatic.com; frame-ancestors 'none'`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains` (HTTPS only; `X-Forwarded-Proto` only honored from a peer inside a `TRUSTED_PROXIES` network)
- `Cache-Control: no-store` (API responses only — prevents caching of authenticated data). The exact resource-event SSE path uses `no-cache, no-store` so intermediaries do not cache or transform its reconnect stream; other API and SSE paths retain `no-store`.

## CORS

- **Methods**: `GET`, `POST`, `PUT`, `DELETE` (no wildcard)
- **Headers**: `Content-Type`, `Cookie`, `X-CSRF-Token` (no wildcard)
- **Credentials**: Allowed
- **Origins**: Configurable via `CORS_ORIGIN`. Wildcard origins must be `*.domain.tld` format (e.g., `*.trycloudflare.com`) — bare TLDs like `*.com` are rejected at startup. Defaults to `localhost`/`127.0.0.1` on ports 8080 and 5173 only for dev (not any arbitrary port).

## Error Handling

- **Generation, scoring, and LoRA job errors**: `_sanitize_error` maps known worker and setup doses to fixed musician-facing messages and logs raw failures with the job ID only on the server; generation, scoring, and LoRA store that returned message in `job.error` (`jobs/_runtime.py:38-45,62-78`; `jobs/generation.py:473-483`; `jobs/scoring.py:194-213`; `jobs/lora_training.py:506-515,618-631`). Raw reasons live in the service's JSON container log, retained as five rotated 10 MB files.
- **API errors**: HTTPException messages on ordinary validation paths are human-readable strings with no internal paths or stack traces (`settings_api.py:463-467`, `chat_api.py:266-269`); the model-catalog failure path now uses a fixed message (`settings_api.py:577-578,658-659`; #476 closed).
- **Validation errors**: The custom `RequestValidationError` handler returns only affected field names, not full Pydantic error details (constraints, expected types, internal schema) (`server.py:273-290`).
- **ACE-Step errors**: Worker failures map through `_sanitize_error` to a fixed message before the generation job persists `job.error`; only the silent-stream dose stays distinct (`jobs/_runtime.py:38-45,62-78`; `jobs/generation.py:469-480`).
- **Claude CLI errors**: Chat paths log the exit code and stderr length, not stderr itself (`claude/provider.py:297-305,1829-1835,1889-1895`). The live co-writer emits an SSE event with `status: 503` and `<provider> is currently unavailable` on an otherwise HTTP 200 response (`conversation_api.py:556-564,620-625`), while the legacy chat endpoint returns HTTP 503 with `Claude is currently unavailable` (`chat_api.py:266-269`). The model catalog passes the fixed HTTP-facing dose through the catalog adapter after #476 closed (`cowriter/catalog.py:443-447`; `settings_api.py:570-578,651-659`).
- **OpenAPI/docs**: Disabled (`server.py:167`).

## Request Size Limits

Songmaker itself enforces these limits: `BodySizeLimitMiddleware` (raw ASGI) first checks `Content-Length` for fast rejection, then wraps the receive channel to count bytes as they stream in — aborting with 413 once the limit is exceeded without buffering the entire body.

JSON API requests are capped at 1 MiB (`MAX_REQUEST_BODY_BYTES`). Large multipart uploads use a path-exact allowlist, not a suffix match:

| Path | File budget | Multipart body budget |
|---|---|---|
| Default JSON | — | 1 MiB |
| `POST /api/audio/upload` | 50 MiB per file | 50 MiB + 1 MiB envelope |
| `POST /api/loras/{lora_id}/samples` | 50 MiB per file | 50 MiB + 1 MiB envelope |
| `POST /api/songs/{song_id}/reimport` | two audio files | 100 MiB + 1 MiB envelope |
| `POST /api/albums/{album_id}/cover` | 8 MiB per image | 8 MiB + 1 MiB envelope |
| `POST /api/songs/{song_id}/cover` | 8 MiB per image | 8 MiB + 1 MiB envelope |

File limits and body limits are separate so a legal 50 MiB file is not rejected for multipart headers. `POST /api/loras/{id}/samples/{sample_id}` is not a large-upload path.

### Reference audio upload

`POST /api/audio/upload` accepts audio files (.mp3, .wav, .flac, .ogg) up to 50 MB. Files are stored in `{audio_dir}/{user_id}/refs/{uuid}.{ext}` — the UUID filename prevents name collisions and path injection. The `reference_audio_path` field on `GenerationParams` is validated at three levels:

1. **API validation**: Pydantic validator rejects any value containing `..`
2. **Song write**: the path must resolve under `{audio_dir}/{authenticated_user_id}/refs`
3. **Job execution**: the same owner-root resolver runs again; a foreign, symlink, or missing path fails the job instead of falling back to no reference

### Album and song cover upload

`POST /api/albums/{album_id}/cover` and `POST /api/songs/{song_id}/cover` accept JPEG and PNG only (SVG and WebP are rejected). The server checks magic bytes, decodes with Pillow, applies EXIF orientation, and strips metadata before writing. Named pixel and byte ceilings reject decompression bombs. Card and detail derivatives are written at upload time; GET never resizes. Album files live at `{audio_dir}/covers/{album_id}/`; song files live at `{audio_dir}/song-covers/{song_id}/`. Authenticated GET/POST/DELETE use `check_album_access` / `check_song_access` (foreign resources 404). Authenticated and public song cover endpoints stream only that song's files — 404 when the song has no own cover, even if the parent album has one. Public bytes use the matching share slug. The song-cover body budget is the cover ceiling; it is not the `/api/songs/{id}/reimport` ceiling.

Album cover suggestions are private rows bound to an album and its cover job. Every suggestion endpoint applies `check_album_access`; missing, foreign, malformed, and unsafe stored paths return the same 404 response. A suggestion path must equal `cover-suggestions/{album_id}/{suggestion_id}.png` under the audio volume, and selection passes the validated PNG through the existing album-cover writer. Suggestions have no public or share URL. Discard deletes database rows before their files, while album hard-delete removes the sibling suggestion tree after commit; neither action removes the selected `cover_key` image. The music worker selects the Codex CLI path only through the co-writer dispatch owner and never falls back to an HTTP image API. Each image call receives a new private `CODEX_HOME` containing only a copied login mirror; the bounded runner gets that path through its child-only environment, reaps the CLI, then accepts exactly one PNG found beneath that private tree. The image command uses the fixed read-only image argv with Code Mode host enabled only for that run, no MCP servers, and web search disabled. Its streamed-event gate permits `image_gen` and exactly one measured `command_execution` start/completion pair that reads the bundled image skill; any other command or tool event fails the job with the fixed image-tool message. Pillow rewrites its exactly one accepted PNG as a metadata-free 1024×1024 RGB PNG. The stdin-only prompt quotes album values as data, limits each track's style and lyrics excerpts to 500 characters, and limits the complete prompt to 6,000 characters.

All Codex text and cover CLI calls use one process-wide admission pool. `CODEX_CLI_MAX_CONCURRENT_PROCESSES` caps every reserved, running, and unreaped Codex process (default 8); `COVER_MAX_CONCURRENT_RUNS` additionally caps cover processes (default 1). A slot is reserved before spawn, bound only by the bounded runner's spawn callback, and released only by its reap callback. A call whose caller deadline expires before a delayed spawn therefore remains admitted until that late process is reaped; zombies cannot grow the pool. The Co-Writer uses the server-owned text tool protocol, never Codex CLI tool permissions: every start and resume gets the read-only sandbox, `approval_policy="never"`, no shell tool, no web search, and no MCP servers. Its event gate aborts on every file, command, MCP, or web-search event before the process is reaped. Saturated Co-Writer calls return the named busy route error, and saturated cover jobs retain the musician-facing “Codex is busy. Try generating the cover again shortly.” error.

**Deployment boundary**: This repository ships no reverse-proxy service or configuration (nginx, Caddy, Traefik, and tunnel configuration are absent). An operator who puts a proxy in front of Songmaker may add equivalent path-specific limits to reject oversized requests at the edge; those limits are defense in depth, not the application's only body limit. A blanket 1 MiB upstream limit would block the documented audio-upload and cover routes. The missing in-repository edge configuration is recorded in #327.

## Response Compression

`SelectiveGZipMiddleware` (`middleware/gzip.py`, mounted just inside the outermost `ResourceStreamDeadlineMiddleware`) gzips a response only when it is status 200, carries no `Content-Range`, and its `Content-Type` matches an explicit allowlist (`application/json`, `text/*` except `text/event-stream`, `application/javascript`, `application/manifest+json`) at or above `GZIP_MINIMUM_SIZE_BYTES` (1 KiB) — never `audio/*`, `image/*`, `video/*`, `application/octet-stream`, or any other binary media, and never a byte-range response. `Accept-Encoding` is parsed as real RFC 9110 q-values (`gzip;q=0` is honored, not compressed) rather than a substring check, and `Vary: Accept-Encoding` is set on every eligible response regardless of whether this particular client asked for gzip, so a downstream cache never serves one client's (un)compressed copy to another. `text/event-stream` (the co-writer chat and job-progress SSE endpoints) is on the never-compress list, so those responses pass through unbuffered, one ASGI send per source chunk. When a response is compressed, `Accept-Ranges` is deleted from it (matching nginx's own gzip behavior) since byte offsets into the compressed stream no longer correspond to the original bytes. Compression level is `GZIP_COMPRESS_LEVEL` (6, zlib's own default) — level 9 saves under a percentage point more reduction for roughly 3x the CPU per request.

## Request Timeout

`REQUEST_TIMEOUT` (default 30s) is Uvicorn's `timeout-keep-alive`: Songmaker closes an *idle keep-alive connection* after that period. It is not a general request deadline. This repository ships no reverse proxy, so it provides no proxy-level request timeout; an operator who deploys one owns any upstream timeout policy. The absence of that in-repository edge policy is recorded in #327.

The resource-event SSE has its own monotonic 60-second wall. DB polling runs outside
the async event loop, is awaited only for the remaining wall time, and no DB session
spans an SSE yield or sleep. The response applies the same wall around ASGI sends, so
a slow reader cannot keep the socket or lease alive after the deadline. The endpoint
emits 15-second comment heartbeats so a correctly configured proxy sees activity
before the deliberate reconnect. The library page's native EventSource probes
`/api/auth/me` on `onerror`; 401/403 stop the stream and clear auth, and logout
closes the owner before the logout request.

The job-progress SSE (`/api/jobs/{id}/stream`) has the same monotonic 60-second wall
and off-loop, deadline-bounded DB polling, and the same 15-second comment heartbeats.
It does not have the resource-event stream's outer ASGI-level send wall
(`ResourceStreamDeadlineMiddleware` governs only the resource-event path) — a reader
so slow its TCP window blocks the next `send()` can still hold the connection past
the in-generator deadline check. This gap is narrower than it looks: the endpoint
takes no request-scoped `Depends()` at all (neither `get_db_session` nor
`get_current_user`, which itself takes `get_db_session` — see "Job streams" above)
and no poll holds a DB session across a `send()` or a sleep, so a stuck slow-reader
`send()` pins neither a pool connection nor a blocked thread — only the ASGI
connection itself, capped in turn by the Redis lease's concurrent-stream ceiling. This
remaining send-side gap is tracked by #331.
Two earlier attempts (2026-09-01 and 2026-09-02) still had a `Depends()`-held
session somewhere in the request -- first directly, then one level up through
`get_current_user` -- and each would have let this same slow-reader gap also pin a
pool connection for as long as the reader stayed stuck, which is why the lease's
own sizing docs (see "Job streams" above) depend on this fix, in its final form,
being in place.

## Claude Chat Security

- **System prompt**: Hardcoded server-side (`SYSTEM_PROMPT` in `chat_api.py`). Clients cannot override it. Song context is wrapped in `<song_context>` XML tags with an untrusted-data notice instructing Claude to ignore instructions inside tags.
- **Multi-turn history**: Stored in `chat_messages` and scoped to a conversation; the co-writer applies a token budget with a rolling summary for older messages (`conversation_api.py:477-503`; `cowriter/history.py:65-76,89-144`). Ownership is enforced via `check_song_access()` on every endpoint.
- **Context built server-side**: Mentioned song/version IDs are sent by the frontend, but the backend resolves them from the DB — the client never sends raw context. Each mentioned song is ownership-checked.
- **CLI backend, every call shape**: `_build_mcp_cli_cmd()` (the co-writer, MCP tools attached) and `_build_cli_cmd()` (the legacy `/songs/{id}/chat` endpoint and the lyrical-coherence judge, no tools at all) both apply `--tools ""` (removes the CLI's entire built-in tool set, so a tool a future Claude Code version ships cannot be called even though nobody here has heard of it), `--setting-sources ""` (drops any profile `~/.claude/settings.json`, whose `permissions.allow` and `defaultMode` would otherwise decide what a session may do), `--strict-mcp-config` (ignores MCP servers configured anywhere but in the temporary config we write, when one is attached at all), and `--disable-slash-commands` (the CLI otherwise still resolves its own slash commands and skills from a prompt beginning with `/`; our own prompts never do, but this closes the channel rather than relying on that). The co-writer additionally gets `--allowedTools mcp__songmaker__*`, pre-approving our own MCP tools so the non-interactive session never waits for a permission answer nobody is there to give. No `--disallowedTools` list is kept, and `--permission-mode bypassPermissions` is gone from both — with nothing but the allowlisted tools present, there is nothing left to bypass. The two builders themselves check nothing — they format flags — which is why the next bullet is a separate mechanism, not a property of these functions.
- **Tool-surface verification, one gate per call shape, not per caller**: `_build_cli_cmd()` is reached only through `_call_cli()`/`_acall_cli()`, and those two call `verify_no_builtin_cli_tools()`/`averify_no_builtin_cli_tools()` themselves before building anything — so `chat_api.py`'s legacy endpoint and the lyrical-coherence judge are covered by the same gate without either having called it themselves (#351). `_build_mcp_cli_cmd()` is reached only through the two MCP-attached entry points (`acall_claude_with_mcp`/`acall_claude_with_mcp_stream`), which call `verify_cli_tool_surface()` themselves the same way — a separate gate, not routed through `_call_cli()`/`_acall_cli()`. On a cache **miss**, the CLI is a bind-mounted binary that updates itself, so the relevant gate starts a session with exactly the flags above and reads the tool names — and the `slash_commands` list — out of the CLI's own `system` init event (`subtype` checked too, not just `type`); a cache **hit** returns the remembered verdict without starting a session at all. The co-writer's probe attaches the real `--mcp-config` and requires the reported tool set to equal, exactly, the eleven `mcp__songmaker__*` names — a hand-maintained literal tuple in `provider.py`, not imported from `mcp_server/server.py` (that would pull the `mcp` package into containers that do not carry it), kept honest by a test that compares the two — not merely a subset check, so a tool going missing is caught the same way an extra one is, but an unexpected tool or a reachable slash command is *always* a permanent mismatch regardless of whether the MCP connection itself came up (a CLI reporting `tools=["Bash"]` with its MCP connection also down is confirmed dangerous, not merely unverifiable). The tool-free probe requires no tool and no slash command at all, and deliberately never attaches `--mcp-config`: registering and listing MCP tools touches no database (only a tool *call* does), so that is not why this probe stays separate — it needs the `mcp` extra, which the scoring-worker container does not install; that container does have a reachable database (it writes scores back to it), so the database is not its actual gap (confirmed live: a missing `mcp` package makes the MCP connection fail, and a failed connection reports zero tools, the same shape a clean tool-free CLI reports).
  A mismatch raises `CliToolSurfaceError` and only that call is refused, not the whole server — but a failed MCP connection with nothing else wrong is not a mismatch: it is treated as a probe failure (see below), because it reports the same empty tool list a clean, intentionally tool-free CLI would, and confusing the two used to cache "all eleven missing" forever. A genuine verdict — this build's tool surface, clean or not — is cached per resolved binary build (path, size, mtime) with no expiry, since it only changes when the build does. A probe **failure** (timeout, unparseable output, or a failed MCP connection with nothing else unexpected) is cached separately, only for `CLAUDE_CLI_TOOL_SURFACE_FAILURE_CACHE_SECONDS`. A process that outlives SIGKILL is a third case, checked before parsing, the MCP check, or the verdict ever run — a clean read followed by a zombie is not trusted either. Not a verdict about the build (the build is fine; this one instance is stuck) and not an ordinary failure either — ten more seconds will not make it healthy — so it gets the much longer `CLAUDE_CLI_ZOMBIE_FAILURE_CACHE_SECONDS` instead, so the ordinary retry schedule cannot spawn a fresh zombie every ten seconds.

  Single-flight is a *published future*, not a held lock (round 5 — rounds 3 and 4 held a per-key mutex across the whole probe and spent two rounds finding a new unbounded wait inside it). The dict lock only ever guards a lookup/insert; the first cold caller for a key publishes an `asyncio.Future` (the async gates) or `concurrent.futures.Future` (`_call_cli`'s sync gate) under that lock, releases it immediately, and probes with nothing held at all, while every later caller for that key awaits the published future with its own timeout — proven with genuine concurrency (`asyncio.gather`, real threads) and an explicit "the follower reached its wait" signal, not a sleep loop or a timed `join()` guess; the future is always resolved (success, probe failure, or a bug evaluating the result), so the dict entry is never left dangling, and a cancelled leader hands followers a normal `UnavailableError`, never its own literal `CancelledError`. A sync and an async caller for the same key still do not exclude each other, since a thread future cannot be awaited without blocking the loop and an asyncio future cannot be waited on from a thread without one — an accepted, narrow gap given the only key both domains ever share is the no-MCP one.

  Tool-surface probes use the single bounded process layer, `agent_cli.run_cli_bounded`, for spawn, bounded stdin/stdout exchange, output limits, and process-group cleanup. The sync gate calls it directly; the async gate reaches that same gate via `asyncio.to_thread`, keeping a stuck spawn off the event loop without a third probe-specific thread. `claude/provider.py` keeps the policy around that runner: per-build verdict/failure cache, ordinary and zombie TTLs, single-flight, and the shared Claude process pool. It reserves a slot before invoking the runner, binds it in `on_spawned`, and releases it only in `on_reaped`; a `DEADLINE_BEFORE_SPAWN` may return while a later spawn is still live, so its result must never release that reservation. A `became_zombie` outcome wins before parsing the init event, receives the zombie TTL, and blocks a new process when the shared pool is full. The gate resolves the CLI's symlink once, at probe time, and hands that literal path back for the real turn to run — so a self-update landing between the probe and the turn cannot execute a build that was never checked.
- **What the probe does not guarantee**: reading the `system` init event and then killing the session bounds but does not eliminate a probe's API cost — the full probe prompt is already on the wire by the time that line arrives, so a request already in flight is not excluded. The CLI's own `--max-budget-usd` was checked live against 2.1.257 and only aborts a session *after* a call completes, not before one starts, so it does not close that gap either; no flag in this CLI version does.
- **API backend**: Uses the Anthropic Python SDK with `max_tokens=1024` to limit response cost.
- **A drifted tool surface never fails server startup** (operator ruling, round 6): #351 literally asked for an unknown tool to fail the boot, but once the gate above was confirmed to cover every call path, a server that refuses albums and playback over a co-writer problem is a worse outage than the co-writer being unavailable. `lifecycle.report_claude_cli_tool_surface()` probes at boot, logs the result, and returns `"ok"` (verified clean), `"drift"` (verified, a real mismatch), or `"unverified"` (the probe could not reach a verdict at all — never silently reported as `"ok"`, the exact silent-default shape `check_no_silent_fallbacks.py` exists to catch); that state lives as a live value in `claude/provider.py` (`claude_cli_tool_surface_health()`), updated by every `verify_cli_tool_surface()` call — cache hit or fresh probe alike — not captured once at boot, so a later verdict overrides an earlier one instead of staying stuck at whatever booted; `GET /health` reports it under the same field name, so the state reaches monitoring and the operator, not only the first musician who opens a chat and finds it broken. Nothing polls in the background: the value only changes when the gate itself runs again, so if the CLI disappears without a fresh probe following it, `/health` keeps reporting the last verdict until the next call to the gate. `tests/test_lifecycle_claude_tool_surface.py` and `tests/test_health_api.py` pin the boot report and the live `/health` field across all three states; that a co-writer turn is actually refused on drift is proven separately, in `tests/test_claude_provider.py`'s `test_cowriter_turn_refuses_a_cli_with_an_unverified_tool_surface` and `test_cowriter_non_stream_turn_refuses_a_cli_with_an_unverified_tool_surface`.
- **Legacy endpoint**: `POST /api/songs/{id}/chat` (`chat_api.py`) has no caller left — not the frontend, not the CLI, not a test outside its own suite. The live co-writer chat is `POST /chat/turn` in `conversation_api.py`. It is gated the same as every other tool-free call above, but it is a public endpoint, so removing it outright needs the operator's word, not a decision made in this file.

## Agent-CLI Mounts

`songmaker-web` mounts the Claude, Grok, and Codex binaries and redacted
credential mirrors read-only. The music worker mounts the Codex binary and
redacted credential mirror read-only because it executes private cover jobs.
The scoring worker mounts only Claude's binary and credential mirror; it does
not mount Grok or Codex (`docker-compose.yml:246-259`).

`scripts/mirror_agent_cli_credentials.py` publishes a **redacted copy** of each
login into `~/.songmaker/agent-cli-credentials/`, kept current by
`songmaker-cli-credentials-mirror.{service,path,timer}` and installed with
`scripts/install-cli-credentials-mirror.sh`.

Grok access tokens expire after six hours. Issue #350's host-side mirror
service, path watcher, and ten-minute timer are the sole refresh path: each
host refresh replaces the mounted access token in place while keeping
`refresh_token` empty. A Grok CLI turn with an expired or OIDC-rejected mirror
returns `cli_login_expired`; it never changes to the API-key path mid-turn.
Its single-turn command passes `--deny '*'`, a permission rule, plus
`--max-turns 1`; neither proves that the CLI exposes no built-in tools. The
streaming parser loudly rejects every reported `tool_call` or
`tool_call_update`, so Songmaker refuses that turn after the CLI reports a
tool call. The 2026-09-03 `Antworte nur OK` experiment without `XAI_API_KEY`
still emitted `available_commands` events with built-in tools and no
`tool_call`; it does not exclude a tool execution before such an event. R1
does not add `--disallowed-tools` as a substitute for that reported-event
gate.

Codex uses its mirrored `tokens.access_token` only when it is a nonempty
string; an absent or tokenless mirror selects the existing `OPENAI_API_KEY`
path, while an unreadable or malformed mirror fails as `codex_cli_error`.
The host remains the only refresh owner: the mounted Codex document keeps
`tokens.refresh_token` empty. A selected Codex CLI route never changes to HTTP
within that turn; an expired login is `cli_login_expired` and other CLI
failures retain the named Codex error.

Codex has a resumable Co-Writer tool loop and a fixed cover-image command. The
Co-Writer begins with `codex exec --json --sandbox read-only`; later rounds use
`codex exec resume`. Both command shapes apply `--skip-git-repo-check`,
`--ignore-user-config`, `--ignore-rules`, `approval_policy="never"`,
`mcp_servers={}`, disabled shell, unified-exec, browser, computer, multi-agent,
image-generation, plugin, hook, and Code Mode features, and disabled web search.
They deliberately omit `--ephemeral`: the CLI's persisted, server-issued thread
is required for the next `resume` round. The transport runs from an empty private
`work/` directory beside its private `codex-home/`, requires a UUID from
`thread.started` before it can resume, and passes prompts only on stdin. The
cover-image command also uses a read-only sandbox, but enables `code_mode_host`
only for that image run and adds `web_search="disabled"`; its only permitted Code
Mode command is the measured read of the bundled image skill. Each receives the
runner's secret-scrubbed environment, so `OPENAI_API_KEY` is never inherited.

The Co-Writer JSONL gate refuses every native Codex command, MCP, web-search,
file-change, or other non-text tool item. Completed assistant text is parsed as
Songmaker's textual tool protocol; the shared server loop executes the owned
Songmaker operation and supplies its result in the next CLI resume round. Unknown
or malformed items are `codex_cli_stream_protocol_error`. Only a completed
`error` item is a named CLI failure when no completed turn follows; an error item
that is started or updated remains a protocol failure. Event payloads, prompts,
and stderr are not logged; failure logging contains only the return code and
stderr length. `approval_policy="never"` means auto-approval within the sandbox,
not that tools cannot run, so the transport's reported-event gate and the shared
tool loop remain the execution boundary.

**The renewal secret never leaves the host.** The mirror publishes the
short-lived access token and blanks the long-lived one, so whatever eventually
reads a copy can spend what it holds until it expires but cannot mint a new
one. What each CLI tolerates was measured on 2026-09-02, each variant run in a
throwaway container against the real binaries:

| CLI | what the mirror publishes | measured |
|---|---|---|
| claude | an **allowlist**: `accessToken`, `expiresAt`, `scopes` — nothing else | `accessToken` + `scopes` is the whole requirement; dropping `scopes` alone flips `claude auth status` to `loggedIn:false`. Without `refreshToken` a full turn runs unchanged. |
| grok | the document, with `refresh_token` blanked and the four personal fields dropped | its CLI needs every other field (dropping `create_time` alone yields "You are not authenticated"), but tolerates a blank refresh token and the loss of `email`, `first_name`, `last_name`, `profile_image_asset_id`. |
| codex | the document, with `tokens.refresh_token` blanked and `OPENAI_API_KEY` nulled | the refresh field may not be absent ("missing field `refresh_token`") but may be empty; `id_token` must stay a well-formed JWT. |

The two shapes are not an inconsistency. Claude's allowlist cannot leak: a
field added tomorrow is simply not carried. Grok and Codex must carry their
whole document or their CLI refuses it, so for those two **an unknown field
stops the mirror with a named error** instead of being copied — a CLI update
introducing `device_refresh_token` would otherwise ride along unnoticed.

**How it writes.** In place: one write into the existing inode, never a
rename, because a file bind-mount is pinned to the inode it was made from and
would not follow a rename. It never truncates — shorter content is padded with
trailing spaces, which every JSON reader ignores — and it reads the bytes back
through the same descriptor before reporting success. That is not a universal
atomicity guarantee and is not claimed as one: on ext4 and xfs a *completed*
buffered write is serialised against a concurrent read, a retried short write
is the one window, and a reader using `mmap` can still straddle the change.
Two runs cannot overlap: the second waits for an `flock` and, if it never gets
it, fails rather than reporting success.

**How it refuses.** Every path is opened with `O_NOFOLLOW` and checked on the
open descriptor before it is read or written: a regular file, owned by us,
with exactly one hard link, and no larger than a login document can be — a
file too big to read in full is refused rather than judged on its first bytes,
and a target that had somehow grown is refused rather than padded back out to
its own size. `O_NOFOLLOW` covers the last path segment; a symlink somewhere
in a parent directory is followed, which is why the mirror directory is
required to be ours and `0700` before anything in it is touched. It is created
`0700` rather than chmodded afterwards. A mirrored file's mode is *set* to
`0600` when it is written and *required* to be `0600` when it is verified; the
difference is deliberate, since the writer owns that file and the verifier only
inspects it.

`scripts/check_agent_cli_mounts.sh` is the preflight: it calls
`mirror_agent_cli_credentials.py --verify`, which applies those same checks to
each published file, parses the JSON, and refuses any non-empty value under a
renewal-token key found anywhere in it — so a login copied in by hand is
caught rather than mounted. It also asks systemd whether the mirror service,
its login watch and its timer are installed and enabled, whether the two
triggers are running, and whether the service itself has failed: files that
look right prove nothing about currency if what rewrites them has been
erroring out since yesterday. The service is not required to be *active* — a
finished oneshot is legitimately inactive.

`SONGMAKER_CLAUDE_CLI`, `SONGMAKER_GROK_CLI`, and `SONGMAKER_CODEX_CLI` take
effect only when exported in the deployment environment, not when written only
in `.env`: the preflight reads its values from the exported environment and
does not load `.env`. For systemd boot and auto-deploy, these non-secret paths
therefore belong in the persistent service environment. Compose currently
mounts `SONGMAKER_CLAUDE_CLI`, `SONGMAKER_GROK_CLI`, and
`SONGMAKER_CODEX_CLI` into `songmaker-web`; the Codex binary and redacted
`codex.json` mirror are also mounted read-only into `songmaker-music-worker`.

**Boot coupling.** `songmaker.service` has both `Requires=` and `After=` on
`songmaker-cli-credentials-mirror.service`, then runs the argumentless
preflight as `ExecStartPre` from the main checkout. A failed or absent mirror
means `songmaker.service` does not run its boot-time `docker compose up -d`:
the boot catch-up stays off; a red preflight fails the unit and alerts through
`OnFailure=`, while a missing or failed mirror aborts the start job as a
dependency failure (journal: result 'dependency'), which is not covered by
`OnFailure=`. Containers dockerd restarts itself under `restart: unless-stopped`
are unaffected. The two-minute deploy tick runs that same argumentless
preflight, so boot and deploy resolve the same mirror location. That preflight
also requires all three agent-CLI binaries, including Codex's Node path, to be
resolvable; this blast radius is likewise limited to the boot catch-up and the
deploy tick, not to
containers dockerd restarts itself.

The mirror installer freezes its resolved directory in the mirror service's
`--mirror-dir` argument. An argumentless preflight reads that installed service
and requires exactly one matching value; an unreadable, missing, ambiguous, or
different value refuses with `Spiegel-Installer erneut ausführen`. After
changing `SONGMAKER_CLI_CREDENTIALS_DIR` in `.env`, run
`sudo ./scripts/install-cli-credentials-mirror.sh` again from the main
checkout before the next boot or deploy.

Refresh the mirror with `sudo systemctl start songmaker-cli-credentials-mirror.service`, not `restart`: restarting this required unit also restarts `songmaker.service` and therefore runs `docker compose up -d` against the live stack.

That call has been deleted from this script once already, by an edit that
rearranged the systemd checks around it, and nothing went red: the verifier's
own tests kept passing while the surface the deploy tick runs stopped checking
anything at all. The shell entry point therefore has its own tests, separate
from the Python ones. The installer, boot, and the auto-deploy tick use this
same check before Compose mounts the credential mirrors and the default or
environment-selected CLI binaries.

Where the mirror lives has one answer, owned by that same module: an exported
`SONGMAKER_CLI_CREDENTIALS_DIR` wins, then the same key in `.env`, then the
default under the stack owner's home — compose's own order. The value must be
an absolute path or `~/…` with no whitespace and no `%`, because systemd
splits directive values on whitespace and expands `%` as a specifier; anything
else is refused loudly rather than mangled into a unit.

**Installing.** `scripts/install-cli-credentials-mirror.sh` refuses to run
from a linked worktree — these units outlive the shell that installed them,
and the day a throwaway worktree is removed the unit stops — refuses to run as
root, whose logins are not the operator's, and refuses to silently replace any
of the four units it writes when that unit belongs to something else. Ownership
is judged per unit by the one directive that names its owner: the script an
`ExecStart` runs, the file a `PathChanged` watches, the service a timer drives.
A unit carrying no such directive counts as foreign — a file that cannot be
identified is the one to stop at — and the comparison must reach a token
boundary, so our own unit with different arguments is still ours while a
lookalike path is not. `--force` overrides. Every one of those checks runs
before the first write, so a refusal leaves the machine exactly as it was
rather than half-installed.

The installer is driven end to end by
`tests/test_install_cli_credentials_mirror.py` against a throwaway checkout.
Every invocation goes through one harness that replaces `sudo`, `systemctl`
and `getent`, and those fakes refuse rather than comply: a candidate path is
resolved with `readlink -m` before it is compared, so `..` and symlinked
parents cannot walk out of the test's own directory, and an unmodelled
`systemctl` command is an error rather than a success. The variables that hold
that containment together cannot be overridden by a test. A run that reached
the real `sudo` because a guard regressed must fail on the fake, not on the
machine, and there is a test that points the installer at `/etc/systemd/system`
from the main checkout to prove exactly that. That test exists
because two crashes shipped in this script while `bash -n` was the only thing
looking at it — neither an unset variable at runtime nor a directory whose
parent does not exist is visible to a syntax check — and it now also pins the
refusals above, each of which turns it red when removed.

### What each service mounts

These host files are received read-only:

| Service | Host path | Container path |
|---|---|---|
| `songmaker-web` | `$SONGMAKER_CLAUDE_CLI` (default `~/.local/bin/claude`) | `/usr/local/bin/claude` |
| `songmaker-web` | `$SONGMAKER_CLI_CREDENTIALS_DIR/claude.json` | `/home/songmaker/.claude/.credentials.json` |
| `songmaker-web` | `$SONGMAKER_GROK_CLI` (default `~/.grok/bin/grok`) | `/usr/local/bin/grok` |
| `songmaker-web` | `$SONGMAKER_CLI_CREDENTIALS_DIR/grok.json` | `/home/songmaker/.grok/auth.json` |
| `songmaker-web` | `$SONGMAKER_CODEX_CLI` (default native Codex binary) | `/usr/local/bin/codex` |
| `songmaker-web` | `$SONGMAKER_CLI_CREDENTIALS_DIR/codex.json` | `/home/songmaker/.codex/auth.json` |
| `songmaker-music-worker` | `$SONGMAKER_CODEX_CLI` (default native Codex binary) | `/usr/local/bin/codex` |
| `songmaker-music-worker` | `$SONGMAKER_CLI_CREDENTIALS_DIR/codex.json` | `/home/songmaker/.codex/auth.json` |

`songmaker-scoring-worker` owns only `.claude` and mounts only the Claude
binary and `claude.json` mirror. Its Grok and Codex judge calls use
`XAI_API_KEY` and `OPENAI_API_KEY`; mounting their subscription logins would
only widen the blast radius.

The Grok mirror is mounted only into its `songmaker-web` consumer. Grok turns
run with a private `0700` working directory and their own session tree, both
removed after success or abort; prompts and tool results reach the CLI only
through a private prompt file. The text tool protocol does not grant Grok CLI
tools: every start and resume keeps `--deny '*'`, and native tool-call events
abort the turn. The Codex binary and mirror are also mounted into
`songmaker-music-worker`, not into the scoring worker.

The cover-image route starts Codex with the fixed read-only image
argv (`--sandbox read-only`, no MCP servers, and `web_search="disabled"`),
with Code Mode enabled only for this image run. Each run creates a private
`0700` root whose `codex-home/` and `work/` directories are separate `0700`
siblings; the home contains only the redacted `auth.json` mirror (`0600`) and
the process cwd is the resolved `work/` path. The streamed event gate permits
`image_gen` and exactly one measured bootstrap pair: matching
`item.started`/`item.completed` `command_execution` events with the same ID,
the `sed -n '1,240p' CODEX_HOME/skills/.system/imagegen/SKILL.md` command,
that cwd in both events, and completed exit code 0. Any other command, cwd,
file change, MCP call, web search, collaboration or unknown event requests
abort and is reported as `ImageToolBlockedError`; the process is reaped before
the route returns. Every Co-Writer tool-loop round keeps Code Mode disabled.

Claude creates `~/.claude.json` itself, so it is neither seeded nor mounted.
Every bind uses Compose long syntax, `read_only: true`, and
`bind.create_host_path: false`: a missing source fails before a writable host
directory can be created. Only files, never an operator profile directory, are
mounted; a compromised container cannot add host-side profile settings or hooks.

### Provider API keys

`ANTHROPIC_API_KEY`, `XAI_API_KEY`, and `OPENAI_API_KEY` are configured only
through the deployment `.env` and become `Settings` secrets. Both
provider-facing images install the `claude` extra, so `ANTHROPIC_API_KEY`
serves the Claude judge, model catalog, and API co-writer tool loop. It does
not replace the web container's Claude CLI mirror: the selected CLI route
still uses Songmaker's MCP tools. The API and DOM expose only safe readiness
metadata (`set`/`not set` through route state), never a key value, raw
provider body, command output, or a secret-derived value. A Co-Writer route
is administrator-selected; a failed selected route returns its fixed safe
reason and never retries the sibling CLI/API route. The Judge remains
API-only.

**#327 F5:** Settings reads and validation never start an agent CLI or catalog
request. `provider_status_refresh` owns those probes; an empty snapshot is reported
as `unverified` rather than guessed as usable.

## Child Process Secret Scrubbing

Two packages spawn *external* child processes that must not inherit every secret in the parent's environment: `songmaker_cli.claude.provider` (the Claude CLI, for chat) and `acestep_worker.subprocess_runner` (the ACE-Step HTTP subprocess). Both packages scrub `os.environ.copy()` with a `SECRET_ENV_KEYS` tuple before passing `env=` to the child, covering `ANTHROPIC_API_KEY`, `XAI_API_KEY`, `OPENAI_API_KEY`, `SESSION_SECRET`, `SONGMAKER_INTERNAL_TOKEN`, `DATABASE_URL`, `REDIS_URL`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `HF_TOKEN`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `GRAFANA_USER`, and `GRAFANA_PASSWORD`. A login is scrubbed as a pair — the name half is no secret on its own, but handing a child process one half of a credential buys nothing.

The bootstrap admin credentials are on that list because compose sets them on the long-running web container, not on a one-shot setup job: `lifecycle.auto_setup_admin` re-reads `ADMIN_USERNAME`/`ADMIN_PASSWORD` at every startup so a database restored from empty gets its admin back. They therefore sit in the parent environment for the container's whole life, and this scrub is what keeps them out of every child it spawns.

`acestep_worker` cannot import from `songmaker_cli` (engine packages are independent — see CLAUDE.md), so each package keeps its own `SECRET_ENV_KEYS` tuple: `songmaker_cli/constants.py` and `acestep_worker/constants.py`. `tests/test_secret_scrub_parity.py` imports both, asserts they name the same set, and pins the literal expected set of keys — so the two cannot silently drift apart the way they did before issue #157 (the Claude CLI child inherited `SONGMAKER_INTERNAL_TOKEN` because the two lists disagreed), and neither list can quietly shrink to empty and still pass.

`HF_TOKEN` is scrubbed from the ACE-Step subprocess even though the subprocess genuinely does call Hugging Face: `vendor/acestep/acestep/api/model_download.py`'s `download_from_huggingface` runs both at subprocess startup (for the DiT and VAE models) and at request time (for LM models), and it passes no explicit `token=`, so `huggingface_hub` would pick up `HF_TOKEN` from the environment implicitly if it were present. However, every repo ID the subprocess can resolve on its own (via `MODEL_REPO_MAPPING` / `DEFAULT_REPO_ID` in that same module) is public and answers anonymously; the ACE-Step catalog's only two gated repos (`ACE-Step/acestep-v15-turbo`, `ACE-Step/acestep-5Hz-lm-1.7B`) are fetched exclusively by `acestep_worker.downloads.run_download`, which passes `token=` explicitly rather than relying on ambient env. So scrubbing `HF_TOKEN` here does not break any download this deployment performs — the consequence is that the subprocess's own Hugging Face requests go out anonymously and are subject to Hugging Face's stricter unauthenticated rate limits. See `acestep_worker/constants.py` for the same reasoning next to the list.

A third case needs a different mechanism: `songmaker_cli.scoring.subprocess_runner` starts the long-lived scorer child via `multiprocessing`'s `spawn` start method, which has no `env=` parameter — the child process inherits the parent's complete `os.environ` at spawn time, the same way it would inherit any other process-wide state. `_child_main` (the child's entry point) calls `_scrub_secret_env_vars()` as its literal first statement — but by the time `_child_main` runs, the spawn bootstrap has already imported the whole `subprocess_runner` module and everything it pulls in at module level (`scoring.pipeline`, `settings`, `auth`, `api_models`, ...), because multiprocessing's spawn target must be importable before it can be called. The scrub cannot undo anything a module-level import already did; it only guarantees that no code invoked *after* it — `default_registry.ensure_loaded()`'s scorer-module imports and every scorer function call that follows — can read a secret out of `os.environ`. `tests/test_scorer_subprocess.py::test_scorer_child_drops_secret_env_keys_at_spawn` drives the real `_child_main` entry point (via the existing `_run_child_with_messages` test harness, not a stand-in) with every `SECRET_ENV_KEYS` entry (plus a non-secret marker) set in the parent's environment beforehand, sends it an `EnvProbeRequest`, and asserts none of them come back present while the marker does — a spawned process's own `os.environ` cannot be observed from outside it any other way, so this round trip is what makes deleting the `_scrub_secret_env_vars()` call site fail the test.

Everything a child scorer needs is resolved in the parent and carried into the child as data — never re-read from the child's own environment — and none of it is a secret. `scoring_worker.py` and `jobs/scoring.py` call `get_settings()` at worker startup and per-job respectively, in the parent process; `scoring_device`, `scorer_timeout_seconds`, and `text_accuracy_timeout_seconds` flow into `PipelineConfig` fields (`device`, `scorer_timeout`, `text_accuracy_timeout`), and `scoring_max_jobs` separately bounds ARQ worker concurrency (`ScoringWorkerSettings.max_jobs`) — it never crosses the pipe at all. `lyrical_coherence.py` — the one scorer that calls an external provider (Claude, Grok, or Codex, whichever the judge is configured for, #315) — used to run in the child and call `get_settings()` there to read `anthropic_api_key`; after the scrub that field is simply absent, so `get_settings()` would raise (`Settings.database_url` has no default and is also in `SECRET_ENV_KEYS`) rather than degrade gracefully. Issue #173 handed the key to the child on `PipelineConfig` instead; issue #176 took the secret out of the child altogether. `scoring/registry.py` marks that scorer `host=ScorerHost.PARENT`, the child's registry refuses to register a parent-hosted scorer at all, and `jobs/scoring.py` calls `judge_lyrical_coherence()` itself, in the worker parent, on the `SongScores` the child returned — the transcription it judges comes from that result's `text_accuracy` value. `PipelineConfig` carries no secret field, so there is no key in the child's memory to leak through the model weights it loads.

The invariant this protects: no module reachable from `subprocess_runner`'s own import chain may read `os.environ` or construct `Settings()` as a *module-level* side effect (that code runs before the scrub ever gets a chance to act), and no scorer module — all of them imported later, inside `_child_main`, after the scrub — may read `os.environ` or construct `Settings()` at call time either. A future scorer that needs a secret does not belong in the child at all: give its spec `host=ScorerHost.PARENT` and run it in the worker parent on the result the child returned, the way `lyrical_coherence` does. Non-secret configuration reaches a child scorer through a new `PipelineConfig` field filled by the parent, never through a `get_settings()` call in the child.

Moving the judge out of the child (#176) only relocated *where* the provider call happens — it did not give the worker parent a credential to make that call with. `jobs/scoring.py` resolves `judge_provider`/`judge_model` from the DB and hands them to `judge_lyrical_coherence()` on a credential-free `CoherenceJudgeConfig`. `call_provider_once()` resolves the real credential in the worker parent: Claude falls through to the CLI whenever `ANTHROPIC_API_KEY` is unset, while Grok and Codex require `XAI_API_KEY` / `OPENAI_API_KEY`. The scoring image owns a writable `/home/songmaker/.claude` profile and mounts only the self-contained Claude binary plus the redacted `/home/songmaker/.claude/.credentials.json` mirror; Claude creates its own `~/.claude.json`. It deliberately mounts no Grok or Codex login because it never runs those CLIs. The credential remains in the worker parent, not the scorer child, so the child-process scrub and credential-free `PipelineConfig` are unaffected.

The scrub is also weaker than the Popen `env=` path used for the Claude CLI and ACE-Step children: `del os.environ[key]` calls libc's `unsetenv()`, which blocks `getenv()` — every subsequent read via `os.environ`/`os.getenv`, and every process this one execs from here on, sees the key as gone — but it does not erase the bytes the kernel copied onto the process's stack at its own `execve()`, which is what `/proc/<pid>/environ` reads directly. So the scrubbed keys stay visible in `/proc/<pid>/environ` for the child's entire lifetime even though `getenv()` can no longer see them. Accepted risk per CLAUDE.md's "Trust boundaries: subprocesses share OS user" entry: reading another process's `/proc/<pid>/environ` requires being that same OS user (or root), and the scoring-worker container's `songmaker` user has no other tenant sharing it, so this gap adds no new exploitation path beyond the one already accepted there. Never bind-mount `.env` into the `songmaker-scoring-worker` container — `Settings` walks up the filesystem looking for it, and doing so would hand the scrubbed child back every secret the scrub just removed.

The child never outlives a scorer it could not stop. A scorer's time budget is a ceiling: `_call_with_timeout` abandons a call that blows it (`shutdown(wait=False)`) instead of joining it, because a Python thread cannot be killed. Inside the child that abandoned thread goes on holding the Whisper/AudioBox model globals and their GPU memory, so the next request would otherwise reuse a child whose GPU memory is still held, beside a scorer still running. Two things prevent that. `ScorerProcess` marks itself tainted when a response reports `SongScores.any_child_scorer_timed_out`, under the same `_pipe_lock` that serializes requests, and `_ensure_started()` then refuses to hand that child to the next request — it kills and respawns instead. That holds even when the job that tainted it was cancelled and returned early. On top of it, `jobs/scoring.py` calls `ScorerProcess.recycle()` right after persisting the values of such a run, so the GPU is reclaimed immediately rather than at a next request that may be minutes away. Both paths kill the same way: SIGTERM first, so the child's own handler releases CUDA memory, SIGKILL after a 5-second grace period; the replacement child runs `_scrub_secret_env_vars()` again by construction. The taint counts only child-hosted scorers: a parent-hosted one over budget (the coherence judge) leaves its thread in the worker parent, where killing the child would reclaim nothing and only cost the next job a model reload. `tests/test_jobs.py` and `tests/test_scorer_subprocess.py` pin every direction — a timed-out child scorer keeps its scores and loses its child, a cancelled job's tainted child is still not reused, a clean run and a timed-out judge both keep the child they had.

The scorer's two Hugging Face models (`faster-whisper`'s `large-v3`, `audiobox-aesthetics`'s default checkpoint) are baked into the `songmaker-scoring-worker` image at build time — `docker/scoring-worker.Dockerfile` downloads them with `HF_TOKEN` wired in only for that `RUN --mount=type=secret` build step, and the running container's `docker-compose.yml` service definition never sets `HF_TOKEN` as a runtime env var at all, so there is nothing for the scrub to take away at request time.

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

### Deployment boundary

This repository ships no reverse-proxy service or configuration: there is no
nginx, Caddy, Traefik, or tunnel policy here. The internal API trusts any caller
that knows the token, and has no per-user authorization. Compose publishes the
web port only on the host loopback interface, while workers use the Compose
network; an operator who adds an upstream proxy or tunnel is responsible for
keeping `/api/internal/*` unavailable to public traffic. That edge policy is not
implemented by this repository (#327).

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

If exposure to untrusted traffic becomes a concern, the next step is to bind `/api/internal/*` to a separate port (and bind it to the Docker network, not `0.0.0.0`). Today the single-port design has no repository-provided edge path filter; its safety depends on the loopback-only published port and on any operator-provided upstream access policy.

## Requirement Approval Witnesses

Requirement approval uses an authorization comment from the configured
repository account. The operator may act directly or explicitly delegate the
posting to a coordinating agent after the required independent reviews and a
transparent disclosure in the owning issue. The offline registry pins a strict
witness file by SHA-256; the witness pins the numeric repository, issue,
comment, and author identities, timestamps, and exact approval body. This proves
durable byte relationships but neither human authorship nor compliance with the
procedural review/disclosure policy.

The live verifier uses Python's standard HTTPS stack with the default verified
TLS context. It permits only `api.github.com` and three fixed read-only route
shapes for `FlexOr2/songmaker`, does not follow redirects, checks API and HTML
URLs across the repository→issue→comment chain, and fails closed on malformed or
oversized responses. Responses are capped at 256 KiB, reads/connects at 15
seconds, and the internal monotonic deadline is 120 seconds. The workflow also
wraps the process in a 120-second OS watchdog, with a three-minute GitHub job
timeout as provider-level defense. Registry, requirement, acceptance, witness,
and decoded-body inputs also have explicit count/byte bounds.

GitHub Actions grants only `contents: read` and `issues: read`. Checkout never
persists credentials, and `GITHUB_TOKEN` is passed as an environment variable
only to the live-verifier step. The token-bearing job skips fork pull requests;
the tokenless offline gate continues to validate those diffs. Live results are
point-in-time observations,
so pushes, manual runs, weekly checks, and approval-comment edit/delete events
rerun verification. The binder re-fetches immediately before a local write, and
the resulting pushed commit must pass the live workflow.

Every third-party GitHub Action is pinned to the full commit SHA of its reviewed
release tag (with the release series recorded beside it), so a moved tag cannot
change a workflow. Project tooling in CI and application dependencies in worker
images are installed through `uv` with the committed `uv.lock`; Bandit and
pip-audit run in separate tool environments so they do not change that lock.
The repository itself is installed as the trusted local editable project. All
third-party dependencies must be wheels except `nvidia-ml-py3`, whose locked,
hash-verified release has no published wheel.

The local requirement binder now owns that write boundary. A parent process
enforces a 120-second wall limit over one guarded private worker process group;
an inherited pipe terminates that group if the parent disappears, and timeouts
return the manual-recovery exit code. The worker holds a no-symlink lock in the
worktree Git directory through its prepared-success output, requires an index
exactly matching HEAD and exactly one candidate delta, and rechecks HEAD, Git status, candidate,
and owned outputs before and after the network phase. Git is invoked only as the
fixed local `/usr/bin/git`, without a shell or network command, under short
timeouts and output caps. Every Git child receives an allowlisted environment
that excludes `GITHUB_TOKEN`, user/system Git configuration, replacement
objects, lazy object fetches, and interactive prompts. Repository-local config
remains inside the cooperative trust boundary, while explicit overrides disable
fsmonitor, ignorestat, untracked-cache, and file-mode shortcuts. Assume-unchanged,
skip-worktree, sparse, or otherwise nonordinary index entries are refused.
Contract-visible directory scans stream entries and stop at the same fixed
file-count bound used for baseline materialization before sorting or building sets.

Witness JSON has one canonical ASCII representation: sorted keys, compact
separators, no NaN, and exactly one final LF. New witness installation uses a
same-directory temporary file plus atomic hard-link no-clobber. Registry and
PRODUCT replacements preserve their snapshotted permission bits and are
protected against cooperating binders by the lock. A noncooperating process
with the same OS identity is outside this boundary; snapshot comparisons detect
it at defined gates, and rollback removes a witness only when the successful
link's held descriptor, target identity, exact bytes, and mode still prove binder
ownership.
There is no false multi-file atomicity claim: interruption may leave the original
candidate-only state, a partial state that the offline gate rejects, or the
complete end state that was validated before the first install.

## Audit Trail

All mutating operations are logged to the `audit_log` table:

- **Actions tracked**: `create`, `update`, `delete`, `generate`, `score`, `cleanup`, `share`, `unshare`, `deactivate`, `session_ip_change`, `session_ua_change`
- **Fields**: `user_id`, `action`, `resource_type`, `resource_id`, `detail`, `created_at`
- **Admin access**: `GET /api/admin/audit-log?limit=100`

## Production Deployment

### Recommended

| Setting | How |
|---------|-----|
| HTTPS termination | Songmaker does not terminate TLS. An operator-provided TLS terminator must set `X-Forwarded-Proto: https`; Songmaker honors it only when the direct peer matches `TRUSTED_PROXIES`, which activates the `Secure` cookie flag and HSTS. No terminator configuration is shipped here. |
| Session secret | Set `SESSION_SECRET` env var (min 32 chars). Required — startup fails with `ValidationError` if missing. Stable across restarts. Generate with `python3 -c "import secrets; print(secrets.token_hex(32))"`. |
| CORS origin | Set `CORS_ORIGIN=https://yourdomain.com` or `CORS_ORIGIN=*.yourdomain.com`. Wildcard must include a registrable domain (e.g., `*.trycloudflare.com`). Bare TLDs rejected. |
| Trusted proxies | Set `TRUSTED_PROXIES=10.0.0.1,172.16.0.0/12` (comma-separated addresses and/or CIDR networks). Only peers inside these networks are trusted for `X-Forwarded-For` and `X-Forwarded-Proto`; the rightmost untrusted `X-Forwarded-For` entry is used to prevent spoofing. An unparsable or zone-scoped entry fails startup, and a malformed forwarded chain falls back to the direct peer. Without this, the client's direct IP is always used for rate limiting and no forwarded HTTPS signal is honored — see "Proxy trust". |
| Public base URL | Set `PUBLIC_BASE_URL=https://yourdomain.com` (scheme + host, no trailing path). The one owner of "what address am I reachable at from outside" for share links (album/song/generation/playlist — issue #339); `api_helpers.resolve_public_base_url()` is the only caller site. Not derived from the request: `request.base_url` reflects the literal ASGI transport's scheme, which is always `http` behind a TLS-terminating proxy since `proxy_headers=False` (see "Proxy trust") leaves nothing to rewrite it. Unset or malformed fails the share call with `500` rather than building a link with a guessed scheme. |
| Allowed hosts | Set `ALLOWED_HOSTS=yourdomain.com,yourdomain.com:443` (comma-separated). Used by CSRF origin verification. Defaults to `localhost`/`127.0.0.1` regex for dev. |
| Host binding | Default is `127.0.0.1` (localhost only). Set `HOST=0.0.0.0` only when the deployment's network policy keeps the service private. The Docker deployment does set `HOST=0.0.0.0` — that binding is *inside* the container, where the Compose network needs it. |
| Published ports | `docker-compose.yml` publishes `songmaker-web`, Grafana, and Prometheus as `127.0.0.1:8080:8080` / `127.0.0.1:3000:3000` / `127.0.0.1:9090:9090`. Do not drop the `127.0.0.1:` prefix: Docker's NAT chain bypasses the host INPUT chain, so a plain `8080:8080` reaches the whole LAN no matter what UFW says. The Prometheus API is host-local for the same reason; its lifecycle HTTP endpoints stay disabled, so Compose-network peers cannot stop or reload it. The tunnel (`cloudflared`), the Vite dev proxy, and the CLI all run host-local; in-cluster callers use `songmaker-web:8080` on the compose network. |
| Workers | Production runs in Docker only. The web container uses a single uvicorn process; concurrency comes from arq worker containers (`MUSIC_MAX_JOBS`, `SCORING_MAX_JOBS`). PostgreSQL is the only supported production DB — SQLite is test-only. |
| Request body limit | App-level: `MAX_REQUEST_BODY_BYTES` (default 1 MB). If an operator provides an upstream proxy, align its path-specific limits for defense in depth; this repository provides no such proxy configuration. |
| IP rate limit | `IP_RATE_LIMIT` (API class, default 120/min), `MEDIA_RATE_LIMIT` (`/audio/*`, default 600/min), `STREAM_RATE_LIMIT` (SSE opens, default 45/min). Adjust based on expected traffic — see "Per-IP (global middleware)" above. |
| Resource-event stream open limit | `RESOURCE_EVENT_STREAM_OPEN_LIMIT` (per-user resource-events stream opens, default 12/min). CI overrides it — see "Resource-event streams" above. |
| Request timeout | `REQUEST_TIMEOUT` (default 30s) limits idle keep-alive connections, not full requests. The two SSE routes have their own 60-second walls; Songmaker has no general application request deadline. |
| Auto-deploy cleanup timeout | `SONGMAKER_AUTODEPLOY_PRUNE_TIMEOUT_SECONDS` (default 600). Bounds each post-deploy Docker cleanup command. |

The two-minute auto-deploy tick checks the active-job queue and required alert-channel configuration before it pulls or builds. It also runs `scripts/check_agent_cli_mounts.sh` before those steps when that verifier is installed; a verifier failure is a named deploy refusal, so it increments the tick's existing consecutive-failure counter and follows its alert escalation. A checkout that predates the verifier logs `mount preflight not installed, skipping` and continues with its installed guards, making the temporary compatibility state visible rather than silently bypassing it. After fetching `origin/main`, the tick asks GitHub about the newest ten first-parent commits (configurable with `SONGMAKER_AUTODEPLOY_CHECK_RUN_LOOKBACK_COMMITS`) and fast-forwards only to the newest commit whose reported runs have all completed successfully. Running and failed candidates are named in the log and skipped; no runs stay neutral only for the 30-minute grace period measured from the local host clock when the HEAD SHA was first seen; a commit timestamp supplied by Git cannot postpone that alarm. An unavailable or malformed GitHub answer, or a 60-second check-run lookup timeout, is a named deploy refusal that uses the same counter and alert escalation. Every Git command in the tick disables repository hooks and the filesystem monitor and runs with a minimal Git environment.

After a successful recreate, the tick runs `docker image prune --force --filter until=48h`: dangling images only, so it does not remove tagged base images, stopped E2E stacks, or images belonging to another project. Before recreating, it tags only running Compose services with a `build:` section as `<project>-<service>:previous`; `<project>` comes from `docker compose config --format json --no-interpolate | jq -r '.name'`, so the tag follows the actual Compose project without materializing `.env` secrets. To roll back a built service, run `project="$(docker compose config --format json --no-interpolate | jq -r '.name')"; docker tag "${project}-<service>:previous" "${project}-<service>:latest" && docker compose up -d --force-recreate <service>`. Both cleanup commands are bounded by `SONGMAKER_AUTODEPLOY_PRUNE_TIMEOUT_SECONDS` (600 seconds by default); an error or timeout is logged at `err` with its command and exit code, while the completed deployment remains successful and the tick does not change either counter. The builder cleanup deliberately uses `docker builder prune --all --force --filter until=48h`, preserving cache used in the last 48 hours but allowing a quiet host's next rebuild to take its normal cold-cache 8–15 minutes.

### Secrets

- `SESSION_SECRET`: HMAC signing key for session cookies. Required at startup (Settings raises ValidationError if missing).
- `ANTHROPIC_API_KEY`: Optional (for server-side Claude chat). Never logged or returned in responses.
- `.env`: Gitignored. Never committed. Single source for pydantic Settings and
  Docker Compose substitutions except the non-secret
  `SONGMAKER_CLAUDE_CLI`, `SONGMAKER_GROK_CLI`, and `SONGMAKER_CODEX_CLI` path
  overrides: systemd boot and auto-deploy must receive those as persistent
  exported environment values so the preflight sees the same paths as Compose.

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

Audio file serving resolves the requested path and verifies that it remains below the configured audio root to prevent directory traversal. The authenticated audio endpoint (`/audio/{owner_id}/{filename}`) checks that the requesting user owns the files (or is admin) — no DB lookup needed since the path is keyed by user ID. Album, song, and playlist shared-audio endpoints reject a requested filename unless it is already canonical, log traversal rejection without the root, and then decide the share allowlist in the query layer before delivering bytes. Their public JSON routes present stored audio paths only when those paths already meet the same canonical rule, so the scalar SQL filename equality is exact. Album and song covers are never served from `/audio/{owner_id}/{filename}`; authenticated covers use `/api/albums/{id}/cover` and `/api/songs/{id}/cover`, and public covers use `/shared/{slug}/cover` and `/shared/song/{slug}/cover`.

## GPU Resource Safety

- **Isolation by container**: `songmaker-acestep-worker-0` is the only container given a GPU (`runtime: nvidia`, `NVIDIA_VISIBLE_DEVICES: "0"`). `songmaker-scoring-worker` is given no GPU device and runs with `SCORING_DEVICE=cpu`, so scorer models and ACE-Step cannot contend for the same VRAM. There is no cross-container release handshake, because with CPU scoring there is nothing to release.
- **Generation VRAM**: The acestep-worker owns its own budget end to end — an LRU model cache bounded by `VRAM_BUDGET_GB` that evicts to fit an incoming load, and NVML heartbeats (`acestep_worker/gpu_util.py`) reporting live used/total GB to the control plane.
- **Scorer subprocess**: The child installs a SIGTERM handler that calls `torch.cuda.empty_cache()` before exiting, so the kill paths above (timeout, taint, `recycle()`) release device memory rather than orphaning it. On CPU that handler is a no-op; it exists for the CUDA case.
- **ACE-Step lifecycle**: The acestep-worker container manages the ACE-Step HTTP subprocess, sending SIGTERM (with SIGKILL fallback) on model switch, worker restart, or shutdown. See `docs/acestep.md` for the worker pool architecture.

Moving scoring onto the GPU (`SCORING_DEVICE=cuda`) would put two containers on one device and does need an arbitration protocol — a scorer-side release plus a verified-free check before generation. That protocol is not built; see issues #161 and #182.

## Known Limitations

- **Claude CLI agents**: `--disable-slash-commands` closes slash commands and skills (verified empty in the init event's `slash_commands` list — see Claude Chat Security above), but the CLI still lists five built-in *agents* (`claude`, `Explore`, `general-purpose`, `Plan`, `statusline-setup`) in that same init event even with every isolation flag set. No exploit path is confirmed: reaching one needs a `Task`-shaped tool, and `--tools ""` already removes that. A future CLI version that could reach an agent some other way would reopen this; the tool-surface gate does not check the `agents` field today.
- **No IP binding on sessions**: A stolen session cookie works from any IP. The auth dependency calls `resolve_client_ip()` to obtain the real client IP when the direct peer is in `TRUSTED_PROXIES` (otherwise the direct peer), then stores it for later comparisons; an IP or user-agent change is written to the audit trail. It is not an authorization check: the session remains valid so ordinary mobile-network changes do not log a user out (#327).
- **No MFA**: Single-factor auth only. Acceptable for invite-only deployments.
- **Redis session staleness**: If Redis delete fails during user deactivation or after a failed login commit, the cached session remains valid until the next background sync (up to 5 minutes) or Redis TTL expiry. The background sync detects and cleans up orphaned/deactivated sessions.
- **Worker control endpoints have no cooldown**: `POST /api/admin/workers/{id}/restart`, `POST /api/admin/workers/{id}/pin_model`, and `POST /api/admin/registry/{mode}/download` are not rate-limited. Repeated calls by a compromised admin could disrupt GPU workers or exhaust download bandwidth. Admin-only auth is the only gate.
- **`/metrics` endpoint is unauthenticated**: Exposes Prometheus metrics (request counts, latencies, queue depth, VRAM usage) without auth (`health_api.py:211-218`). The web container binds port 8080 to `127.0.0.1`, so the repository makes this endpoint host-local by default (`docker-compose.yml:89-90`); a public deployment needs a filtering layer in front of it, which this repository does not provide (#327).

## Hardening Roadmap (for public internet exposure)

The application-layer security (auth, CSRF, IDOR, injection, error sanitization) is solid for a self-hosted tool. The gaps below are infrastructure-level and would need addressing before exposing the app to untrusted public traffic at scale; any public edge configuration is operator-owned, not shipped by this repository.

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

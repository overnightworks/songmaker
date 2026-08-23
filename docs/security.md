# Songmaker Security

## Authentication

Session-based auth with bcrypt password hashing (12 rounds).

- **Session tokens**: `secrets.token_urlsafe(32)` — 256-bit entropy, stored in both DB and Redis
- **Redis session cache**: Session validation reads from Redis first (no DB hit on cache hit). DB is the durable store, synced every 5 minutes via a background task. Redis failure degrades gracefully to DB-only mode. Session TTL in Redis replaces per-request DB writes for sliding window renewal. Login writes the new session to Redis before the DB transaction commits (and deletes that key if commit fails) so a concurrent prune cannot be overwritten by a late cache `SET`.
- **HMAC-signed cookies**: Session cookies are `{session_id}.{hmac_sha256}` signed with a server-side secret. A DB or Redis leak does not yield usable cookies. The secret comes from the `SESSION_SECRET` env var (min 32 chars) and is required at startup — Settings raises `ValidationError` if missing. There is no auto-generation fallback (was removed in the W1 no-silent-fallbacks cleanup; the old fallback masked deployment misconfigurations).
- **Cookie flags**: `HttpOnly`, `SameSite=Strict`, `Secure` (auto-detected; `X-Forwarded-Proto` only honored when the direct peer is in `TRUSTED_PROXIES`)
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
| Song | `/shared/song/{slug}` | `/shared/song/{slug}/audio/{file}`, `/shared/song/{slug}/cover` |
| Generation | `/shared/gen/{slug}` | `/shared/gen/{slug}/audio/{file}` |
| Playlist | `/shared/playlist/{slug}` | `/shared/playlist/{slug}/audio/{file}` |

Album and song shares serve the picked unarchived generation when one exists, otherwise the latest unarchived generation. Generation shares serve the shared generation. Playlist shares serve playlist entry generations. Public JSON responses omit scores and edit history; audio URLs include the exact stored relative audio path needed by the filename allowlist. Album JSON includes `cover` only while the album is shared and the cover file exists. Song JSON includes `cover` only while the song is shared and the **song** cover file exists — never the parent album's art. Public cover bytes are served from `/shared/{slug}/cover` or `/shared/song/{slug}/cover` using that same slug gate — never a client-supplied path on `/audio/{owner_id}/{filename}`. Unshare, replace, or delete 404s the previous public cover URL. Share slugs are UUID v4 values (122 bits of entropy, unguessable). Sharing is revocable by the resource owner.

### Per-IP (global middleware)

All requests are subject to a global per-IP rate limit (default: 120 requests/minute). This prevents multi-account abuse and unauthenticated request floods. The rate limiter is memory-bounded (max 10k tracked IPs with automatic eviction of stale entries). Configurable via `IP_RATE_LIMIT` env var. When `TRUSTED_PROXIES` is configured, the rate limiter uses the real client IP from `X-Forwarded-For` (rightmost untrusted entry), matching the login rate limiter's behavior. If Redis is unavailable, the rate limiter fails closed (returns 503 with `Retry-After: 5`) rather than allowing all requests through.

Static `_app/` build assets and the static PWA root assets (`/manifest.webmanifest`, `/robots.txt`, `/favicon.svg`, `/icon-192.png`, `/icon-512.png`, `/service-worker.js`) are exempt from this budget — they're fetched by the browser and the service worker outside of user-driven navigation and would otherwise crowd out real `/api/*` calls from the same IP. `/health` is deliberately **not** exempt: it is the most expensive anonymous endpoint (a DB query plus roughly six Redis round trips for worker/queue state) and the only caller is the browser's 15s poll (~4/min) — exempting it would let an anonymous caller hammer the priciest endpoint for free. No `/api/*` path is exempt.

Configure via env vars: `LOGIN_RATE_LIMIT`, `LOGIN_LOCKOUT_THRESHOLD`, `LOGIN_LOCKOUT_WINDOW`, `GENERATION_RATE_LIMIT_USER`, `GENERATION_RATE_LIMIT_ADMIN`, `SCORING_RATE_LIMIT_USER`, `SCORING_RATE_LIMIT_ADMIN`, `CHAT_RATE_LIMIT_USER`, `CHAT_RATE_LIMIT_ADMIN`, `MAX_QUEUE_DEPTH`, `IP_RATE_LIMIT`.

### Resource-event streams

The global IP limit is supplemented by a fail-closed per-user opening limit of 12
streams per minute; rejected attempts are not retained in the bounded Redis window.
Redis leases cap live streams at six per user and at most 12
globally, reduced automatically when the configured DB pool has less spare capacity.
If reserving one non-stream DB slot leaves no capacity, stream admission returns 503.
Acquire is one Lua operation across user and global sorted sets; UUID lease members
carry absolute expiry scores and release targets that exact token on disconnect. A
crashed process cannot retain a slot beyond 65 seconds. Lease release runs off the async loop; the
Redis client bounds connect and socket waits to two seconds, with expiry as the final
fallback. Redis failure returns 503 rather than opening an unbounded poller.

## Security Headers

All responses include:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; connect-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self' https://fonts.gstatic.com; frame-ancestors 'none'`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains` (HTTPS only; `X-Forwarded-Proto` only honored from `TRUSTED_PROXIES`)
- `Cache-Control: no-store` (API responses only — prevents caching of authenticated data). The exact resource-event SSE path uses `no-cache, no-store` so intermediaries do not cache or transform its reconnect stream; other API and SSE paths retain `no-store`.

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

`BodySizeLimitMiddleware` (raw ASGI) first checks `Content-Length` for fast rejection, then wraps the receive channel to count bytes as they stream in — aborting with 413 once the limit is exceeded without buffering the entire body.

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

**Note**: For production deployments exposed to the internet, configure equivalent path-specific limits at the reverse proxy so oversized requests are rejected at the network edge. A blanket 1 MiB proxy limit would also block the documented audio-upload and cover routes.

## Response Compression

`SelectiveGZipMiddleware` (`middleware/gzip.py`, mounted just inside the outermost `ResourceStreamDeadlineMiddleware`) gzips a response only when it is status 200, carries no `Content-Range`, and its `Content-Type` matches an explicit allowlist (`application/json`, `text/*` except `text/event-stream`, `application/javascript`, `application/manifest+json`) at or above `GZIP_MINIMUM_SIZE_BYTES` (1 KiB) — never `audio/*`, `image/*`, `video/*`, `application/octet-stream`, or any other binary media, and never a byte-range response. `Accept-Encoding` is parsed as real RFC 9110 q-values (`gzip;q=0` is honored, not compressed) rather than a substring check, and `Vary: Accept-Encoding` is set on every eligible response regardless of whether this particular client asked for gzip, so a downstream cache never serves one client's (un)compressed copy to another. `text/event-stream` (the co-writer chat and job-progress SSE endpoints) is on the never-compress list, so those responses pass through unbuffered, one ASGI send per source chunk. When a response is compressed, `Accept-Ranges` is deleted from it (matching nginx's own gzip behavior) since byte offsets into the compressed stream no longer correspond to the original bytes. Compression level is `GZIP_COMPRESS_LEVEL` (6, zlib's own default) — level 9 saves under a percentage point more reduction for roughly 3x the CPU per request.

## Request Timeout

Uvicorn's `timeout-keep-alive` is set to `REQUEST_TIMEOUT` (default 30s). Idle connections exceeding this are closed. For production, use a reverse proxy timeout (e.g., nginx `proxy_read_timeout`) for full request-level timeout enforcement.

The resource-event SSE has its own monotonic 60-second wall. DB polling runs outside
the async event loop, is awaited only for the remaining wall time, and no DB session
spans an SSE yield or sleep. The response applies the same wall around ASGI sends, so
a slow reader cannot keep the socket or lease alive after the deadline. The endpoint
emits 15-second comment heartbeats so a correctly configured proxy sees activity
before the deliberate reconnect. The library page's native EventSource probes
`/api/auth/me` on `onerror`; 401/403 stop the stream and clear auth, and logout
closes the owner before the logout request.

## Claude Chat Security

- **System prompt**: Hardcoded server-side (`SYSTEM_PROMPT` in `chat_api.py`). Clients cannot override it. Song context is wrapped in `<song_context>` XML tags with an untrusted-data notice instructing Claude to ignore instructions inside tags.
- **Multi-turn history**: Stored in `chat_messages` table, scoped to song. Ownership enforced via `check_song_access()` on every endpoint. Max 50 messages per song.
- **Context built server-side**: Mentioned song/version IDs are sent by the frontend, but the backend resolves them from the DB — the client never sends raw context. Each mentioned song is ownership-checked.
- **CLI backend**: All known tools disabled via `--disallowedTools` denylist. Note: `--tools ""` and `--allowedTools ""` do not reliably block tools in current Claude CLI versions, so a comprehensive denylist is used instead. This list must be updated when new tools are added to Claude Code.
- **API backend**: Uses the Anthropic Python SDK with `max_tokens=1024` to limit response cost.

## Child Process Secret Scrubbing

Two packages spawn *external* child processes that must not inherit every secret in the parent's environment: `songmaker_cli.claude.provider` (the Claude CLI, for chat) and `acestep_worker.subprocess_runner` (the ACE-Step HTTP subprocess). Both packages scrub `os.environ.copy()` with a `SECRET_ENV_KEYS` tuple before passing `env=` to the child, covering `ANTHROPIC_API_KEY`, `SESSION_SECRET`, `SONGMAKER_INTERNAL_TOKEN`, `DATABASE_URL`, `REDIS_URL`, `POSTGRES_PASSWORD`, and `HF_TOKEN`.

`acestep_worker` cannot import from `songmaker_cli` (engine packages are independent — see CLAUDE.md), so each package keeps its own `SECRET_ENV_KEYS` tuple: `songmaker_cli/constants.py` and `acestep_worker/constants.py`. `tests/test_secret_scrub_parity.py` imports both, asserts they name the same set, and pins the literal expected set of seven keys — so the two cannot silently drift apart the way they did before issue #157 (the Claude CLI child inherited `SONGMAKER_INTERNAL_TOKEN` because the two lists disagreed), and neither list can quietly shrink to empty and still pass.

`HF_TOKEN` is scrubbed from the ACE-Step subprocess even though the subprocess genuinely does call Hugging Face: `vendor/acestep/acestep/api/model_download.py`'s `download_from_huggingface` runs both at subprocess startup (for the DiT and VAE models) and at request time (for LM models), and it passes no explicit `token=`, so `huggingface_hub` would pick up `HF_TOKEN` from the environment implicitly if it were present. However, every repo ID the subprocess can resolve on its own (via `MODEL_REPO_MAPPING` / `DEFAULT_REPO_ID` in that same module) is public and answers anonymously; the ACE-Step catalog's only two gated repos (`ACE-Step/acestep-v15-turbo`, `ACE-Step/acestep-5Hz-lm-1.7B`) are fetched exclusively by `acestep_worker.downloads.run_download`, which passes `token=` explicitly rather than relying on ambient env. So scrubbing `HF_TOKEN` here does not break any download this deployment performs — the consequence is that the subprocess's own Hugging Face requests go out anonymously and are subject to Hugging Face's stricter unauthenticated rate limits. See `acestep_worker/constants.py` for the same reasoning next to the list.

A third case needs a different mechanism: `songmaker_cli.scoring.subprocess_runner` starts the long-lived scorer child via `multiprocessing`'s `spawn` start method, which has no `env=` parameter — the child process inherits the parent's complete `os.environ` at spawn time, the same way it would inherit any other process-wide state. `_child_main` (the child's entry point) calls `_scrub_secret_env_vars()` as its literal first statement — but by the time `_child_main` runs, the spawn bootstrap has already imported the whole `subprocess_runner` module and everything it pulls in at module level (`scoring.pipeline`, `settings`, `auth`, `api_models`, ...), because multiprocessing's spawn target must be importable before it can be called. The scrub cannot undo anything a module-level import already did; it only guarantees that no code invoked *after* it — `default_registry.ensure_loaded()`'s scorer-module imports and every scorer function call that follows — can read a secret out of `os.environ`. `tests/test_scorer_subprocess.py::test_scorer_child_drops_secret_env_keys_at_spawn` drives the real `_child_main` entry point (via the existing `_run_child_with_messages` test harness, not a stand-in) with all seven keys (plus a non-secret marker) set in the parent's environment beforehand, sends it an `EnvProbeRequest`, and asserts none of the seven come back present while the marker does — a spawned process's own `os.environ` cannot be observed from outside it any other way, so this round trip is what makes deleting the `_scrub_secret_env_vars()` call site fail the test.

Everything a child scorer needs is resolved in the parent and carried into the child as data — never re-read from the child's own environment — and none of it is a secret. `scoring_worker.py` and `jobs/scoring.py` call `get_settings()` at worker startup and per-job respectively, in the parent process; `scoring_device`, `scorer_timeout_seconds`, and `text_accuracy_timeout_seconds` flow into `PipelineConfig` fields (`device`, `scorer_timeout`, `text_accuracy_timeout`), and `scoring_max_jobs` separately bounds ARQ worker concurrency (`ScoringWorkerSettings.max_jobs`) — it never crosses the pipe at all. `lyrical_coherence.py` — the one scorer that calls Claude — used to run in the child and call `get_settings()` there to read `anthropic_api_key`; after the scrub that field is simply absent, so `get_settings()` would raise (`Settings.database_url` has no default and is also in `SECRET_ENV_KEYS`) rather than degrade gracefully. Issue #173 handed the key to the child on `PipelineConfig` instead; issue #176 took the secret out of the child altogether. `scoring/registry.py` marks that scorer `host=ScorerHost.PARENT`, the child's registry refuses to register a parent-hosted scorer at all, and `jobs/scoring.py` calls `judge_lyrical_coherence()` itself, in the worker parent, on the `SongScores` the child returned — the transcription it judges comes from that result's `text_accuracy` value. `PipelineConfig` carries no secret field, so there is no key in the child's memory to leak through the model weights it loads.

The invariant this protects: no module reachable from `subprocess_runner`'s own import chain may read `os.environ` or construct `Settings()` as a *module-level* side effect (that code runs before the scrub ever gets a chance to act), and no scorer module — all of them imported later, inside `_child_main`, after the scrub — may read `os.environ` or construct `Settings()` at call time either. A future scorer that needs a secret does not belong in the child at all: give its spec `host=ScorerHost.PARENT` and run it in the worker parent on the result the child returned, the way `lyrical_coherence` does. Non-secret configuration reaches a child scorer through a new `PipelineConfig` field filled by the parent, never through a `get_settings()` call in the child.

The scrub is also weaker than the Popen `env=` path used for the Claude CLI and ACE-Step children: `del os.environ[key]` calls libc's `unsetenv()`, which blocks `getenv()` — every subsequent read via `os.environ`/`os.getenv`, and every process this one execs from here on, sees the key as gone — but it does not erase the bytes the kernel copied onto the process's stack at its own `execve()`, which is what `/proc/<pid>/environ` reads directly. So the scrubbed keys stay visible in `/proc/<pid>/environ` for the child's entire lifetime even though `getenv()` can no longer see them. Accepted risk per CLAUDE.md's "Trust boundaries: subprocesses share OS user" entry: reading another process's `/proc/<pid>/environ` requires being that same OS user (or root), and the scoring-worker container's `songmaker` user has no other tenant sharing it, so this gap adds no new exploitation path beyond the one already accepted there. Never bind-mount `.env` into the `songmaker-scoring-worker` container — `Settings` walks up the filesystem looking for it, and doing so would hand the scrubbed child back every secret the scrub just removed.

The child never outlives a scorer it could not stop. A scorer's time budget is a ceiling: `_call_with_timeout` abandons a call that blows it (`shutdown(wait=False)`) instead of joining it, because a Python thread cannot be killed. Inside the child that abandoned thread goes on holding the Whisper/AudioBox model globals and their GPU memory, so `release_gpu()` would free nothing and the next `ScoreRequest` would run beside it. Once the run's values are persisted, `jobs/scoring.py` therefore calls `ScorerProcess.recycle()` for any run whose `SongScores` reports a `timed_out` scorer — SIGTERM first, so the child's own handler releases CUDA memory, SIGKILL after a 5-second grace period — and the next request spawns a fresh child, which by construction runs `_scrub_secret_env_vars()` again. `tests/test_jobs.py` pins both directions: a run with a timed-out scorer keeps its scores and leaves the old pid gone, a run without one keeps the same child.

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

Audio file serving uses `.resolve()` + `.is_relative_to()` to prevent directory traversal. The authenticated audio endpoint (`/audio/{owner_id}/{filename}`) checks that the requesting user owns the files (or is admin) — no DB lookup needed since the path is keyed by user ID. Shared audio endpoints first resolve the slug to a shared album, song, generation, or playlist, then validate the requested filename against that resource's allowed generation paths before reading from disk. Album and song covers are never served from `/audio/{owner_id}/{filename}`; authenticated covers use `/api/albums/{id}/cover` and `/api/songs/{id}/cover`, and public covers use `/shared/{slug}/cover` and `/shared/song/{slug}/cover`.

## GPU Resource Safety

- **Per-job cleanup**: Both generation and scoring jobs call `gc.collect()` + `torch.cuda.empty_cache()` in a `finally` block, ensuring VRAM is released even on failure.
- **Mode-switch cleanup**: The GPU queue clears scoring models before generation and vice versa, with VRAM verification (waits up to 10s for release).
- **ACE-Step lifecycle**: The acestep-worker container manages the ACE-Step HTTP subprocess, sending SIGTERM (with SIGKILL fallback) on model switch, worker restart, or shutdown. See `docs/acestep.md` for the worker pool architecture.

## Known Limitations

- **Claude CLI tool denylist**: Uses `--disallowedTools` (denylist, not allowlist) because `--tools ""` doesn't reliably block tools. New Claude Code tools require updating the list in `provider.py`.
- **No IP binding on sessions**: A stolen session cookie works from any IP. IP/UA changes are logged to the audit trail but not blocked, to avoid breaking mobile users who switch networks.
- **No MFA**: Single-factor auth only. Acceptable for invite-only deployments.
- **Redis session staleness**: If Redis delete fails during user deactivation or after a failed login commit, the cached session remains valid until the next background sync (up to 5 minutes) or Redis TTL expiry. The background sync detects and cleans up orphaned/deactivated sessions.
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

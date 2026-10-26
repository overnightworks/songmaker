# Songmaker Security

The auth layer itself is not in this repository. `webauth` ships as the
distribution `overnightworks-webauth` from
[overnightworks/webauth](https://github.com/overnightworks/webauth), pinned in
the `server` extra to the release wheel of tag `v0.20.1` and hash-locked in
`uv.lock` (#879, #1765). Module names below such as `webauth.dependencies` are its
import paths; which of songmaker's paths each policy applies to remains
songmaker's decision, built in `request_policies.py`.

The provider layer is likewise not in this repository. `agent_providers` ships
as the distribution `overnightworks-agent-providers` from
[overnightworks/agent-providers](https://github.com/overnightworks/agent-providers),
pinned bare in the `server` extra to the release wheel of tag `v0.1.3` and
hash-locked in `uv.lock` (#886). Module names below such as
`agent_providers.claude.provider` are its import paths; the runtime values it
runs on — binaries, credential mirrors, secret-scrub list, the sandbox
directory names — remain songmaker's decision, installed through
`ProviderRuntimeConfig`.

## Authentication

People sign in through the operator's Keycloak realm (OpenID Connect, authorization code with PKCE); songmaker holds no password, no password hash and no admin bootstrap. `GET /login/oidc?next=` starts the sign-in with a pending-login cookie, `GET /auth/callback` finishes it, `POST /auth/logout` ends it. After sign-in songmaker's own signed session cookie, backed by a DB row, is the credential; the realm is consulted only at sign-in and sign-out.

- **Relying party**: `OIDC_ISSUER` and `OIDC_CLIENT_ID` come from the environment; the endpoints are derived from the issuer. The ID token's issuer is bound to the configured realm, so a token from another realm is refused. The settings are validated where the web relying party is built, so the workers and the migrate step start without them; a missing or unreadable client secret stops web and names only the path. `PUBLIC_BASE_URL` is also required: the redirect and post-logout addresses are built from it.
- **Client secret**: the edge owns the file `~/.secrets/keycloak/clients/songmaker`. Compose mounts it read-only into `songmaker-web` alone, as the file-backed secret `keycloak_client_secret` at `/run/secrets/keycloak_client_secret`; `OIDC_CLIENT_SECRET_FILE` names that path. It is in no environment variable, log or response. The agent-CLI child processes of the web container run as the same OS user and can read the file; this is the accepted single-user trust model ([Trust model](#trust-model-and-accepted-risks)), not a boundary.
- **Admission**: the ID token must carry the group `/apps/songmaker` or the sign-in ends at `/no-access` with no account, session or cookie. The group `/apps/songmaker/admin` makes the account an admin; both are re-read at every sign-in, so a promotion or demotion applies at the next sign-in. The account id is the Keycloak subject. An existing row whose id equals the subject is reused, otherwise a fresh account is created, and the username is display text only (it is not unique, and it is cut to the column length of 100 characters). Account creation and role changes are written to the audit trail without a person.
- **Callback outcomes**: success is a 303 to the validated `next` (a path of this app, else `/`); a non-member is a 303 to `/no-access`; every other refusal (state mismatch, expired or missing pending login, foreign issuer, token-exchange failure) is a 403 carrying the SPA shell, "Login failed" and a "Try again" link to `/login/oidc`. The library clears the pending-login cookie that the submitted state names (foreign issuer, expired login) and leaves the others, so a callback with an unknown state keeps another tab's pending login intact until it expires. Admission and the new session are one database transaction under the write lock, committed before the cookies are issued, so a failed commit leaves no cookie, account or session. `/login/oidc`, `/auth/callback` and `/auth/logout` answer `Cache-Control: no-store`, refusals included.
- **Session tokens**: `secrets.token_urlsafe(32)` — 256-bit entropy, stored in the DB.
- **DB session authority**: Every authenticated request loads the session and account from the DB; the library checks the stored idle expiry and the absolute age from `created_at`. Renewal must update an existing row (`touch()` returns `True`); a missing or revoked row cannot be recreated.
- **HMAC-signed cookies**: Session cookies are `{session_id}.{hmac_sha256}` signed with a server-side secret. A DB leak alone does not yield usable cookies. The secret comes from the `SESSION_SECRET` env var (min 32 chars) and is required at startup — Settings raises `ValidationError` if missing. There is no auto-generation fallback.
- **Cookie flags and names**: The session cookie is `HttpOnly`, `SameSite=Strict`, `Secure` when `COOKIE_SECURE` is true (the default). The session and CSRF cookies are then named with the `__Host-` prefix (`__Host-session_id`, `__Host-csrf_token`), which a browser accepts only on a `Secure` cookie carrying no `Domain`. The CSRF cookie is deliberately not `HttpOnly`: the client reads it back into a header. The library's pending-login cookie is `SameSite=Lax`, because the return from Keycloak is a cross-site navigation, and the logout hint cookie is `__Secure-`, `HttpOnly`, `Strict` and scoped to the logout path. `COOKIE_SECURE=false` drops `Secure` and the `__Host-` prefix together, for local plain-http development and the CI stack; production never sets it false.
- **Session lifetime**: `SESSION_IDLE_SECONDS` (default 7 days) is renewed by every authenticated request, including `GET /api/auth/me`, up to `SESSION_ABSOLUTE_MAX_AGE` (default 30 days) from `created_at`. The cap per account is `MAX_CONCURRENT_SESSIONS_PER_USER` (default 10); a sign-in ends the session its request carried and prunes only the oldest overflow.
- **Logout**: `POST /auth/logout` is a same-origin fetch. It deletes the DB session, commits, clears all three cookies and answers `{logout_url}`: Keycloak's end-session address, with the ID-token hint when the browser still holds one. The SPA then navigates to it, which ends the Keycloak session too and returns to `/login` ("You are logged out."). The route is exempt from the CSRF token (a signed-out browser must be able to clear its cookies) but not from the origin check. Without a session it still clears the cookies and answers a `logout_url`; the hint is read from its own cookie independently of the session, so it is present whenever the browser still holds it.
- **Session cookies of the old login**: the 0.14 library's cookies are refused (`401`); the migration also deletes every session row.
- **Frontend auth-check classification**: A non-public 401 navigates the whole page to `/login/oidc?next=…`; the public paths (`/shared/*`, `/share/*`, the legal pages) never redirect. A 429, a 5xx or a network error on the SPA's startup `GET /api/auth/me` is transient: the known session state is kept and the layout shows a retry-able error instead of forcing a sign-out.

### Keycloak outage

Signed-in requests never call Keycloak: the session is songmaker's own, so the app, generation, scoring and the co-writer keep working while the realm is down. Web boots without reaching the issuer. During an outage a new sign-in fails at the browser (the redirect to Keycloak does not load) or, when the failure happens while songmaker exchanges the code, ends in the "Login failed" page; sign-out ends the songmaker session and the redirect to Keycloak then fails in the browser. Existing sessions are not affected.

### Revocation

Keycloak is the account owner, but songmaker applies its answers only at sign-in. Disabling a user or removing them from `/apps/songmaker` ends nothing by itself: a session stays valid until it goes idle for `SESSION_IDLE_SECONDS` or reaches `SESSION_ABSOLUTE_MAX_AGE`, and continued use renews it, so the bound is the absolute age (30 days by default), not the idle time. Two ways to end access now:

1. Sign out in Keycloak or in songmaker: `POST /auth/logout` on that device ends that device's session and the Keycloak session, and a sign-out at Keycloak ends every songmaker session of that account through the back channel (below).
2. Delete the sessions in the database: `DELETE FROM user_sessions WHERE user_id = '<subject>';` (all of them: `DELETE FROM user_sessions;`). The next request is a 401.

**Back-channel logout.** Keycloak posts a signed Logout Token to `POST /auth/backchannel-logout`, and songmaker ends every session of the token's subject (`webauth.oidc_login.receive_backchannel_logout`, audited as a `delete` of resource `session` without a person). The token must be a `logout+jwt` of the bound issuer for this client, carry the back-channel logout event and a `sub`, and no `nonce`; the realm client sets `backchannel.logout.session.required` to `false` because `sid` is ignored. The route answers 200 only after the commit and 400 for any refusal or failure, in its own worker-thread session and transaction. The boundary is the Logout Token's signature (webauth verifies the issuer's RS256 key, `typ`, `aud`, age, event, `sub` and the absent `nonce`) and the edge's public deny of the path. The Host check only filters routing: the realm posts to `<PUBLIC_BASE_URL host>:8080` on the external network `hal_backchannel_songmaker` (declared `external: true`, created by the edge stack, joined by `songmaker-web` alone, which carries the public host as its alias there); any other admitted Host, the public host without the port and `songmaker-web:8080` included, gets an empty 404, an unlisted Host gets TrustedHost's 400, and the body is capped at 32 KiB. The exact path is exempt from the rate limit and from the origin check, and from nothing else; a variant such as `/auth/backchannel-logoutx` is not. A logout that completes before a later sign-in cannot end that later session; this limit is accepted. Three residues are accepted: webauth keeps no `jti` store, so a token can be replayed within its short validity window (about two minutes); a transient failure answers 400, is logged and is not retried, so the session lasts until its idle or absolute bound; and the origin and rate-limit middlewares match `request.url.path`, so `%3F` and `%23` path variants count as exempt but route to the SPA shell, which ends no session (owner: webauth).

### Rollback

A deploy that must be undone is undone by restore (`scripts/backup.sh` and `scripts/restore.sh`, which need both the database and the audio files): the migration drops the password-era columns and tables and its downgrade recreates them empty. Restore the paired database and audio backup taken before the deploy, then deploy the previous revision.

## Authorization

Two-layer defense:

1. **Dependency-based auth** (`webauth.dependencies`, bound to songmaker's stores in `auth_dependencies.py`): `get_current_user` validates the signed cookie and the DB session, checks expiry and lifetime, and renews the existing row with an update-only `touch`, so a session deleted meanwhile stays deleted. Its own short transaction commits renewal before the endpoint runs, without committing endpoint writes. Manual stream callers commit and close their authentication transaction before starting the stream.
   The logout route does not depend on `get_current_user`: the library's `log_out` reads the session cookie itself, deletes the stored session it names, and clears the cookies either way; the route then commits.
2. **Endpoint** (`api.py`): Authenticated resource endpoints use `Depends(get_current_user)` and return 401 if unauthenticated. The sign-in routes are deliberately unauthenticated; worker control-plane routes under `/api/internal/*` use the internal token instead of sessions. Ownership checks enforce default-deny: access is blocked unless the resource belongs to the user (or the user is admin). Missing resources are denied.

Roles: `Literal["admin", "user"]` — validated at the Pydantic schema level. No other role values are accepted by the API. The role is set from the Keycloak admin group at each sign-in; there is no in-app account administration.

Generation invalidation history is partitioned by `user_id` in PostgreSQL. Its
monotonic sequence allocator and event row participate in the same transaction as
the generation, with unique constraints on `(user_id, sequence)` and
`(kind, generation_id)`. Cursor and event rows cascade only with their owning user;
historical song/generation identifiers are intentionally not foreign keys. The
authenticated SSE endpoint reads only the exact authenticated user partition; admin
role does not bypass this filter and frames contain no user ID. Authentication and
the initial cursor reads finish in a function-local DB session before streaming
begins. Polls use independent short sessions, and every connection ends after at
most 60 seconds so session expiry or revocation is enforced on reconnect.

## Proxy trust

`TRUSTED_PROXIES` is a comma-separated list of IP addresses and CIDR networks
(default: empty — no peer is trusted; the Docker deployment sets
`172.16.0.0/12`, the bridge-network range the tunnel's container gateway sits
in). `app_context.parse_trusted_proxies()` turns each entry into an
`ip_network` at startup and puts the result into the `WebAuthConfig` the
application installs, and a peer is trusted when its address falls inside one of them — so
`172.16.0.0/12` covers the gateway address `172.18.0.1`, and a bare
`10.0.0.1` covers only itself. An entry that is not a valid address or
network (including one with host bits set, like `10.0.0.1/24`) raises at
startup rather than being carried along as a rule that can never match. An
entry carrying an interface zone (`fe80::1%eth0`) is rejected too: a zone is
local to one host and is dropped when an address is matched against a network,
so the entry would silently widen to every interface.

That decision governs `X-Forwarded-For`: it is read for the real client IP
(rightmost untrusted entry) — every per-IP budget and
the access log use that address; from an
untrusted peer the header is ignored and the direct peer address is used.
`X-Forwarded-Proto` is read the same way for `request_is_https()` (used by
share-link scheme resolution, see #339 below), but since webauth v0.11.0 it no
longer decides the cookie `Secure` flag or `Strict-Transport-Security`: both
follow the deployment's static `COOKIE_SECURE` setting instead — see
"Authentication" above.

`webauth.proxies.resolve_client_ip()` and `webauth.proxies.request_is_https()`
own both decisions and read the trusted networks from the installed
`WebAuthConfig`; no endpoint or middleware reads those headers itself. The chain is read from
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

Five-layer defense:

1. **`SameSite=Strict` cookies**: Prevents cross-site cookie transmission in modern browsers
2. **Session-bound CSRF token**: The sign-in callback sets a `csrf_token` cookie (`__Host-csrf_token` when `COOKIE_SECURE` is true, non-HttpOnly, `SameSite=Strict`) whose value is `HMAC-SHA256(session_secret, "csrf:" + session_id)`. All mutating `/api/` requests and `POST /auth/logout` (except the logout, which needs only the origin check, and the internal worker routes) must include an `X-CSRF-Token` header. The token policy lists its protected set explicitly (`/api/` and the exact logout path), so the sign-in routes are never token-checked. The server verifies the token by recomputing the HMAC from the current session — it does not trust the cookie value. This prevents subdomain cookie injection attacks (where a sibling subdomain sets a forged cookie).
3. **Origin verification**: When `Sec-Fetch-Site` is absent or `same-site`, every state-changing request (not only `/api/` and the sign-in routes: the `/shared/*/stream` share manifests too) with an `Origin`/`Referer` header that doesn't match `ALLOWED_HOSTS` (or localhost by default) are rejected (403). Uses a server-side allowlist instead of the request's `Host` header to prevent header-spoofing bypasses.
4. **Form-submit blocking**: On that same fallback path, mutating requests without `Origin`/`Referer` are rejected if their `Content-Type` is a form type (`application/x-www-form-urlencoded`, `multipart/form-data`, `text/plain`). This blocks HTML form CSRF in browsers that don't enforce SameSite, while allowing JSON API clients (fetch).
5. **Fetch metadata**: `Sec-Fetch-Site` is checked before the Origin allowlist. `same-origin` passes the origin check; `cross-site` and `none` are rejected (403), even with an allowed Origin. `same-site` and a missing header follow the Origin/Referer allowlist and form-submit rules above. The session-bound token is still required. The internal worker routes remain token-exempt but still follow this origin check. [Server tests](../tests/test_server.py) prove the accepted and rejected header cases.

### History: deliberate changes with the webauth migration (#905)

- The per-IP middleware starts fresh budgets once at deployment because its Redis keys change to the class-qualified names documented below. Session keys, stored data and rights are unchanged.
- The fetch-metadata check above hardens mutating `/api/` requests. Songmaker's frontend is same-origin; CLI and workers omit `Sec-Fetch-Site` and keep their existing behavior. A cross-site browser client cannot make these mutations, even when its Origin is configured.
- Logout clears both cookies with `SameSite=Strict`, previously Starlette's `lax`. The header text changes; deletion still matches the same cookie name, domain and path. The logout behavior remains covered by [auth API tests](../tests/test_auth_api.py); no test pins this deletion attribute.

### History: deliberate changes with webauth v0.11.0 (#1320)

- The session and CSRF cookie names are no longer request-scheme-dependent: they are fixed at startup from the static `COOKIE_SECURE` setting (`__Host-session_id` / `__Host-csrf_token` when true, `session_id` / `csrf_token` when false). `X-Forwarded-Proto` and `TRUSTED_PROXIES` no longer influence the `Secure` flag or `Strict-Transport-Security`; see "Authentication" and "Proxy trust" above.

### History: deliberate changes with webauth v0.19.0 and v0.20.0 (#1765)

- Sign-in moved from a password form to Keycloak; the password hasher, the login-attempt budget and the account lockout left with it, and the migration `7c3e91d0a4b2` dropped `users.password_hash`, `users.is_active`, `login_attempts` and the session origin columns (`ip_address`, `user_agent`), and the unique index on `users.username`. Every session row was deleted, so everyone signed in again once.
- With v0.20.0 the session row holds the issuer's refresh token in `user_sessions.refresh_token` (added by the same migration; `NULL` when the issuer gave none, for example in seeded e2e sessions). It is a secret at rest: the column holds it as plain text (it is in the database dump), the `UserSession.refresh_token` property hands it out only as a `SecretStr`, the engine hides SQL parameters (`hide_parameters=True`) so a failed insert keeps it out of the traceback, and no response, log line or `/health` carries it; the only session-related response is a count of active sessions. It leaves with the row on logout, expiry, pruning and revocation. Nothing in songmaker renews an access token with it yet (`replace_refresh_token` stores a rotated token for the library's `fresh_access_token`, which no route calls).
- The Host check is songmaker's own `TrustedHostMiddleware` over `ALLOWED_HOSTS` (the library's host lists are Origin allowlists only). A request for another Host is answered 400. Compose always appends `localhost`, `127.0.0.1` and `songmaker-web` to the list, because the container health check, the ACE-Step control plane and Prometheus call the web service by those names; the public host still comes from `ALLOWED_HOSTS`.

## Rate Limiting

### Per-user (API endpoints)

| Resource     | Limit             | Scope    |
|-------------|-------------------|----------|
| Generation   | 30 / hour         | Per user |
| Scoring      | 100 / hour        | Per user |
| Chat         | 300 / hour        | Per user |
| Queue depth  | 100 total         | Global   |
| Active jobs  | 10 concurrent     | Per user |

Every account has the same limits; the operator sets them globally or per user in settings.

Rate limit checks and job creation are atomic (`BEGIN IMMEDIATE`) to prevent TOCTOU races where concurrent requests bypass limits.

### Shared endpoints (public, no auth)

Album, song, generation, and playlist shares expose public read-only endpoints with a dedicated per-IP rate limiter (default: 60 requests/minute, configurable via `SHARED_RATE_LIMIT`):

| Resource | JSON endpoint | Audio endpoint |
|----------|---------------|----------------|
| Album | `/shared/{slug}` | `/shared/{slug}/audio/{generation_id}.mp3`, `/shared/{slug}/cover` |
| Song | `/shared/song/{slug}` | `/shared/song/{slug}/audio/{generation_id}.mp3`, `/shared/song/{slug}/cover`, `/shared/song/{slug}/album-cover` |
| Generation | `/shared/gen/{slug}` | `/shared/gen/{slug}/audio/{generation_id}.mp3`, `/shared/gen/{slug}/album-cover` |
| Playlist | `/shared/playlist/{slug}` | `/shared/playlist/{slug}/audio/{generation_id}.mp3`, `/shared/playlist/{slug}/cover`, `/shared/playlist/{slug}/album-cover/{album_id}` |

Album and song shares serve the picked unarchived generation when one exists, otherwise the latest unarchived generation. Generation shares serve the shared generation. Playlist shares expose audio only for playable entry generations. Their page manifest supplies a playlist `cover` only when its uploaded file exists, otherwise up to four `album_covers` from its entries. Those mosaic URLs remain bound to the playlist share slug: the public route accepts an album only when it belongs to that shared playlist and its requested version key is current; it never redirects to or reveals a private `/api/albums/{id}/cover` URL. Stream manifests likewise contain only playable takes and no cover fields, so every listed audio URL is authorized to return bytes. `create_generation()` canonicalizes every non-empty MP3 path at the single write boundary and rejects a path that would leave the audio root; WAV-only takes retain their empty MP3 sentinel. Public audio addresses name the take (`{generation_id}.mp3`) and never contain the stored path or the creator's account id; JSON assembly builds them without filesystem resolution, and an old account-prefixed stored-path address answers `404`: authorization uses the take's identity, and a root-level stored file named `{generation_id}.mp3` is the new address itself. Operators must run `scripts/audit_generation_audio_paths.py` once before deploying this boundary to identify legacy rows. The audit never changes rows: each reported ID must be reimported when its source is known, or archived until its file identity can be established, because blindly normalizing an old filename can attach a take to the wrong recording. Public JSON responses omit scores and edit history; an audio URL is present only when its stored relative path is already canonical and remains below the audio root. A noncanonical stored path is a data defect: it is not silently repaired, is omitted from the response, and is logged at `WARNING`. Album JSON includes `cover` only while the album is shared and the cover file exists. Song JSON includes `cover` only while the song is shared and the **song** cover file exists. Song and generation JSON include `album_cover` only while their own share remains public and the parent album cover file exists. Public cover bytes are served through the matching album, song, generation, or playlist share slug — never a client-supplied path on `/audio/{owner_id}/{filename}`. Unshare, replace, or delete 404s the previous public cover URL. Share slugs are UUID v4 values (122 bits of entropy, unguessable). Sharing is revocable by the resource owner.

`audio_paths` owns stored-audio path resolution: queue-stream assembly uses
`resolve_audio_path()`, while the album, song, and playlist shared-audio
handlers parse the take id from the requested name and authorize that take's
membership in the share by id with one scalar query. Only a take that passed
yields its canonical stored path, which is then checked for an existing file
below the audio root before bytes are delivered. A take outside the share
(even one stored in the same file as a presented take), a name that is not a
take id, a missing file, and a path that would escape the audio root (including
through a symlink) all return the indistinguishable visitor response `404 Not
Found`. Traversal rejection is logged at `WARNING` without the caller-supplied
path.

### Per-IP (global middleware)

Every request is subject to a global per-IP rate limit, split into three budget
classes (issue #257) so that one traffic pattern cannot exhaust the budget
another pattern from the same IP needs. `RateLimitPolicy.classify`
(`webauth.policies`) is the single place that maps a path to a class, and
the paths it reads are songmaker's own, built by
`request_policies.build_rate_limit_policy` and installed on the middleware in
`server.create_app`; every request gets exactly one class, and an unrecognized
path falls back to the API class — fail closed, not fail open. Each class is a
Redis sliding-window counter (`webauth.rate_limit.RedisRateLimitBackend`,
supplied as `WebAuthConfig.rate_limits`) over its own 60-second window. Keys
are `rl:ip:API:<ip>`, `rl:ip:MEDIA:<ip>` and `rl:ip:STREAM:<ip>`, so exhausting
one class's counter never touches another's. These replace `rl:ip:<ip>`,
`rl:ip-media:<ip>` and `rl:ip-stream:<ip>` respectively. Direct sharing, queue
stream and resource-event limiters retain their existing `prefix:key` keys;
each call supplies its limit and window, and `Retry-After` remains that window.

| Class  | Paths | Default | Why |
|--------|-------|---------|-----|
| API    | Everything not matched below (including `/health` and unrecognized paths) | 120/min | Unchanged from the original single budget. `/health` is deliberately **not** exempt: it is the most expensive anonymous endpoint (a DB query plus roughly six Redis round trips for worker/queue state) and the only caller is the browser's 15s poll (~4/min) — exempting it would let an anonymous caller hammer the priciest endpoint for free. |
| Media  | `/audio/*`; every `/shared/**/audio/*` and `/shared/queue-streams/{id}/audio` route | 600/min | Range-request media playback is normal use, not abuse: a single MP3 played with normal seeking is **estimated** at roughly 40 range requests (order-of-magnitude from typical browser Range-chunking, not measured), and comparing takes can move through several songs a minute (40 × 5 = 200/min in ordinary use). 600 leaves headroom for aggressive seeking while still bounding an IP's disk I/O — not unlimited. All of these paths serve a `FileResponse` (Range-capable) — the public share audio routes carry the same seek/scrub pattern as the owner's own player, just from a stranger listening to a public share, so they get the same class. The policy matches each share-audio route with a regex anchored on the literal `audio` segment at the position that route defines, so a slug that literally reads `audio` cannot pass as one by shape alone. The metadata routes on the same slug — `/shared/{slug}`, `/shared/song/{slug}`, `/shared/gen/{slug}`, `/shared/playlist/{slug}`, every one of their `/cover` routes (song and album cover are both API, deliberately, not just the album one), and the `/stream` manifest POSTs — are deliberately excluded and stay API: only the byte-serving audio routes are Range-served. |
| Stream | `/api/resource-events/stream`, `/api/jobs/*/stream` | 45/min | SSE connection *opens*, not per-message traffic, sized between the legitimate worst case and the observed storm rate. Legitimate worst case: a normal page load opens one resource-events stream plus one job stream per active job; at the `max_user_active_jobs` default (10) that's 11 opens/load, and 3 page loads within a minute (full queue, operator reloads) is 33. Storm rate: the operator incident's reconnect storm, from job streams that reopened with no delay at all, ran at roughly 80 opens/min. Client pacing (`nextReconnectDelayMs` and `watchReconnectOpportunities` in `frontend/src/lib/stores/sseReconnect.ts`, constants in `frontend/src/lib/constants.ts`): a failing stream reopens after 2, 4, 8, 8… s — an 8 s ceiling plus 0–20% jitter, so no wait exceeds 9.6 s, because the #1032 ruling caps how long a take may lag the network's return at 10 s — and at once when the page becomes visible, regains focus, or the browser reports `online`. That is 8 reopens per failing stream in its first minute and 7.5/min after. After `JOB_STREAM_MAX_CONNECTION_ERRORS` (25) consecutive errors of its timed retries while the page is online, about three minutes, a job stream reads its job once over `GET /api/jobs/{id}` instead of dropping it: an ended job finishes, a running one keeps its card and its stream goes on at the same ceiling pace with a fresh count (#1141). An immediate reopen on return and a failure while the page is offline never count, and a stream that opens resets the count, so neither returning to the app nor any number of outages drops a running take; the one resource-events stream keeps retrying under its own per-user limit below. The reported incident's 5 failing streams (four job streams plus the resource stream) cost 40 reopens in the first minute and 37.5/min after — under this budget. **Accepted over-budget case:** at the theoretical ceiling of 11 concurrently failing streams the pacing alone asks for 88 reopens in the first minute and 82.5/min after — above both this 45/min budget and the 80/min storm rate it was sized against. The limiter, not the client, holds the budget there: every open past 45/min gets a 429, a 429 to an `EventSource` is fatal per spec (no browser auto-reconnect), so each stream counts it as one more failed attempt and waits out its own backoff, and a job stream re-reads its job over REST at 25 errors rather than reopening any faster. The API and Media classes are separate buckets, so the rejected opens never block API calls or playback. That is the price of a take arriving within seconds of the network's return (#1032). The budget itself is sized against page loads, not reconnects: 45 sits clearly above 33 and clearly below 80 — there is no live dependency on `max_user_active_jobs`; raising that setting should prompt re-checking this math, not a settings cross-reference. The resource-events endpoint additionally enforces its own tighter per-user open limit (`RESOURCE_EVENT_STREAM_OPEN_LIMIT`, see below). |

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

When the request arrives from a peer inside a `TRUSTED_PROXIES` network, the rate limiter uses the real client IP from `X-Forwarded-For` (rightmost untrusted entry), as every per-IP budget does — see "Proxy trust". Without it every visitor behind the same proxy shares one budget. If Redis is unavailable, the rate limiter fails closed (returns 503 with `Retry-After: 5`) rather than allowing all requests through.

Configure via env vars: `GENERATION_RATE_LIMIT_USER`, `SCORING_RATE_LIMIT_USER`, `CHAT_RATE_LIMIT_USER`, `MAX_QUEUE_DEPTH`, `MAX_USER_ACTIVE_JOBS`, `IP_RATE_LIMIT`, `MEDIA_RATE_LIMIT`, `STREAM_RATE_LIMIT`, `RESOURCE_EVENT_STREAM_OPEN_LIMIT`.

### Resource-event streams

The global IP limit is supplemented by a fail-closed per-user opening limit,
`RESOURCE_EVENT_STREAM_OPEN_LIMIT` (default 12 streams per minute, unchanged
in production); rejected attempts are not retained in the bounded Redis
window. CI overrides it to 200 in `docker/docker-compose.ci.yml`, the same shape as
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
`api_stream_resource_events`; auth (`authenticate_request(request, session)` from `auth_dependencies.py`)
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

`SecurityHeadersMiddleware` (`webauth.middleware.security_headers`) writes
them; the CSP line, its inline-script hashes, and which paths may be cached
come from songmaker's `SecurityHeadersPolicy`
(`request_policies.build_security_headers_policy`).

All responses include:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Content-Security-Policy: default-src 'none'; base-uri 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self'; manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; form-action 'self'` (`script-src` also lists the hash of each inline script in the built `index.html`). The SvelteKit build applies inline styles, so `'unsafe-inline'` is the one source songmaker adds to webauth's default policy, in `request_policies.build_security_headers_policy`; no external host is allowed.
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains` (present whenever `COOKIE_SECURE` is true, the default; absent when it is false — see "Authentication")
- `Cache-Control: no-store` (API responses only — prevents caching of authenticated data). The exact resource-event SSE path uses `no-cache, no-store` so intermediaries do not cache or transform its reconnect stream; other API and SSE paths retain `no-store`.
- `Cache-Control: private, max-age=31536000, immutable` on generation audio: `/audio/*` and every `/shared/**/audio/*` route (`sharing_api.py`). A generation file never changes under its name, so the listener's browser keeps it for a year, while `private` forbids any shared cache (CDN, proxy) from holding it. Consequence: a revoked share stays playable from that listener's own browser cache. Queue-stream snapshot audio is not a generation file — it expires within hours — so `/shared/queue-streams/{id}/audio` sends `no-store`.

## CORS

- **Methods**: `GET`, `POST`, `PUT`, `DELETE` (no wildcard)
- **Headers**: `Content-Type`, `Cookie`, `X-CSRF-Token` (no wildcard)
- **Credentials**: Allowed
- **Origins**: The normal interface calls the API under the same origin, so it needs no CORS permission. A deliberately separate trusted browser client may set `CORS_ORIGIN` to its one literal origin, but cross-site browsers cannot make mutating `/api/` calls because the fetch-metadata check rejects them even with CORS permission; startup rejects wildcards and comma-separated lists. `SameSite=Strict` does not isolate sibling subdomains of the same site, so do not trust a credentialed subdomain wildcard. When unset, CORS defaults to `localhost`/`127.0.0.1` on ports 8080 and 5173 only for dev (not any arbitrary port).

## Error Handling

- **Generation, scoring, and LoRA job errors**: `_sanitize_error` maps known worker and setup doses to fixed musician-facing messages and logs raw failures with the job ID only on the server; generation, scoring, and LoRA store that returned message in `job.error` (`jobs/_runtime.py:38-45,62-78`; `jobs/generation.py:473-483`; `jobs/scoring.py:194-213`; `jobs/lora_training.py:506-515,618-631`). Raw reasons live in the service's JSON container log, retained as five rotated 10 MB files.
- **API errors**: HTTPException messages on ordinary validation paths are human-readable strings with no internal paths or stack traces (`settings_api.py`); the model-catalog failure path now uses a fixed message (`settings_api.py` `_cowriter_response` and `_judge_response`, which show the catalogue's fixed failure message or `PROVIDER_MODEL_CATALOG_UNVERIFIED`; #476 closed).
- **Validation errors**: The custom `RequestValidationError` handler returns only affected field names, not full Pydantic error details (constraints, expected types, internal schema) (`server.py:273-290`).
- **ACE-Step errors**: Worker failures map through `_sanitize_error` to a fixed message before the generation job persists `job.error`; only the silent-stream dose stays distinct (`jobs/_runtime.py:38-45,62-78`; `jobs/generation.py:469-480`).
- **Claude CLI errors**: Chat paths log the exit code and stderr length, not stderr itself (`agent_providers/claude/provider.py:253-258,343-348,1905-1910,1968-1973`). The live co-writer emits an SSE event with `status: 503` and `<provider> is currently unavailable` on an otherwise HTTP 200 response (`conversation_api.py:556-564,620-625`). The model catalog passes the fixed HTTP-facing dose through the catalog adapter after #476 closed (`agent_providers/catalog.py`; `settings_api.py` `_cowriter_response` and `_judge_response`).
- **OpenAPI/docs**: Disabled (`server.py:167`).

## Request Size Limits

Songmaker itself enforces these limits: `BodySizeLimitMiddleware` (`webauth.middleware.body_size`, raw ASGI) first checks `Content-Length` for fast rejection, then wraps the receive channel to count bytes as they stream in — aborting with 413 once the limit is exceeded without buffering the entire body. Which route may exceed the default, and by how much, is songmaker's `BodySizePolicy` (`request_policies.build_body_size_policy`).

JSON API requests are capped at 1 MiB (`MAX_REQUEST_BODY_BYTES`). Large multipart uploads use a path-exact allowlist, not a suffix match:

| Path | File budget | Multipart body budget |
|---|---|---|
| Default JSON | — | 1 MiB |
| `POST /api/audio/upload` | 50 MiB per file | 50 MiB + 1 MiB envelope |
| `POST /api/loras/{lora_id}/samples` | 50 MiB per file | 50 MiB + 1 MiB envelope |
| `POST /api/songs/{song_id}/reimport` | two audio files | 100 MiB + 1 MiB envelope |
| `POST /api/albums/{album_id}/cover` | 8 MiB per image | 8 MiB + 1 MiB envelope |
| `POST /api/songs/{song_id}/cover` | 8 MiB per image | 8 MiB + 1 MiB envelope |
| `POST /api/playlists/{playlist_id}/cover` | 8 MiB per image | 8 MiB + 1 MiB envelope |

File limits and body limits are separate so a legal 50 MiB file is not rejected for multipart headers. `POST /api/loras/{id}/samples/{sample_id}` is not a large-upload path.

### Reference audio upload

`POST /api/audio/upload` accepts audio files (.mp3, .wav, .flac, .ogg) up to 50 MiB (52,428,800 bytes) per file. Files are stored in `{audio_dir}/{user_id}/refs/{uuid}.{ext}` — the UUID filename prevents name collisions and path injection. Each user also has a positive aggregate quota: `reference_audio_quota_bytes=500_000_000` (decimal 500 MB) and `reference_audio_quota_files=50`. Admission inventories every regular file, including retained references, unused uploads and crash remnants. Existing overage refuses additions without deleting anything. The exact quota refusal is HTTP 409, `{"detail":"Reference audio storage limit reached."}`; the previous draft reference survives. A full user has no self-service cleanup in this slice (#1301 R2 owns cleanup); the operator can raise these settings.

`reference_audio.py` owns the synchronous operation and its database session. A PostgreSQL transaction-scoped advisory lock keyed by namespace and user (SQLite: `BEGIN IMMEDIATE`) covers inventory through completed exclusive file creation, including after request cancellation. It does not lock the user row, so unrelated writes referencing that user can proceed. Waiting uploads hold database connections; the existing upload rate limit bounds this accepted cost. Future reference cleanup must acquire the same owner lock.

Symlinked ancestors or files, unexpected nesting, nonregular entries and unreadable inventory fail closed with HTTP 500, `{"detail":"Reference audio storage could not be checked."}`. This refusal also covers the configured `audio_dir`'s own ancestors. Logs identify the user and entry/error kind without content. A failed write removes only its own partial file under the lock; cleanup failure is surfaced and surviving regular bytes count on the next admission.

The `reference_audio_path` field on `GenerationParams` is validated at three levels:

1. **API validation**: Pydantic validator rejects any value containing `..`
2. **Song write**: the path must resolve under `{audio_dir}/{authenticated_user_id}/refs`
3. **Job execution**: the same owner-root resolver runs again; a foreign, symlink, or missing path fails the job instead of falling back to no reference

### Album, song, and playlist cover upload

`POST /api/albums/{album_id}/cover`, `POST /api/songs/{song_id}/cover`, and `POST /api/playlists/{playlist_id}/cover` accept JPEG and PNG only (SVG and WebP are rejected). The server checks magic bytes, decodes with Pillow, applies EXIF orientation, and strips metadata before writing. Named pixel and byte ceilings reject decompression bombs. Card and detail derivatives are written at upload time; GET never resizes. Album files live at `{audio_dir}/covers/{album_id}/`; song files live at `{audio_dir}/song-covers/{song_id}/`; playlist files live at `{audio_dir}/playlist-covers/{playlist_id}/`. Authenticated GET/POST/DELETE use `check_album_access`, `check_song_access`, or the matching playlist ownership check (foreign resources 404). Authenticated and public song cover endpoints stream only that song's files — 404 when the song has no own cover, even if the parent album has one. Public bytes use the matching share slug. The song- and playlist-cover body budgets are the cover ceiling; neither is the `/api/songs/{id}/reimport` ceiling.

Album cover suggestions are private rows bound to an album and its cover job. Every suggestion endpoint applies `check_album_access`; missing, foreign, malformed, and unsafe stored paths return the same 404 response. A suggestion path must equal `cover-suggestions/{album_id}/{suggestion_id}.png` under the audio volume, and selection passes the validated PNG through the existing album-cover writer. Suggestions have no public or share URL. Discard deletes database rows before their files, while album hard-delete removes the sibling suggestion tree after commit; neither action removes the selected `cover_key` image. The web container is the sole production cover executor: its runner claims queued jobs, owns recovery, and resolves the admin-selected cover provider, route, and model only through the co-writer dispatch owner; a selection without an image tool ends the job named, and no path falls back to an HTTP image API. Each image call receives a new private `CODEX_HOME` containing only a copied login mirror; the bounded runner gets that path through its child-only environment, reaps the CLI, then accepts exactly one PNG found beneath that private tree. The image command uses the fixed read-only image argv with Code Mode host enabled only for that run, no MCP servers, and web search disabled. Its streamed-event gate permits `image_gen` and exactly one measured `command_execution` start/completion pair that reads the bundled image skill; any other command or tool event fails the job with the fixed image-tool message. Pillow rewrites its exactly one accepted PNG as a metadata-free 1024×1024 RGB PNG. The stdin-only prompt quotes album values as data, limits each track's style and lyrics excerpts to 500 characters, and limits the complete prompt to 6,000 characters.

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

- **System prompt**: Hardcoded server-side (`build_cowriter_system_prompt()` in `conversation_api.py`). Clients cannot override it. Song, memory, and mention context is wrapped in XML tags, and `COWRITER_UNTRUSTED_NOTICE` instructs the model to treat everything inside those tags and all tool outputs as untrusted data and never follow instructions found there.
- **Co-writer authorization**: All twelve shared tools require album ownership, including for administrators, through both MCP and in-process dispatch. Lists and searches filter to owned resources; foreign resource IDs return not-found before creating versions, work records, songs, or cover jobs. HTTP administration retains its existing access. User-selected current-song, current-take, and @-mention context also retains admin access: an admin can load foreign context, but tool calls against it return not-found. Residual risk: foreign context or tool output can still steer writes to the admin’s own songs; the untrusted notice is guidance, while owner-only authorization enforces the foreign-resource boundary. [Ownership matrix](../tests/test_cowriter_ownership.py) pins both dispatch paths.
- **Multi-turn history**: Stored in `chat_messages` and scoped to a conversation; the co-writer applies a token budget with a rolling summary for older messages (`conversation_api.py:477-503`; `cowriter/history.py:65-76,89-144`). Ownership is enforced via `check_song_access()` on every endpoint.
- **Context built server-side**: Mentioned song/version IDs are sent by the frontend, but the backend resolves them from the DB — the client never sends raw context. Each mentioned song is ownership-checked.
- **CLI backend, every call shape**: `_build_mcp_cli_cmd()` (the co-writer, MCP tools attached) and `_build_cli_cmd()` (the lyrical-coherence judge, no tools at all) both apply `--tools ""` (removes the CLI's entire built-in tool set, so a tool a future Claude Code version ships cannot be called even though nobody here has heard of it), `--setting-sources ""` (drops any profile `~/.claude/settings.json`, whose `permissions.allow` and `defaultMode` would otherwise decide what a session may do), `--strict-mcp-config` (ignores MCP servers configured anywhere but in the temporary config we write, when one is attached at all), and `--disable-slash-commands` (the CLI otherwise still resolves its own slash commands and skills from a prompt beginning with `/`; our own prompts never do, but this closes the channel rather than relying on that). The co-writer additionally gets `--allowedTools mcp__songmaker__*`, pre-approving our own MCP tools so the non-interactive session never waits for a permission answer nobody is there to give — derived from the host's `McpServerSpec`, which is also where the config file's contents, its `songmaker-mcp-` prefix and the expected tool names come from (`ProviderRuntimeConfig.mcp_server`, #837); a deployment that declares no MCP server routes its co-writer turns through `_build_cli_cmd()` and the zero-tool gate instead. No `--disallowedTools` list is kept, and `--permission-mode bypassPermissions` is gone from both — with nothing but the allowlisted tools present, there is nothing left to bypass. The two builders themselves check nothing — they format flags — which is why the next bullet is a separate mechanism, not a property of these functions.
- **Tool-surface verification, one gate per call shape, not per caller**: `_build_cli_cmd()` is reached through `_call_cli()`/`_acall_cli()`, and those two call `verify_no_builtin_cli_tools()`/`averify_no_builtin_cli_tools()` themselves before building anything — so the lyrical-coherence judge is covered by the gate without having called it itself (#351). Since #837 it has one further reach: `_cowriter_cli_command()` builds it for a co-writer turn when the host declared no MCP server (`ProviderRuntimeConfig.mcp_server is None`). That route is gated too, and by the matching expectation — `verify_cli_tool_surface()` delegates to `averify_no_builtin_cli_tools()` for exactly that case, so the shape that is verified is always the shape that runs. `_build_mcp_cli_cmd()` is reached only through the two MCP-attached entry points (`acall_claude_with_mcp`/`acall_claude_with_mcp_stream`), which call `verify_cli_tool_surface()` themselves the same way — a separate gate, not routed through `_call_cli()`/`_acall_cli()`. On a cache **miss**, the CLI is a bind-mounted binary that updates itself, so the relevant gate starts a session with exactly the flags above and reads the tool names — and the `slash_commands` list — out of the CLI's own `system` init event (`subtype` checked too, not just `type`); a cache **hit** returns the remembered verdict without starting a session at all. The co-writer's probe attaches the real `--mcp-config` and requires the reported tool set to equal, exactly, the `mcp__songmaker__*` names — a hand-maintained literal in `songmaker_cli/cowriter/mcp_spec.py`, not imported from `mcp_server/server.py` (that would pull the `mcp` package into containers that do not carry it), kept honest by a test that compares the two — not merely a subset check, so a tool going missing is caught the same way an extra one is, but an unexpected tool or a reachable slash command is *always* a permanent mismatch regardless of whether the MCP connection itself came up (a CLI reporting `tools=["Bash"]` with its MCP connection also down is confirmed dangerous, not merely unverifiable). The tool-free probe requires no tool and no slash command at all, and deliberately never attaches `--mcp-config`: registering and listing MCP tools touches no database (only a tool *call* does), so that is not why this probe stays separate — it needs the `mcp` extra, which the scoring-worker container does not install; that container does have a reachable database (it writes scores back to it), so the database is not its actual gap (confirmed live: a missing `mcp` package makes the MCP connection fail, and a failed connection reports zero tools, the same shape a clean tool-free CLI reports).
  A mismatch raises `CliToolSurfaceError` and only that call is refused, not the whole server — but a failed MCP connection with nothing else wrong is not a mismatch: it is treated as a probe failure (see below), because it reports the same empty tool list a clean, intentionally tool-free CLI would, and confusing the two used to cache "every tool missing" forever. A genuine verdict — this build's tool surface, clean or not — is cached per resolved binary build (path, size, mtime) with no expiry, since it only changes when the build does. A probe **failure** (timeout, unparseable output, or a failed MCP connection with nothing else unexpected) is cached separately, only for `CLAUDE_CLI_TOOL_SURFACE_FAILURE_CACHE_SECONDS`. A process that outlives SIGKILL is a third case, checked before parsing, the MCP check, or the verdict ever run — a clean read followed by a zombie is not trusted either. Not a verdict about the build (the build is fine; this one instance is stuck) and not an ordinary failure either — ten more seconds will not make it healthy — so it gets the much longer `CLAUDE_CLI_ZOMBIE_FAILURE_CACHE_SECONDS` instead, so the ordinary retry schedule cannot spawn a fresh zombie every ten seconds.

  Single-flight is a *published future*, not a held lock (round 5 — rounds 3 and 4 held a per-key mutex across the whole probe and spent two rounds finding a new unbounded wait inside it). The dict lock only ever guards a lookup/insert; the first cold caller for a key publishes an `asyncio.Future` (the async gates) or `concurrent.futures.Future` (`_call_cli`'s sync gate) under that lock, releases it immediately, and probes with nothing held at all, while every later caller for that key awaits the published future with its own timeout — proven with genuine concurrency (`asyncio.gather`, real threads) and an explicit "the follower reached its wait" signal, not a sleep loop or a timed `join()` guess; the future is always resolved (success, probe failure, or a bug evaluating the result), so the dict entry is never left dangling, and a cancelled leader hands followers a normal `UnavailableError`, never its own literal `CancelledError`. A sync and an async caller for the same key still do not exclude each other, since a thread future cannot be awaited without blocking the loop and an asyncio future cannot be waited on from a thread without one — an accepted, narrow gap given the only key both domains ever share is the no-MCP one.

  Tool-surface probes use the single bounded process layer, `agent_providers.process.run_cli_bounded`, for spawn, bounded stdin/stdout exchange, output limits, and process-group cleanup. The sync gate calls it directly; the async gate reaches that same gate via `asyncio.to_thread`, keeping a stuck spawn off the event loop without a third probe-specific thread. `agent_providers/claude/provider.py` keeps the policy around that runner: per-build verdict/failure cache, ordinary and zombie TTLs, single-flight, and the shared Claude process pool. It reserves a slot before invoking the runner, binds it in `on_spawned`, and releases it only in `on_reaped`; a `DEADLINE_BEFORE_SPAWN` may return while a later spawn is still live, so its result must never release that reservation. A `became_zombie` outcome wins before parsing the init event, receives the zombie TTL, and blocks a new process when the shared pool is full. The gate resolves the CLI's symlink once, at probe time, and hands that literal path back for the real turn to run — so a self-update landing between the probe and the turn cannot execute a build that was never checked. All four gated command paths — `acall_claude_with_mcp`, `acall_claude_with_mcp_stream`, `_call_cli` and `_acall_cli` — carry that assurance as a test that compares the probed command line against the executed one, so a future caller that resolves the binary a second time fails a test rather than shipping.
- **What the probe does not guarantee**: reading the `system` init event and then killing the session bounds but does not eliminate a probe's API cost — the full probe prompt is already on the wire by the time that line arrives, so a request already in flight is not excluded. The CLI's own `--max-budget-usd` was checked live against 2.1.257 and only aborts a session *after* a call completes, not before one starts, so it does not close that gap either; no flag in this CLI version does.
- **API backend**: Uses the Anthropic Python SDK with `max_tokens=1024` to limit response cost.
- **A drifted tool surface never fails server startup** (operator ruling, round 6): #351 literally asked for an unknown tool to fail the boot, but once the gate above was confirmed to cover every call path, a server that refuses albums and playback over a co-writer problem is a worse outage than the co-writer being unavailable. `lifecycle.report_claude_cli_tool_surface()` probes at boot, logs the result, and returns `"ok"` (verified clean), `"drift"` (verified, a real mismatch), or `"unverified"` (the probe could not reach a verdict at all — never silently reported as `"ok"`, the exact silent-default shape `check_no_silent_fallbacks.py` exists to catch); that state lives as a live value in `agent_providers/claude/provider.py` (`claude_cli_tool_surface_health()`), updated by every `verify_cli_tool_surface()` call — cache hit or fresh probe alike — not captured once at boot, so a later verdict overrides an earlier one instead of staying stuck at whatever booted; `GET /health` reports it under the same field name, so the state reaches monitoring and the operator, not only the first musician who opens a chat and finds it broken. Nothing polls in the background: the value only changes when the gate itself runs again, so if the CLI disappears without a fresh probe following it, `/health` keeps reporting the last verdict until the next call to the gate. `tests/test_lifecycle_claude_tool_surface.py` and `tests/test_health_api.py` pin the boot report and the live `/health` field across all three states; that a co-writer turn is actually refused on drift is proven separately, in the agent-providers library's own provider tests (`test_cowriter_turn_refuses_a_cli_with_an_unverified_tool_surface` and `test_cowriter_non_stream_turn_refuses_a_cli_with_an_unverified_tool_surface`).
- **No per-song chat endpoint**: the legacy `POST /api/songs/{id}/chat` (`chat_api.py`) and its `/api/settings/claude-models` settings were removed (#1190); `POST /chat/turn` in `conversation_api.py` is the only co-writer entry point.

## Agent-CLI Mounts

`songmaker-web` mounts the Claude, Grok, and Codex binaries and redacted
credential mirrors read-only. The music worker does not register, recover, or
execute cover jobs: `COVER_EXECUTOR=web` makes the web runner the sole owner.
Its obsolete Codex mounts remain only until W5 removes them. The scoring worker
mounts only Claude's binary and credential mirror; it does
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

The web service alone runs under the host profile `songmaker-web` and the
repository's `scripts/seccomp/songmaker-web.json`. The seccomp file is a pinned
copy of Docker's default profile with only Bubblewrap's namespace and mount
setup syscalls freed from Docker's `CAP_SYS_ADMIN` filter; its adjacent README
names the Moby revision and the test proves the exact diff. It grants no
capability. AppArmor remains the mount-shape boundary inside the nested user
and mount namespaces, while Compose still drops every container capability and
sets `no-new-privileges:true`; neither profile replaces the other.

### Masks by AppArmor instead of Docker

`songmaker-web` sets `systempaths=unconfined`. Docker normally overlays its
masked and read-only system paths, but those overmounts make Bubblewrap's fresh
`--proc /proc` mount fail the kernel's `mount_too_revealing` check: a new procfs
in the user namespace needs a source `/proc` without those overmounts. The
`songmaker-web` AppArmor profile therefore enforces the relevant path policy
instead, for every task carrying `songmaker-web`, including the Bubblewrap
child. A fresh child procfs would not retain Docker's proc masks in any case,
and `/sys` is where the rules do the real work: the cover command's
`--ro-bind / /` carries the now-unmasked host `/sys` into the sandbox, so
`/sys/firmware` and `/sys/devices/virtual/powercap` are out of reach there by
AppArmor alone.

This is a path-access replacement, not an inode-hiding replacement. Alias walks
are covered: AppArmor mediates the resolved pathname, so a walk through
`/proc/self/root/...` or `/proc/1/root/...` is denied like the plain path. What
remains true is narrower — the inode itself stays present instead of being
covered by an overmount, and a second mount of the same tree would carry a
pathname the profile does not name. Every rule therefore uses the `{,/,/**}`
form: AppArmor matches a directory only with its trailing slash, so without the
middle alternative the directory itself stayed listable while only its contents
were denied.

| Docker system path | `songmaker-web` rule |
| --- | --- |
| `/proc/acpi` | `deny /proc/acpi{,/,/**} rwklx` |
| `/proc/asound` | `deny /proc/asound{,/,/**} rwklx` |
| `/proc/interrupts` | `deny /proc/interrupts{,/,/**} rwklx` |
| `/proc/kcore` | `deny /proc/kcore{,/,/**} rwklx` |
| `/proc/keys` | `deny /proc/keys{,/,/**} rwklx` |
| `/proc/latency_stats` | `deny /proc/latency_stats{,/,/**} rwklx` |
| `/proc/sched_debug` | `deny /proc/sched_debug{,/,/**} rwklx` |
| `/proc/scsi` | `deny /proc/scsi{,/,/**} rwklx` |
| `/proc/timer_list` | `deny /proc/timer_list{,/,/**} rwklx` |
| `/proc/timer_stats` | `deny /proc/timer_stats{,/,/**} rwklx` |
| `/sys/devices/virtual/powercap` | `deny /sys/devices/virtual/powercap{,/,/**} rwklx` |
| `/sys/firmware` | `deny /sys/firmware{,/,/**} rwklx` |
| `/proc/bus` | `deny /proc/bus{,/,/**} w` |
| `/proc/fs` | `deny /proc/fs{,/,/**} w` |
| `/proc/irq` | `deny /proc/irq{,/,/**} w` |
| `/proc/sys` | `deny /proc/sys{,/,/**} w` |
| `/proc/sysrq-trigger` | `deny /proc/sysrq-trigger{,/,/**} rwklx` (stricter than Docker's read-only mask) |

The `/proc/sys` rule intentionally has no `shm*` write exception: Songmaker
does not write those kernel settings.

The runtime proof checks that the web-service parent and the private Bubblewrap
child both receive `Permission denied` when reading `/proc/interrupts`,
`/proc/keys`, `/proc/latency_stats`, `/sys/devices/virtual/powercap`, and
`/sys/firmware/memmap/1/type`. Those five reads discriminate: nothing but the
AppArmor rules denies them, so dropping a rule fails the proof. The sixth check,
the write to `/proc/sys/kernel/shmmax`, does not. That file is root-owned and
mode 0644 while the container runs as the unprivileged `songmaker` user, so DAC
denies the write on its own and the check would still pass with
`deny /proc/sys{,/,/**} w` removed. It stands only as a regression guard against
the mask section disappearing entirely, never as evidence for the write rule.

An operator installs the AppArmor policy with
`sudo scripts/apparmor/install.sh` and then recreates the service with
`docker compose up -d songmaker-web`. The script stages a copy of the profile
as a dotfile in `/etc/apparmor.d/`, checks that those staged bytes parse
(`apparmor_parser -QK`) and declare the `songmaker-web` profile and no other
(`apparmor_parser -QK -N`), and renames them over
`/etc/apparmor.d/songmaker-web` (mode 0644, fresh mtime), so the boot-loaded
pathname never holds a partial or unvalidated file and a source edited
mid-run cannot slip past the check. It then loads that copy
(`apparmor_parser -r`) and requires `aa-status` to list a profile of exactly
that name. If the load or that check fails, the previous copy goes back and is
reloaded (on a first install the new copy is removed), and the script fails.
`apparmor_parser` skips dotfiles when it loads a directory, so a staged copy
never reaches the boot load, and the script removes it on every exit.
`apparmor.service` loads every profile under
`/etc/apparmor.d/` before `sysinit.target`, and `docker.service` starts after
it, so both Docker's own `unless-stopped` restarts and `songmaker.service`
find the profile after a reboot without a manual step. Run the script once
per change to the profile in the repository; running it twice gives the same
result. Installing changes the host kernel policy, so the script deliberately
requires root. The profile derives
Docker Engine 29.1.3's `docker-default` template (Moby
`profiles/apparmor`, ABI 3.0) and retains its `/proc` and `/sys` denials. It
adds `userns` for Ubuntu's restricted unprivileged user namespaces, plus only
Bubblewrap 0.12.0's private-root setup operations: recursive-slave propagation,
construction and sandbox tmpfs mounts, root binds and remounts, both
`pivot_root` calls, the retained-proc bind from `/oldroot/proc/` to `/proc/`,
fresh `proc`, writable-proc covers, and minimal `dev`/`devpts`. Codex's
per-run startup probe gets its own `tmpfs` at `/newroot/`, then read-only binds
only `/bin`, `/etc`, `/lib`, `/lib64`, `/sbin`, and `/usr`; its `dev` and `proc`
mounts use the same minimal rules as the cover command. The allowlist also
names only the three traced protected-home overlays (`.git`, `.agents`, and
`.codex`) below the cover, Co-Writer, and post-rollout probe home prefixes:
Bubblewrap mounts `tmpfs` there with `rw,nosuid,nodev`, after preparing each
target with `--perms 555`, and then read-only remounts it. It accepts
Bubblewrap's optional `silent` flag only where its mount syscall uses it and
preserves the observed inherited mount flags during remounts. Compose applies
the profile only to `songmaker-web`, drops every container capability, and sets
`no-new-privileges:true`.

The three prefixes those private homes carry — the cover turn's, the
Co-Writer turn's, and the proof's — live in `agent_providers/sandbox/paths.py`
and nowhere else. The provider layer creates the directories, this profile is
the only thing that permits their mounts, and
`tests/test_prove_codex_image_sandbox.py` reads the module and every rule form
in the profile, including its brace lists, so a rename that reaches only one
of them is a red test instead of a silently refused mount. A project that
embeds `agent_providers` takes those prefixes and derives its own profile from
them. The profile *name* is a parameter wherever it is used —
`sudo scripts/apparmor/install.sh [profile]`,
`python scripts/prove_codex_image_sandbox.py [profile]`, and Compose's
`SONGMAKER_APPARMOR_PROFILE` — each defaulting to `songmaker-web`.
`tests/test_prove_codex_image_sandbox.py` holds Compose's and the proof's
defaults and the profile file's own declaration to that one name, and
`tests/test_apparmor_install.py` drives the installer without an argument and
requires it to install the profile of that name. The installer refuses a name
that is not a regular profile file beside it, a symlink included, so a typo or
a link to another host file never reaches `apparmor_parser`.

Docker's default seccomp profile keeps `clone3` at `ENOSYS` without
`CAP_SYS_ADMIN`, so Bubblewrap and libc use their `clone` fallback.

Do not use `apparmor=unconfined` as a Sandbox diagnostic on this Ubuntu host.
With `kernel.apparmor_restrict_unprivileged_userns=1`, an unconfined process is
blocked before it can create the required user namespace; that result says
nothing about the confined `songmaker-web` profile or its seccomp policy. The
confined profile explicitly permits `userns`, so its child can create the
namespace with the capabilities it needs inside that namespace.

Unprivileged user namespaces enlarge the kernel attack surface; this is the
deliberate #666 trade-off because the alternative is Option 2.

`lifecycle.py` and `scripts/prove_codex_image_sandbox.py` pin three different
Codex Bubblewrap forms because they answer different questions:

- The **boot check** requires both Codex's startup capability probe and its
  per-run startup probe. The capability probe's literal argv is `bwrap
  --unshare-user --unshare-net --ro-bind / / /bin/true`. Source: the Codex
  0.147.0 Linux binary's embedded string, confirmed by the boot check's direct
  `subprocess.run` assertion. It asks whether Bubblewrap can create the
  namespace and read-only root at all; the second form below proves the fresh
  procfs setup as well. `ready` means that both commands succeeded. This
  boot check's verdict (`ready`, `not_set_up`, or `unverified` before the
  boot check has run) is also `GET /health`'s live `codex_image_sandbox_runtime`
  field, so the operator sees sandbox readiness without reading the boot log.
- Codex then runs this **per-run startup probe** before its sandbox command.
  `strace -f -e trace=execve -s 400 codex sandbox -- /bin/true` on 06.09.2026
  (Codex 0.147.0) recorded its literal argv:

  ```text
  bwrap --new-session --die-with-parent --tmpfs / --dev /dev --ro-bind /bin /bin --ro-bind /etc /etc --ro-bind /lib /lib --ro-bind /lib64 /lib64 --ro-bind /sbin /sbin --ro-bind /usr /usr --unshare-user --unshare-pid --unshare-net --proc /proc -- /usr/bin/true
  ```

  The startup probe is an empty private root, not the read-only-root form from
  the capability probe. The boot check and post-rollout proof run this exact
  form before the G4 command, and their tests pin every argument, so an AppArmor
  rule cannot be kept without the observed command that needs it.
- The **post-rollout proof** uses the real read-only command form, with its
  terminal command replaced by G4 assertions. Source: `strace -f -e
  trace=execve -s 400` of `codex sandbox --sandbox-state-json … -- /bin/true`
  in the throwaway `songmaker-songmaker-web` container with `--network none`,
  `--cap-drop ALL`, `no-new-privileges:true`, `apparmor=songmaker-web`, and
  `seccomp=scripts/seccomp/songmaker-web.json`. The traced argv is:

  ```text
  bwrap --new-session --die-with-parent --ro-bind / / --dev /dev --bind /tmp/songmaker-codex-sandbox-probe/codex-home /tmp/songmaker-codex-sandbox-probe/codex-home --perms 555 --tmpfs /tmp/songmaker-codex-sandbox-probe/codex-home/.git --remount-ro /tmp/songmaker-codex-sandbox-probe/codex-home/.git --perms 555 --tmpfs /tmp/songmaker-codex-sandbox-probe/codex-home/.agents --remount-ro /tmp/songmaker-codex-sandbox-probe/codex-home/.agents --perms 555 --tmpfs /tmp/songmaker-codex-sandbox-probe/codex-home/.codex --remount-ro /tmp/songmaker-codex-sandbox-probe/codex-home/.codex --unshare-user --unshare-pid --unshare-net --proc /proc --argv0 codex-linux-sandbox -- /usr/local/bin/codex --sandbox-policy-cwd /tmp/songmaker-codex-sandbox-probe/workdir --command-cwd /tmp/songmaker-codex-sandbox-probe/workdir --permission-profile {"type":"managed","file_system":{"type":"restricted","entries":[{"path":{"type":"special","value":{"kind":"root"}},"access":"read"},{"path":{"type":"path","path":"/tmp/songmaker-codex-sandbox-probe/codex-home"},"access":"write"}]},"network":"restricted"} --apply-seccomp-then-exec -- /bin/true
  ```

  The proof pins the complete Bubblewrap setup and Codex helper re-exec through
  `--apply-seccomp-then-exec`, including the only writable `CODEX_HOME` bind
  and Codex's three protected-home tmpfs overlays; it replaces only the traced
  terminal `/bin/true` with G4 assertions. It must allow writing only below
  `CODEX_HOME`, reject writes to `/app` and the rest of `/tmp`, have no
  network, retain `NoNewPrivs: 1`, and expose an empty `CapEff`. The G4 shell
  snippet compares `CapEff` to the literal `0000000000000000` that Python
  embeds while building the snippet; the traced Bubblewrap argv therefore
  gains no environment-setting argument. Its `docker-default` control runs the
  same prepared form and must fail.

The 06.09.2026 live audit of the per-run startup probe recorded exactly one
denial: `bwrap` mounting `tmpfs` at `/newroot/` with `rw,nosuid,nodev`
(`info="failed flags match"`). The matching profile rule permits that mount;
the traced `/bin`, `/etc`, `/lib`, `/lib64`, `/sbin`, and `/usr` binds are the
only additional startup-probe rules. Before the operator reloads the profile,
the checked-in rules and `apparmor_parser -Q -K` prove only source and syntax;
the live proof remains the next rollout step.

An operator runs the rollout and proof in this exact order:

```sh
sudo scripts/apparmor/install.sh
docker compose up -d songmaker-web
python scripts/prove_codex_image_sandbox.py
```

That the profile survives a reboot is proven by unloading it from the kernel
and letting `apparmor.service` load it again from the installed copy; a
missing copy fails the second `aa-status` check. Each check matches the whole
profile name, so a profile whose name merely contains `songmaker-web` never
counts. A real reboot followed by the same checks counts as well:

```sh
docker compose stop songmaker-web
sudo apparmor_parser -R /etc/apparmor.d/songmaker-web
sudo aa-status | awk 'NF == 1 && $1 == "songmaker-web" { found = 1 } END { print (found ? "present" : "absent"); exit !found }'   # prints absent
sudo systemctl reload apparmor.service
systemctl is-active --quiet apparmor.service && echo active
sudo aa-status | awk 'NF == 1 && $1 == "songmaker-web" { found = 1 } END { print (found ? "present" : "absent"); exit !found }'   # prints present
docker compose up -d songmaker-web && python scripts/prove_codex_image_sandbox.py
```

The installed copy does not follow later edits to the profile in the
repository: until the installer runs again, every boot loads the rules it last
installed.

To remove the profile from the host, stop the service that requires it,
unload the profile, then delete the installed copy. `apparmor_parser -R` reads
the profile file to learn which profile to unload, so it runs before the copy
is gone:

```sh
docker compose stop songmaker-web
sudo apparmor_parser -R /etc/apparmor.d/songmaker-web
sudo rm /etc/apparmor.d/songmaker-web
```

The proof script imports `songmaker_cli.lifecycle` for the startup-probe argv
and `agent_providers.sandbox.paths` for its probe directory, so it runs from
the main checkout with its virtualenv, or from a worktree with
`PYTHONPATH=<worktree>/src`. An `ImportError` there is a missing import path,
not a sandbox failure. Both the installer and the proof take the profile name
as an optional first argument; a stack proven under another profile passes it
to both.

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
`SONGMAKER_CODEX_CLI` into `songmaker-web`. The music worker's remaining
read-only Codex binary and `codex.json` mirror have no execution path after the
cutover and are removed by W5.

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
an absolute path or `~/…` with no whitespace, no `%` and no `$`, because
systemd splits directive values on whitespace, expands `%` as a specifier and
`$` as a variable in the ExecStart that carries the path; anything else is
refused loudly rather than mangled into a unit.

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
abort the turn. The music worker's temporary Codex mounts have no execution
path after the cover cutover; W5 removes them. The scoring worker does not
mount Codex.

The cover-image route starts Codex with the fixed read-only image
argv (`--sandbox read-only`, no MCP servers, and `web_search="disabled"`),
with Code Mode enabled only for this image run. Its one variable part is the
admin-stored cover model, appended as `--model <slug>` when that setting is
not empty. Each run creates a private
`0700` root whose `codex-home/` and `work/` directories are separate `0700`
siblings; the home contains only the redacted `auth.json` mirror (`0600`) and
the process cwd is the resolved `work/` path. The streamed event gate admits a
completed turn without requiring a command or an `image_gen` event. No command is admitted, including the former
skill-read command. The measured Codex CLI 0.163.0 turn produced one PNG
without reporting either a command or an `image_gen` event. Reported blocked
items (including commands, file changes, MCP calls, web searches and
collaboration) and unknown event or item types request abort and are reported
as `ImageToolBlockedError`; the process is reaped before the route returns.

The gate sees only what the CLI reports. This measurement does not establish
whether other tools using the invisible path would be reported. The PNG is
associated with the turn through its private `CODEX_HOME` location and
normalization under the host `ImagePolicy`. The gate is defense in depth;
containment rests on the Codex read-only sandbox and songmaker's AppArmor and
seccomp profiles. Fixture replay proves event handling, not live containment.
Every Co-Writer tool-loop round keeps Code Mode disabled.

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
reason and never retries the sibling CLI/API route. Judge settings are also
admin-only and expose the saved route with safe readiness metadata. The
[Agent routes contract](architecture.md#agent-routes) describes the startup pin
and the temporary separation between that saved route and the worker's
unchanged credential resolution below.

**#327 F5:** Settings reads and validation never start an agent CLI or catalog
request. `provider_status_refresh` owns those probes; an empty snapshot is reported
as `unverified` rather than guessed as usable.

## Child Process Secret Scrubbing

Two packages spawn *external* child processes that must not inherit every secret in the parent's environment: `agent_providers` (the Claude, Grok and Codex CLIs) and `acestep_worker.subprocess_runner` (the ACE-Step HTTP subprocess). The provider layer has one scrubber, `agent_providers.process.scrubbed_env()`, and all three CLI spawners go through it — the Claude backends in `agent_providers/claude/provider.py`, `agent_providers/grok/transport.py`, `agent_providers/codex/transport.py`, and the bounded runner's own `_child_env()`, which adds a spawner's explicit variables on top of that scrubbed base rather than beside it. Both packages scrub `os.environ.copy()` with a `SECRET_ENV_KEYS` tuple before passing `env=` to the child, covering `ANTHROPIC_API_KEY`, `XAI_API_KEY`, `OPENAI_API_KEY`, `SESSION_SECRET`, `SONGMAKER_INTERNAL_TOKEN`, `DATABASE_URL`, `REDIS_URL`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `HF_TOKEN`, `GRAFANA_USER`, and `GRAFANA_PASSWORD`. A login is scrubbed as a pair — the name half is no secret on its own, but handing a child process one half of a credential buys nothing.

The Keycloak client secret is not in that list because it is not in the environment: it is a file, mounted into the web container only. The scrub cannot hide a file from a child that runs as the same OS user, so the agent-CLI processes can read it; see "Authentication".

`acestep_worker` cannot import from `songmaker_cli` (engine packages are independent — see AGENTS.md "Code patterns"), so each package keeps its own `SECRET_ENV_KEYS` tuple: `songmaker_cli/constants.py` and `acestep_worker/constants.py`. `agent_providers` may import neither, so the provider layer scrubs with the list its host injects on `ProviderRuntimeConfig.secret_env_keys` — songmaker fills it from its own constant in `agent_runtime.py` (#836), which makes the injected runtime a third owner of the same list. `tests/test_secret_scrub_parity.py` pins all three against the same literal expected set of keys — so they cannot silently drift apart the way the first two did before issue #157 (the Claude CLI child inherited `SONGMAKER_INTERNAL_TOKEN` because the two lists disagreed), no list can quietly shrink to empty and still pass, and a drifted list names its own owner.

`HF_TOKEN` is scrubbed from the ACE-Step subprocess even though the subprocess genuinely does call Hugging Face: `vendor/acestep/acestep/api/model_download.py`'s `download_from_huggingface` runs both at subprocess startup (for the DiT and VAE models) and at request time (for LM models), and it passes no explicit `token=`, so `huggingface_hub` would pick up `HF_TOKEN` from the environment implicitly if it were present. However, every repo ID the subprocess can resolve on its own (via `MODEL_REPO_MAPPING` / `DEFAULT_REPO_ID` in that same module) is public and answers anonymously; the ACE-Step catalog's only two gated repos (`ACE-Step/acestep-v15-turbo`, `ACE-Step/acestep-5Hz-lm-1.7B`) are fetched exclusively by `acestep_worker.downloads.run_download`, which passes `token=` explicitly rather than relying on ambient env. So scrubbing `HF_TOKEN` here does not break any download this deployment performs — the consequence is that the subprocess's own Hugging Face requests go out anonymously and are subject to Hugging Face's stricter unauthenticated rate limits. See `acestep_worker/constants.py` for the same reasoning next to the list.

A third case needs a different mechanism: `songmaker_cli.scoring.subprocess_runner` starts the long-lived scorer child via `multiprocessing`'s `spawn` start method, which has no `env=` parameter — the child process inherits the parent's complete `os.environ` at spawn time, the same way it would inherit any other process-wide state. `_child_main` (the child's entry point) calls `_scrub_secret_env_vars()` as its literal first statement — but by the time `_child_main` runs, the spawn bootstrap has already imported the whole `subprocess_runner` module and everything it pulls in at module level (`scoring.pipeline`, `settings`, `auth`, `api_models`, ...), because multiprocessing's spawn target must be importable before it can be called. The scrub cannot undo anything a module-level import already did; it only guarantees that no code invoked *after* it — `default_registry.ensure_loaded()`'s scorer-module imports and every scorer function call that follows — can read a secret out of `os.environ`. `tests/test_scorer_subprocess.py::test_scorer_child_drops_secret_env_keys_at_spawn` drives the real `_child_main` entry point (via the existing `_run_child_with_messages` test harness, not a stand-in) with every `SECRET_ENV_KEYS` entry (plus a non-secret marker) set in the parent's environment beforehand, sends it an `EnvProbeRequest`, and asserts none of them come back present while the marker does — a spawned process's own `os.environ` cannot be observed from outside it any other way, so this round trip is what makes deleting the `_scrub_secret_env_vars()` call site fail the test.

Everything a child scorer needs is resolved in the parent and carried into the child as data — never re-read from the child's own environment — and none of it is a secret. `scoring_worker.py` and `jobs/scoring.py` call `get_settings()` at worker startup and per-job respectively, in the parent process; `scoring_device`, `scorer_timeout_seconds`, and `text_accuracy_timeout_seconds` flow into `PipelineConfig` fields (`device`, `scorer_timeout`, `text_accuracy_timeout`), and `scoring_max_jobs` separately bounds ARQ worker concurrency (`ScoringWorkerSettings.max_jobs`) — it never crosses the pipe at all. `lyrical_coherence.py` — the one scorer that calls an external provider (Claude, Grok, or Codex, whichever the judge is configured for, #315) — used to run in the child and call `get_settings()` there to read `anthropic_api_key`; after the scrub that field is simply absent, so `get_settings()` would raise (`Settings.database_url` has no default and is also in `SECRET_ENV_KEYS`) rather than degrade gracefully. Issue #173 handed the key to the child on `PipelineConfig` instead; issue #176 took the secret out of the child altogether. `scoring/registry.py` marks that scorer `host=ScorerHost.PARENT`, the child's registry refuses to register a parent-hosted scorer at all, and `jobs/scoring.py` calls `judge_lyrical_coherence()` itself, in the worker parent, on the `SongScores` the child returned — the transcription it judges comes from that result's `text_accuracy` value. `PipelineConfig` carries no secret field, so there is no key in the child's memory to leak through the model weights it loads.

The invariant this protects: no module reachable from `subprocess_runner`'s own import chain may read `os.environ` or construct `Settings()` as a *module-level* side effect (that code runs before the scrub ever gets a chance to act), and no scorer module — all of them imported later, inside `_child_main`, after the scrub — may read `os.environ` or construct `Settings()` at call time either. A future scorer that needs a secret does not belong in the child at all: give its spec `host=ScorerHost.PARENT` and run it in the worker parent on the result the child returned, the way `lyrical_coherence` does. Non-secret configuration reaches a child scorer through a new `PipelineConfig` field filled by the parent, never through a `get_settings()` call in the child.

Moving the judge out of the child (#176) only relocated *where* the provider call happens — it did not give the worker parent a credential to make that call with. `jobs/scoring.py` resolves `judge_provider`/`judge_model` from the DB and hands them to `judge_lyrical_coherence()` on a credential-free `CoherenceJudgeConfig`. `call_provider_once()` resolves the real credential in the worker parent: Claude falls through to the CLI whenever `ANTHROPIC_API_KEY` is unset, while Grok and Codex require `XAI_API_KEY` / `OPENAI_API_KEY`. The scoring image owns a writable `/home/songmaker/.claude` profile and mounts only the self-contained Claude binary plus the redacted `/home/songmaker/.claude/.credentials.json` mirror; Claude creates its own `~/.claude.json`. It deliberately mounts no Grok or Codex login because it never runs those CLIs. The credential remains in the worker parent, not the scorer child, so the child-process scrub and credential-free `PipelineConfig` are unaffected.

The scrub is also weaker than the Popen `env=` path used for the Claude CLI and ACE-Step children: `del os.environ[key]` calls libc's `unsetenv()`, which blocks `getenv()` — every subsequent read via `os.environ`/`os.getenv`, and every process this one execs from here on, sees the key as gone — but it does not erase the bytes the kernel copied onto the process's stack at its own `execve()`, which is what `/proc/<pid>/environ` reads directly. So the scrubbed keys stay visible in `/proc/<pid>/environ` for the child's entire lifetime even though `getenv()` can no longer see them. Accepted risk per [Trust model and accepted risks](#trust-model-and-accepted-risks) (subprocesses share the OS user): reading another process's `/proc/<pid>/environ` requires being that same OS user (or root), and the scoring-worker container's `songmaker` user has no other tenant sharing it, so this gap adds no new exploitation path beyond the one already accepted there. Never bind-mount `.env` into the `songmaker-scoring-worker` container — `Settings` walks up the filesystem looking for it, and doing so would hand the scrubbed child back every secret the scrub just removed.

The child never outlives a scorer it could not stop. A scorer's time budget is a ceiling: `_call_with_timeout` abandons a call that blows it (`shutdown(wait=False)`) instead of joining it, because a Python thread cannot be killed. Inside the child that abandoned thread goes on holding the Whisper/AudioBox model globals and their GPU memory, so the next request would otherwise reuse a child whose GPU memory is still held, beside a scorer still running. Two things prevent that. `ScorerProcess` marks itself tainted when a response reports `SongScores.any_child_scorer_timed_out`, under the same `_pipe_lock` that serializes requests, and `_ensure_started()` then refuses to hand that child to the next request — it kills and respawns instead. That holds even when the job that tainted it was cancelled and returned early. On top of it, `jobs/scoring.py` calls `ScorerProcess.recycle()` right after persisting the values of such a run, so the GPU is reclaimed immediately rather than at a next request that may be minutes away. Both paths kill the same way: SIGTERM first, so the child's own handler releases CUDA memory, SIGKILL after a 5-second grace period; the replacement child runs `_scrub_secret_env_vars()` again by construction. The taint counts only child-hosted scorers: a parent-hosted one over budget (the coherence judge) leaves its thread in the worker parent, where killing the child would reclaim nothing and only cost the next job a model reload. `tests/test_jobs.py` and `tests/test_scorer_subprocess.py` pin every direction — a timed-out child scorer keeps its scores and loses its child, a cancelled job's tainted child is still not reused, a clean run and a timed-out judge both keep the child they had.

The scorer's two Hugging Face models (`faster-whisper`'s `large-v3`, `audiobox-aesthetics`'s default checkpoint) are baked into the `songmaker-scoring-worker` image at build time — `docker/scoring-worker.Dockerfile` downloads them with `HF_TOKEN` wired in only for that `RUN --mount=type=secret` build step, and the running container's `docker-compose.yml` service definition never sets `HF_TOKEN` as a runtime env var at all, so there is nothing for the scrub to take away at request time.

## ACE-Step Worker Pool Trust Boundary

The ACE-Step worker pool runs each model-serving worker as a separate peer container. Workers self-register with the web container at startup and heartbeat ephemeral state to Redis. The control plane (web container) and the workers communicate over an **internal HTTP API** mounted under `/api/internal/*`.

### Internal token

- **Env var**: `SONGMAKER_INTERNAL_TOKEN` — a shared secret that must be set on both the web container and every worker container before startup.
- **Header**: Workers send `X-Internal-Token: <token>` on every internal call. The web container does the same when the music-worker scheduler proxies `/load_model` / `/evict_model` to a worker.
- **Worker side**: every route of the acestep-worker (`src/acestep_worker/wrapper.py`) requires the same header except `GET /health`, which the Compose healthcheck calls headerless and which answers only `ok` or a 503 reason. The worker's routes sit on one router that carries `verify_internal_token`, so a new route is protected by default; the FastAPI `/docs`, `/redoc` and `/openapi.json` routes are disabled. A missing header answers 422, a wrong, empty or non-ASCII token 401 (the comparison runs on encoded bytes, so a non-ASCII value cannot crash into a 500). `tests/acestep_worker/test_wrapper.py` enumerates every route the app serves and fails if one but `/health` answers without the token.
- **Verification**: `internal_api.verify_internal_token` is mounted as a router-level dependency, so every endpoint under `/api/internal/*` automatically requires the header. Comparison uses `hmac.compare_digest` on encoded bytes for timing safety.
- **Failure modes**: Missing env var → 503 ("Internal API not configured"). Missing header → 422; wrong, empty or non-ASCII token → 401. The 503 vs 401 split tells the operator whether the issue is config or credentials.
- **CSRF**: `/api/internal/*` is exempt from the session-bound token check, but still follows the origin/fetch-metadata check. Workers send JSON without `Sec-Fetch-Site` or Origin headers and authenticate with the internal token; they do not have sessions.

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

### Trust model and accepted risks

- **Subprocesses share the OS user.** ACE-Step and scorer subprocesses run as the same `songmaker` user in Docker. `songmaker-acestep-worker-0`, `songmaker-music-worker` and `songmaker-scoring-worker` drop every capability (`cap_drop: [ALL]`, no `cap_add`) and set `no-new-privileges`; they carry none of `songmaker-web`'s seccomp, AppArmor or `systempaths` options, which exist only for its Bubblewrap sandbox. Compromised model weights or ACE-Step code get user-level disk access. Container isolation mitigates this; OS-user separation would need separate containers for marginal benefit. Accepted for a single-user deployment.
- **One shared token.** All workers hold the same `SONGMAKER_INTERNAL_TOKEN`; compromising one grants full internal-API access. Multi-node deployments should move to per-worker tokens or mTLS.
- **Single node.** One acestep-worker per GPU on one host, the ACE-Step HTTP subprocess inside the worker container. Multi-node distribution (separate hosts, shared model storage, cross-host Redis heartbeats) is untested, and the image/packaging refactor that would precede it (decoupling the ACE-Step subprocess image from the worker image) is unwritten.

### Future hardening

If exposure to untrusted traffic becomes a concern, the next step is to bind `/api/internal/*` to a separate port (and bind it to the Docker network, not `0.0.0.0`). Today the single-port design has no repository-provided edge path filter; its safety depends on the loopback-only published port and on any operator-provided upstream access policy.

## CI Supply Chain

Every third-party GitHub Action is pinned to the full commit SHA of its reviewed
release tag (with the release series recorded beside it), so a moved tag cannot
change a workflow. Project tooling in CI and application dependencies in worker
images are installed through `uv` with the committed `uv.lock`; Bandit and
pip-audit run in separate tool environments so they do not change that lock.
The repository itself is installed as the trusted local editable project. All
third-party dependencies must be wheels except `nvidia-ml-py3`, whose locked,
hash-verified release has no published wheel.

## Audit Trail

Mutating operations are logged to the `audit_log` table. Account creation, role changes and back-channel logouts are written without a person (`user_id` null):

- **Actions tracked**: `create`, `update`, `delete`, `generate`, `score`, `cleanup`, `share`, `unshare`
- **Fields**: `user_id`, `action`, `resource_type`, `resource_id`, `detail`, `created_at`
- **Read access**: none over HTTP — the `GET /api/admin/audit-log` endpoint was removed until an admin surface shows the trail (#1190); the rows stay in the database and are read there.

## Production Deployment

### Recommended

| Setting | How |
|---------|-----|
| HTTPS termination | Songmaker does not terminate TLS. Leave `COOKIE_SECURE` at its default `true` so the session and CSRF cookies carry `Secure` and the `__Host-` prefix, and responses carry HSTS; set `COOKIE_SECURE=false` only for local plain-http development (CI and the e2e Compose overrides do this). No terminator configuration is shipped here. |
| Session secret | Set `SESSION_SECRET` env var (min 32 chars). Required — startup fails with `ValidationError` if missing. Stable across restarts. Generate with `python3 -c "import secrets; print(secrets.token_hex(32))"`. |
| CORS origin | Leave unset when the interface and API share an origin. For a separate trusted browser client, set one exact origin, for example `CORS_ORIGIN=https://client.yourdomain.com`. Cross-site browser mutations to `/api/` remain rejected by `Sec-Fetch-Site`, even with this permission. Startup rejects `*`, subdomain wildcards, and comma-separated lists; `SameSite=Strict` does not make sibling subdomains separate sites. |
| Trusted proxies | Set `TRUSTED_PROXIES=10.0.0.1,172.16.0.0/12` (comma-separated addresses and/or CIDR networks). Only peers inside these networks are trusted for `X-Forwarded-For` and `X-Forwarded-Proto`; the rightmost untrusted `X-Forwarded-For` entry is used to prevent spoofing. An unparsable or zone-scoped entry fails startup, and a malformed forwarded chain falls back to the direct peer. Without this, the client's direct IP is always used for rate limiting — see "Proxy trust". Cookie `Secure`/HSTS are unaffected either way; they follow `COOKIE_SECURE` alone. |
| Public base URL | Set `PUBLIC_BASE_URL=https://yourdomain.com` (scheme + host, no trailing path). The one owner of "what address am I reachable at from outside" for share links (album/song/generation/playlist — issue #339); `api_helpers.resolve_public_base_url()` is the only caller site. Not derived from the request: `request.base_url` reflects the literal ASGI transport's scheme, which is always `http` behind a TLS-terminating proxy since `proxy_headers=False` (see "Proxy trust") leaves nothing to rewrite it. Unset or malformed fails the share call with `500` rather than building a link with a guessed scheme. |
| Allowed hosts | Set `ALLOWED_HOSTS=yourdomain.com,yourdomain.com:443` (comma-separated). Used by CSRF origin verification and as the Host allowlist. Compose always adds `localhost`, `127.0.0.1` and `songmaker-web`. |
| Host binding | Default is `127.0.0.1` (localhost only). Set `HOST=0.0.0.0` only when the deployment's network policy keeps the service private. The Docker deployment does set `HOST=0.0.0.0` — that binding is *inside* the container, where the Compose network needs it. |
| Published ports | `docker-compose.yml` publishes `songmaker-web`, Grafana, and Prometheus as `127.0.0.1:8080:8080` / `127.0.0.1:3000:3000` / `127.0.0.1:9090:9090`. Do not drop the `127.0.0.1:` prefix: Docker's NAT chain bypasses the host INPUT chain, so a plain `8080:8080` reaches the whole LAN no matter what UFW says. The Prometheus API is host-local for the same reason; its lifecycle HTTP endpoints stay disabled, so Compose-network peers cannot stop or reload it. The tunnel (`cloudflared`), the Vite dev proxy, and the CLI all run host-local; in-cluster callers use `songmaker-web:8080` on the compose network. |
| Workers | Production runs in Docker only. The web container uses a single uvicorn process; concurrency comes from arq worker containers (`MUSIC_MAX_JOBS`, `SCORING_MAX_JOBS`). PostgreSQL is the only supported production DB — SQLite is test-only. |
| Request body limit | App-level: `MAX_REQUEST_BODY_BYTES` (default 1 MB). If an operator provides an upstream proxy, align its path-specific limits for defense in depth; this repository provides no such proxy configuration. |
| IP rate limit | `IP_RATE_LIMIT` (API class, default 120/min), `MEDIA_RATE_LIMIT` (`/audio/*`, default 600/min), `STREAM_RATE_LIMIT` (SSE opens, default 45/min). Adjust based on expected traffic — see "Per-IP (global middleware)" above. |
| Resource-event stream open limit | `RESOURCE_EVENT_STREAM_OPEN_LIMIT` (per-user resource-events stream opens, default 12/min). CI overrides it — see "Resource-event streams" above. |
| Request timeout | `REQUEST_TIMEOUT` (default 30s) limits idle keep-alive connections, not full requests. The two SSE routes have their own 60-second walls; Songmaker has no general application request deadline. |
| Auto-deploy cleanup timeout | `SONGMAKER_AUTODEPLOY_PRUNE_TIMEOUT_SECONDS` (default 600). Bounds each post-deploy Docker cleanup command. |

The two-minute auto-deploy tick first runs `docker compose config --quiet` on the checked-out configuration, then checks the active-job queue and required alert-channel configuration before it checks out or builds. Compose owns the list of required variables (every `${VAR:?…}` in `docker-compose.yml`), so a missing one such as `GRAFANA_PASSWORD` is a named deploy refusal quoting compose's own message before anything is checked out — the job guard's `docker compose exec` would not notice it, and the build would fail only after the checkout. The refusal uses the same counter and alert escalation. The tick asks again right after the checkout, before any base-image or Compose build, so a variable that the newly selected commit requires is named before anything is built or recreated. `--quiet` is mandatory there: without it, compose prints the fully interpolated configuration, every `.env` secret included, into the journal. The tick also runs `scripts/check_agent_cli_mounts.sh` before those steps when that verifier is installed; a verifier failure is a named deploy refusal, so it increments the tick's existing consecutive-failure counter and follows its alert escalation. A checkout that predates the verifier logs `mount preflight not installed, skipping` and continues with its installed guards, making the temporary compatibility state visible rather than silently bypassing it. After fetching `origin/main` and its `v*` release tags into a private ref namespace, the tick asks GitHub about the newest ten eligible releases (configurable with `SONGMAKER_AUTODEPLOY_CHECK_RUN_LOOKBACK_COMMITS`; see [auto-deploy architecture](architecture.md#auto-deploy) for what makes a tag eligible) and checks out detached only the newest release whose commit's GitHub Actions (`app.slug == github-actions`) runs have all completed, at least one of them successfully and every other one successfully, skipped, or neutral (a skipped or neutral run neither blocks nor passes a commit); other apps' runs are logged as advisory and ignored, and a check run without a job name is a malformed answer. Releases with running, cancelled, or failed Actions are named in the log once and skipped; no Actions runs stay neutral only for the 30-minute grace period measured from the local host clock when the HEAD SHA was first seen; a commit timestamp supplied by Git cannot postpone that alarm. An unavailable or malformed GitHub answer, or a 60-second check-run lookup timeout, is a named deploy refusal that uses the same counter and alert escalation. Every Git command in the tick disables repository hooks and the filesystem monitor and runs with a minimal Git environment. That includes the one network fetch the ACE-Step pin adds: before the checkout, the tick fetches the commit the selected revision pins `vendor/acestep` to, by SHA, from the submodule's `origin` (a public fork; the tick adds no credential of its own). With the scrubbed environment, no hooks and no filesystem monitor, nothing the fork serves can run code on the host while the fetch stores its objects. The submodule's own local Git configuration (`remote.origin.uploadpack`, `core.sshCommand`, `url.*.insteadOf`) is trusted like the superproject's, because it decides how the fetch connects. The tick then checks the pin out with `git submodule update --checkout --no-fetch`. If the pin cannot be fetched, or `vendor/acestep` is not initialised, the tick fails closed: a counted refusal that leaves the checkout, the running stack and `deployed.sha` untouched. Both git fetches of a tick run under `SONGMAKER_AUTODEPLOY_GIT_FETCH_TIMEOUT_SECONDS` (120 by default) with `SONGMAKER_AUTODEPLOY_GIT_FETCH_KILL_GRACE_SECONDS` (5) before the kill, so a hung transport reaches the same alert instead of holding the deploy lock forever. Each fetch runs in a process group of its own that the script kills outright once git has exited, so a transport that ignores the deadline's TERM cannot outlive the tick; a kill can leave a git lock file that an operator removes by hand, never the script. After a refused or failed tick past the checkout (`hal` missing, `hal` exiting non-zero, a compose failure), `HEAD` stays detached at the new release while `deployed.sha` keeps the old one, so the checkout is ahead of the running stack until a later tick succeeds; the next tick retries, and the third consecutive failure alerts.

Under the deploy lock, each tick first removes leftovers directly in its Git admin directory whose names match the script’s four temp prefixes (`songmaker-autodeploy.git-fetch.`, `songmaker-autodeploy.compose-stderr.`, `songmaker-autodeploy.prometheus-ps-stderr.`, `songmaker-autodeploy.gh-stderr.`) followed by exactly six ASCII letters or digits. Symlinks are unlinked without following their targets; state files and nested worktree admin directories are untouched. Each removal is logged; a failed removal refuses the tick and counts toward the third-tick alert, including when already up to date. In-tick removal remains best-effort: an interrupted tick’s leftovers are removed by the next tick that acquires the lock and can remove them. This assumes one lock per Git admin directory; overriding `SONGMAKER_AUTODEPLOY_LOCK_FILE` to share an admin directory between independently locked ticks is unsupported.

When the selected release's alembic head differs from the running commit's, the tick first runs `hal backup songmaker --pre-apply` (path from `SONGMAKER_AUTODEPLOY_HAL`); a failed or missing backup is a counted refusal before any build or recreate. Before its Compose build, the tick inspects the two local-only base images. It runs `scripts/build_images.sh bases` without a timeout when either image is missing, when `docker/base/**` or the `vendor/acestep` submodule pin changed between the deployed revision and the selected release, or when the deployed revision cannot be compared. Its output streams directly into the service journal. After a successful recreate, the tick runs `docker image prune --force --filter until=48h --filter label!=songmaker.base-image=true`: Docker accepts this negated label filter, and `scripts/build_images.sh` applies that label to both base images so the cleanup never selects them. Before recreating, it tags only running Compose services with a `build:` section as `<project>-<service>:previous`; `<project>` comes from `docker compose config --format json --no-interpolate | jq -r '.name'`, so the tag follows the actual Compose project without materializing `.env` secrets. To roll back a built service, run `project="$(docker compose config --format json --no-interpolate | jq -r '.name')"; docker tag "${project}-<service>:previous" "${project}-<service>:latest" && docker compose up -d --force-recreate <service>`. Both cleanup commands are bounded by `SONGMAKER_AUTODEPLOY_PRUNE_TIMEOUT_SECONDS` (600 seconds by default); an error or timeout is logged at `err` with its command and exit code, while the completed deployment remains successful and the tick does not change either counter. The builder cleanup deliberately uses `docker builder prune --all --force --filter until=48h`, preserving cache used in the last 48 hours but allowing a quiet host's next rebuild to take its normal cold-cache 8–15 minutes.

### arq JSON queue deployment (#1684)

For the operator changing queue format: the web producer and both workers use
one UTF-8 JSON codec (`arq_codec.py`) for jobs and results. Unsupported objects,
non-string object keys and nonfinite numbers are rejected. No class is imported
or reconstructed, and there is no pickle fallback. The wire tests in
[`test_arq_codec.py`](../tests/test_arq_codec.py) cover the configured entry points.
Redis access control and network isolation remain separate requirements (#1301).

arq 0.27 cannot JSON-encode exception objects in failed or cancelled results. It
logs one serialization warning and stores inert `r="unable to serialize result"`
with `s=False`; its public result reader raises `SerializationError`. The app
does not read arq results. A leftover pickle job is rejected visibly with its job
ID, executes nothing and leaves a readable failed result. A legacy pickle result
read fails explicitly. Preserve that evidence and reconcile the application job
before retrying; never purge or silently retry these entries.

Use a coordinated operator window. Mixed pickle/JSON processes are unsupported,
and the auto-deploy guard checks database jobs, not queue-format compatibility.
Run host commands from the deployment checkout:

1. **Before the release tag**, stop `songmaker-autodeploy.timer` with
   `sudo systemctl stop songmaker-autodeploy.timer`. Record the running pre-merge
   git SHA for rollback. Keep the old release running.
2. The head's named landing task merges the PR, and the head tags the merge SHA
   once all Actions checks on `main` are green for it. The deploy script selects
   the newest fully green release; keep the window coordinated with other
   landings so the release is that SHA. If checks fail, leave the timer stopped
   and the old release running; fix forward with a newer tag and wait for green
   before draining.
3. Stop submissions. There is no maintenance switch: first wait until no cover
   jobs are queued or running (covers run in the web process), then run
   `docker compose stop songmaker-web`.
4. Wait for all application jobs and both arq queues to drain, including follow-on
   scoring. This read-only database check must return no rows:

   ```sh
   docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
   SELECT type, status, count(*) FROM jobs
   WHERE status IN ('queued', 'running') GROUP BY type, status;
   SQL
   ```

   For step 3, the same query's `cover` rows must be absent before stopping web.
   These queue checks must both print `0` (names owned by the worker settings):

   ```sh
   docker compose exec -T redis redis-cli ZCARD arq:queue:music
   docker compose exec -T redis redis-cli ZCARD arq:queue:scoring
   ```

   If anything remains, postpone; never purge. Once both checks are clear, run
   `docker compose stop songmaker-music-worker songmaker-scoring-worker`.
   Re-run both `ZCARD` checks after the workers stop; both must return `0`.
   If either is nonzero, for example because a cron job was enqueued between
   the drain check and shutdown, start the old workers again, let them drain,
   stop them again and repeat both checks. Proceed only when both return `0`;
   never purge. A pickle job that still appears is rejected visibly with its
   job ID by the JSON worker after restart; keep that fallback evidence.
5. With the timer still stopped, run one deploy tick:
   `sudo systemctl start songmaker-autodeploy.service`. The script owns fetch,
   release checkout, submodule update, build and joint startup. Check
   `journalctl -t songmaker-autodeploy -n 20` and its deployed-SHA marker against
   the tagged merge SHA. By default the marker is
   `$(git rev-parse --absolute-git-dir)/songmaker-autodeploy.deployed-sha`;
   `SONGMAKER_AUTODEPLOY_DEPLOYED_SHA_FILE` can override it. If the tick refuses or
   defers, fix the cause named in the journal (work clone or dirty checkout,
   Compose or alert configuration, mount preflight, database or CI) and rerun it.
6. Complete one smoke generation with scoring on that SHA, then run
   `sudo systemctl start songmaker-autodeploy.timer`. If smoke fails, drain again
   using steps 3–4 before rollback.

If the JSON release cannot deploy within the window, restart the old release
only with empty queues. If the tick has already checked out the release,
rebuild from the recorded pre-merge SHA. Rollback requires the same drain and a
joint restart of web and both workers. Name the rollback release by git SHA:
rollback image tags skip stopped services and can still point at the release
before the pickle release. Before restarting the timer, leave the deployment
checkout detached at a release; the tick never moves a checkout backwards, so
later ticks deploy only a release that contains it. See [auto-deploy architecture](architecture.md) for the tick's
existing guards.

### Secrets

- `OIDC_ISSUER`: Required, with no default; every `docker compose` command that reads `docker-compose.yml` refuses without it, like `GRAFANA_PASSWORD`. `OIDC_CLIENT_ID` defaults to `songmaker`. A leftover `ADMIN_USERNAME` or `ADMIN_PASSWORD` in `.env` stops startup (`Settings` rejects unknown keys), so remove them when deploying the Keycloak sign-in.
- `keycloak_client_secret`: the Keycloak client secret, a file owned by the edge (`~/.secrets/keycloak/clients/songmaker`, or `KEYCLOAK_CLIENT_SECRET_FILE` for a throwaway stack), mounted read-only into the web container at `/run/secrets/keycloak_client_secret`. Never an environment variable.
- `SESSION_SECRET`: HMAC signing key for session cookies. Required at startup (Settings raises ValidationError if missing).
- `ANTHROPIC_API_KEY`: Optional (for server-side Claude chat). Never logged or returned in responses.
- `GRAFANA_PASSWORD`: Required, with no default. When it is unset or empty, every `docker compose` command that reads `docker-compose.yml` refuses before it does anything, naming the variable — `up` and `build`, but also the recovery commands `down`, `logs`, and `ps` — so set it in `.env` first. `exec` into an already running service still works, and so do `ps`, `logs`, and `down` when the project is named without a file (`docker compose -p songmaker logs`, the project name being the checkout directory's name). Grafana never falls back to admin/admin. Setting it in the first place is the one command `./scripts/grafana-password`, run from the main checkout: if `.env` has no `GRAFANA_PASSWORD`, an empty one, or a publicly known one (`admin`, anything starting with `CHANGEME`), it writes a fresh random value there, then applies the `.env` value to the running Grafana and prints `set` (fresh value written) or `already set` once an authenticated API login with that value succeeds; if Grafana is not running, it says whether `.env` changed and asks you to start the stack and run it again. The value only seeds Grafana's first start, but the command applies whatever `.env` holds, so it also changes the admin password of an existing Grafana: put the new value in `.env` and run it. Without the command, put the new value in `.env`, run `docker compose up -d grafana`, then `docker compose exec -T grafana sh -c 'printf %s "$GF_SECURITY_ADMIN_PASSWORD" | grafana cli admin reset-admin-password --password-from-stdin'`. The password never appears in an argv (shell history, `ps`): the single quotes keep the host shell from expanding it, and `printf` is a builtin of the container's shell. Never pass it as the positional `<new password>` argument. CI uses a fixed throwaway literal (`.github/workflows/e2e.yml`).
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
- No raw SQL — 100% SQLAlchemy ORM with parameterized queries
- No Python `eval` or `exec`, `shell=True`, or `yaml.load` in `src/`.
- Untrusted arq data uses the JSON boundary above; trusted local scorer-process
  serialization is a separate boundary, not a queue decoder.

## Path Traversal Protection

Audio file serving resolves the requested path and verifies that it remains below the configured audio root to prevent directory traversal. The authenticated audio endpoint (`/audio/{owner_id}/{filename}`) checks that the requesting user owns the files (or is admin) — no DB lookup needed since the path is keyed by user ID. Album, song, and playlist shared-audio endpoints accept only a take id (`{generation_id}.mp3`), decide in the query layer by generation id whether the share presents that take (a playlist excludes entries whose song was deleted, as album and song shares do), and only then resolve the take's canonical stored path and check that the file exists below the audio root, logging traversal rejection without the root. A stored path in the address answers `404`. Their public JSON routes emit an audio address only when the take's stored path meets the canonical rule. Album and song covers are never served from `/audio/{owner_id}/{filename}`; authenticated covers use `/api/albums/{id}/cover` and `/api/songs/{id}/cover`, and public covers use `/shared/{slug}/cover` and `/shared/song/{slug}/cover`.

## GPU Resource Safety

- **Isolation by container**: `songmaker-acestep-worker-0` is the only container given a GPU (`runtime: nvidia`, `NVIDIA_VISIBLE_DEVICES: "0"`). `songmaker-scoring-worker` is given no GPU device and runs with `SCORING_DEVICE=cpu`, so scorer models and ACE-Step cannot contend for the same VRAM. There is no cross-container release handshake, because with CPU scoring there is nothing to release.
- **Generation VRAM**: The acestep-worker owns its own budget end to end — an LRU model cache bounded by `VRAM_BUDGET_GB` that evicts to fit an incoming load, and NVML heartbeats (`acestep_worker/gpu_util.py`) reporting live used/total GB to the control plane.
- **Scorer subprocess**: The child installs a SIGTERM handler that calls `torch.cuda.empty_cache()` before exiting, so the kill paths above (timeout, taint, `recycle()`) release device memory rather than orphaning it. On CPU that handler is a no-op; it exists for the CUDA case.
- **ACE-Step lifecycle**: The acestep-worker container manages the ACE-Step HTTP subprocess, sending SIGTERM (with SIGKILL fallback) on model switch, worker restart, or shutdown. See `docs/acestep.md` for the worker pool architecture.

Moving scoring onto the GPU (`SCORING_DEVICE=cuda`) would put two containers on one device and does need an arbitration protocol — a scorer-side release plus a verified-free check before generation. That protocol is not built; see issues #161 and #182.

## Known Limitations

- **Claude CLI agents**: `--disable-slash-commands` closes slash commands and skills (verified empty in the init event's `slash_commands` list — see Claude Chat Security above), but the CLI still lists five built-in *agents* (`claude`, `Explore`, `general-purpose`, `Plan`, `statusline-setup`) in that same init event even with every isolation flag set. No exploit path is confirmed: reaching one needs a `Task`-shaped tool, and `--tools ""` already removes that. A future CLI version that could reach an agent some other way would reopen this; the tool-surface gate does not check the `agents` field today.
- **No IP binding on sessions**: A stolen session cookie works from any IP. Songmaker stores no address or user agent per session; the session stays valid across mobile-network changes (#327).
- **No MFA in songmaker**: second factors, if any, are Keycloak's. Acceptable for invite-only deployments.
- **Worker control endpoints have no cooldown**: `POST /api/admin/workers/{id}/restart`, `POST /api/admin/workers/{id}/pin_model`, and `POST /api/admin/registry/{mode}/download` are not rate-limited. Repeated calls by a compromised admin could disrupt GPU workers or exhaust download bandwidth. Admin-only auth is the only gate.
- **`/metrics` endpoint is unauthenticated**: Exposes Prometheus metrics (request counts, latencies, queue depth, VRAM usage) without auth (`health_api.py:211-218`). The web container binds port 8080 to `127.0.0.1`, so the repository makes this endpoint host-local by default (`docker-compose.yml:89-90`); a public deployment needs a filtering layer in front of it, which this repository does not provide (#327).

## Hardening Roadmap (for public internet exposure)

The application-layer security (auth, CSRF, IDOR, injection, error sanitization) is solid for a self-hosted tool. The gaps below are infrastructure-level and would need addressing before exposing the app to untrusted public traffic at scale; any public edge configuration is operator-owned, not shipped by this repository.

### ~~1. Replace SQLite with PostgreSQL~~ (Done)
PostgreSQL is now required for production. SQLite is used only in tests (`init_test_db()`).

### ~~2. Persistent rate limiting (Redis)~~ (Done)
Redis-backed sliding-window rate limiting is now the only implementation. Rate limit state survives restarts and is shared across workers.

### ~~3. Account lockout / progressive delays~~ (Gone)
Passwords left with the Keycloak sign-in; lockout and brute-force throttling are Keycloak's.

### 4. Multi-worker architecture
**Priority: Medium** — PostgreSQL and Redis are in place. Multiple uvicorn workers can be added via `--workers N`. The arq worker already runs as a separate process.

### 5. Content Security Policy — remove `'unsafe-inline'` from `style-src`
**Priority: Low** — CSP now enforces `script-src 'self'` and `default-src 'none'`. The production build needs `style-src 'unsafe-inline'` for Svelte's inline styles and style attributes. Tightening means style hashes or nonces (`'unsafe-hashes'` for the attributes).

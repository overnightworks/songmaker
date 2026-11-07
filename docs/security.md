# Songmaker Security

The auth layer itself is not in this repository. `webauth` ships as the
distribution `overnightworks-webauth` from
[overnightworks/webauth](https://github.com/overnightworks/webauth), pinned in
the `server` extra to a git tag; `pyproject.toml` names the tag and `uv.lock` the commit.
Every image and CI sync passes `--frozen`, which installs that commit: the flag is the integrity
control, since `uv lock --check` does not notice a force-moved tag.
Module names below such as `webauth.dependencies` are its
import paths; which of songmaker's paths each policy applies to remains
songmaker's decision, built in `request_policies.py`.

## Authentication

People sign in through the operator's Keycloak realm (OpenID Connect, authorization code with PKCE); songmaker holds no password, no password hash and no admin bootstrap. `GET /login/oidc?next=` starts the sign-in with a pending-login cookie, `GET /auth/callback` finishes it, `POST /auth/logout` ends it; webauth serves these routes and the back-channel one. After sign-in songmaker's own signed session cookie, backed by a DB row, is the credential; the realm is consulted only at sign-in and sign-out.

- **Relying party**: `OIDC_ISSUER` and `OIDC_CLIENT_ID` come from the environment; the endpoints are derived from the issuer. The ID token's issuer is bound to the configured realm, so a token from another realm is refused. The settings are validated where the web relying party is built, so the workers start without them; a missing or unreadable client secret stops web and names only the path. `PUBLIC_BASE_URL` is also required: the redirect and post-logout addresses are built from it.
- **Client secret**: the edge owns the file `~/.secrets/keycloak/clients/songmaker`. Compose mounts it read-only into `songmaker-web` alone, as the file-backed secret `keycloak_client_secret` at `/run/secrets/keycloak_client_secret`; `OIDC_CLIENT_SECRET_FILE` names that path. It is in no environment variable, log or response. The agent-CLI child processes of the web container run as the same OS user and can read the file; this is the accepted single-user trust model ([Trust model](#trust-model-and-accepted-risks)), not a boundary.
- **Admission**: the ID token must carry the group `/apps/songmaker` or the sign-in ends at `/no-access` with no account, session or cookie. The group `/apps/songmaker/admin` makes the account an admin; both are re-read at every sign-in and at every token call ([Person tokens](#authentication)), so a promotion or demotion applies at the next one of them. The account id is the Keycloak subject. An existing row whose id equals the subject is reused, otherwise a fresh account is created, and the username is display text only (it is not unique, and it is cut to the column length of 100 characters). Account creation and role changes are written to the audit trail without a person.
- **Callback outcomes**: success is a 303 to the validated `next` (a path of this app, else `/`); a non-member is a 303 to `/no-access`; every other refusal (state mismatch, expired or missing pending login, foreign issuer, token-exchange failure) is a 403 carrying the SPA shell, "Login failed" and a "Try again" link to `/login/oidc`. The library clears the pending-login cookie that the submitted state names (foreign issuer, expired login) and leaves the others, so a callback with an unknown state keeps another tab's pending login intact until it expires. Admission and the new session are one database transaction under the write lock, committed before the cookies are issued, so a failed commit leaves no cookie, account or session. `/login/oidc`, `/auth/callback` and `/auth/logout` answer `Cache-Control: no-store`, refusals included.
- **Person tokens**: a token created through hal acts as the person behind it, with that person's rights, deletion included, on `/api/` and `/audio/` only. `TOKEN_CLIENTS` (comma list, empty by default; empty, it admits no person token, and with MCP on the gate then holds only the resource: `/mcp` and its marked routes) names the `azp` values admitted; the match is exact and case-sensitive, an empty entry in a non-empty list stops startup, and the token's only audience must be this client. `/shared/`, the sign-in routes and WebSockets are not reachable by token; `/api/internal/` lies under `/api/` but keeps its own internal-token dependency, so a token alone registers no worker. `Authorization` is not an allowed CORS header; a CLI needs no CORS. An unknown subject gets an account at its first token call as at a first sign-in (audited without a person), and no session is created. A token's groups rewrite the stored role at each token call, so an older token can write its older role back within its lifetime. The per-address rate limit is shared with the browser. The co-writer needs the browser session to read the person's groups, so `POST /api/chat/turn` answers 403 `The co-writer needs a browser login.` to a token before it writes any chat state (the token's admission may already have created the account).
- **Resource tokens**: see [MCP endpoint for a person's own agent](#mcp-endpoint-for-a-persons-own-agent); such a token is not a person token, and `TOKEN_CLIENTS` does not name its client.
- **Session tokens**: `secrets.token_urlsafe(32)` — 256-bit entropy, stored in the DB.
- **DB session authority**: Every authenticated request loads the session and account from the DB; the library checks the stored idle expiry and the absolute age from `created_at`. Renewal must update an existing row (`touch()` returns `True`); a missing or revoked row cannot be recreated. A request carrying a verified token on a person path has no session: the token decides (next item).
- **HMAC-signed cookies**: Session cookies are `{session_id}.{hmac_sha256}` signed with a server-side secret. A DB leak alone does not yield usable cookies. The secret is the file `session-secret` in the secrets directory (mounted as `/run/secrets/session_secret`, min 32 chars) and is required at startup — Settings raises `ValidationError` if it is missing or empty. There is no auto-generation fallback.
- **Cookie flags and names**: The session cookie is `HttpOnly`, `SameSite=Strict`, `Secure` when `COOKIE_SECURE` is true (the default), and is then named with the `__Host-` prefix (`__Host-session_id`), which a browser accepts only on a `Secure` cookie carrying no `Domain`. The library's pending-login cookie is `SameSite=Lax`, because the return from Keycloak is a cross-site navigation. Sign-in sets no other cookie: no CSRF cookie and no logout hint cookie; a browser that still holds either from an earlier version keeps it until its own `Max-Age` runs out, and neither is read or cleared. `COOKIE_SECURE=false` drops `Secure` and the `__Host-` prefix together, for local plain-http development and the CI stack; production never sets it false.
- **Session lifetime**: `SESSION_IDLE_SECONDS` (default 7 days) is renewed by every authenticated request, including `GET /api/auth/me`, up to `SESSION_ABSOLUTE_MAX_AGE` (default 30 days) from `created_at`. The cap per account is `MAX_CONCURRENT_SESSIONS_PER_USER` (default 10); a sign-in ends the session its request carried and prunes only the oldest overflow.
- **Tokens at rest**: the session row holds the issuer's refresh token in `user_sessions.refresh_token` (`NULL` when the issuer gave none) and the ID token in `user_sessions.id_token`. Both are secrets at rest: plain text in the database dump, handed out only as a `SecretStr` by `UserSession`, and the engine hides SQL parameters (`hide_parameters=True`) so a failed insert keeps them out of the traceback. No response, log line or `/health` carries either; both leave with the row on logout, expiry, pruning and revocation. The refresh token serves the co-writer turn, which reads the person's groups with it (`current_groups` stores a rotated refresh token before it answers; see "Co-writer turn through the gateway"); the ID token's one use is the hint on the logout page.
- **Logout**: `POST /auth/logout` is a top-level form POST from the SPA, which first checks that the server answers (`GET /api/auth/me`; unreachable means it stays signed in and says so) and then leaves through the history controller. The route deletes the DB session in one transaction, clears the session cookie and answers the library's page (`no-store`, under its own Content-Security-Policy): a form that posts the client ID, the post-logout address and the ID token stored in the session row to Keycloak's end-session endpoint and submits itself, so Keycloak ends its session without asking and returns to `/login` ("You are logged out."). With no script the page shows one button, "Sign out" (`LOGOUT_BUTTON_LABEL`, the label of the SPA's account menu entry). Without a session, or with a row from before the upgrade that holds no ID token, the page posts no hint and Keycloak asks once. The route is behind the origin check like every write. A database failure answers a plain 500 with no page and no cookie cleared. The ID token appears in no log line, URL or header; the one response that carries it is this page. Sign-out also leaves a cross-tab marker in `localStorage` under `playbackLogout:<user id>` so other tabs stop saving playback; its key holds the user's id and its value is an opaque random string, no secret.
- **Session cookies of the old login**: the 0.14 library's cookies are refused (`401`); the migration also deletes every session row.
- **Frontend auth-check classification**: A non-public 401 navigates the whole page to `/login/oidc?next=…`; the public paths (`/shared/*`, `/share/*`) never redirect. A 429, a 5xx or a network error on the SPA's startup `GET /api/auth/me` is transient: the known session state is kept and the layout shows a retry-able error instead of forcing a sign-out.

### Keycloak outage

Signed-in requests never call Keycloak: the session is songmaker's own, so the app, generation, scoring and the co-writer keep working while the realm is down. Web boots without reaching the issuer. During an outage a new sign-in fails at the browser (the redirect to Keycloak does not load) or, when the failure happens while songmaker exchanges the code, ends in the "Login failed" page; sign-out ends the songmaker session and the form POST to Keycloak then fails in the browser. Existing sessions are not affected.

### Revocation

Keycloak is the account owner, but songmaker applies its answers only at sign-in and at each token call. Disabling a user or removing them from `/apps/songmaker` ends nothing by itself: a session stays valid until it goes idle for `SESSION_IDLE_SECONDS` or reaches `SESSION_ABSOLUTE_MAX_AGE`, and continued use renews it, so the bound is the absolute age (30 days by default), not the idle time. Two ways to end access now:

1. Sign out in Keycloak or in songmaker: `POST /auth/logout` on that device ends that device's session and the Keycloak session, and a sign-out at Keycloak ends every songmaker session of that account through the back channel (below).
2. Delete the sessions in the database (a person token is not a session: signing out, a back-channel logout or a Keycloak block leaves it valid until its expiry plus leeway, and a copied token is the person until then): `DELETE FROM user_sessions WHERE user_id = '<subject>';` (all of them: `DELETE FROM user_sessions;`). The next request is a 401.

**Back-channel logout.** Keycloak posts a signed Logout Token to `POST /auth/backchannel-logout`, and songmaker ends every session of the token's subject (webauth's back-channel route, audited as a `delete` of resource `session` without a person). The token must be a `logout+jwt` of the bound issuer for this client, carry the back-channel logout event and a `sub`, and no `nonce`; the realm client sets `backchannel.logout.session.required` to `false` because `sid` is ignored. The route answers 200 only after the commit and an empty 400 for any refusal or failure (a failure is re-raised after the answer and logged by the server), in its own worker-thread session and transaction; an audit failure after the deletion rolls the deletion back too. The boundary is the Logout Token's signature (webauth verifies the issuer's RS256 key, `typ`, `aud`, age, event, `sub` and the absent `nonce`) and the edge's public deny of the path. The Host check only filters routing: the realm posts to `<PUBLIC_BASE_URL host>:8080` on the external network `hal_backchannel_songmaker` (declared `external: true`, created by the edge stack, joined by `songmaker-web` alone, which carries the public host as its alias there); any other admitted Host, the public host without the port and `songmaker-web:8080` included, gets an empty 404 (a dependency on the route, answered by an exception handler), an unlisted Host gets TrustedHost's 400, and the body is capped at 32 KiB. The exact path (`SignInPaths.backchannel`) is exempt from the rate limit and from the origin check, and from nothing else; a variant such as `/auth/backchannel-logoutx` is not. A logout that completes before a later sign-in cannot end that later session; this limit is accepted. Two residues are accepted: webauth keeps no `jti` store, so a token can be replayed within its short validity window (about two minutes); and a transient failure answers 400, is logged and is not retried, so the session lasts until its idle or absolute bound.

## Authorization

Two-layer defense:

1. **Dependency-based auth** (`webauth.dependencies`, bound to songmaker's stores in `auth_dependencies.py`): `get_current_user` returns the account of a verified person token on a person path (no cookie or session is read, see Person tokens above) and otherwise validates the signed cookie and the DB session, checks expiry and lifetime, and renews the existing row with an update-only `touch`, so a session deleted meanwhile stays deleted. Its own short transaction commits renewal before the endpoint runs, without committing endpoint writes. Manual stream callers commit and close their authentication transaction before starting the stream.
   The logout route does not depend on `get_current_user`: the library's logout route reads the session cookie itself, deletes the stored session it names, and clears the cookies either way.
2. **Endpoint** (`api.py`): Authenticated resource endpoints use `Depends(get_current_user)` and return 401 if unauthenticated. The sign-in routes are deliberately unauthenticated; worker control-plane routes under `/api/internal/*` use the internal token instead of sessions. Ownership checks enforce default-deny: access is blocked unless the resource belongs to the user (or the user is admin). Missing resources are denied.

Roles: `Literal["admin", "user"]` — validated at the Pydantic schema level. No other role values are accepted by the API. The role is set from the Keycloak admin group at each sign-in and each token call; there is no in-app account administration.

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
a deployment-time fact, so they call `public_share_url()`
instead, backed by the validated `PUBLIC_BASE_URL` setting — see "Production
Deployment" below.

## CSRF Protection

Three-layer defense, with the origin check as the only guard:

1. **`SameSite=Strict` cookies**: Prevents cross-site cookie transmission in modern browsers
2. **Fetch metadata**: A state-changing request is judged by `Sec-Fetch-Site` first. `same-origin` passes; `cross-site` and `none` are rejected (403), even with an allowed Origin; `same-site` falls through to the Origin allowlist.
3. **Origin verification**: Without `Sec-Fetch-Site`, a state-changing request (every route, not only `/api/`: the `/shared/*/stream` share manifests and `POST /auth/logout` too) needs an `Origin` that matches `ALLOWED_HOSTS` by exact host name (localhost by default), and with `COOKIE_SECURE` on the origin must be `https`. A request with neither header gets 403 `Missing Origin header`; `Referer` is not read. The allowlist is server-side, not the request's `Host` header, so a spoofed `Host` does not help.

For a cookie no token is involved: the session cookie is `SameSite=Strict` and the origin layer decides. A request with a verified token on a person path bypasses the check, because a browser never attaches `Authorization` by itself. Two routes are exempt because their callers are no browser and prove themselves otherwise: the exact path `/auth/backchannel-logout` (the Logout Token's signature) and the prefix `/api/internal/` (the internal token). Variants such as `/auth/backchannel-logoutx` or `/api/internalx` are not exempt. A browser that sends neither fetch-metadata header on a write (older than the current Chrome, Edge, Firefox and Safari) is refused. [Server tests](../tests/songmaker_cli/test_server_middleware.py) prove the accepted and rejected header cases.

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

Album and song shares serve the picked unarchived generation when one exists, otherwise the latest unarchived generation. Generation shares serve the shared generation. Playlist shares expose audio only for playable entry generations. Their page manifest supplies a playlist `cover` only when its uploaded file exists, otherwise up to four `album_covers` from its entries. Those mosaic URLs remain bound to the playlist share slug: the public route accepts an album only when it belongs to that shared playlist and its requested version key is current; it never redirects to or reveals a private `/api/albums/{id}/cover` URL. Stream manifests likewise contain only playable takes and no cover fields, so every listed audio URL is authorized to return bytes. `create_generation()` canonicalizes every non-empty MP3 path at the single write boundary and rejects a path that would leave the audio root; WAV-only takes retain their empty MP3 sentinel. Public audio addresses name the take (`{generation_id}.mp3`) and never contain the stored path or the creator's account id; JSON assembly builds them without filesystem resolution, and an old account-prefixed stored-path address answers `404`: authorization uses the take's identity, and a root-level stored file named `{generation_id}.mp3` is the new address itself. Public JSON responses omit scores and edit history; an audio URL is present only when its stored relative path is already canonical and remains below the audio root. A noncanonical stored path is a data defect: it is not silently repaired, is omitted from the response, and is logged at `WARNING`. Album JSON includes `cover` only while the album is shared and the cover file exists. Song JSON includes `cover` only while the song is shared and the **song** cover file exists. Song and generation JSON include `album_cover` only while their own share remains public and the parent album cover file exists. Public cover bytes are served through the matching album, song, generation, or playlist share slug — never a client-supplied path on `/audio/{owner_id}/{filename}`. Unshare, replace, or delete 404s the previous public cover URL. Share slugs are UUID v4 values (122 bits of entropy, unguessable). Sharing is revocable by the resource owner.

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
| API    | Everything not matched below (including `/health` and unrecognized paths) | 120/min | Unchanged from the original single budget. `/health` is deliberately **not** exempt: it is the most expensive anonymous endpoint (a DB check and two DB queries, plus Redis reads that grow with the registered workers) and its callers are the container healthcheck (every 30 s), the CI smoke and CI's E2E (`offline-boot.spec.ts`) — exempting it would let an anonymous caller hammer the priciest endpoint for free. |
| Media  | `/audio/*`; every `/shared/**/audio/*` and `/shared/queue-streams/{id}/audio` route; `/api/references/{id}/audio` | 600/min | Range-request media playback is normal use, not abuse: a single MP3 played with normal seeking is **estimated** at roughly 40 range requests (order-of-magnitude from typical browser Range-chunking, not measured), and comparing takes can move through several songs a minute (40 × 5 = 200/min in ordinary use). 600 leaves headroom for aggressive seeking while still bounding an IP's disk I/O — not unlimited. All of these paths serve a `FileResponse` (Range-capable) — the public share audio routes carry the same seek/scrub pattern as the owner's own player, just from a stranger listening to a public share, so they get the same class. The policy matches each share-audio route with a regex anchored on the literal `audio` segment at the position that route defines, so a slug that literally reads `audio` cannot pass as one by shape alone. The metadata routes on the same slug — `/shared/{slug}`, `/shared/song/{slug}`, `/shared/gen/{slug}`, `/shared/playlist/{slug}`, every one of their `/cover` routes (song and album cover are both API, deliberately, not just the album one), and the `/stream` manifest POSTs — are deliberately excluded and stay API: only the byte-serving audio routes are Range-served. `/api/references/{id}/audio` is the one `/api/` path in this class: it serves a person's own reference recording with Range, answers only the owner (an admin included, no bypass) and answers a foreign, unknown or unusable file with the same 404; it keeps the API-wide `no-store`, so a seek is a fresh request. |
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
- `Cache-Control: no-cache` on every response that carries the SPA shell (`spa_fallback`, so `/` and each client-side route), set by the shell response itself because a path rule cannot name every SPA path: the browser revalidates it at each load and a deploy reaches it, instead of reusing a shell whose hashed `/_app/` files the new build deleted. The hashed files under `/_app/` keep their caching.
- `Cache-Control: private, max-age=31536000, immutable` on generation audio: `/audio/*` and every `/shared/**/audio/*` route (`sharing_api.py`). A generation file never changes under its name, so the listener's browser keeps it for a year, while `private` forbids any shared cache (CDN, proxy) from holding it. Consequence: a revoked share stays playable from that listener's own browser cache. Queue-stream snapshot audio is not a generation file — it expires within hours — so `/shared/queue-streams/{id}/audio` sends `no-store`.

## CORS

- **Methods**: `GET`, `POST`, `PUT`, `DELETE` (no wildcard)
- **Headers**: `Content-Type`, `Cookie` (no wildcard)
- **Credentials**: Allowed
- **Origins**: The normal interface calls the API under the same origin, so it needs no CORS permission. A deliberately separate trusted browser client may set `CORS_ORIGIN` to its one literal origin, but cross-site browsers cannot make mutating `/api/` calls because the fetch-metadata check rejects them even with CORS permission; startup rejects wildcards and comma-separated lists. `SameSite=Strict` does not isolate sibling subdomains of the same site, so do not trust a credentialed subdomain wildcard. When unset, CORS defaults to `localhost`/`127.0.0.1` on ports 8080 and 5173 only for dev (not any arbitrary port).

## Error Handling

- **Generation, scoring, and LoRA job errors**: `_sanitize_error` maps known worker and setup doses to fixed musician-facing messages and logs raw failures with the job ID only on the server; generation, scoring, and LoRA store that returned message in `job.error` (`jobs/_runtime.py:38-45,62-78`; `jobs/generation.py:473-483`; `jobs/scoring.py:194-213`; `jobs/lora_training.py:506-515,618-631`). Raw reasons live in the service's JSON container log, retained as five rotated 10 MB files.
- **API errors**: HTTPException messages on ordinary validation paths are human-readable strings with no internal paths or stack traces (`settings_api.py`).
- **Validation errors**: The custom `RequestValidationError` handler returns only affected field names, not full Pydantic error details (constraints, expected types, internal schema) (`server.py:273-290`).
- **ACE-Step errors**: Worker failures map through `_sanitize_error` to a fixed message before the generation job persists `job.error`; only the silent-stream dose stays distinct (`jobs/_runtime.py:38-45,62-78`; `jobs/generation.py:469-480`).
- **Co-writer errors**: A co-writer turn the agent did not run ends with an SSE error frame on an otherwise HTTP 200 response: `status` (503, 429, 403 or 401), the named `problem` (`unavailable`, `busy`, `not_enabled`, `sign_in_again`) and, for `busy`, `retry_after_seconds`. The frame carries no gateway or provider detail; the reason is logged server side.
- **OpenAPI/docs**: Disabled (`server.py:167`).

## Request Size Limits

Songmaker itself enforces these limits: `BodySizeLimitMiddleware` (`webauth.middleware.body_size`, raw ASGI) first checks `Content-Length` for fast rejection, then wraps the receive channel to count bytes as they stream in — aborting with 413 once the limit is exceeded without buffering the entire body. Which route may exceed the default, and by how much, is songmaker's `BodySizePolicy` (`request_policies.build_body_size_policy`).

JSON API requests are capped at 1 MiB (`MAX_REQUEST_BODY_BYTES`). Large multipart uploads use a path-exact allowlist, not a suffix match:

| Path | File budget | Multipart body budget |
|---|---|---|
| Default JSON | — | 1 MiB |
| `POST /api/references` | 50 MiB per file | 50 MiB + 1 MiB envelope |
| `POST /api/loras/{lora_id}/samples` | 50 MiB per file | 50 MiB + 1 MiB envelope |
| `POST /api/albums/{album_id}/cover` | 8 MiB per image | 8 MiB + 1 MiB envelope |
| `POST /api/songs/{song_id}/cover` | 8 MiB per image | 8 MiB + 1 MiB envelope |
| `POST /api/playlists/{playlist_id}/cover` | 8 MiB per image | 8 MiB + 1 MiB envelope |

File limits and body limits are separate so a legal 50 MiB file is not rejected for multipart headers. `POST /api/loras/{id}/samples/{sample_id}` is not a large-upload path.

### Reference audio upload

`POST /api/references` accepts audio files (.mp3, .wav, .flac, .ogg) up to 50 MiB (52,428,800 bytes) per file. Files are stored in `{audio_dir}/{user_id}/refs/{uuid}.{ext}` — the UUID filename prevents name collisions and path injection. Each user also has a positive aggregate quota: `reference_audio_quota_bytes=500_000_000` (decimal 500 MB) and `reference_audio_quota_files=50`. Every upload is a `reference_recordings` row (owner, `storage_path`, original filename, size, duration) and the file is the row's `storage_path`; admission counts the owner's rows, never a directory listing. A file without a row (a remnant) counts nowhere, blocks nothing and is never touched by an upload; the daily reconciliation removes it. Existing overage refuses additions without deleting anything. A filename carrying NUL or another C0 control character is refused with 400 `{"detail":"Invalid filename."}`. The exact quota refusal is HTTP 409, `{"detail":"Reference audio storage limit reached."}`; the previous draft reference survives. A person deletes an unused reference through `DELETE /api/references/{id}`: it locks the row, refuses a used one with 409 `{"detail":"Reference audio is in use."}` (the two foreign keys from `versions` and `generations` decide, trashed songs and archived takes included), commits the row's removal with an audit record, then unlinks the file at once through the same `O_NOFOLLOW` walk; a failed unlink still answers 204 and the daily reconciliation removes the file. A stored path other than `<user>/refs/<one name>` refuses with 500 and keeps the row. The operator can raise these settings.

`reference_audio.py` owns the synchronous operation and its database session. A PostgreSQL transaction-scoped advisory lock keyed by namespace and user (SQLite: `BEGIN IMMEDIATE`) covers the row count through the commit of the new row, including after request cancellation. It does not lock the user row, so unrelated writes referencing that user can proceed. Waiting uploads hold database connections; the existing upload rate limit bounds this accepted cost.

The music worker's daily reconciliation (`DAILY_CLEANUP_HOUR_UTC`) deletes every regular file under a person's `refs/` directory that none of that person's rows names. Per person it takes the same owner lock, reads the person's `storage_path`s only after the lock (each statement under PostgreSQL's default READ COMMITTED takes a fresh snapshot, so a concurrent upload's commit is seen or its admission waits) and holds the lock through the unlinks. It walks to `refs/` without following a symlink and creates nothing. It refuses a symlinked or non-directory ancestor, a row whose `storage_path` is not exactly `<user>/refs/<one name>` (nothing is deleted for that person) and any non-regular entry (left in place). One person's failure leaves the others running. Logs carry the user id, counts and error kinds, never a file name or path.

A version save (`POST /api/songs`, `PUT /api/songs/{song_id}`) that sets `reference_recording_id` loads the owner's row under `SELECT … FOR NO KEY UPDATE` and commits the link in the same transaction; a missing or foreign id answers 404 `{"detail":"Not Found"}` and writes nothing. A concurrent delete of that row either waits and fails on the foreign key (`versions.reference_recording_id`, ON DELETE RESTRICT) or commits first and the save answers 404, so no version links a missing row. A save that omits `reference_recording_id` takes no explicit reference-row lock. A take takes the same lock when it is saved: a reference deleted between the job's start and the take's persistence fails the job with "The reference track was deleted while this take was generating." and saves nothing, and the foreign key (`generations.reference_recording_id`, ON DELETE RESTRICT) backs the lock.

A symlinked or non-directory owner root or ancestor fails closed with HTTP 500, `{"detail":"Reference audio storage could not be checked."}`; this also covers the configured `audio_dir`'s own ancestors. Logs carry the user id, the reference id, bytes and an error kind, never the original filename, a path, an OS error text or content. A database failure at any stage (owner lock, insert, flush, commit) answers with the same 500 body as a storage failure and is logged with a database error kind. A failure before the commit (write, insert, flush) removes the upload's own file; if that removal fails the file stays as a remnant until the next daily reconciliation. A commit that raises keeps the file, because the commit may have succeeded with its confirmation lost: without a row the file is an uncounted remnant until the next daily reconciliation, with the row committed row and file agree.

A version names its reference by `reference_recording_id` only. `reference_audio_path` is not a field of a version, a preset or a global generation default: a request that sends it is refused with 422 (`extra="forbid"`). The reference is checked twice, the id at save time and the path at job time:

1. **Song write**: the id must name a row of the authenticated user, loaded owner-scoped under its row lock
2. **Job execution**: the job loads the job user's own row and resolves its `storage_path` under `{audio_dir}/{user_id}/refs` with the owner-root resolver; a foreign or missing row, a symlink or a missing file fails the job instead of falling back to no reference

### Album, song, and playlist cover upload

`POST /api/albums/{album_id}/cover`, `POST /api/songs/{song_id}/cover`, and `POST /api/playlists/{playlist_id}/cover` accept JPEG and PNG only (SVG and WebP are rejected). The server checks magic bytes, decodes with Pillow, applies EXIF orientation, and strips metadata before writing. Named pixel and byte ceilings reject decompression bombs. Card and detail derivatives are written at upload time; GET never resizes. Album files live at `{audio_dir}/covers/{album_id}/`; song files live at `{audio_dir}/song-covers/{song_id}/`; playlist files live at `{audio_dir}/playlist-covers/{playlist_id}/`. Authenticated GET/POST/DELETE use `check_album_access`, `check_song_access`, or the matching playlist ownership check (foreign resources 404). Authenticated and public song cover endpoints stream only that song's files — 404 when the song has no own cover, even if the parent album has one. Public bytes use the matching share slug. The song- and playlist-cover body budgets are the cover ceiling.

Album cover suggestions are private rows bound to an album and its cover job. Every suggestion endpoint applies `check_album_access`; missing, foreign, malformed, and unsafe stored paths return the same 404 response. A suggestion path must equal `cover-suggestions/{album_id}/{suggestion_id}.png` under the audio volume, and selection passes the validated PNG through the existing album-cover writer. Suggestions have no public or share URL. Discard deletes database rows before their files, while album hard-delete removes the sibling suggestion tree after commit; neither action removes the selected `cover_key` image. The web container is the sole cover executor: its runner claims queued jobs, owns recovery, and draws each picture through the gateway (see "Cover picture through the gateway"); no path falls back to a CLI or another image API. `covers.decode_cover_image` accepts one PNG or JPEG within `COVER_MAX_BYTES` and `COVER_MAX_PIXELS` and rewrites it as a metadata-free PNG. The prompt quotes album values as data, limits each track's style and lyrics excerpts to 500 characters, and limits the complete prompt to 6,000 characters.

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

- **System prompt**: The body of the agent file `agents/cowriter.md`, shipped with the code and sent as the run's system prompt. It holds no user content and clients cannot override it. Song, memory, and mention context is wrapped in XML tags, and the untrusted notice in the agent file instructs the model to treat everything inside those tags and all tool outputs as untrusted data and never follow instructions found there.
- **Co-writer authorization**: All thirteen co-writer tools require album ownership, including for administrators, through the gateway turn's hand tools. Lists and searches filter to owned resources; foreign resource IDs return not-found before creating versions, work records, songs, or cover jobs. HTTP administration retains its existing access. User-selected current-song, current-take, and @-mention context also retains admin access: an admin can load foreign context, but tool calls against it return not-found. Residual risk: foreign context or tool output can still steer writes to the admin’s own songs; the untrusted notice is guidance, while owner-only authorization enforces the foreign-resource boundary. [Ownership matrix](../tests/songmaker_cli/cowriter/test_tools_ownership.py) pins both paths (in-process dispatch and hand tools).
- **Multi-turn history**: Stored in `chat_messages` and scoped to a conversation; the co-writer applies a token budget with a rolling summary for older messages (`conversation_api.py:477-503`; `cowriter/history.py:65-76,89-144`). Ownership is enforced via `check_song_access()` on every endpoint.
- **Context built server-side**: Mentioned song/version IDs are sent by the frontend, but the backend resolves them from the DB — the client never sends raw context. Each mentioned song is ownership-checked.
- **No co-writer turn or cover runs on a Claude CLI**, so no song content reaches one. The co-writer runs only through the gateway (next section).
- **No per-song chat endpoint**: the legacy `POST /api/songs/{id}/chat` (`chat_api.py`) and its `/api/settings/claude-models` settings were removed (#1190); `POST /chat/turn` in `conversation_api.py` is the only co-writer entry point.

## Co-writer turn through the gateway

`POST /chat/turn` runs `agents/cowriter.md` through agent-runtime-client's `GatewayBackend` against the LiteLLM gateway; no model runs inside `songmaker-web`, and `songmaker-web` serves the turn no tool endpoint: the person's own agent's MCP endpoint ([next section](#mcp-endpoint-for-a-persons-own-agent)) is a separate path. `agent/backend.py` owns the turn and `agent/tools.py` the tools.

**Configuration and the key.** The nested setting `agent` (`AGENT__BACKEND`, `AGENT__GATEWAY__ORIGIN`, `AGENT__GATEWAY__KEY_FILE`, `AGENT__GATEWAY__CA_FILE`, `AGENT__API_GROUP`) holds the gateway's origin, the file with the app's key and the API group. Unset, the turn ends `unavailable` and no request leaves; a partly set value, an unknown `AGENT__` key or all-empty values stop startup. The key stays in its file: the client reads it for each turn, sends it only as the bearer to the configured origin and writes it to no log or exception, and a missing or unreadable file ends the turn `unavailable`. Compose sets `agent` for `songmaker-web` (the gateway's plain-http origin on `hal_agent_songmaker`, so no CA file) and mounts the `gateway_key` secret; a person needs the Keycloak group `/services/agent-service/api` beside `/apps/songmaker`, or the turn ends `not_enabled`. The HTTP backend sits in the `agent` extra that only the web image installs; the workers load `Settings` with the bare client.

**Who may ask.** The client checks the account's role against the agent file's `appRoles` and the person's groups against the API group before it reads the key. The groups come from a fresh refresh grant at the issuer (`current_groups`), so a person removed from the group is refused at the next turn; a refusal of that grant is never read as an empty membership. A person outside the group or the roles gets `not_enabled`; a session without a usable refresh grant gets `sign_in_again`; an issuer that is down gives `unavailable`. In all three, no request leaves.

**What the gateway learns about the person.** The request's `user` field is the client's fingerprint of the normalised issuer and the account id (`fp-` and 64 hexadecimal digits) and nothing else; the gateway budgets by it. No request carries the account id or the issuer.

**Tools.** Each hand tool takes the person only from the turn's principal (the account id), loads the account from the database in a fresh session and applies today's owner-only checks. The tool schemas carry no user or owner field, so the model cannot name a person. `execute_cowriter_tool` checks the arguments against the tool's own declaration before any handler runs: an unknown key, a missing required key or a value of another JSON type is a tool error naming the field, with no commit. A handler that raises gives the model the client's fixed sentence and logs only the exception class. A turn is cut by `maxToolCalls` and `maxDurationSeconds` of the agent file.

**Order and refusals.** A turn ends in one of four named problems: `unavailable` (no `agent`, a refused agent file, a gateway error or refusal including a budget refusal, a refused connection, an unusable key, a crossed limit, a finished turn without words), `busy` (a 429 with its `Retry-After`), `not_enabled` and `sign_in_again`. It never falls back to a local provider, and no assistant message is stored for a problem. Named gaps: a person over budget sees `unavailable` without the reason; a turn that wrote and then failed shows `unavailable` while the write stands; words the model writes beside a tool call never reach the person.

**A started turn finishes.** A browser that left only stops listening; the turn runs to its end and stores its answer (#1014). Versions a tool wrote before a failure stay; no partial answer is stored as the answer.

**The network.** `songmaker-web` joins `hal_agent_songmaker` (external, internal, fixed name), on which the gateway's front is reachable. Its members are direct peers of `songmaker-web:8080` and can open it on any path with `Host: songmaker-web`. They meet today's protections: no session means 401 on `/api/`, a mutation that names neither a same-origin fetch nor an allowed origin means 403, the internal worker routes need `X-Internal-Token`. `GET /health` answers them with the status `ok` or `degraded` and nothing else; that is the intended exposure. `GET /metrics` and `GET /health/details` answer only a request carrying the monitoring token.

**Named gap: the forwarded address.** With `TRUSTED_PROXIES` at `172.16.0.0/12`, a direct peer can send `X-Forwarded-For` and the per-IP budgets and the access log use the forged address. Sessions, the origin check and the internal token do not depend on the address. Narrowing the range needs the default network's subnet pinned, which recreates the live network. Trigger: a new peer on `hal_agent_songmaker` or an observed budget evasion.

**Retention outside songmaker.** The gateway receives the turn's system prompt, messages, tool calls and results and forwards them to the model provider over the provider's API. Songmaker keeps the conversation in `chat_messages` only.

## MCP endpoint for a person's own agent

`songmaker-web` serves `POST /mcp` (`agent/mcp.py`, agent-runtime-client's `McpPersonFront`) to the agent of one signed-in person; it is on only while `AGENT__MCP_CLIENT_ID` and `AGENT__MCP_SCOPE` are set together, and off otherwise, when `/mcp` and `/.well-known/oauth-protected-resource/mcp` answer like any unknown path. One value without the other stops startup. A route is a tool only when it carries the `agent_tool` mark; `agent/mcp.py` reads the marks from the app's own schema at startup (also while MCP is off, so a mark outside the generator's profile fails the build), and a test pins the tool list.

- **Token**: a resource token of webauth's `ProtectedResource`: issuer and RS256 `at+jwt` as every token, the only audience the `/mcp` URL (`PUBLIC_BASE_URL` plus `/mcp`), the `azp` of the public client the person's agent signs in with, the configured scope, and membership of the Keycloak group `/apps/songmaker/mcp` (a subgroup of `/apps/songmaker`, so it alone makes the person an app member). It lives the realm's 300 seconds. The same token is also accepted on the marked routes themselves, beside the cookie session and, where `TOKEN_CLIENTS` names its client, a hal token. On an unmarked path the agent token is not admitted. While `TOKEN_CLIENTS` names a client, the person-path check refuses an agent bearer there with 401, even beside a valid cookie. While `TOKEN_CLIENTS` is empty, that check is off, the bearer is ignored there and the cookie or a 401 decides. Its client is not in `TOKEN_CLIENTS`.
- **Person**: the account behind the token's subject, which must have signed in once (the token creates no account), admitted as role `user` whatever role is stored; an admin's agent sees only that admin's own content. Cookie sessions and CSRF on the API are unchanged; a cookie beside an invalid bearer on a marked route is 401.
- **Reach**: the tools are `list_albums`, `create_album`, `list_songs`, `create_song`, `get_song`, `generate_song`, `get_active_generation` and `get_last_failed_generation`; each calls its route in-process through the whole middleware stack, so ownership checks, the per-address budget and the person's generation limit apply as for the browser. No route that deletes, shares, publishes or sends outward is marked, so a token cannot delete or share. No per-person cap on created songs and albums exists; the per-address `/api` budget bounds a loop.
- **Recipient**: the tools answer with the full response of the route, so every field of those responses goes to the person's own agent and, as content, to its model provider, at that person's request. That includes the take paths `mp3_path` and `wav_path` of `GET /api/songs/{song_id}`, which hold the person's pseudonymous account id. The provider is named in the privacy notice before anyone but the operator joins the group.

## Cover picture through the gateway

A cover suggestion runs `agents/cover.md` through the same `GatewayBackend` and key as the co-writer turn; `agent/backend.py` owns the call (`run_cover_picture`) and the click's check (`cover_admission`), and `cover_runner.py` the job.

**Who may ask, twice.** Suggest needs a browser session: a hal token (bearer) gets 403 "Cover suggestions need a browser login." and no job. The click then reads the person's groups through a fresh refresh grant, as a turn does: no `agent` or an issuer that is down answers 503, outside the API group or a refused grant answers 403, each with `{"detail": {"problem": …}}` and no job. A refused group or grant never answers 401, because the frontend reads it as a logout; only a session that ends during the request still answers 401. The job references the session that asked (`jobs.session_id`, `ON DELETE SET NULL`, cleared when the job ends, never in a response, frame or log); the co-writer's cover tool binds the calling turn's session, and a tool call outside a bound turn refuses. The job checks again at its start through that session: a person who left the group meanwhile ends `not_enabled`, an ended session or a job with no reference `sign_in_again`, and a user who is gone `not_enabled`, each before any request.

**What leaves.** Album title, artist name and quoted excerpts of style prompts and lyrics, with the account's fingerprint as `user`, the same fingerprint the turn sends. No request carries the account id, the session id or the issuer.

**Outcomes.** A picture is checked by `covers.decode_cover_image`; WebP and anything else that is not a bounded PNG or JPEG ends `unavailable`, logged only as a closed detail. The job ends in one of the turn's four problems: `busy` (a 429; its `Retry-After`, capped by the client, is kept as `jobs.retry_after_seconds`), `not_enabled`, `sign_in_again` or `unavailable` (everything else, a budget or moderation refusal and the 88 s limit of the agent file included). The job's `error` holds one closed sentence per problem, never the gateway's words, a key, a token or the session id. Only a completed run spends the daily count. An explicit Cancel closes the picture's request; an answer the gateway already billed stays billed.

**Retention outside songmaker.** The gateway receives what leaves and forwards it to the image provider over the provider's API; what is stored and deleted there is the agent service's, named in the privacy text's Agent-Dienst section. Songmaker keeps only the stored suggestion.

## Agent-CLI Mounts

No container binds an agent CLI or a login: no service mounts anything under
`/home/songmaker`, and none mounts the mirror directory; a CI test fails on a
compose bind that does. The deploy tick runs no mount preflight.

`scripts/mirror_agent_cli_credentials.py` publishes a **redacted copy** of each
login into `~/.songmaker/agent-cli-credentials/`, kept current by
`songmaker-cli-credentials-mirror.{service,path,timer}` and installed with
`scripts/install-cli-credentials-mirror.sh`.

Grok access tokens expire after six hours. The host-side mirror
service, path watcher, and ten-minute timer are the sole refresh path: each
host refresh replaces the published access token in place while keeping
`refresh_token` empty. The host remains the only refresh owner: the host's
mirrored Codex document, which no container mounts, keeps `tokens.refresh_token`
empty.

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
caught by verification. It also asks systemd whether the mirror service,
its login watch and its timer are installed and enabled, whether the two
triggers are running, and whether the service itself has failed: files that
look right prove nothing about currency if what rewrites them has been
erroring out since yesterday. The service is not required to be *active* — a
finished oneshot is legitimately inactive.

`SONGMAKER_CLAUDE_CLI`, `SONGMAKER_GROK_CLI`, and `SONGMAKER_CODEX_CLI` take
effect only when exported in the deployment environment, not when written only
in `.env`: the preflight reads its values from the exported environment and
does not load `.env`. Compose reads none of them.

**Boot coupling.** `songmaker.service` orders itself only after
`docker.service` and runs no preflight: it starts the stack with
`docker compose up -d` whether or not the mirror runs. The two-minute deploy
tick runs no preflight either.

The mirror installer freezes its resolved directory in the mirror service's
`--mirror-dir` argument. An argumentless preflight reads that installed service
and requires exactly one matching value; an unreadable, missing, ambiguous, or
different value refuses with `Spiegel-Installer erneut ausführen`. After
changing `SONGMAKER_CLI_CREDENTIALS_DIR` in `.env`, run
`sudo ./scripts/install-cli-credentials-mirror.sh` again from the main
checkout.

Refresh the mirror with `sudo systemctl restart songmaker-cli-credentials-mirror.service`; that does not touch `songmaker.service` or the live stack.

That call has been deleted from this script once already, by an edit that
rearranged the systemd checks around it, and nothing went red: the verifier's
own tests kept passing while the surface the installer runs stopped checking
anything at all. The shell entry point therefore has its own tests, separate
from the Python ones. The installer is its one caller.

Where the mirror lives has one answer, owned by that same module: an exported
`SONGMAKER_CLI_CREDENTIALS_DIR` wins, then the same key in `.env`, then the
default under the stack owner's home — the order the stack resolves its settings in. The value must be
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

No service mounts an agent CLI or a login.

Claude creates `~/.claude.json` itself, so it is neither seeded nor mounted.

### Provider API keys

`ANTHROPIC_API_KEY`, `XAI_API_KEY`, and `OPENAI_API_KEY` are retired: no
process reads them, compose passes none, and no image installs a provider SDK.
`Settings` declares them unread so a `.env` that still holds them validates.
Neither the API nor the DOM exposes a key value, raw
provider body, command output, or a secret-derived value. The co-writer has no
route to select: it runs through the gateway (see "Co-writer turn through the
gateway"), and neither has the cover (see "Cover picture through the
gateway"); [the Models page](architecture.md#the-models-page) shows both rows
read-only.

**#327 F5:** Settings reads and validation never start an agent CLI or catalog
request.

## Child Process Secret Scrubbing

Two places spawn child processes that must not inherit every secret in the parent's environment: the scoring subprocess (`songmaker_cli/scoring/subprocess_runner.py`) and `acestep_worker.subprocess_runner` (the ACE-Step HTTP subprocess). Both scrub their environment with a `SECRET_ENV_KEYS` tuple before the child runs, covering `ANTHROPIC_API_KEY`, `XAI_API_KEY`, `OPENAI_API_KEY`, `SESSION_SECRET`, `SONGMAKER_INTERNAL_TOKEN`, `DATABASE_URL`, `REDIS_URL`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `HF_TOKEN`, `GRAFANA_USER`, and `GRAFANA_PASSWORD`. A login is scrubbed as a pair — the name half is no secret on its own, but handing a child process one half of a credential buys nothing.

The Keycloak client secret is not in that list because it is not in the environment: it is a file, mounted into the web container only. The same holds for the four songmaker secret files in the container deployment (see "Secrets"): the list stays for direct runs and tests, which pass the same values as environment variables. The scrub cannot hide a file from a child that runs as the same OS user, so the agent-CLI processes can read it; see "Authentication".

`acestep_worker` cannot import from `songmaker_cli` (engine packages are independent — see AGENTS.md "Code patterns"), so each package keeps its own `SECRET_ENV_KEYS` tuple: `songmaker_cli/constants.py` and `acestep_worker/constants.py`. `tests/songmaker_cli/test_constants_secret_scrub_parity.py` pins both against the same literal expected set of keys, so they cannot silently drift apart, no list can quietly shrink to empty and still pass, and a drifted list names its own owner.

`HF_TOKEN` is scrubbed from the ACE-Step subprocess even though the subprocess genuinely does call Hugging Face: `vendor/acestep/acestep/api/model_download.py`'s `download_from_huggingface` runs both at subprocess startup (for the DiT and VAE models) and at request time (for LM models), and it passes no explicit `token=`, so `huggingface_hub` would pick up `HF_TOKEN` from the environment implicitly if it were present. However, every repo ID the subprocess can resolve on its own (via `MODEL_REPO_MAPPING` / `DEFAULT_REPO_ID` in that same module) is public and answers anonymously; the ACE-Step catalog's only two gated repos (`ACE-Step/acestep-v15-turbo`, `ACE-Step/acestep-5Hz-lm-1.7B`) are fetched exclusively by `acestep_worker.downloads.run_download`, which passes `token=` explicitly rather than relying on ambient env. So scrubbing `HF_TOKEN` here does not break any download this deployment performs — the consequence is that the subprocess's own Hugging Face requests go out anonymously and are subject to Hugging Face's stricter unauthenticated rate limits. See `acestep_worker/constants.py` for the same reasoning next to the list.

The scoring subprocess needs a different mechanism: `songmaker_cli.scoring.subprocess_runner` starts the long-lived scorer child via `multiprocessing`'s `spawn` start method, which has no `env=` parameter — the child process inherits the parent's complete `os.environ` at spawn time, the same way it would inherit any other process-wide state. `_child_main` (the child's entry point) calls `_scrub_secret_env_vars()` as its literal first statement — but by the time `_child_main` runs, the spawn bootstrap has already imported the whole `subprocess_runner` module and everything it pulls in at module level (`scoring.pipeline`, `settings`, `auth`, `api_models`, ...), because multiprocessing's spawn target must be importable before it can be called. The scrub cannot undo anything a module-level import already did; it only guarantees that no code invoked *after* it — `default_registry.ensure_loaded()`'s scorer-module imports and every scorer function call that follows — can read a secret out of `os.environ`. `tests/songmaker_cli/scoring/test_subprocess_runner_scoring.py::test_scorer_child_drops_secret_env_keys_at_spawn` drives the real `_child_main` entry point (via the existing `_run_child_with_messages` test harness, not a stand-in) with every `SECRET_ENV_KEYS` entry (plus a non-secret marker) set in the parent's environment beforehand, sends it an `EnvProbeRequest`, and asserts none of them come back present while the marker does — a spawned process's own `os.environ` cannot be observed from outside it any other way, so this round trip is what makes deleting the `_scrub_secret_env_vars()` call site fail the test.

Everything a child scorer needs is resolved in the parent and carried into the child as data — never re-read from the child's own environment — and none of it is a secret. `scoring_worker.py` and `jobs/scoring.py` call `get_settings()` at worker startup and per-job respectively, in the parent process; `scoring_device`, `scorer_timeout_seconds`, and `text_accuracy_timeout_seconds` flow into `PipelineConfig` fields (`device`, `scorer_timeout`, `text_accuracy_timeout`), and `scoring_max_jobs` separately bounds ARQ worker concurrency (`ScoringWorkerSettings.max_jobs`) — it never crosses the pipe at all. No scorer calls an external provider, so no scorer holds a credential and `PipelineConfig` carries no secret field: there is no key in the child's memory to leak through the model weights it loads.

The invariant this protects: no module reachable from `subprocess_runner`'s own import chain may read `os.environ` or construct `Settings()` as a *module-level* side effect (that code runs before the scrub ever gets a chance to act), and no scorer module — all of them imported later, inside `_child_main`, after the scrub — may read `os.environ` or construct `Settings()` at call time either. A scorer that needs a secret does not belong in the child at all. Non-secret configuration reaches a child scorer through a new `PipelineConfig` field filled by the parent, never through a `get_settings()` call in the child.

The scoring worker holds no provider credential: its container sets no `ANTHROPIC_API_KEY`, `XAI_API_KEY` or `OPENAI_API_KEY`, mounts no Claude, Grok or Codex binary or login.

The scrub is also weaker than the Popen `env=` path used for the ACE-Step child: `del os.environ[key]` calls libc's `unsetenv()`, which blocks `getenv()` — every subsequent read via `os.environ`/`os.getenv`, and every process this one execs from here on, sees the key as gone — but it does not erase the bytes the kernel copied onto the process's stack at its own `execve()`, which is what `/proc/<pid>/environ` reads directly. So the scrubbed keys stay visible in `/proc/<pid>/environ` for the child's entire lifetime even though `getenv()` can no longer see them. Accepted risk per [Trust model and accepted risks](#trust-model-and-accepted-risks) (subprocesses share the OS user): reading another process's `/proc/<pid>/environ` requires being that same OS user (or root), and the scoring-worker container's `songmaker` user has no other tenant sharing it, so this gap adds no new exploitation path beyond the one already accepted there. Never bind-mount `.env` into the `songmaker-scoring-worker` container — `Settings` walks up the filesystem looking for it, and doing so would hand the scrubbed child back every secret the scrub just removed.

The child never outlives a scorer it could not stop. A scorer's time budget is a ceiling: `_call_with_timeout` abandons a call that blows it (`shutdown(wait=False)`) instead of joining it, because a Python thread cannot be killed. Inside the child that abandoned thread goes on holding the Whisper/AudioBox model globals and their GPU memory, so the next request would otherwise reuse a child whose GPU memory is still held, beside a scorer still running. Two things prevent that. `ScorerProcess` marks itself tainted when a response reports `SongScores.any_child_scorer_timed_out`, under the same `_pipe_lock` that serializes requests, and `_ensure_started()` then refuses to hand that child to the next request — it kills and respawns instead. That holds even when the job that tainted it was cancelled and returned early. On top of it, `jobs/scoring.py` calls `ScorerProcess.recycle()` right after persisting the values of such a run, so the GPU is reclaimed immediately rather than at a next request that may be minutes away. Both paths kill the same way: SIGTERM first, so the child's own handler releases CUDA memory, SIGKILL after a 5-second grace period; the replacement child runs `_scrub_secret_env_vars()` again by construction. `tests/songmaker_cli/test_jobs.py` and `tests/songmaker_cli/scoring/test_subprocess_runner_scoring.py` pin every direction — a timed-out child scorer keeps its scores and loses its child, a cancelled job's tainted child is still not reused, a clean run keeps the child it had.

The scorer's two Hugging Face models (`faster-whisper`'s `large-v3`, `audiobox-aesthetics`'s default checkpoint) are baked into the `songmaker-scoring-worker` image at build time — `docker/scoring-worker.Dockerfile` downloads them with `HF_TOKEN` wired in only for that `RUN --mount=type=secret` build step, and the running container's `docker-compose.yml` service definition never sets `HF_TOKEN` as a runtime env var at all, so there is nothing for the scrub to take away at request time.

## ACE-Step Worker Pool Trust Boundary

The ACE-Step worker pool runs each model-serving worker as a separate peer container. Workers self-register with the web container at startup and heartbeat ephemeral state to Redis. The control plane (web container) and the workers communicate over an **internal HTTP API** mounted under `/api/internal/*`.

### Internal token

- **Secret file**: `internal-token` in the secrets directory, mounted as `/run/secrets/songmaker_internal_token` into the web container and the music, scoring and ACE-Step workers — a shared secret that each must have before startup. It is no environment variable and compose has no default for it.
- **Header**: Workers send `X-Internal-Token: <token>` on every internal call. The web container does the same when the music-worker scheduler proxies `/load_model` / `/evict_model` to a worker.
- **Worker side**: every route of the acestep-worker (`src/acestep_worker/wrapper.py`) requires the same header except `GET /health`, which the Compose healthcheck calls headerless and which answers only `ok` or a 503 reason. The worker's routes sit on one router that carries `verify_internal_token`, so a new route is protected by default; the FastAPI `/docs`, `/redoc` and `/openapi.json` routes are disabled. A missing header answers 422, a wrong, empty or non-ASCII token 401 (the comparison runs on encoded bytes, so a non-ASCII value cannot crash into a 500). `tests/acestep_worker/test_wrapper.py` enumerates every route the app serves and fails if one but `/health` answers without the token.
- **Verification**: `internal_api.verify_internal_token` is mounted as a router-level dependency, so every endpoint under `/api/internal/*` automatically requires the header. Comparison uses `hmac.compare_digest` on encoded bytes for timing safety.
- **Failure modes**: A missing or empty token stops the service at startup (the setting requires at least one character), so the internal API never runs unconfigured. Missing header → 422; wrong, empty or non-ASCII token → 401.
- **CSRF**: `/api/internal/*` is exempt from the origin check. Workers send JSON without `Sec-Fetch-Site` or Origin headers and authenticate with the internal token; they do not have sessions.

### Deployment boundary

This repository ships no reverse-proxy service or configuration: there is no
nginx, Caddy, Traefik, or tunnel policy here. The internal API trusts any caller
that knows the token, and has no per-user authorization. Compose publishes the
web port only on the host loopback interface, while workers use the Compose
network; an operator who adds an upstream proxy or tunnel is responsible for
keeping `/api/internal/*` unavailable to public traffic. That edge policy is not
implemented by this repository (#327).

### Token rotation

1. Generate a new token into a file in the secrets directory, not to the terminal (e.g. `openssl rand -hex 32 > internal-token.new`).
2. Write the new value into `internal-token` in the secrets directory, as a new file moved over the old one. If `.env` still holds `SONGMAKER_INTERNAL_TOKEN`, set it to the same new value too, or the next auto-deploy preflight refuses the mismatch (see "Secrets").
3. Recreate the web container and every worker (`docker compose up -d --force-recreate`): a replaced file keeps its old inode in a running container until then. There is no DB state to update — registration is idempotent and the next worker startup re-registers with the new token.

There is no graceful "two valid tokens" overlap. Restarting workers in sequence is acceptable because the music-worker scheduler tolerates worker outages (it routes to surviving workers).

### Trust scope of a compromised worker

A compromised acestep-worker container has:

- The shared internal token (it needs it to register and to receive scheduler calls).
- The model-weights volume mount (read/write, but only its own checkpoints directory).
- The `audiofiles` volume, read-write at `/app/data/audio`: every musician's audio files.
- The default compose network, so network access to every service on it, including Redis, the web container and the music-worker container.
- Redis without authentication, through the same `REDIS_URL` every service uses: every key is readable and writable, arq queues and rate-limit state included.

It does **not** have:

- A direct database connection (the worker has no `DATABASE_URL`; it only calls `/api/internal/workers/register`, which writes a single identity row).
- The session secret (the acestep worker has no `SESSION_SECRET`).

A compromised worker can overwrite or delete any stored audio file, enqueue or alter arq jobs, rewrite rate-limit state, publish bogus state to Redis, register with a wrong host/port, or refuse to load models. User audio integrity and queue contents are within its reach. It has no direct database connection, but the jobs it forges or alters run in workers that hold `DATABASE_URL` (for example, a scoring job for a chosen generation writes that generation's scores), so database rows are reachable indirectly. The session secret is not.

### How a take reaches music

A worker writes a take only into its container-local output root, which it empties at every start. The `done` event names no path: music fetches the take by `task_id` with `GET /tasks/{task_id}/result` (the worker resolves the file only from its own task record, never from a caller's path) and then frees it with `DELETE`. Music streams the body into a temp file of its own and aborts at `generation_result_max_bytes`, which only music's settings hold; a refused, oversized, cut-off or timed-out fetch is one failed take with no retry. Both routes sit behind the internal token. The worker's expiry sweep removes a result file together with its task record. Reference, repaint and cover inputs and the LoRA export still use the shared audio volume.

### Container confinement

Every service runs under Docker's default AppArmor and seccomp profiles, and
Docker masks its system paths. `songmaker-web` and the three workers drop every
capability and set `no-new-privileges:true`.

### Trust model and accepted risks

- **Subprocesses share the OS user.** ACE-Step and scorer subprocesses run as the same `songmaker` user in Docker. Every image creates that user as uid and gid 1000 and runs `USER 1000:1000`: the named volumes and the checkpoints bind mount belong to that uid, and Kubernetes' `runAsNonRoot` can verify only a numeric `USER`. `songmaker-acestep-worker-0`, `songmaker-music-worker` and `songmaker-scoring-worker` drop every capability (`cap_drop: [ALL]`, no `cap_add`) and set `no-new-privileges`. Compromised model weights or ACE-Step code get user-level disk access. Container isolation mitigates this; OS-user separation would need separate containers for marginal benefit. Accepted for a single-user deployment.
- **Secret files are readable by every child of the same uid.** The session secret, database password, internal token and monitoring token are files under `/run/secrets` in the containers that read them, as the Keycloak client secret is: the scrub cannot hide a file from the agent-CLI and scorer children of the same OS user, and the files are mode 0644 inside a 0700 host directory because postgres (uid 70) and Prometheus (65534) read theirs under other uids. Only a process on the host as the operator, or root, reaches the host directory.
- **One shared token.** All workers hold the same internal token (`internal-token`); compromising one grants full internal-API access. Multi-node deployments should move to per-worker tokens or mTLS.
- **Single node.** One acestep-worker per GPU on one host, the ACE-Step HTTP subprocess inside the worker container. Multi-node distribution (separate hosts, shared model storage, cross-host Redis heartbeats) is untested, and the image/packaging refactor that would precede it (decoupling the ACE-Step subprocess image from the worker image) is unwritten.
- **No repository-provided edge path filter.** The single-port design serves `/api/internal/*` on the same port as the rest; its safety rests on the loopback-only published port and on any operator-provided upstream access policy.

## CI Supply Chain

The Release workflow builds the web, music worker, scoring worker and acestep worker images on
GitHub-hosted runners from the commit quality's gate judged, main's green head.
The acestep worker's build also checks out the pinned `vendor/acestep` commit,
one level deep and without credentials.
Each job holds only its own permissions: only the tag job writes contents, and
only the image jobs hold `packages`, `id-token` and `attestations`. Quality's
`image.yml` signs each image's build provenance. Anyone with write access to the
repository can dispatch the workflow; the gate bounds what that releases to main's
green head, and the workflow passes no secret.

Every third-party GitHub Action is pinned to the full commit SHA of its reviewed
release tag (with the release series recorded beside it), so a moved tag cannot
change a workflow.
The container images in the Dockerfiles and `docker-compose.yml` (Python, Node,
`uv`, PostgreSQL, Redis) and the CI references (the promtool image, CI's PostgreSQL
service) are pinned by exact version and digest, as `<name>:<version>@sha256:<digest>`,
so a rebuild cannot pull a different binary than CI tested. `scripts/backup.sh` and `scripts/restore.sh`
copy audio through the digest-pinned `postgres` image compose names (Alpine-based:
`sh`, `cp -a`, `find`), so no helper image is pulled unpinned. The frozen monitoring
stack is not pinned. Dependabot moves the Dockerfile and compose pins, patch releases
only (PostgreSQL within 16); a major or minor move of an image is its own change,
for PostgreSQL 17 a data migration. The CI pins are moved by hand; `scripts/check_pinned_images_match.py` fails while
CI's PostgreSQL service differs from compose's, so a Dependabot PostgreSQL bump
needs the same edit in `.github/workflows/ci.yml`. Project tooling in CI and application dependencies in worker
images are installed through `uv` with the committed `uv.lock`; Bandit and
pip-audit run in separate tool environments so they do not change that lock.
The repository itself is installed as the trusted local editable project. All
third-party dependencies must be wheels except `nvidia-ml-py3`, whose locked,
hash-verified release has no published wheel. The two first-party libraries
are git pins built from source at image build; the three images that sync them
(web, music worker, scoring worker) carry `git`, and the music worker builds
only those two from source, after a `--no-build` step that refuses any
third-party source distribution. Their build requirements (`setuptools`, `wheel`)
float on PyPI, unlocked and unhashed: a malicious release would run at image
build, as root in the web image. This risk is accepted.

## Audit Trail

Mutating operations are logged to the `audit_log` table. Account creation, role changes and back-channel logouts are written without a person (`user_id` null):

- **Actions tracked**: `create`, `update`, `delete`, `generate`, `score`, `cleanup`, `share`, `unshare`
- **Fields**: `user_id`, `action`, `resource_type`, `resource_id`, `detail`, `created_at`
- **Read access**: none over HTTP — the `GET /api/admin/audit-log` endpoint was removed until an admin surface shows the trail (#1190); the rows stay in the database and are read there.

## Production Deployment

### Recommended

| Setting | How |
|---------|-----|
| HTTPS termination | Songmaker does not terminate TLS. Leave `COOKIE_SECURE` at its default `true` so the session cookie carries `Secure` and the `__Host-` prefix, and responses carry HSTS; set `COOKIE_SECURE=false` only for local plain-http development (CI and the e2e Compose overrides do this). No terminator configuration is shipped here. |
| Session secret | Put it in the `session-secret` file of the secrets directory (min 32 chars). Required — startup fails with `ValidationError` if missing or empty. Stable across restarts. hal makes the file, see "Secrets". |
| CORS origin | Leave unset when the interface and API share an origin. For a separate trusted browser client, set one exact origin, for example `CORS_ORIGIN=https://client.yourdomain.com`. Cross-site browser mutations to `/api/` remain rejected by `Sec-Fetch-Site`, even with this permission. Startup rejects `*`, subdomain wildcards, and comma-separated lists; `SameSite=Strict` does not make sibling subdomains separate sites. |
| Trusted proxies | Set `TRUSTED_PROXIES=10.0.0.1,172.16.0.0/12` (comma-separated addresses and/or CIDR networks). Only peers inside these networks are trusted for `X-Forwarded-For` and `X-Forwarded-Proto`; the rightmost untrusted `X-Forwarded-For` entry is used to prevent spoofing. An unparsable or zone-scoped entry fails startup, and a malformed forwarded chain falls back to the direct peer. Without this, the client's direct IP is always used for rate limiting — see "Proxy trust". Cookie `Secure`/HSTS are unaffected either way; they follow `COOKIE_SECURE` alone. |
| Public base URL | Set `PUBLIC_BASE_URL=https://yourdomain.com` (scheme + host, no trailing path). The one owner of "what address am I reachable at from outside": the `Settings.public_base_url` validator parses it once at startup and stores the bare origin (a query or fragment is dropped, a path is refused). The one builder of an absolute share address (album/song/generation/playlist — issue #339) is `public_share_url()` in `api_models/songs.py`; the song summary's `share_url` carries it to the song page's link chip. The sign-in redirect addresses (`oidc_client.py`) and the back-channel host (`auth_api.py`) read the same validated setting. Not derived from the request: `request.base_url` reflects the literal ASGI transport's scheme, which is always `http` behind a TLS-terminating proxy since `proxy_headers=False` (see "Proxy trust") leaves nothing to rewrite it. A missing or malformed value stops the web app at startup rather than building a link with a guessed scheme. |
| Allowed hosts | Set `ALLOWED_HOSTS=yourdomain.com,yourdomain.com:443` (comma-separated exact host names; an entry containing `*` stops startup). Used by CSRF origin verification and, through songmaker's own `TrustedHostMiddleware`, as the Host allowlist: a request for another Host is answered 400 (the library's host lists are Origin allowlists only). Compose always adds `localhost`, `127.0.0.1` and `songmaker-web`. |
| Host binding | Default is `127.0.0.1` (localhost only). Set `HOST=0.0.0.0` only when the deployment's network policy keeps the service private. The Docker deployment does set `HOST=0.0.0.0` — that binding is *inside* the container, where the Compose network needs it. |
| Published ports | `docker-compose.yml` publishes `songmaker-web`, Grafana, and Prometheus as `127.0.0.1:8080:8080` / `127.0.0.1:3000:3000` / `127.0.0.1:9090:9090`. Do not drop the `127.0.0.1:` prefix: Docker's NAT chain bypasses the host INPUT chain, so a plain `8080:8080` reaches the whole LAN no matter what UFW says. The Prometheus API is host-local for the same reason; its lifecycle HTTP endpoints stay disabled, so Compose-network peers cannot stop or reload it. The tunnel (`cloudflared`), the Vite dev proxy, and the CLI all run host-local; in-cluster callers use `songmaker-web:8080` on the compose network. |
| Workers | Production runs in Docker only. The web container uses a single uvicorn process; concurrency comes from arq worker containers (`MUSIC_MAX_JOBS`, `SCORING_MAX_JOBS`). PostgreSQL is the only supported database. |
| Request body limit | App-level: `MAX_REQUEST_BODY_BYTES` (default 1 MB). If an operator provides an upstream proxy, align its path-specific limits for defense in depth; this repository provides no such proxy configuration. |
| IP rate limit | `IP_RATE_LIMIT` (API class, default 120/min), `MEDIA_RATE_LIMIT` (`/audio/*`, default 600/min), `STREAM_RATE_LIMIT` (SSE opens, default 45/min). Adjust based on expected traffic — see "Per-IP (global middleware)" above. |
| Resource-event stream open limit | `RESOURCE_EVENT_STREAM_OPEN_LIMIT` (per-user resource-events stream opens, default 12/min). CI overrides it — see "Resource-event streams" above. |
| Request timeout | `REQUEST_TIMEOUT` (default 30s) limits idle keep-alive connections, not full requests. The two SSE routes have their own 60-second walls; Songmaker has no general application request deadline. |
| Auto-deploy cleanup timeout | `SONGMAKER_AUTODEPLOY_PRUNE_TIMEOUT_SECONDS` (default 600). Bounds each post-deploy Docker cleanup command. |

The two-minute auto-deploy tick first runs `docker compose config --quiet` on the checked-out configuration, then checks the active-job queue and required alert-channel configuration before it checks out or builds. Compose owns the list of required variables (every `${VAR:?…}` in `docker-compose.yml`), so a missing one such as `GRAFANA_PASSWORD` is a named deploy refusal quoting compose's own message before anything is checked out — the job guard's `docker compose exec` would not notice it, and the build would fail only after the checkout. The refusal uses the same counter and alert escalation. The tick asks again right after the checkout, before any Compose build, so a variable that the newly selected commit requires is named before anything is built or recreated. `--quiet` is mandatory there: without it, compose prints the fully interpolated configuration, every `.env` secret included, into the journal. Right after it the tick runs `scripts/secret_files.py --verify`, which refuses a release whose declared secret files are missing, empty or different from `.env` (a counted refusal like the others); it reads the interpolated configuration in memory only, never writes it anywhere and prints no value. After fetching `origin/main` and its `v*` release tags into a private ref namespace, the tick asks GitHub about the newest ten eligible releases (configurable with `SONGMAKER_AUTODEPLOY_CHECK_RUN_LOOKBACK_COMMITS`; see [auto-deploy architecture](architecture.md#auto-deploy) for what makes a tag eligible) and checks out detached only the newest release whose commit's GitHub Actions (`app.slug == github-actions`) runs have all completed, at least one of them successfully and every other one successfully, skipped, or neutral (a skipped or neutral run neither blocks nor passes a commit); other apps' runs are logged as advisory and ignored, and a check run without a job name is a malformed answer. A second lookup of the commit's workflow runs finds the check suites of Dependabot's update runs and of Release runs, matched by exactly the paths `dynamic/dependabot/dependabot-updates` and `.github/workflows/release.yml`; exactly those suites leave the judgement, so a failed update job or a Release run cannot block a release while every other failed or unknown run still does. Releases with running, cancelled, or failed Actions are named in the log once and skipped; no Actions runs stay neutral only for the 30-minute grace period measured from the local host clock when the HEAD SHA was first seen; a commit timestamp supplied by Git cannot postpone that alarm. An unavailable or malformed GitHub answer from either lookup, or a 60-second lookup timeout, is a named deploy refusal that uses the same counter and alert escalation. Every Git command in the tick disables repository hooks and the filesystem monitor and runs with a minimal Git environment. That includes the one network fetch the ACE-Step pin adds: before the checkout, the tick fetches the commit the selected revision pins `vendor/acestep` to, by SHA, from the submodule's `origin` (a public fork; the tick adds no credential of its own). With the scrubbed environment, no hooks and no filesystem monitor, nothing the fork serves can run code on the host while the fetch stores its objects. The submodule's own local Git configuration (`remote.origin.uploadpack`, `core.sshCommand`, `url.*.insteadOf`) is trusted like the superproject's, because it decides how the fetch connects. The tick then checks the pin out with `git submodule update --checkout --no-fetch`. If the pin cannot be fetched, or `vendor/acestep` is not initialised, the tick fails closed: a counted refusal that leaves the checkout, the running stack and `deployed.sha` untouched. Both git fetches of a tick run under `SONGMAKER_AUTODEPLOY_GIT_FETCH_TIMEOUT_SECONDS` (120 by default) with `SONGMAKER_AUTODEPLOY_GIT_FETCH_KILL_GRACE_SECONDS` (5) before the kill, so a hung transport reaches the same alert instead of holding the deploy lock forever. Each fetch runs in a process group of its own that the script kills outright once git has exited, so a transport that ignores the deadline's TERM cannot outlive the tick; a kill can leave a git lock file that an operator removes by hand, never the script. After a refused or failed tick past the checkout (`hal` missing, `hal` exiting non-zero, a compose failure), `HEAD` stays detached at the new release while `deployed.sha` keeps the old one, so the checkout is ahead of the running stack until a later tick succeeds; the next tick retries, and the third consecutive failure alerts.

Under the deploy lock, each tick first removes leftovers directly in its Git admin directory whose names match the script’s four temp prefixes (`songmaker-autodeploy.git-fetch.`, `songmaker-autodeploy.compose-stderr.`, `songmaker-autodeploy.prometheus-ps-stderr.`, `songmaker-autodeploy.gh-stderr.`) followed by exactly six ASCII letters or digits. Symlinks are unlinked without following their targets; state files and nested worktree admin directories are untouched. Each removal is logged; a failed removal refuses the tick and counts toward the third-tick alert, including when already up to date. In-tick removal remains best-effort: an interrupted tick’s leftovers are removed by the next tick that acquires the lock and can remove them. This assumes one lock per Git admin directory; overriding `SONGMAKER_AUTODEPLOY_LOCK_FILE` to share an admin directory between independently locked ticks is unsupported.

When the selected release's schema differs from the running commit's (the `schema:` line of the release's annotated tag message when it has one, else the alembic head of its commit; any doubt, such as an unreadable running state or several heads, counts as differing), the tick first runs `hal backup songmaker --pre-apply` (path from `SONGMAKER_AUTODEPLOY_HAL`); a failed or missing backup is a counted refusal before any build or recreate. A deploy that changed the schema is undone by restoring the paired database and audio backup taken before it (`scripts/restore.sh`; both are needed), then deploying the previous revision. Its Compose build runs without a timeout, and its output streams directly into the service journal. After a successful recreate, the tick runs `docker image prune --force --filter until=48h`. Before recreating, it tags only running Compose services with a `build:` section as `<project>-<service>:previous`; `<project>` comes from `docker compose config --format json --no-interpolate | jq -r '.name'`, so the tag follows the actual Compose project without materializing `.env` secrets. To roll back a built service, run `project="$(docker compose config --format json --no-interpolate | jq -r '.name')"; docker tag "${project}-<service>:previous" "${project}-<service>:latest" && docker compose up -d --force-recreate <service>`. Both cleanup commands are bounded by `SONGMAKER_AUTODEPLOY_PRUNE_TIMEOUT_SECONDS` (600 seconds by default); an error or timeout is logged at `err` with its command and exit code, while the completed deployment remains successful and the tick does not change either counter. The builder cleanup deliberately uses `docker builder prune --all --force --filter until=48h`, preserving cache used in the last 48 hours but allowing a quiet host's next rebuild to take its normal cold-cache 8–15 minutes.

### arq JSON queue codec

The web producer and both workers use
one UTF-8 JSON codec (`arq_codec.py`) for jobs and results. Unsupported objects,
non-string object keys and nonfinite numbers are rejected. No class is imported
or reconstructed, and there is no pickle fallback. The wire tests in
[`test_arq_codec.py`](../tests/songmaker_cli/test_arq_codec.py) cover the configured entry points.
The codec is not Redis access control or network isolation; those are separate requirements.

arq 0.27 cannot JSON-encode exception objects in failed or cancelled results. It
logs one serialization warning and stores inert `r="unable to serialize result"`
with `s=False`; its public result reader raises `SerializationError`. The app
does not read arq results. A leftover pickle job is rejected visibly with its job
ID, executes nothing and leaves a readable failed result. A legacy pickle result
read fails explicitly. Preserve that evidence and reconcile the application job
before retrying; never purge or silently retry these entries.

### Secrets

- `OIDC_ISSUER`: Required, with no default; every `docker compose` command that reads `docker-compose.yml` refuses without it, like `GRAFANA_PASSWORD`. `OIDC_CLIENT_ID` defaults to `songmaker`. A leftover `ADMIN_USERNAME` or `ADMIN_PASSWORD` in `.env` stops startup (`Settings` rejects unknown keys), so remove them when deploying the Keycloak sign-in.
- `keycloak_client_secret`: the Keycloak client secret, a file owned by the edge (`~/.secrets/keycloak/clients/songmaker`, or `KEYCLOAK_CLIENT_SECRET_FILE` for a throwaway stack), mounted read-only into the web container at `/run/secrets/keycloak_client_secret`. Never an environment variable.
- `gateway_key`: the app key for hal's LiteLLM gateway, a file owned by hal (`~/.secrets/litellm/apps/songmaker`, or `GATEWAY_KEY_FILE` for a throwaway stack), mounted read-only into `songmaker-web` alone at `/run/secrets/gateway_key`; `AGENT__GATEWAY__KEY_FILE` names that path. Never an environment variable.
- The songmaker secret files: `session-secret`, `postgres-password`, `internal-token` and `monitoring-token` in `SONGMAKER_SECRETS_DIR` (default `~/.secrets/songmaker`, a 0700 directory with 0644 files, made by hal: `hal setup` creates a missing file with a generated value and keeps an existing one; `hf-token` is created empty by hand on a fresh host, since it is an unverified token. `scripts/secret_files.py` below stays the one-time copy from `.env` for an existing deploy, and a live value is never regenerated). Compose declares each as a file secret and mounts it only into the services that read them: the session secret into the web, music and scoring services; the database password into postgres (`POSTGRES_PASSWORD_FILE`), web, music and scoring; the internal token into web and the music, scoring and ACE-Step workers; the monitoring token into web and, as `monitoring_token`, Prometheus. `Settings` and `WorkerSettings` read `/run/secrets/<field name>`; none of the four is an environment variable, a `.env` key or a compose default, so `docker inspect` and `docker compose config` hold no value, and no service reads a `.env` key of the same name. Until the retirement of `.env` (#2206 B4), `scripts/secret_files.py --verify` in the deploy preflight still reads such a key when `.env` has it, and refuses a file that differs from it. A missing file stops `docker compose up` before it creates the service and names the file. An empty file stops web, music, scoring and the workers at startup for the session secret, the internal token and the database password (their settings require a value), but not postgres on an existing volume, which keeps the password it was initialised with; an empty `monitoring-token` does not stop web, `/metrics` answers 503. The deploy preflight refuses every empty file except `hf-token`, so an empty file never reaches a deploy. The web service checks the monitoring token on `/metrics`; Prometheus sends it. Rotating any of them is a file write plus a recreate of its readers (`docker compose up -d --force-recreate`), and until B4 also the same change to a same-named `.env` key if `.env` still has one, or the next auto-deploy preflight refuses the differing values: the mount points at the file's inode, so a replaced file stays unseen by a running container, and compose does not recreate a service whose secret file changed. Rotate `session-secret` and `postgres-password` only with their consequences in mind: a new session secret signs everyone out, and a new database password locks the app out until postgres has it too.
- `GRAFANA_PASSWORD`: Required, with no default. When it is unset or empty, every `docker compose` command that reads `docker-compose.yml` refuses before it does anything, naming the variable — `up` and `build`, but also the recovery commands `down`, `logs`, and `ps` — so set it in `.env` first. `exec` into an already running service still works, and so do `ps`, `logs`, and `down` when the project is named without a file (`docker compose -p songmaker logs`, the project name being the checkout directory's name). Grafana never falls back to admin/admin. Setting it in the first place is the one command `./scripts/grafana_password.py`, run from the main checkout: if `.env` has no `GRAFANA_PASSWORD`, an empty one, or a publicly known one (`admin`, anything starting with `CHANGEME`), it writes a fresh random value there, then applies the `.env` value to the running Grafana and prints `set` (fresh value written) or `already set` once an authenticated API login with that value succeeds; if Grafana is not running, it says whether `.env` changed and asks you to start the stack and run it again. The value only seeds Grafana's first start, but the command applies whatever `.env` holds, so it also changes the admin password of an existing Grafana: put the new value in `.env` and run it. Without the command, put the new value in `.env`, run `docker compose up -d grafana`, then `docker compose exec -T grafana sh -c 'printf %s "$GF_SECURITY_ADMIN_PASSWORD" | grafana cli admin reset-admin-password --password-from-stdin'`. The password never appears in an argv (shell history, `ps`): the single quotes keep the host shell from expanding it, and `printf` is a builtin of the container's shell. Never pass it as the positional `<new password>` argument. CI uses a fixed throwaway literal (`.github/workflows/e2e.yml`).
- `scripts/secret_files.py`: moves the stack's secrets (`SESSION_SECRET`, `POSTGRES_PASSWORD`, `SONGMAKER_INTERNAL_TOKEN`, `SONGMAKER_MONITORING_TOKEN`, optional `HF_TOKEN`) into one file each under `SONGMAKER_SECRETS_DIR` (default `~/.secrets/songmaker`, a directory with mode 0700 and files with mode 0644). Run without arguments it is the one-time migration for an existing deploy (a fresh host gets its files from `hal setup`); it copies the live `.env` values byte-exact, never regenerates one, skips and names a key absent from `.env`, and refuses to overwrite a file holding another value, a key exported in the shell with another value, a directory that is not yours with mode 0700, a symlinked file or directory, or a value with surrounding whitespace, and it publishes by hard link so a file that appears meanwhile is never overwritten; `.env` stays untouched. With `--verify` it reads `docker compose config --format json` in memory and judges the files compose declares: a missing, empty (except `hf-token`), differing or unknown file is refused, and a compose that declares none passes. Neither mode prints a value; a refusal names the file and the key.
- `.env`: Gitignored. Never committed. Single source for pydantic Settings and
  Docker Compose substitutions except the non-secret
  `SONGMAKER_CLAUDE_CLI`, `SONGMAKER_GROK_CLI`, and `SONGMAKER_CODEX_CLI` path
  overrides: only the mount preflight reads them, from the exported environment.

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

Audio file serving resolves the requested path and verifies that it remains below the configured audio root to prevent directory traversal. The authenticated audio endpoint (`/audio/{owner_id}/{filename}`) checks that the requesting user owns the files (or is admin) — no DB lookup needed since the path is keyed by user ID. Album, song, and playlist shared-audio endpoints accept only a take id (`{generation_id}.mp3`), decide in the query layer by generation id whether the share presents that take (a playlist excludes entries whose song was deleted, as album and song shares do), and only then resolve the take's canonical stored path and check that the file exists below the audio root, logging traversal rejection without the root. A stored path in the address answers `404`. Their public JSON routes emit an audio address only when the take's stored path meets the canonical rule. The configured audio folder may itself be a symlink or a mount; a take's stored, served and deleted path counts where it resolves and must lie strictly below that folder, so neither the folder itself nor a link leading out of it is served, stored or deleted. A queue snapshot is read only from strictly below the snapshot folder (`QUEUE_STREAM_DIRNAME` under the data folder). A cover is served, stored and deleted only from strictly below its cover folder, which may itself be a link, but an entry inside it that leads out is refused. A cover suggestion is read and removed only through its canonical stored path below the audio folder, and its removal stays strictly below the suggestion folder. One owner, `audio_paths.py`, decides all of these. Album and song covers are never served from `/audio/{owner_id}/{filename}`; authenticated covers use `/api/albums/{id}/cover` and `/api/songs/{id}/cover`, and public covers use `/shared/{slug}/cover` and `/shared/song/{slug}/cover`.

## GPU Resource Safety

- **Isolation by container**: `songmaker-acestep-worker-0` is the only container given a GPU (`runtime: nvidia`, `NVIDIA_VISIBLE_DEVICES: "0"`). `songmaker-scoring-worker` is given no GPU device and runs with `SCORING_DEVICE=cpu`, so scorer models and ACE-Step cannot contend for the same VRAM. There is no cross-container release handshake, because with CPU scoring there is nothing to release.
- **Generation VRAM**: The acestep-worker owns its own budget end to end — an LRU model cache bounded by `VRAM_BUDGET_GB` that evicts to fit an incoming load, and NVML heartbeats (`acestep_worker/gpu_util.py`) reporting live used/total GB to the control plane.
- **Scorer subprocess**: The child installs a SIGTERM handler that calls `torch.cuda.empty_cache()` before exiting, so the kill paths above (timeout, taint, `recycle()`) release device memory rather than orphaning it. On CPU that handler is a no-op; it exists for the CUDA case.
- **ACE-Step lifecycle**: The acestep-worker container manages the ACE-Step HTTP subprocess, sending SIGTERM (with SIGKILL fallback) on model switch, worker restart, or shutdown. See `docs/acestep.md` for the worker pool architecture.

Moving scoring onto the GPU (`SCORING_DEVICE=cuda`) would put two containers on one device and does need an arbitration protocol — a scorer-side release plus a verified-free check before generation. That protocol is not built; see issues #161 and #182.

## Known Limitations

- **No IP binding on sessions**: A stolen session cookie works from any IP. Songmaker stores no address or user agent per session; the session stays valid across mobile-network changes (#327).
- **No MFA in songmaker**: second factors, if any, are Keycloak's. Acceptable for invite-only deployments.
- **Worker control endpoints have no cooldown**: `POST /api/admin/workers/{id}/restart`, `POST /api/admin/workers/{id}/pin_model`, and `POST /api/admin/registry/{mode}/download` are not rate-limited. Repeated calls by a compromised admin could disrupt GPU workers or exhaust download bandwidth. Admin-only auth is the only gate.
- **`/health/details` names the running release and commit** for the monitoring-token holder; signed-in people read them from `/api/release`. Anonymous `/health` carries neither. Both values are non-secret and public in the repository's tags.
- **`/metrics` requires the monitoring token**: it exposes request counts, latencies, queue depth and VRAM usage, so `require_monitoring_token` in `health_api.py` admits only `Authorization: Bearer <the monitoring token>` (constant-time comparison, one uniform 401 for every wrong or missing credential, 503 while the token is unset). The token is the `monitoring-token` file; compose mounts it into web as `songmaker_monitoring_token` and into Prometheus as `monitoring_token`. The deploy preflight refuses a missing or empty file.
- **The production CSP keeps `style-src 'unsafe-inline'`**: the build needs it for Svelte's inline styles and style attributes. Removing it would take style hashes or nonces (`'unsafe-hashes'` for the attributes).

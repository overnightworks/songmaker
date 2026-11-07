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

`POST /chat/turn` runs `agents/cowriter.md` through agent-runtime-client's `GatewayBackend` against the LiteLLM gateway; no model runs inside `songmaker-web`, and `songmaker-web` serves no tool endpoint for a caller: the `/mcp` path answers like any unknown path. `agent/backend.py` owns the turn and `agent/tools.py` the tools.

**Configuration and the key.** The nested setting `agent` (`AGENT__BACKEND`, `AGENT__GATEWAY__ORIGIN`, `AGENT__GATEWAY__KEY_FILE`, `AGENT__GATEWAY__CA_FILE`, `AGENT__API_GROUP`) holds the gateway's origin, the file with the app's key and the API group. Unset, the turn ends `unavailable` and no request leaves; a partly set value, an unknown `AGENT__` key or all-empty values stop startup. The key stays in its file: the client reads it for each turn, sends it only as the bearer to the configured origin and writes it to no log or exception, and a missing or unreadable file ends the turn `unavailable`. Compose sets `agent` for `songmaker-web` (the gateway's plain-http origin on `hal_agent_songmaker`, so no CA file) and mounts the `gateway_key` secret; a person needs the Keycloak group `/services/agent-service/api` beside `/apps/songmaker`, or the turn ends `not_enabled`. The HTTP backend sits in the `agent` extra that only the web image installs; the workers load `Settings` with the bare client.

**Who may ask.** The client checks the account's role against the agent file's `appRoles` and the person's groups against the API group before it reads the key. The groups come from a fresh refresh grant at the issuer (`current_groups`), so a person removed from the group is refused at the next turn; a refusal of that grant is never read as an empty membership. A person outside the group or the roles gets `not_enabled`; a session without a usable refresh grant gets `sign_in_again`; an issuer that is down gives `unavailable`. In all three, no request leaves.

**What the gateway learns about the person.** The request's `user` field is the client's fingerprint of the normalised issuer and the account id (`fp-` and 64 hexadecimal digits) and nothing else; the gateway budgets by it. No request carries the account id or the issuer.

**Tools.** Each hand tool takes the person only from the turn's principal (the account id), loads the account from the database in a fresh session and applies today's owner-only checks. The tool schemas carry no user or owner field, so the model cannot name a person. `execute_cowriter_tool` checks the arguments against the tool's own declaration before any handler runs: an unknown key, a missing required key or a value of another JSON type is a tool error naming the field, with no commit. A handler that raises gives the model the client's fixed sentence and logs only the exception class. A turn is cut by `maxToolCalls` and `maxDurationSeconds` of the agent file.

**Order and refusals.** A turn ends in one of four named problems: `unavailable` (no `agent`, a refused agent file, a gateway error or refusal including a budget refusal, a refused connection, an unusable key, a crossed limit, a finished turn without words), `busy` (a 429 with its `Retry-After`), `not_enabled` and `sign_in_again`. It never falls back to a local provider, and no assistant message is stored for a problem. Named gaps: a person over budget sees `unavailable` without the reason; a turn that wrote and then failed shows `unavailable` while the write stands; words the model writes beside a tool call never reach the person.

**A started turn finishes.** A browser that left only stops listening; the turn runs to its end and stores its answer (#1014). Versions a tool wrote before a failure stay; no partial answer is stored as the answer.

**The network.** `songmaker-web` joins `hal_agent_songmaker` (external, internal, fixed name), on which the gateway's front is reachable. Its members are direct peers of `songmaker-web:8080` and can open it on any path with `Host: songmaker-web`. They meet today's protections: no session means 401 on `/api/`, a mutation that names neither a same-origin fetch nor an allowed origin means 403, the internal worker routes need `X-Internal-Token`. `GET /health` answers them with the status `ok` or `degraded` and nothing else; that is the intended exposure. `GET /metrics` and `GET /health/details` answer only a request carrying the monitoring token.

**Named gap: the forwarded address.** With `TRUSTED_PROXIES` at `172.16.0.0/12`, a direct peer can send `X-Forwarded-For` and the per-IP budgets and the access log use the forged address. Sessions, the origin check and the internal token do not depend on the address. Narrowing the range needs the default network's subnet pinned, which recreates the live network. Trigger: a new peer on `hal_agent_songmaker` or an observed budget evasion.

**Retention outside songmaker.** The gateway receives the turn's system prompt, messages, tool calls and results and forwards them to the model provider over the provider's API. Songmaker keeps the conversation in `chat_messages` only.

## Cover picture through the gateway

A cover suggestion runs `agents/cover.md` through the same `GatewayBackend` and key as the co-writer turn; `agent/backend.py` owns the call (`run_cover_picture`) and the click's check (`cover_admission`), and `cover_runner.py` the job.

**Who may ask, twice.** Suggest needs a browser session: a hal token (bearer) gets 403 "Cover suggestions need a browser login." and no job. The click then reads the person's groups through a fresh refresh grant, as a turn does: no `agent` or an issuer that is down answers 503, outside the API group or a refused grant answers 403, each with `{"detail": {"problem": …}}` and no job. A refused group or grant never answers 401, because the frontend reads it as a logout; only a session that ends during the request still answers 401. The job references the session that asked (`jobs.session_id`, `ON DELETE SET NULL`, cleared when the job ends, never in a response, frame or log); the co-writer's cover tool binds the calling turn's session, and a tool call outside a bound turn refuses. The job checks again at its start through that session: a person who left the group meanwhile ends `not_enabled`, an ended session or a job with no reference `sign_in_again`, and a user who is gone `not_enabled`, each before any request.

**What leaves.** Album title, artist name and quoted excerpts of style prompts and lyrics, with the account's fingerprint as `user`, the same fingerprint the turn sends. No request carries the account id, the session id or the issuer.

**Outcomes.** A picture is checked by `covers.decode_cover_image`; WebP and anything else that is not a bounded PNG or JPEG ends `unavailable`, logged only as a closed detail. The job ends in one of the turn's four problems: `busy` (a 429; its `Retry-After`, capped by the client, is kept as `jobs.retry_after_seconds`), `not_enabled`, `sign_in_again` or `unavailable` (everything else, a budget or moderation refusal and the 88 s limit of the agent file included). The job's `error` holds one closed sentence per problem, never the gateway's words, a key, a token or the session id. Only a completed run spends the daily count. An explicit Cancel closes the picture's request; an answer the gateway already billed stays billed.

**Retention outside songmaker.** The gateway receives what leaves and forwards it to the image provider over the provider's API; what is stored and deleted there is the agent service's, named in the privacy text's Agent-Dienst section. Songmaker keeps only the stored suggestion.

## Agent-CLI Mounts

`songmaker-web` mounts the Claude and Grok binaries and redacted
credential mirrors read-only. Cover jobs run only in the web process; the music
worker mounts no agent CLI. The scoring worker mounts no agent CLI.

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
The host remains the only refresh owner: the host's mirrored Codex document,
which no container mounts, keeps `tokens.refresh_token` empty. A selected Codex
CLI route never changes to HTTP within that turn; an expired login is
`cli_login_expired` and other CLI failures retain the named Codex error.

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

An operator installs the AppArmor policy with
`sudo scripts/apparmor/install_profile.sh` and then recreates the service with
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
`.codex`) below the cover, Co-Writer, and probe home prefixes:
Bubblewrap mounts `tmpfs` there with `rw,nosuid,nodev`, after preparing each
target with `--perms 555`, and then read-only remounts it. It accepts
Bubblewrap's optional `silent` flag only where its mount syscall uses it and
preserves the observed inherited mount flags during remounts. Compose applies
the profile only to `songmaker-web`, drops every container capability, and sets
`no-new-privileges:true`.

The profile permits the private Codex-home mounts under three `/tmp` prefixes
(the cover turn's, the Co-Writer turn's and the probe's); nothing in songmaker
binds them. The profile *name* is a parameter wherever it is used —
`sudo scripts/apparmor/install_profile.sh [profile]` and Compose's
`SONGMAKER_APPARMOR_PROFILE` — each defaulting to `songmaker-web`.
`tests/scripts/test_apparmor_install.py` drives the installer without an
argument and requires it to install the profile file beside it. The installer
refuses a name that is not a regular profile file beside it, a symlink
included, so a typo or a link to another host file never reaches
`apparmor_parser`.

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
docker compose up -d songmaker-web
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
mounts `SONGMAKER_CLAUDE_CLI` and `SONGMAKER_GROK_CLI` into `songmaker-web`.

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

`songmaker-scoring-worker` mounts no agent CLI and no login mirror: a scoring
run calls no provider.

The Grok mirror is mounted only into its `songmaker-web` consumer. Grok turns
run with a private `0700` working directory and their own session tree, both
removed after success or abort; prompts and tool results reach the CLI only
through a private prompt file. The text tool protocol does not grant Grok CLI
tools: every start and resume keeps `--deny '*'`, and native tool-call events
abort the turn.

Claude creates `~/.claude.json` itself, so it is neither seeded nor mounted.
Every bind uses Compose long syntax, `read_only: true`, and
`bind.create_host_path: false`: a missing source fails before a writable host
directory can be created. Only files, never an operator profile directory, are
mounted; a compromised container cannot add host-side profile settings or hooks.

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

A third case needs a different mechanism: `songmaker_cli.scoring.subprocess_runner` starts the long-lived scorer child via `multiprocessing`'s `spawn` start method, which has no `env=` parameter — the child process inherits the parent's complete `os.environ` at spawn time, the same way it would inherit any other process-wide state. `_child_main` (the child's entry point) calls `_scrub_secret_env_vars()` as its literal first statement — but by the time `_child_main` runs, the spawn bootstrap has already imported the whole `subprocess_runner` module and everything it pulls in at module level (`scoring.pipeline`, `settings`, `auth`, `api_models`, ...), because multiprocessing's spawn target must be importable before it can be called. The scrub cannot undo anything a module-level import already did; it only guarantees that no code invoked *after* it — `default_registry.ensure_loaded()`'s scorer-module imports and every scorer function call that follows — can read a secret out of `os.environ`. `tests/songmaker_cli/scoring/test_subprocess_runner_scoring.py::test_scorer_child_drops_secret_env_keys_at_spawn` drives the real `_child_main` entry point (via the existing `_run_child_with_messages` test harness, not a stand-in) with every `SECRET_ENV_KEYS` entry (plus a non-secret marker) set in the parent's environment beforehand, sends it an `EnvProbeRequest`, and asserts none of them come back present while the marker does — a spawned process's own `os.environ` cannot be observed from outside it any other way, so this round trip is what makes deleting the `_scrub_secret_env_vars()` call site fail the test.

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

### Trust model and accepted risks

- **Subprocesses share the OS user.** ACE-Step and scorer subprocesses run as the same `songmaker` user in Docker. Every image creates that user as uid and gid 1000 and runs `USER 1000:1000`: the named volumes and the checkpoints bind mount belong to that uid, and Kubernetes' `runAsNonRoot` can verify only a numeric `USER`. `songmaker-acestep-worker-0`, `songmaker-music-worker` and `songmaker-scoring-worker` drop every capability (`cap_drop: [ALL]`, no `cap_add`) and set `no-new-privileges`; they carry none of `songmaker-web`'s seccomp, AppArmor or `systempaths` options, which exist only for its Bubblewrap sandbox. Compromised model weights or ACE-Step code get user-level disk access. Container isolation mitigates this; OS-user separation would need separate containers for marginal benefit. Accepted for a single-user deployment.
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
hash-verified release has no published wheel. The three first-party libraries
are git pins built from source at image build; the three images that sync them
(web, music worker, scoring worker) carry `git`, and the music worker builds
only those three from source, after a `--no-build` step that refuses any
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
| Workers | Production runs in Docker only. The web container uses a single uvicorn process; concurrency comes from arq worker containers (`MUSIC_MAX_JOBS`, `SCORING_MAX_JOBS`). PostgreSQL is the only supported production DB — SQLite is test-only. |
| Request body limit | App-level: `MAX_REQUEST_BODY_BYTES` (default 1 MB). If an operator provides an upstream proxy, align its path-specific limits for defense in depth; this repository provides no such proxy configuration. |
| IP rate limit | `IP_RATE_LIMIT` (API class, default 120/min), `MEDIA_RATE_LIMIT` (`/audio/*`, default 600/min), `STREAM_RATE_LIMIT` (SSE opens, default 45/min). Adjust based on expected traffic — see "Per-IP (global middleware)" above. |
| Resource-event stream open limit | `RESOURCE_EVENT_STREAM_OPEN_LIMIT` (per-user resource-events stream opens, default 12/min). CI overrides it — see "Resource-event streams" above. |
| Request timeout | `REQUEST_TIMEOUT` (default 30s) limits idle keep-alive connections, not full requests. The two SSE routes have their own 60-second walls; Songmaker has no general application request deadline. |
| Auto-deploy cleanup timeout | `SONGMAKER_AUTODEPLOY_PRUNE_TIMEOUT_SECONDS` (default 600). Bounds each post-deploy Docker cleanup command. |

The two-minute auto-deploy tick first runs `docker compose config --quiet` on the checked-out configuration, then checks the active-job queue and required alert-channel configuration before it checks out or builds. Compose owns the list of required variables (every `${VAR:?…}` in `docker-compose.yml`), so a missing one such as `GRAFANA_PASSWORD` is a named deploy refusal quoting compose's own message before anything is checked out — the job guard's `docker compose exec` would not notice it, and the build would fail only after the checkout. The refusal uses the same counter and alert escalation. The tick asks again right after the checkout, before any Compose build, so a variable that the newly selected commit requires is named before anything is built or recreated. `--quiet` is mandatory there: without it, compose prints the fully interpolated configuration, every `.env` secret included, into the journal. Right after it the tick runs `scripts/secret_files.py --verify`, which refuses a release whose declared secret files are missing, empty or different from `.env` (a counted refusal like the others); it reads the interpolated configuration in memory only, never writes it anywhere and prints no value. The tick also runs `scripts/check_agent_cli_mounts.sh` before those steps when that verifier is installed; a verifier failure is a named deploy refusal, so it increments the tick's existing consecutive-failure counter and follows its alert escalation. A checkout that predates the verifier logs `mount preflight not installed, skipping` and continues with its installed guards, making the temporary compatibility state visible rather than silently bypassing it. After fetching `origin/main` and its `v*` release tags into a private ref namespace, the tick asks GitHub about the newest ten eligible releases (configurable with `SONGMAKER_AUTODEPLOY_CHECK_RUN_LOOKBACK_COMMITS`; see [auto-deploy architecture](architecture.md#auto-deploy) for what makes a tag eligible) and checks out detached only the newest release whose commit's GitHub Actions (`app.slug == github-actions`) runs have all completed, at least one of them successfully and every other one successfully, skipped, or neutral (a skipped or neutral run neither blocks nor passes a commit); other apps' runs are logged as advisory and ignored, and a check run without a job name is a malformed answer. A second lookup of the commit's workflow runs finds the check suites of Dependabot's update runs and of Release runs, matched by exactly the paths `dynamic/dependabot/dependabot-updates` and `.github/workflows/release.yml`; exactly those suites leave the judgement, so a failed update job or a Release run cannot block a release while every other failed or unknown run still does. Releases with running, cancelled, or failed Actions are named in the log once and skipped; no Actions runs stay neutral only for the 30-minute grace period measured from the local host clock when the HEAD SHA was first seen; a commit timestamp supplied by Git cannot postpone that alarm. An unavailable or malformed GitHub answer from either lookup, or a 60-second lookup timeout, is a named deploy refusal that uses the same counter and alert escalation. Every Git command in the tick disables repository hooks and the filesystem monitor and runs with a minimal Git environment. That includes the one network fetch the ACE-Step pin adds: before the checkout, the tick fetches the commit the selected revision pins `vendor/acestep` to, by SHA, from the submodule's `origin` (a public fork; the tick adds no credential of its own). With the scrubbed environment, no hooks and no filesystem monitor, nothing the fork serves can run code on the host while the fetch stores its objects. The submodule's own local Git configuration (`remote.origin.uploadpack`, `core.sshCommand`, `url.*.insteadOf`) is trusted like the superproject's, because it decides how the fetch connects. The tick then checks the pin out with `git submodule update --checkout --no-fetch`. If the pin cannot be fetched, or `vendor/acestep` is not initialised, the tick fails closed: a counted refusal that leaves the checkout, the running stack and `deployed.sha` untouched. Both git fetches of a tick run under `SONGMAKER_AUTODEPLOY_GIT_FETCH_TIMEOUT_SECONDS` (120 by default) with `SONGMAKER_AUTODEPLOY_GIT_FETCH_KILL_GRACE_SECONDS` (5) before the kill, so a hung transport reaches the same alert instead of holding the deploy lock forever. Each fetch runs in a process group of its own that the script kills outright once git has exited, so a transport that ignores the deadline's TERM cannot outlive the tick; a kill can leave a git lock file that an operator removes by hand, never the script. After a refused or failed tick past the checkout (`hal` missing, `hal` exiting non-zero, a compose failure), `HEAD` stays detached at the new release while `deployed.sha` keeps the old one, so the checkout is ahead of the running stack until a later tick succeeds; the next tick retries, and the third consecutive failure alerts.

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

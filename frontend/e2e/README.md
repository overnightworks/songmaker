# End-to-end flows

Playwright drives the real stack — `docker-compose.ci.yml` (Postgres, Redis,
migrations, web) — through the click paths an operator walks by hand. Unit
tests keep missing those; `.github/workflows/e2e.yml` runs these on every PR.

## What runs

| File                       | Covers                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `library.spec.ts`          | Wall → album → play the pick → judge a take → add it to a playlist → reorder and prune the playlist → play and judge a playlist row → shuffle → open the public album link logged out. A second test walks the rail itself (issue #326): a playlist track click, an album row's label and chevron (on-demand load, no navigation, the one-open-album rule as real CSS visibility, not an attribute), the LIBRARY group's own title, and the Settings/user-row pin promise proven by actually scrolling                                                                                                                                                                                                    |
| `album-address.spec.ts`    | An album address pasted into a tab that knows nothing else → open a track under its own song address → Back → Forward, with the shell standing throughout (issue #269); a song address pasted into a tab that knows nothing else, on its own (issue #275); a take address pasted into a tab that knows nothing else, on its own (issue #281); a legacy `/?song=<uuid>` bookmark redirects onto the song address in place, and Back skips the old form (issue #284)                                                                                                                                                                                                                                        |
| `playlist-address.spec.ts` | A playlist address pasted into a tab that knows nothing else, on its own, and an unknown playlist slug states the address names nothing rather than redirecting away (issue #286) — the last new address of #265's chain, a sibling of `/` rather than nested under `/album/<slug>`                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `kinetic-strip.spec.ts`    | The take strip's kinetic scrolling (issue #358) against a real render, in both layouts its own container query switches it between: dragged, released with momentum that coasts past where the drag stopped, and a click that catches it mid-roll without opening the take it lands on — then a plain click still opens one, the wheel is proven directly against the dispatched event (native on the column layout, converted on the row layout), and Home/End/arrow keys follow the real axis. A third test proves the strip's absence on the compact shell at phone width, not kinetic behaviour — there is nothing of this action's to exercise there yet (WriteColumn.svelte's own `!compact` guard) |

`album-address.spec.ts` and `playlist-address.spec.ts` run on **desktop
only**: what they pin is the router's behaviour across an address that
changes the route, which is the same code on both shells, and both projects
share one rate-limit window. They are here rather than in the unit suite
because jsdom has no router — only a real browser shows whether moving
between `/`, `/album/<slug>`, `/album/<slug>/<song-slug>`,
`/album/<slug>/<song-slug>/take/<n>` and `/playlist/<slug>` keeps the
workspace standing or tears it down. `album-address.spec.ts`'s evidence that
nothing was torn down is that the page opened the live event stream exactly
once; `playlist-address.spec.ts` is a standalone cold open with nothing to
cross from, the same shape as the standalone cold song and take opens below.

`kinetic-strip.spec.ts` also runs on **desktop only**, for a different
reason: the strip it drives has no compact-shell counterpart to exercise —
its own third test proves exactly that absence, once, rather than every
other test silently skipping on `mobile`. It is here rather than in the unit
suite because jsdom computes no layout at all: whether a drag actually moves
the strip, whether momentum coasts past the release point on a real
container query's real overflow, and which axis that container query puts
the strip on are all unprovable without a real render (its own file header
has the full reasoning). Its takes are seeded directly against the database
(`seedTakeStripSong` in `seed.ts`, `scripts/seed_e2e_song_takes.py`) rather
than through individual reimport requests — the same reasoning as the rail's
filler albums below.

Two Chromium projects walk that flow: **`desktop`** at 1440×900 and
**`mobile`** at 390×844 with touch input. The spec is written once for the
steps both shells share, and spells out the mobile expectation wherever the
compact shell differs:

| Compact shell | What the mobile project pins                                                    |
| ------------- | ------------------------------------------------------------------------------- |
| Rail          | The header opens it as a drawer, and the drawer's Library row closes it again   |
| Song editor   | Opens on **Write**; the takes arrive through the **Takes** tab                  |
| Now Playing   | Stacks, so the judging panel is a sheet — and Escape closes sheet, then overlay |
| Transport     | One 64px row, with a play control at least the frequent-hitbox size             |
| Album header  | Still a readable title over its breadcrumb when the shell narrows to 320        |

`fullyParallel: false` with one worker: both shells hit one stack behind one IP
rate-limit window, so their cost stays additive instead of a burst.

## How a run is set up

`global-setup.ts` logs in **once** with the stack's admin account, seeds a
library through the public API (`seed.ts`) and saves the session as the storage
state every test reuses. Seeding is the only place that talks to the API
directly; everything a flow asserts, it clicks.

The seed builds one base album with three songs, a real take per song imported from
`fixtures/take.mp3` via `POST /api/songs/{id}/reimport`, one pick, a playlist
holding two of those takes, and a public link for the album — plus a second,
songs-only album for the rail's one-open-album proof, a dedicated empty album
for the kinetic-strip flow, and enough filler albums
(`RAIL_FILLER_ALBUM_COUNT` in `seed.ts`) to overflow the rail's own scroll
region for the Settings pin promise. The filler albums are seeded directly
against the database (`scripts/seed_e2e_filler_albums.py`, run inside the web
container), not through `POST /api/albums` — they never reach the server over
HTTP at all, so unlike the rest of this seed, they cost nothing against
either a flow's `FlowGuard` budget or the server's own IP rate limit. Issue
#344 is why this distinction matters: 30 individual `POST /api/albums` calls
for data that exercises no API semantics were most of what pushed a CI run
over that limit, and the limiter counts every request it receives regardless
of which Playwright context sent it — a flow's own `/api` budget below is
not the same measurement as the server's (see "Guard rails").

`fixtures/take.mp3` is a 3-second 440 Hz tone, mono, 32 kbps (~12 KB), and
Chromium plays it: `canPlayType('audio/mpeg')` answers `probably`. Regenerate
with:

```bash
ffmpeg -y -f lavfi -i "sine=frequency=440:sample_rate=22050:duration=3" \
  -ac 1 -c:a libmp3lame -b:a 32k e2e/fixtures/take.mp3
```

## Guard rails

`FlowGuard` (see `helpers.ts`) fails a flow on any 429 or 5xx response, on any
browser console error, and on any uncaught page exception. It also counts what
the flow costs the API and holds it under a named budget.

**The budget is a ceiling, not a knob.** Each flow has its own, measured on a
green run and carrying headroom. The library flow's and the rail flow's own
numbers live in `LIBRARY_FLOW_API_REQUEST_BUDGET` and
`RAIL_FLOW_API_REQUEST_BUDGET` (`helpers.ts`) — that comment is the one place
the measured count is written down; this file and `docs/testing.md` point
there rather than restate it, which is exactly how the library flow's number
drifted into three different values before a test audit caught it (issue
#326). `album-address.spec.ts` carries four —
22 for the cold album open, one-step track click and Back/Forward, 16 for a
standalone cold song open, 16 for a standalone cold take open, 15 for the
legacy `/?song=` bookmark redirect (issue #284, two full cold page loads: a
genuine earlier page, then the bookmark) — against a shared budget of 30, and
`playlist-address.spec.ts` carries two — 11 for the cold playlist open, 9 for
the unknown-slug open — against a shared budget of 15. Every cold open (song,
take, playlist, or the redirected legacy bookmark) races the live stream's
own bootstrap the same way — whichever of the two restores the library state
finishes second re-applies the same state (documented on `openAlbumAddress`
in `stores/libraryContext.ts`) — so a green run can measure a request or two
either side of these numbers; the budget's headroom is sized for exactly
that, not for a real regression. A flow that suddenly needs several more
round trips is a regression — find the extra requests instead of raising the
number. The measured count is printed on every run.

`kinetic-strip.spec.ts` carries its own, `KINETIC_STRIP_FLOW_API_REQUEST_BUDGET`
(local to the spec, same as `album-address.spec.ts`'s own): 24-28 measured
over several green runs for the column and row tests (a cold song open, the
co-writer toggle, playing two takes), against a ceiling of 35; the
mobile-absence test costs 15 and never comes close. Seeding the strip's own
takes never touches this budget at all — it runs directly against the
database (`seedTakeStripSong`), the same way the rail's filler albums do.

Summed together, the per-flow `FlowGuard` totals above (158 `/api` requests
on **desktop**, 59 on **mobile**) are **not** what the server's own IP rate
limit sees, and issue #344 is the reason that distinction is written down
explicitly rather than assumed: a `FlowGuard` only counts `/api/*` requests
the page itself made, so it misses HTML document navigations (`_classify_path`
in `middleware/rate_limit.py` puts every unrecognized path, including a plain
page load, in the same API class — fail closed, not fail open), the CI
workflow's own `/health`/login smoke test before Playwright even starts,
anything seeded through Playwright's `request` API context (global setup's
library, each attempt's playlist), and a retry re-running a whole flow inside
the same window. What the rate limiter actually counts is measured the same
way `docker-compose.ci.yml`'s own `IP_RATE_LIMIT` comment measures it: from
`docker compose logs songmaker-web`'s access log, filtered to the runner's
one IP and to the API class. One full local run of the whole suite (the CI
workflow's smoke-test curls plus both Playwright projects) measured 288 such
requests, finishing in about 35 seconds — so the 60-second window's peak is
that same 288 — comfortably under the CI stack's `IP_RATE_LIMIT: "600"`
override (`docker-compose.ci.yml`), which carries roughly 2x headroom over
that measurement, including room for one CI retry landing inside the same
window. Re-running the suite repeatedly against the same stack inside that
window is cumulative, not reset per run — see "Running it locally" below. If
this suite gains more specs, re-measure the same way rather than trusting
the `FlowGuard` sum — that gap between the two is exactly what let #344
through.

Opening a track from an open album address is still a route-file crossing
(issue #269): a song addresses `/album/<slug>/<song-slug>` instead of the
address-less `/?song=…`, and each of the four library addresses is still a
different `+page.svelte`. #265's S3 (issue #275) measured what that crossing
cost the library flow — 28 requests instead of a pre-address 25, because each
address mounted its own `LibraryWorkspace` and a crossing tore the previous
one down — without removing the cause; #276 did. `/`, `/album/[slug]`,
`/album/[slug]/[song]` and, since #281, `/album/[slug]/[song]/take/[n]` now
sit inside one `(library)` route group whose own `+layout.svelte` mounts
`LibraryWorkspace` once, so a crossing swaps only the thin leaf page under it
instead of tearing the workspace down and rebuilding it. That folded the
library flow to 26 (from 28) and the album-address flow's
cold-open-plus-crossing case to 22 (from 24) — not all the way back to the
pre-address 25, since a route-file crossing is still a real SvelteKit
navigation with its own cost, just no longer a workspace rebuild on top of
it. The standalone cold song and cold take opens stay at 16: neither crosses
a route to begin with, so there was never a rebuild to fold away for either.
What #275 bought stands unchanged: the address itself (a song is linkable and
survives a cold open on its own, 404s honestly on an unknown slug, and
follows a rename) and the crossing-detection fix that keeps the router in
step one segment deeper (`libraryRouteShape` in `stores/libraryContext.ts`).

Chasing the cold-take-open flow against a real stack is what found a real
defect in that race, not just its request count: `hydrateLibraryFromHistory`
(`stores/libraryContext.ts`) used to read `restoreLibraryBrowse`'s own return
value as the live stream's bootstrap success signal, but a `false` from a
restore that lost the race to a newer one is not a failure — only a
genuinely failed one is. Treating it as one closed the live stream and showed
"Library sync failed" on a cold take open every time: a take's extra hop
(loading the rest of the song's generations to find the requested number
before it can address anything at all) reliably loses that race, where a
song's faster resolution usually wins it — which is why this surfaced on the
take address and not, so far, on the album or song ones, even though the same
latent bug sat in their shared code path too. Fixed by reading
`libraryBrowse`'s own final status instead, the same way the branch beside it
already did.

Selectors are roles and accessible names, imported from `src/lib/constants.ts`
— never `data-testid`. A flow that cannot find an element by its accessible
name has found an accessibility defect. Two narrow exceptions this suite has
needed so far, both structural rather than test-only hooks: asserting
`.settings-sidebar` is gone (the old second column has no accessible name to
assert the absence of) and `library.spec.ts`'s own `railAlbumRow` (every
album row's chevron shares one accessible name, `RAIL_ALBUM_DISCLOSE_LABEL`
— the row must be narrowed by its own title text first, since the rail never
nests one navigation landmark per album to scope by role alone).

A row collapsed by the `grid-template-rows: 0fr` + `overflow: hidden` trick
(`.rail-group-panel`, `.album-songs`, ...) is not provable with
`toBeVisible()`/`toBeHidden()`: a descendant clipped by that zero-height
ancestor still reports its own natural bounding box, so Playwright considers
it visible regardless of the ancestor's collapse (found while building the
rail's own e2e coverage, issue #326 — see `expectRailRowExpanded` /
`expectRailRowCollapsed` in `library.spec.ts`). `toBeInViewport()` uses the
browser's own IntersectionObserver, which does resolve clipping through
ancestors, and is the one assertion that actually distinguishes collapsed
from expanded for this pattern.

## Running it locally

Never point the flows at the stack on port 8080; that is the operator's. Boot
the CI stack on its own port and project, run, then throw it away:

```bash
cd <repo root>
export COMPOSE_PROJECT_NAME=songmaker-e2e-local WEB_PORT=18080
export POSTGRES_PASSWORD=e2e-ci-postgres-password
export SESSION_SECRET=e2e-ci-session-secret-do-not-reuse-anywhere-else
export SONGMAKER_INTERNAL_TOKEN=e2e-ci-internal-token
export ADMIN_USERNAME=e2e-ci-admin ADMIN_PASSWORD='E2eCiSmoke#2026!'
export PUBLIC_BASE_URL=http://localhost:18080   # share links (#339) need this or global-setup's seed 500s
docker compose -f docker-compose.yml -f docker-compose.ci.yml \
  up -d --build --wait postgres redis migrate songmaker-web

cd frontend
E2E_BASE_URL=http://localhost:18080 pnpm test:e2e            # both shells
E2E_BASE_URL=http://localhost:18080 pnpm test:e2e --project=mobile

cd .. && docker compose -f docker-compose.yml -f docker-compose.ci.yml down -v
```

Re-running against the same stack repeatedly will trip the app's IP rate limit
— `IP_RATE_LIMIT: "600"` per 60-second window under this CI recipe (see the
budget note above; the production default is 120) — and the flow will report
429s — that is the guard working, not a flaky test. Wait out the window or
reset the stack; a fresh run right after a previous one still counts against
the same window, so back-to-back reruns add up rather than starting over.

Artifacts (`playwright-report/`, `test-results/`) are written on failure only
and uploaded by CI on a failing run. `retries: 1` in CI, with a trace on the
retry.

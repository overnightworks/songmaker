# End-to-end flows

Playwright drives the real stack — `docker-compose.ci.yml` (Postgres, Redis,
migrations, web) — through the click paths an operator walks by hand. Unit
tests keep missing those; `.github/workflows/e2e.yml` runs these on every PR.

## What runs

| File                    | Covers                                                                                                                                                                                                                                                    |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `library.spec.ts`       | Wall → album → play the pick → judge a take → add it to a playlist → reorder and prune the playlist → play and judge a playlist row → shuffle → open the public album link logged out                                                                     |
| `album-address.spec.ts` | An album address pasted into a tab that knows nothing else → open a track under its own song address → Back → Forward, with the shell standing throughout (issue #269); a song address pasted into a tab that knows nothing else, on its own (issue #275) |

`album-address.spec.ts` runs on **desktop only**: what it pins is the router's
behaviour across an address that changes the route, which is the same code on
both shells, and both projects share one rate-limit window. It is here rather
than in the unit suite because jsdom has no router — only a real browser shows
whether moving between `/`, `/album/<slug>` and `/album/<slug>/<song-slug>`
keeps the workspace standing or tears it down. Its evidence that nothing was
torn down is that the page opened the live event stream exactly once.

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

The seed builds one album with three songs, a real take per song imported from
`fixtures/take.mp3` via `POST /api/songs/{id}/reimport`, one pick, a playlist
holding two of those takes, and a public link for the album.

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
green run and carrying headroom: the library flow measures 28 `/api` requests
per shell against a budget of 32, and `album-address.spec.ts` carries two —
24 for the cold album open, one-step track click and Back/Forward, 16 for a
standalone cold song open — against a shared budget of 30. A flow that
suddenly needs more round trips is a regression — find the extra requests
instead of raising the number. The measured count is printed on every run.

Opening a track from an open album address is still a route-file crossing
(issue #269), and #265's S3 (issue #275) did not remove that: a song now
addresses `/album/<slug>/<song-slug>` instead of the address-less
`/?song=…`, but both are a different `+page.svelte` from the album's own, so
the editor still remounts once on the way there — 28 and 24 measure the same
as before #275, not lower. What #275 actually bought is the address itself
(a song is linkable and survives a cold open on its own, 404s honestly on an
unknown slug, and follows a rename) and the crossing-detection fix that keeps
the router in step one segment deeper (`libraryRouteShape` in
`stores/libraryContext.ts`). Folding the remount away for real would need
`/album/[slug]` and `/album/[slug]/[song]` to share one mounted
`LibraryWorkspace` instance across the crossing — a `+layout.svelte` moving
the workspace out of both leaf pages — which is a route-structure change
beyond this slice's file scope, not something this suite can paper over by
adjusting a number.

Selectors are roles and accessible names, imported from `src/lib/constants.ts`
— never `data-testid`. A flow that cannot find an element by its accessible
name has found an accessibility defect.

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
docker compose -f docker-compose.yml -f docker-compose.ci.yml \
  up -d --build --wait postgres redis migrate songmaker-web

cd frontend
E2E_BASE_URL=http://localhost:18080 pnpm test:e2e            # both shells
E2E_BASE_URL=http://localhost:18080 pnpm test:e2e --project=mobile

cd .. && docker compose -f docker-compose.yml -f docker-compose.ci.yml down -v
```

Re-running against the same stack repeatedly will trip the app's IP rate limit
(120 requests per window) and the flow will report 429s — that is the guard
working, not a flaky test. Wait out the window or reset the stack.

Artifacts (`playwright-report/`, `test-results/`) are written on failure only
and uploaded by CI on a failing run. `retries: 1` in CI, with a trace on the
retry.

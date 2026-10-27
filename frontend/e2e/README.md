# End-to-end flows

Playwright drives the real stack — `docker/docker-compose.ci.yml` (Postgres, Redis,
migrations, web) — through the click paths an operator walks by hand. Unit
tests keep missing those; `.github/workflows/e2e.yml` runs these on every PR.

## What runs

| File                              | Covers                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `offline.spec.ts`                 | Phone: offline strip/Generate placement, running-generation and full-batch arrival recovery, and queued-label recovery without navigation. Both shells: server-return, take-play and album-start recovery.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `offline-boot.spec.ts`            | `1160-F42-boot` (#1654): natural service-worker installation followed by offline reloads at root and a deep album address shows the app’s offline strip; online `/health` navigation still returns the server’s JSON; a browser holding a cache from an older build loses it when the new service worker activates, keeps only the current app shell and still boots offline (#1860). Both desktop and mobile.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `library.spec.ts`                 | Wall → album → play the pick → judge a take → add it to a playlist → reorder and prune the playlist → play and judge a playlist row → shuffle → open the public album link logged out. A second test walks the rail itself (issue #326): a playlist track click, an album row as one target (on-demand load and navigation, the one-open-album rule as real CSS visibility, not an attribute), the LIBRARY group's own title, and the Settings/user-row pin promise proven by actually scrolling                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `album-address.spec.ts`           | An album address pasted into a tab that knows nothing else → open a track under its own song address → Back → Forward, with the shell standing throughout (issue #269); a song address pasted into a tab that knows nothing else, on its own (issue #275); a take address pasted into a tab that knows nothing else, on its own (issue #281); a legacy `/?song=<uuid>` bookmark redirects onto the song address in place, and Back skips the old form (issue #284)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `playlist-address.spec.ts`        | A playlist address pasted into a tab that knows nothing else, on its own, and an unknown playlist slug states the address names nothing rather than redirecting away (issue #286) — the last new address of #265's chain, a sibling of `/` rather than nested under `/album/<slug>`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `kinetic-strip.spec.ts`           | The take strip's kinetic scrolling (issue #358) against a real render, in both layouts its own container query switches it between: dragged, released with momentum that coasts past where the drag stopped, and a click that catches it mid-roll without opening the take it lands on — then a plain click still opens one, the wheel is proven directly against the dispatched event (native on the column layout, converted on the row layout), and Home/End/arrow keys follow the real axis. A third test proves the strip's absence on the compact shell at phone width, not kinetic behaviour — there is nothing of this action's to exercise there yet (WriteColumn.svelte's own `!compact` guard)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `admin-models.spec.ts`            | The admin Models tab (issues #820, #846): one row per task with both routes offered and the unusable one greyed with its reason, `No models` where no route is set up, a collapsed Advanced, and every column — Status included — still on screen at 1920, 1440, 1280 and 1024px, where the card the table sits in is hundreds of pixels narrower than the viewport. Then a save the server keeps even though no route can run it, a co-writer turn that ends with its named reason instead of switching provider quietly, and, at 375px, one card per task with labelled lines and no sideways scroll. Replaces `admin-routes.spec.ts`, whose per-provider route cards Fassung 2 removed                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `settings-after-keycloak.spec.ts` | Settings after Keycloak (#1784): the account circle's menu on both shells (name linking to the issuer's account console in a new tab, Settings, theme, Sign out, legal links; no rail account row), Settings for a member and an admin without Account, Legal or Cleanup, Cleanup as the Admin page's last tab with its confirmation (Cancel runs nothing, Delete runs once) and its empty state (retention endpoints answered with test data), and the old `/settings/account` and `/settings/cleanup` behaving like an unknown address.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `auth-flows.spec.ts`              | Signing in through Keycloak as far as it runs without Keycloak (#1765): the sign-in start answers 303 to the issuer's authorization endpoint with a Lax pending-login cookie and `no-store`; the signed-out page says so, redirects by itself never and starts the sign-in only when Log in is pressed; a protected address asks the server to sign in and to come back to it (`/login/oidc?next=`); an API call without a session is a 401; share pages never ask to sign in; no access offers Sign out (a top-level POST, the server's no-store page and the cleared cookie, then the issuer) and Back; a refused return (no pending login, an issuer error) is the 403 shell with Login failed and Try again; a logout from another origin is refused, a same-origin one answers the logout page, and with JavaScript off that page shows one button named like the account menu entry. The CI stack runs no identity provider, so whatever leaves the app's origin ends on a stub (`stubIdentityProvider`). A real login is a named gap of #1620, proven live. Both shells                                                                                                                                                                                                                                                                                                                       |
| `song-phone.spec.ts`              | The song page at phone width (issue #995, #914's L12): the Takes tab lists each take with its own play control at least the frequent-hitbox size, playing one names it in the mini-player by its real seeded version and take number; a running generation shows its percent, take counter and an ETA in both the Generate button and the Takes status slot; failing that same job live, over its own open SSE stream, surfaces the worker's literal sentence under the Generate button, expandable by its chevron; since #1143 Back with an unsaved draft asks first (Cancel keeps the draft and the song's address, Discard leaves without saving), and one desktop row: Discard on the rail's Settings link lands on the page. Mobile project otherwise — see the file's own header for why                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `take-arrives.spec.ts`            | A finished generation's take reaches the phone's Takes list without navigation (issue #1020): with the Takes tab open on a song whose generate job is running, the job ends with its take but without the `generation.created` resource event (standing in for the event a dropped phone stream never received), and the take is in the list alongside the completion toast. Mobile only, seeded against the database like `song-phone.spec.ts`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `take-selection.spec.ts`          | A take selection belongs to one song (#1824): at 1440 px, two takes ticked with Ctrl/⌘-click on song A leave no toolbar and no "n selected" on song B. Delete N asks first (#1844, S11): the dialog names the count, Cancel keeps the ticks, Delete removes exactly the ticked takes and the others survive, read back through the API.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `take-folds.spec.ts`              | The takes fold per version (#1843, S3): the latest version stands open and an earlier one unfolds in place and folds again by keyboard; folding clears the ticks inside the version and ends select mode when none is left; Select all unkept covers rendered takes only; Delete sends only rendered ticked takes, and a Save that folds the version under an open bulk or single dialog changes or cancels the delete, and a take another client deleted never stays ticked after a Save — the delete outcomes of cells 26, 28-31, 33 and 35 read back through the API; folds and ticks survive Back/Forward, the phone's Edit tab and an opened and closed Now Playing, and reset on another song; Imported starts open while no version holds a take, folds away its ticks, and on the phone stays folded through the Edit tab and opens again after another song.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `take-provenance.spec.ts`         | The provenance link of a take made from another take (#1843, rule 10): a plain click or Enter unfolds the folded version holding the source, writes one entry of the song at the take's anchor and scrolls to it, so the song stays open; the same link again writes nothing more; a Ctrl or middle click leaves the tab as it was; with an unsaved draft, Back and Forward between the song's entries ask nothing, while the Back that leaves the song asks as ever, and on the phone Back closes Now Playing and the tab switch rewrites the entry. `foldedSong.ts` seeds the song it shares with `take-folds.spec.ts`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `phone-tabs.spec.ts`              | #1354 row 61: three places, current selection, settings/private pages, full-player visibility and repeated tab navigation. `song-phone.spec.ts` records transient tab attachments on dirty Back and proves none on cold song entry; `shell-bottom-geometry.spec.ts` checks inset ownership.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `library-wall-history.spec.ts`    | Both shells: Settings → Back restores the wall at halfway and actual bottom, with unchanged bounds and the final album fully visible at bottom.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `back-closes-overlay.spec.ts`     | Back closes the open overlay before it moves the library (issue #1114): one table, one row per overlay and way of leaving it — a Settings page found in the phone Search sheet closes it and Back then Forward return to Settings (Back from Settings onto a library entry is #1006 S5), and on the desktop Back docks the full Now Playing and keeps the playlist; the next Back reaches the wall; since #1119 also Back closes the take menu and the phone app bar's song menu (and the desktop song menu) and keeps the song, Back over Now Playing closes the This take sheet before Now Playing, and a playlist entry menu item that opens the song leaves one Back to the playlist; since #1125 Back cancels the delete confirmation on the phone and the desktop and the take stays (Cancel there leaves one Back to the playlist), Back on the unsaved-draft dialog keeps editing with the draft, Back closes the song menu's playlist picker and adds nothing, and Back closes an album's share warning on the phone and keeps the album; since #1331 Back closes overlays outside the library too: the phone account menu on Voices (and after a reload over it one Back leaves the page), the voice delete confirmation keeps the voice, the share page's Now Playing closes on Back and its × leaves no entry, and an album tapped in phone Search over Voices leaves one Back to Voices |
| `song-versions.spec.ts`           | The version chip next to Lyrics opens the song's versions as a sheet on the phone and a popover on the desktop (issue #1262, #1245 rules 1-6 and 9): tapping v1 loads it as the draft with its Loaded from v1 line, and Generate saves the loaded text as v3 while v1 and v2 stay as they were, a take-less v2 included; a dirty draft is asked about first, where Cancel keeps it, Undo after Replace brings it back, and Back closes the sheet; the Undo toast goes with the next action, so typing ends it and the opened sheet stands free of it. Open v1 on its take group loads v1 the same way, and Open v1 in Now Playing lands on Edit with v1 loaded while the take plays on; the seeded library's imported take groups as Imported with no Open link, and Now Playing says why it has no lyrics (issue #1273, rules 7-8). Takes are seeded against the database like `song-phone.spec.ts`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `leave-prompt.spec.ts`            | The browser's leave prompt (#1869, H6f of #1006): with unversioned typing in the song draft, a reload, closing the tab, a document navigation and Back out of the first app entry raise the `beforeunload` dialog (Stay keeps the text, Leave drops it); a saved, retyped-to-saved or untouched draft reloads silently, and an in-app leave shows the app's Unsaved changes dialog and no browser prompt. Both shells. Phone browsers are not driven: Chromium with touch emulation only.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `now-playing-opening.spec.ts`     | Now Playing's opening tab (#1831): one queued take opens on This take, an album played from its page on Queue, and the tab holds while the queue grows; the album ⋯ row, the walk's card and its way out read "Pick album takes" and "Done".                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `growing-text.spec.ts`            | Style and lyrics show their whole text with no scrollbar of their own while the page scrolls, and `[Intro]`-style labels stand out as plain editable text; a tagged style with a long word and a lyric ending in a newline keep the painted text aligned with the field (issue #1819, #1804 rules S1 and S2) at 1440 and 390.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |

A test that belongs to one shell carries that shell's tag, `ONLY_IN_SHELL`
in `helpers.ts`, and the other shell's project leaves it out, instead of the
test skipping itself by shell (`docs/testing.md`, the two projects).

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
its own third test proves exactly that absence, once, in a phone context it
opens itself. It is here rather than in the unit
suite because jsdom computes no layout at all: whether a drag actually moves
the strip, whether momentum coasts past the release point on a real
container query's real overflow, and which axis that container query puts
the strip on are all unprovable without a real render (its own file header
has the full reasoning). Its takes are seeded directly against the database
(`seedTakeStripSong` in `seed.ts`, `scripts/seed_e2e_song_takes.py`) rather
than through individual reimport requests — the same reasoning as the rail's
filler albums below.

`song-phone.spec.ts` runs on **mobile only** (apart from its one desktop unsaved-draft row, #1143), the mirror image of
`kinetic-strip.spec.ts`'s own desktop-only reason: everything it proves —
the compact Edit/Takes tabs, the phone Generate button's progress and
failure states, the Takes status slot — is compact-shell UI with no desktop
counterpart to exercise. CI's e2e stack runs no ACE-Step worker, so its song
(already at a version past v1, to prove the player names the real seeded
version rather than an assumed v1) and both job states are seeded directly
against the database (`scripts/seed_e2e_job_states.py`), the same reasoning
as `kinetic-strip.spec.ts`'s own takes above; a job seeded as failed while its
own SSE stream is still open reaches the page live, the way a real worker
crash would report it, without a reload.

Two Chromium projects walk that flow: **`desktop`** at 1440×900 and
**`mobile`** at 390×844 with touch input. The spec is written once for the
steps both shells share, and spells out the mobile expectation wherever the
compact shell differs:

| Compact shell | What the mobile project pins                                                                                                                                     |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Rail          | Desktop rail collapse persists; phone tabs replace the rail and ignore its collapse preference                                                                   |
| Song editor   | Opens on **Edit**; the **Takes** tab lists every take with its own play control, a running generation's progress and a failed one's cause (`song-phone.spec.ts`) |
| Now Playing   | Stacks, so the judging panel is a sheet — and Escape closes sheet, then overlay                                                                                  |
| Transport     | One 64px row, with a play control at least the frequent-hitbox size                                                                                              |
| Album header  | Still a readable title over its song count when the shell narrows to 320                                                                                         |

`fullyParallel: false` with one worker: both shells hit one stack behind one IP
rate-limit window, so their cost stays additive instead of a burst.

## How a run is set up

`global-setup.ts` signs the e2e admin account in **once** with a seeded
session, seeds a library through the public API (`seed.ts`) and saves the
session as the storage state every test reuses. Seeding is the only place that
talks to the API directly; everything a flow asserts, it clicks.

**Sessions are seeded, not typed.** `support/seed_sessions.py` runs inside the
web container (`docker compose exec -T -e SEED_SESSIONS_REQUEST=... songmaker-web
/app/.venv/bin/python -`, the script on stdin) and goes through the app's own
user and session stores: it finds or creates an account and opens a database
session, then prints the signed session cookie the library issues after a Keycloak
login; the row holds an ID token unless the request says otherwise. The stack has no admin bootstrap, so this helper
is also where the e2e admin account (`E2E_ADMIN_USERNAME`) comes from.
`seedAccount` / `seedAdminAccount` in `seed.ts` return those cookies for
`context.addCookies` and `signedInApi`; the throwaway stack drops the accounts
with the run. The helper sits outside `scripts/`, which the image copies, so it
never ships. No flow types a password: there is none.

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

`admin-models.spec.ts` carries its own file-wide ceiling,
`MODELS_FLOW_API_REQUEST_BUDGET` (local to the spec): 11 for the table at four
desktop widths, 24 for the Cover row's save, reload and restore, 46 for the
co-writer turn, 9 for the phone cards and 24 (20 on the phone) for the Scoring
row's save, reload and restore, against a shared 60. Its four desktop tests
run on **desktop only** and its card test and the Scoring row's phone test on
**mobile only** — the table and the cards are two different surfaces, so each
is driven where it exists rather than skipped in the other shell.

`song-phone.spec.ts` carries `SONG_PHONE_FLOW_API_REQUEST_BUDGET`
(`helpers.ts`, unlike the other file-local budgets above, since the flow
seeds nothing through the run's API context at all) -- see that constant's
own doc comment for the measured count, the flow it covers and its ceiling,
rather than restating the numbers here (the same convention
`LIBRARY_FLOW_API_REQUEST_BUDGET`'s own comment names, and the reason those
numbers drifted apart before). Seeding the song and both job states never
touches this budget: like the rail's filler albums and
`kinetic-strip.spec.ts`'s own takes, all three run directly against the
database rather than through the page (`seedSongPhoneSong`,
`seedRunningGenerationJob`, `failGenerationJob` in `seed.ts`); the failed job
state itself arrives live over the running job's still-open SSE stream, with
no cold open of its own.

Two things that flow needs and no other one does are worth naming here. Its
tests start logged out, which takes an explicitly empty
`storageState: { cookies: [], origins: [] }` -- `undefined` reads as "not
overridden" in `test.use` and silently leaves the project's signed-in admin
state in place, which looks exactly like a passing flow until you notice the
wall it is standing on. And a refusal it drives is reported twice: once as the
response, and once as a console error Chromium writes for every failed fetch,
so `FlowGuard` takes a `refusalsExpectedOn` list of paths, each with the
statuses that are the sentence under proof there: a 401, 403 or 429 on the
session and admin reads, and in the admin flows a 404 on a stale session
revoke or on a Disable of an account deleted meanwhile, and a 409 on a taken
username. A path ending in `/` covers the ids
beneath it. Everywhere else, and for any 5xx, the guard is unchanged, and every
flow, including each extra tab it opens, still asserts it clean.

Summed together, the per-flow `FlowGuard` totals above (436 `/api` requests on
**desktop** and 178 on **mobile**, read off one green run -- CI run
34058495442, 2026-09-07, with `auth-flows.spec.ts`; of that, 86 and 80 are its
own -- rather than carried forward, which is how the
library flow's own number drifted into three values before issue #326) are
**not** what the server's own IP rate
limit sees, and issue #344 is the reason that distinction is written down
explicitly rather than assumed: a `FlowGuard` only counts `/api/*` requests
the page itself made, so it misses HTML document navigations (the rate-limit
policy puts every unrecognized path, including a plain page load, in the same
API class — fail closed, not fail open), the CI
workflow's own `/health` smoke test before Playwright even starts,
anything seeded through Playwright's `request` API context (global setup's
library, each attempt's playlist), and a retry re-running a whole flow inside
the same window. What the rate limiter actually counts is measured from
`docker compose logs songmaker-web`'s access log, filtered to the runner's
one IP and to the API class by the same rate-limit policy the server uses
(`scripts/e2e_rate_window.py`). The E2E workflow's "Busiest API rate-limit
window" step prints that busiest 60-second window after every Playwright run,
counting setup, cleanup, retries and browser traffic, so the figure cannot go
stale. The CI stack's `IP_RATE_LIMIT: "8000"` override
(`docker/docker-compose.ci.yml`) is kept at least three times above that
peak, with room for one CI retry landing inside the same window (#1555). A
request the limiter refused never reaches the access log, so on a run that
hit 429 the printed peak is only a lower bound. Re-running the suite
repeatedly against the same stack inside that window is cumulative, not reset
per run — see "Running it locally" below. If this suite gains more specs,
check the printed peak against the override rather than trusting the
`FlowGuard` sum — that gap between the two is exactly what let #344
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
name has found an accessibility defect. One narrow structural exception is
asserting `.settings-sidebar` is gone: the old second column has no accessible
name to assert its absence. `library.spec.ts` narrows its `railAlbumRow` by
album title because the rail has one navigation landmark for the whole album
tree, not one landmark per row.

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
export E2E_ADMIN_USERNAME=e2e-ci-admin
# The web app boots without reaching Keycloak; these name an issuer that never answers.
export OIDC_ISSUER=https://keycloak.invalid/realms/e2e
export KEYCLOAK_CLIENT_SECRET_FILE="$(mktemp)" && echo e2e-ci-client-secret > "$KEYCLOAK_CLIENT_SECRET_FILE"
export GRAFANA_PASSWORD=e2e-ci-grafana-password    # compose refuses up/down without it
export PUBLIC_BASE_URL=http://localhost:18080   # share links (#339) need this or global-setup's seed 500s
docker compose -f docker-compose.yml -f docker/docker-compose.ci.yml \
  up -d --build --wait postgres redis migrate songmaker-web

cd frontend
E2E_BASE_URL=http://localhost:18080 pnpm test:e2e            # both shells
E2E_BASE_URL=http://localhost:18080 pnpm test:e2e --project=mobile

cd .. && docker compose -f docker-compose.yml -f docker/docker-compose.ci.yml down -v
```

Re-running against the same stack repeatedly will trip the app's IP rate limit
— `IP_RATE_LIMIT: "8000"` per 60-second window under this CI recipe (see the
budget note above; the production default is 120) — and the flow will report
429s — that is the guard working, not a flaky test. Wait out the window or
reset the stack; a fresh run right after a previous one still counts against
the same window, so back-to-back reruns add up rather than starting over.

A failing attempt writes its screenshot and `error-context.md` (the page
snapshot at the failure) to its own folder under `test-results/`. Locally that
is all: no trace is recorded unless you pass `--trace on`. CI runs with
`retries: 1` and records a trace on the retry only, as `trace.zip` in the
retry's own `…-retry1` folder; the failed first attempt's folder keeps its
screenshot and `error-context.md` whether the retry passes or not. CI uploads
the HTML report (`playwright-report/`) with `test-results/`, and the compose
logs, when the job fails or any test was retried; a run where every test passes
first time records no trace and uploads neither.

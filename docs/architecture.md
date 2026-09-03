# Songmaker Architecture

## Overview

```
                    ┌─────────────────────────────────────┐
                    │        SvelteKit Frontend            │
                    │  Song editor, player, co-writer chat,│
                    │  generation settings, filters        │
                    └──────────────┬──────────────────────┘
                                  │ REST API (JSON)
                                  ▼
                    ┌─────────────────────────────────────┐
                    │        FastAPI Backend               │
                    │  Auth middleware → API endpoints     │
                    │  Pydantic request/response models    │
                    └──┬─────────┬──────────┬─────────────┘
                       │         │          │
                       ▼         ▼          ▼
                 PostgreSQL    Redis    Co-writer / judge providers
                 (all data)   (queues,  (selected provider per surface)
                              sessions,
                              rate limits)
```

## Docker Compose Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│ Docker Compose                                                       │
│                                                                      │
│  ┌──────────────────┐   ┌────────────┐   ┌─────────────────────┐    │
│  │  songmaker-web    │   │  postgres   │   │  redis              │    │
│  │  FastAPI + Svelte │──▶│  all data   │◀──│  sessions, queues,  │    │
│  │  port 8080        │   │  port 5432  │   │  rate limits,       │    │
│  │  + control plane  │   │             │   │  worker state (TTL) │    │
│  └────────┬─────────┘   └────────────┘   └──────────┬──────────┘    │
│           │                                          │               │
│           │  enqueue jobs to named Redis queues       │               │
│           ▼                                          ▼               │
│  ┌────────────────────┐            ┌──────────────────────────────┐  │
│  │  music-worker       │            │  scoring-worker              │  │
│  │  no GPU             │            │  CPU (or GPU)                │  │
│  │  scheduler dispatch │            │  Whisper + AudioBox          │  │
│  │  queue: music       │            │  queue: scoring              │  │
│  │  max_jobs: 2        │            │  max_jobs: 1                 │  │
│  └──────────┬──────────┘            └──────────────────────────────┘  │
│             │ HTTP /load_model, /generate, SSE                       │
│             ▼                                                        │
│  ┌──────────────────────┐  ┌──────────────────────┐                  │
│  │  acestep-worker-0    │  │  acestep-worker-1    │ ← future GPU      │
│  │  GPU + ACE-Step      │  │  (added later, no    │                   │
│  │  subprocess          │  │   code change)       │                   │
│  │  /load_model         │  └──────────────────────┘                   │
│  │  /generate → SSE     │                                             │
│  │  registers w/ web    │                                             │
│  └──────────────────────┘                                             │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐                                  │
│  │  prometheus   │  │  grafana     │                                  │
│  │  scrapes      │──│  dashboards  │                                  │
│  │  /metrics     │  │  port 3000   │                                  │
│  └──────────────┘  └──────────────┘                                  │
└──────────────────────────────────────────────────────────────────────┘
```

ACE-Step worker pool: each `acestep-worker-N` is a peer container with its
own GPU. Workers self-register with the web container at startup
(`POST /api/internal/workers/register`) and heartbeat ephemeral state to
Redis with a 15s TTL. The music-worker is now a thin orchestrator: its
arq `generate` job calls the scheduler (`scheduler.py`), which picks an
online worker, INCRs queue depth atomically, dispatches via HTTP, and
consumes the worker's task SSE stream until `done`. A stream that stays silent
for 630 seconds fails the generation with `Worker stream went silent`; transport
drops still use the scheduler's bounded reconnect policy. The music-worker then
post-processes the worker's WAV (decode → splice → master → MP3 → DB
insert) and the job completes. See [acestep.md](acestep.md) for the
worker API surface.

Production application containers (web, music-worker, scoring-worker, and ACE-Step workers) write JSON log lines with `timestamp`, `level`, `logger`, and `event`; Docker retains five 10 MB files per service so operational history remains bounded.

## Job Routing

```
User clicks "Generate"                    User clicks "Score"
        │                                         │
        ▼                                         ▼
  POST /songs/{id}/generate               POST /generations/{id}/score
        │                                         │
        ├── rate limit check                      ├── rate limit check
        ├── ownership check                       ├── ownership check
        ├── create Job record                     ├── create Job record
        │                                         │
        ▼                                         ▼
  arq:queue:music                          arq:queue:scoring
  (Redis sorted set)                       (Redis sorted set)
        │                                         │
        ▼                                         ▼
  Music Worker (orchestrator)              Scoring Worker
  ├── see [Generation Flow](#generation-flow) ├── spawn scorer subprocess
  │   for Lua admission, hold defer, config   ├── Whisper transcription
  │   build, worker HTTP, and persistence      ├── AudioBox aesthetics
  │                                              ├── BPM, dynamics, silence, spectral
  │                                              ├── lyrical coherence (configured judge provider)
  │                                              ├── save scores to DB
  │                                              └── Job status: completed
  ├── post_process_generation (to_thread):
  │   ├── read worker WAV from volume
  │   ├── decode + splice (if repaint)
  │   ├── master → MP3 + ID3 tags
  │   └── INSERT generation + `generation.created` event (one DB transaction)
  └── Job status: completed

  Repaint: POST /generations/{id}/repaint
  Cover:   POST /generations/{id}/cover
  Upload:  POST /api/audio/upload (reference audio)
  Art:     POST /api/albums/{id}/cover and POST /api/songs/{id}/cover (files on the audio volume)

  User clicks "Chat"
        │
        ▼
  POST /api/chat/turn
  (multi-turn: loads history from DB,
   compacts it to a rolling summary plus a token-bounded tail,
   streams through the selected co-writer provider,
   stores user + assistant messages)
```

## Layers

### Frontend (`frontend/`)

SvelteKit single-page app. All state in Svelte stores.

The app shell is one navigation, not modes. A left `Rail` (264px, inline on
wide layouts, behind a drawer with a 46px trigger strip on ≤768px or any
coarse pointer) holds: the brand (the rail's Library shortcut, `openLibraryWall`)
pinned at the top; a scroll container in the middle holding the LIBRARY
group, built on the shared `RailGroup.svelte` (chevron, icon, label, count —
one row shape for every group); and, pinned below that scroll container, the
SETTINGS group (also a `RailGroup.svelte`, via `RailSettings.svelte`) and a
user row (username, theme toggle, Logout — inline, no popup menu;
`shell/UserRow.svelte`). `RailLibraryGroup.svelte` is the LIBRARY group: it
loads every album route-independently (`ensureAllAlbumsLoaded`, #304) and
lists all of them, each expandable one level into its own tracks (a
takes/pick summary per row, an equalizer marking the one actually playing, a
crimson-accent left border marking the selected/current track — the same
token every rail group's active row uses). The open album's row and its
selected track pre-expand automatically on entry without overriding a later
manual collapse; the LIBRARY group's own title does not yet navigate (planned
for a later slice). There is no Studio/Listen mode split and no third library
tab for
Shared; `LibraryWall.svelte` (the main-area library browser) filters by chips
`Albums · Playlists · Shared` instead, backed by `libraryFilter` in
`stores/libraryContext.ts`. Share inventory is the same complete server list
of the current user's public slugs (`GET /api/library/shares`) as before,
just reached via the Shared chip; membership, `N`, and the DELETE endpoints
are unchanged.

An open album has an address of its own, `/album/<slug>` (issue #269; album
ids are already readable slugs), an open song one segment deeper,
`/album/<slug>/<song-slug>` (issue #275; songs carry their own album-unique,
DB-enforced slug — issues #272/#274), a selected take one segment deeper
still, `/album/<slug>/<song-slug>/take/<n>` (issue #281), where `<n>` is
`generation_number` — the number the surface already shows the person ("Take
3"), never the generation's uuid — and an open playlist an address of its
own, `/playlist/<slug>` (issue #286, #265's S5 and last new address of the
chain): a sibling of `/`, not a segment under `/album/<slug>`, since a
playlist has no album to nest inside — its `slug` follows the album
precedent (a globally unique column, reserved via `unique_playlist_slug` in
`api_helpers.py` under its own advisory lock, `_PLAYLIST_SLUG_LOCK_ID`) rather
than a song's per-album one. All five of `/`, `/album/<slug>`,
`/album/<slug>/<song-slug>`, `/album/<slug>/<song-slug>/take/<n>` and
`/playlist/<slug>` sit inside the `routes/(library)` route group, whose own
`+layout.svelte` mounts `components/LibraryWorkspace.svelte` — the bootstrap
gate and the surface switch — exactly once for as long as the browser stays
on any of the five (issue #276); the route files underneath are thin, each
resolving its own address and rendering only an overlay (loading / unknown /
unreachable) stacked over the standing workspace while it does. Before #276
each mounted the workspace itself, so a crossing between any two swapped the
leaf `+page.svelte` and tore the component down with it — the sync stream
survived (`routes/+layout.svelte`, next paragraph) but the workspace, and
everything under it (`SongDetailView` included), did not; measuring the cost
(issue #275, then #276) is what forced the route group. The outer
`routes/+layout.svelte` still owns the live event stream and the history
listener, so swapping between any of the five addresses neither rebuilds the
workspace nor re-runs its bootstrap, and it starts the stream only for a
signed-in browser on a library route — the reach the workspace page had when
it owned this; Settings, login, setup and the share pages leave it off. The
workspace itself gates on `resourceSync.ready` rather than on a promise
resolved once per mount, so a mount that finds the stream already live
(returning to the library after leaving it) shows the library on its first
frame. `libraryHistoryUrl` in `stores/libraryContext.ts` maps library state to
one of the five: an open song addresses `/album/<slug>/<song-slug>` once the
song's slug is known from `songList`, a selected take addresses one segment
deeper still, `/album/<slug>/<song-slug>/take/<n>`, once that take's
`generation_number` is known among the song's loaded generations — a take
selected before its number is known keeps writing the `?gen=…` appendage
until it is (a search hit or a playlist row opened by id alone, before its
own upsert into `songList` lands — see `libraryHistoryUrl`'s own comment) —
an album that is the visible surface but has no song open addresses
`/album/<slug>`, an open playlist addresses `/playlist/<slug>` once its slug
is known from `playlistList` (`openPlaylist` in `navigation.ts` awaits
`ensurePlaylistsLoaded` before pushing history precisely so this is already
true by then; a playlist opened before its slug is known — the same rare
in-flight gap a song's legacy `?song=` form covers — falls back to `/` rather
than a broken address, since a playlist never had a legacy form of its own to
fall back to), and an album or playlist that is only the rail context behind
the wall stays on `/`. The legacy `/?song=<id>[&gen=…]` form a pre-#275/#281 bookmark
or shared link still carries is no longer read as its own entry point:
`(library)/+page.svelte` resolves it (`resolveLegacySongQueryAddress` in
`stores/libraryContext.ts` — one `fetchSong` call gets both the slug and,
when `?gen=` names a generation the song still has, its `generation_number`)
and redirects, `replaceState`, onto the canonical song or take address —
issue #284 — so Back does not step back through the query form, and an
unknown song id gets the same honest 404 treatment `openSongAddress`'s
unknown-song case does rather than a silent landing on the wall. An unknown `?gen=` on an
otherwise known song is dropped rather than 404ed — the song still exists,
and takes are pruned by ordinary cleanup, so a dead take is not the song's
own failure — but not silently: dropping it without saying so would still
hide a fact the surface knows, so the page toasts
`LEGACY_TAKE_LINK_NOT_FOUND_TOAST` once the redirect has landed on the song
address (never before — the bar must already read the new address when the
toast explains why it isn't the take one). A tab whose `history.state`
already names this exact legacy entry (a song not yet in `songList` when its
address was written keeps the query form as a same-shape fallback —
`libraryHistoryUrl`'s own comment — so a later Back/Forward can return to
one) has `onPopstate` apply that state instantly from `history.state`; the
page checks for exactly this before resolving anything itself and, when it
matches, skips its own network round trip and the overlay entirely rather
than re-resolving the same address in parallel (issue #265's S7 closed the
double-resolve this way, once removing the hand-built router guard below
made writing this check the smaller fix — no other read of `history.state`
here needed it, so it stayed a known, self-healing race until then).
`isLibraryWorkspacePath` still counts all five by pathname (it leans on
`isAlbumRoutePath`, true for `/album/<slug>` and every segment deeper, plus
`isPlaylistRoutePath`) rather than by the route group, since
`routes/+layout.svelte` sits outside `(library)` and needs the same five
addresses for its own, separate reach decision (starting the live event
stream) — the only remaining reader of it: #264's own guard,
`ensureLibraryWorkspaceRoute`, forced every collection/song open onto one of
these five paths before writing its history entry, which S7 proved
redundant and removed once `writeLibraryHistory`'s own crossing check
(`libraryRouteShape`, below) covered leaving *any* non-library route,
Settings included, not just crossing between two of the five — see the note
on `LibraryRouteShape`'s `'external'` shape in `stores/libraryContext.ts` for
why that shape has to exist for the guard's removal to be safe, and
`navigation.test.ts`'s "opening a collection from off the library route"
suite for the per-entry-point proof. A cold tab opened on an album, song,
take or playlist address resolves it against the API first (`openAlbumAddress`
/ `openSongAddress` / `openTakeAddress` / `openPlaylistAddress`): an unknown
album slug, an unknown song slug within a known album, an unknown take number
within a known song, or an unknown playlist slug is stated as such — the song
case links back to the album, the take case links back to the song, never to
the wall or the root — instead of falling back to the wall, and a known
address is written into the library's own restore state, so it is restored by
`hydrateLibraryFromHistory` — the same path a reload and Back take — and stays
present even when it is not on the first browse page. Resolving a take number
needs every one of the song's generations loaded, not just whatever the
album/song listing carried along, so `openTakeAddress` runs
`ensureGenerationsLoaded` (`stores/player.ts`) before it looks for the number;
`openPlaylistAddress` has no such second lookup — playlists carry no
pagination, so resolving the slug against the one list call either finds it
or the address is unknown. Because an address can now change the route
pattern, `writeLibraryHistory` in `stores/libraryContext.ts` is the single
owner of every library history write: SvelteKit reconciles its mounted route
tree only on a real navigation, so a write that crosses between any two of the
five route files goes through `goto` (which keeps the router in step and,
since `goto`'s own `state` lands in `page.state`, has the restore state
written onto the entry afterwards), while the frequent same-*shape* churn —
filter, sort, scroll, search cursor, moving to another song within the same
open album since #275, moving to another take of the same open song since
#281, and moving to another open playlist since #286 — keeps the cheap
synchronous write; `libraryRouteShape` (root / album / album-song /
album-song-take / playlist / external) is what the crossing check compares,
not the plain `isAlbumRoutePath` boolean, since that boolean alone cannot
tell an album address from a song or take address one or two segments under
it — a song-to-song move across album boundaries, or a take-to-take move
across song boundaries, stays the same shape and the cheap write, since only
the route-file depth decides a crossing, never which resource the address
names; a playlist-to-playlist move is the one pair the matrix never crosses
for the same reason, since `/playlist/[slug]` is a single route file
regardless of which playlist it names — every other pairing (album,
album-song, album-song-take, root) crosses against a playlist address and
vice versa, since it is a sibling route, not one of theirs. The sixth shape,
`external`, is everything outside the five library addresses — Settings,
login, a share page — and exists so that leaving one always crosses too: it
is what let issue #265's S7 delete `ensureLibraryWorkspaceRoute` (#264's
separate guard, which used to force the browser onto a library path *before*
any history write ran, so `writeLibraryHistory` never had to consider a
non-library `from` at all) without a silent regression on the one pairing
that could not tell the difference on its own — a write landing on `/`
(`openLibraryWall`, or `openPlaylist` before its slug is known) computed
`root` for both a genuine `/` and a `/settings/...` `from` before `external`
existed as its own shape, which would have taken the cheap same-shape branch
and left the router mounted on Settings' route file while the bar already
read `/`. Turning one of the crossing writes back into a bare
`history.pushState` would leave the router mounting the route it last saw
and let the next Back/Forward tear the workspace down mid-edit — collapsing
`external` back into `root` is the same mistake one level up: still a raw
write, just for a `from` no caller used to reach. Crossing writes are
asynchronous and therefore serialized, and
`currentLibraryHistoryState()` — not `history.state` — answers what the entry
will be, so a caller that writes twice in a row (open a song, then pin its
take — now itself a second crossing, queued behind the first) is not read
against a stale entry. A rename changes a song's or a playlist's slug
server-side (`unique_song_slug` / `unique_playlist_slug` in `api_helpers.py`);
the song view's own rename call writes the renamed song back into `songList`
like any other song edit, and a slug-only change on the currently open song is
what pulls its address along (`navigation.ts`, `syncSongAddressToRename`) —
this also covers a rename while a take of that song is addressed, since
`isSongRoutePath` reads true one segment deeper too — and `syncPlaylistAddressToRename`
mirrors this for the currently open playlist, subscribed to `selectedPlaylist`
(derived from `playlistList` + the open collection) rather than a song-list
upsert, since a playlist rename already writes its own row back into
`playlistList` via `updatePlaylistInList`. An ordinary edit (lyrics, prompt,
cover, entry reorder) does not re-touch either address, and a still-legacy
`/?song=…` address is left alone rather than upgraded mid-session.

The single source of navigation truth for "what collection is open" is the
leaf store `stores/collection.ts` (`openCollection: {kind: 'album'|'playlist',
id} | null`), which nothing but `openAlbum`/`openPlaylist`/history restore in
`stores/navigation.ts` and `loadPlaylistDetail` in `stores/playlists.ts`
write. `playlists.ts`'s `selectedPlaylistId` is derived from it, not
independently writable. Opening a song — whatever the entry point (rail row,
search hit, a redirected legacy `?song=` link, history restore) — always leaves the rail
context pointing at that song's album: a module-level subscription in
`navigation.ts` sets `openCollection` to the song's album whenever it doesn't
already match, so the album is never unreachable while a song is open (the
#93 defect this shell replaces). `selectedAlbumId` in `stores/player.ts` is a
separate, narrower concept — the open *song's* album, used by the editor and
queueing — never written from `openCollection`.

A collection interior (`AlbumDetailView` / `PlaylistDetailView`) shares one
header, `CollectionHeader.svelte`: cover, title, subtitle, a primary Play
action, and a single `…` menu (`CollectionMenu.svelte`). `CollectionHeader`
itself is a thin wrapper around `CollectionHeaderFrame.svelte` — the
presentational cover/Play markup with no store or auth coupling — so the
share surface (below) can reuse the identical frame with a plain title in
place of `EditableTitle`/`Breadcrumb`/`CollectionMenu`. There is no visible
Share icon — the menu's first line names the object ("Album · <title>" /
"Playlist · <title>"), then album entries are Share album · Cover… · Remove
cover (only when a cover is set) · Rename · Add to playlist · Delete album,
playlist entries are Share playlist · Save offline · Rename · Delete
playlist. The Share row embeds the existing `ShareButton` component as its
control (same toggle/clipboard/toast logic, not reimplemented); Rename
forwards to the same `EditableTitle` click affordance the title itself uses
(`EditableTitle` exposes an imperative `startEdit()` via `bind:this` for
exactly this). Album rows carry their own Play button
(`playAlbumFromGeneration` on the song's picked/first generation) beside the
existing click-to-open-song target. Album rows are songs — clicking the row
body opens the song in the editor. Playlist rows are takes — clicking the row
plays it, since the editor is an edit view and Now Playing is the play view,
and there is no click target that means both; each row shows the take's
duration and version and a `★` when it is that song's picked generation
(`PlaylistEntryResponse.version_number`/`is_picked`/`audio_duration`, sourced
from the entry's generation and its version), and the row's `…` menu carries
one action, "Open song in editor" (`selectSong` on the take's song). `CollectionHeader` and `SongDetailView`
both show a `Breadcrumb`: the collection interior is `Library › <title>`,
the song editor is `Library › <album title> › Track <n> of <m>` (falling
back to the song's own title when it is not part of a countable album
track list); each crumb before the current one is a button that jumps
straight back to that level (`openLibraryWall` / the open collection).

`PlayerBar` is transport-only: shuffle, prev/play/next, a 44px cover,
title/subtitle, the seek bar, and a "Now Playing" word-button with an
up-chevron. That button is a dialog trigger while Now Playing would open full
screen and a plain disclosure toggle while the docked panel is showing —
pressing it again puts the panel away (issue #140), which is why
`TransportBarFrame` takes `nowPlayingDocked` and drops `aria-haspopup` for it.
The bar itself steps aside under the full surface on every viewport: "one
player, never two" means the full-screen Now Playing carries the only
transport, so `PlayerBar` renders no `TransportBarFrame` while
`nowPlayingSurface` is `'full'`. `--player-height` is the single fact behind
that: it means "the room the transport bar takes right now", and `app.css`
owns every one of its values — the resting 88px, the 64px compact/coarse
overrides, and `html[data-now-playing='full'] { --player-height: 0px }` for
while the app's bar is hidden. That last rule ties with
`html[data-pointer='coarse']` on specificity, so it sits directly below it and
wins on source order; `+layout.svelte` owns only the attribute it keys on. Everything that reserves space for the bar — the shell
rows, `ToastContainer`, `QueueStreamFeedback`, the editor's bottom padding,
the collection views and Now Playing's own sheet — follows from it instead of
carrying its own exception. A share page keeps its bar and never carries the
attribute, so `SharedFooter`'s `var(--player-height, 88px)` stays as it was. Because the bar unmounts, it cannot own the Web Audio graph: an `<audio>` element can be passed to `createMediaElementSource` exactly once, and closing the context that owns that source routes the element's output into a dead graph for the rest of the session — playback that still reports itself as playing but makes no sound. `audioPlayer.svelte.ts` therefore owns the context and the analyser for the element's whole life (`getAnalyser`, `resumeAudioGraph`, closed only in `destroy()`, built lazily so a device that never draws a visualizer never routes its audio through Web Audio), and `TransportBarFrame` only borrows the `AnalyserNode`. The transport chrome and visualizer live in `TransportBarFrame.svelte`, a
presentational component driven by props plus the `audioPlayer` singleton
directly (never a store) — `PlayerBar` supplies the app's idle-state copy,
store-derived prev/next, and its own media-session position/playback-state
wiring; the share surface's `SharedCollection.svelte` drives the same frame
from its own `SharePlayback` owner instead, with no media-session wiring of
its own. `idlePlayTarget` (in `stores/player.ts`)
now takes the single `openCollection` instead of the old
`albumId`/`songId`/`playlist` tuple, so a song open inside an album keeps
that album as the idle Play target instead of falling back to the library
pool. Per-track queue-skip feedback (`QueueStreamFeedback`) and the take-pool picker
live inside the `NowPlaying` surface, not the bar; shuffle is transport and
sits in both (issue #141), labelled from the single `shuffleLabel` derived so
the two can never disagree about the scope they would shuffle. At ≤640px viewport width or any coarse pointer, the bar collapses to
one 64px transport row: cover, title/subtitle, a 44×44px play/pause button,
and the Now Playing chevron — Previous/Next and the seek timeline are not in
the bar at that size, since Previous/Next live inside the `NowPlaying`
overlay and the timeline becomes the decorative `.mobile-progress` line
along the bar's top edge. `PlayerBar` tracks this breakpoint in script via
`subscribeCompactLayout` (its own media string, not the shared 768px
`COMPACT_LAYOUT_MEDIA`) and applies one `.mobile-transport` class, rather
than duplicating the ruleset under both a `@media` block and a
`[data-pointer="coarse"]` selector. `RailDrawer.svelte` and
`CollectionMenu`'s dropdown share one focus trap, `lib/utils/focus-trap.ts`
(Escape closes, Tab/Shift+Tab wrap at the edges).

**The queue is its own owner, separate from navigation.** `queueContext` in
`stores/player.ts` is what is playing; the open album or playlist is where the
listener is browsing, and neither reads the other. A playlist queue therefore
carries its own `PlaylistQueueSource` (`{ id, title }`), captured when the
queue is built the way the album arm carries `albumId`, so leaving a playlist
mid-track cannot rename — or unname — the queue Now Playing is showing.
`playPlaylistFrom(playlist, startIndex)` is the one public way a surface starts
a playlist — a wall tile calls it directly, a row through `playPlaylistEntry`,
which adds the pause/resume of an entry that is already playing — and it owns
the `setShuffle(false)` reset that makes a picked entry honest: a row means
"play from here", which no leftover shuffle from a previous queue may reorder.
The idle transport Play keeps its own path, since it must keep the listener's
shuffle setting. Navigation reads playback only through `idlePlayTarget()`
("what would Play start"), never as a queue.

Queue-stream admission is owned by `queue_stream_api.py`: both authenticated
snapshot endpoints prepare the count-windowed sources after releasing the
request session and before their build can reach ffmpeg. The product cap is six
hours of measured audio; a longer queue receives 422 rather than a shortened
stream. `queue_streams.py` derives its 336-second ffmpeg timeout from that cap,
the measured-rate policy, and its reserve; `tests/test_queue_streams.py` pins
the formula and proves that both endpoints reject an overlong queue before
ffmpeg runs.

Escape is also a global "one level up" shortcut, mounted once in
`+layout.svelte` (`lib/utils/escape-level-up.ts`): from a song it goes to
that song's collection interior, from a collection interior it goes to the
library wall, and it is a no-op at the wall. It yields — does nothing —
whenever an editable element has focus (an input, textarea, or
contenteditable) or an overlay is open, so it never fights a component that
already owns Escape for its own popover. "Overlay open" is detected as any
element in the document carrying `aria-modal="true"` (dialogs, drawers, the
`CollectionMenu`/`SongMenu`/`PlaylistPicker` popovers, the mobile `EditorSheet`
for Recipe) or `data-escape-overlay="true"` for a
popover whose ARIA role does not permit `aria-modal` (the `TakeMenu` overflow
menu's `role="menu"`); either marker is the
whole contract, checked live in the DOM rather than tracked separately. A
popover's own Escape handler runs in the document capture phase and may
unmount the popover before the global bubble listener ever inspects the DOM,
so `hasOpenOverlay()` alone is not enough — every popover Escape handler also
calls `event.preventDefault()`, and `shouldHandleGlobalEscape` yields whenever
`event.defaultPrevented` is set, since that flag survives the whole
capture/target/bubble dispatch of the one `Event` regardless of what the DOM
looks like by the time bubble phase reaches `window`.

Library context — the open collection, filter, search, sort, loaded page,
scroll, selected song/generation — lives on `history.state`
(`kind: 'songmaker'`) so browser-back and the rail's Library link restore the
same view; the Library link always pushes a fresh entry showing the wall
while leaving the open collection in the rail (GitLab-style: it persists
until another collection replaces it). Legacy history blobs from the old
Studio/Listen section shape fail validation and fall back to the library
root.

| Layer | What | Key files |
|-------|------|-----------|
| Routes | Pages: the `(library)` route group (main view, album address `album/[slug]`, song address `album/[slug]/[song]`, take address `album/[slug]/[song]/take/[n]` — issue #281, playlist address `playlist/[slug]` — issue #286, one shared `LibraryWorkspace` mount — issue #276), login, setup, settings, public share pages (`share/[slug]`, `share/playlist`/`song`/`gen`) | `src/routes/` |
| Components | Editor (`components/editor/`: `EditorHeader`, `SongMenu`, `RecipeChips`, `RecipePanel`, `EditorStacked`, `WriteColumn`, `TakeStrip`, `TakesList`, `TakeMenu`, `EditorSheet`), `ConfirmDialog` (generic Save/Discard/Cancel-style confirm), PlayerBar/`TransportBarFrame`, `NowPlaying`/`NowPlayingFrame`/`NowPlayingQueue`/`NowPlayingTake`, LibraryWall, `CollectionHeader`/`CollectionHeaderFrame`/Menu, shell/Rail, CoWriterPanel, `components/share/` (`SharedCollection`, `SharedFooter`), etc. | `src/lib/components/` |
| Stores | Reactive state: player, collection, libraryContext, navigation, editor, recipe, filter, jobs, auth, settings, ui | `src/lib/stores/` |
| API client | Typed HTTP client, mirrors `songmaker_cli.api_models` | `src/lib/api/client.ts`, `types.ts` |

The API client and `types.ts` are the frontend's contract with the backend.
`scripts/generate_types.py --check` derives the browser-facing models from the
registered FastAPI routes' response and body annotations, follows nested
Pydantic models, supplements them with the exported `api_models`, and verifies
their TypeScript interfaces. The backend-only `/api/internal/` worker
protocol is the sole excluded route role. When a routed model changes,
regenerate `types.ts` and run the check.

Frequent studio actions (theme toggle, pick/keep, playlist reorder/remove, new album/playlist, playlist-picker add) share the `[data-hitbox='frequent']` primitive in `frontend/src/lib/styles/hitbox.ts`. The visible glyph or inset face stays compact; the control's hitbox is 24×24px on a fine pointer and 44×44px when any pointer is coarse (including hybrid mouse+touch devices). Labelled controls (album/playlist header Play, the editor's Co-Writer/Recipe toggles and Generate, the compact Write | Takes tabs, Now Playing's Queue | This take tabs, the library search field) take the sibling `[data-hitbox='text']` instead: it raises the height to the same touch target and leaves the width to the label and the layout, since forcing the square would clamp a width the layout owns and `data-hitbox-face` — a fixed 24/44px box — cuts straight through a word (#163). A face is only ever drawn on an icon-only control. PlayerBar and the share surface's transport/Now Playing frames are out of this primitive's scope.

A selected song stays on `SongDetailView`, which composes the `components/editor/` set (epic #98 slice 2). One header row (`EditorHeader`) is identical in every state: cover, editable title, and `SongMenu` (Share song / Rename / Add to playlist / Delete song) on the left; the two independent, stackable views `Co-Writer` and `Recipe` as toggles, a divider, and the single `Generate` action on the right — never a second toolbar row, never a duplicate model/count control next to Generate. `RecipeChips` (Model · Takes · BPM · Duration · Key · Voice · Seed · LM · DIT · Repaint) sit under the header and expand into `RecipePanel`'s Sound / Text / Reproduce groups with a Preset row on top; model, takes-per-generate, and any repaint/cover source are session state in `stores/recipe.ts`; version-scoped edits (lyrics, prompt, BPM, duration, key, generation params) stay in `stores/editor.ts`. Below that, `subscribeCompactLayout` (the same single switch used everywhere else) decides the Write/Takes layout: desktop shows `WriteColumn` and `TakesList` as two simultaneous columns with no tab switcher; compact shows a `Write | Takes` tab pair, defaulting to Takes. How many columns that desktop layout can actually stand up is a separate question, and the editor asks itself rather than the viewport (#185): everything under the header sits in `.editor-body`, a `container-type: inline-size` size container named `editor`, and the write/takes pair and the Co-Writer's chat/lyrics/take-strip row go two- and three-up only above `@container editor (min-width: 680px)` — two 20rem columns plus their 1.2rem gap (659.2px), rounded up to a round 680. `RecipePanel`'s three equal groups need no threshold at all and pack with `repeat(auto-fit, …)`, which also holds inside the compact sheet, where there is no such container. So docking Now Playing, which takes 400px out of `main`, costs the editor a column instead of pushing a take row's actions outside it, and no editor stylesheet asks the viewport anything but whether the shell is compact (`max-width: 768px`). The container deliberately starts below the header: a size container is also the containing block for `position: fixed` descendants, and the header carries two — `SongMenu`'s full-viewport backdrop and the compact Generate bar. The header instead keeps its room intrinsically, giving `.detail-identity` a flex basis so the views and Generate wrap onto their own line rather than squeezing the title box and breadcrumb to a sliver. Turning on Co-Writer replaces the Write/Takes area with `WriteColumn`'s Co-Writer mode (Chat + Lyrics + a `TakeStrip` of ★/♥-badged takes side by side on desktop, Chat | Lyrics tabs with no take strip on mobile) regardless of the Write/Takes tab; on compact it opens as an `EditorSheet` instead, so the `Write | Takes` tabs stay reachable underneath. When Co-Writer and Recipe are both open on desktop, the full `RecipePanel` would push the chat column below the fold, so `RecipeChips`' expansion renders `EditorStacked` instead — one summary row per group (Sound/Text/Reproduce) with an "Edit" button that swaps in the full panel on demand. `TakesList` groups takes by version (newest first), shows a draft banner when the draft differs from the latest saved version, and a generating row while a `generate` job runs, labelled with the version actually generating (`song.version_count`, not the draft's next-version number); each take's `TakeMenu` (`role="menu"`, `data-escape-overlay`) opens with "Take · vN · k" as its first row, and each version group header has a "Delete version…" action (`handleDeleteVersion`, with its takes, behind a confirm). Clicking a take row plays it and opens Now Playing straight on its judging panel (`stores/player.ts#playTakeAndShowNowPlaying`; see the Now Playing section below). A take clicked from the Co-Writer `TakeStrip` always just plays — it never opens Now Playing. Generate is enabled from the draft (unsaved lyrics/prompt), not the last-saved song, so a freshly written song can generate before its first save; `handleSave` and `handleDeleteVersion` in `stores/editor.ts` fail loud (reject instead of swallowing) so a caller — Generate, the song menu's "Save version", or the unsaved-draft guard below — never proceeds past a failed save. Switching or leaving a song with a dirty draft (a rail row, previous/next, the breadcrumb, Escape, or the Library link — all routed through `stores/navigation.ts`) is guarded: the navigation is parked in `pendingDirtyNavigation` until `SongDetailView` resolves a Save / Discard / Cancel confirm (`ConfirmDialog.svelte`, a generic two-or-three-action dialog). `guardDirtyNavigation` in `stores/navigation.ts` is the sole gatekeeper for this — every entry point that changes `selectedSongId` (`selectSong`, `selectNeighborSong`, `backToCollection`, `openLibraryWall`, `revealPlayingSong`, and `revealSharedTake` for LibraryWall's shared-take share-inventory row, which pins a generation alongside the song switch as one guarded action rather than as a follow-up step after — issue #265's S7 fixed a park-then-pin-against-the-old-song gap here, found in #264's review) routes through it rather than re-implementing the check inline. Browser Back/Forward is the one exception: `popstate` fires after the history entry has already changed, so there is no pending navigation left to cancel back into — a dirty draft is auto-saved instead before the popstate state is applied, with a failed save surfacing a toast but never blocking the already-committed navigation. Opening a song from the album interior (the track list, no song open yet) always pushes, since the visible surface changes from the list to the song editor. Once a song is open, selecting another song already inside the open collection (list clicks, previous/next) replaces the current song history entry and keeps the active Write/Takes tab; selecting a song outside the open collection (a search hit, a deep link) pushes, since the rail context changes with it. Back from the second track of an opened album therefore lands on the album, not the wall. Back leaves the song for the rail's open collection (`backToCollection`), or the wall if none is open. Go to song from Now Playing opens the song and pins the rail context to its album, then opens Takes on the playing generation. A take row is a body (play glyph, `vN · take k`, duration, score pill, expiry/archived badge) and an action cluster (★ ♥ …), and only the body carries the row's own text: the row wraps the cluster onto its own line as soon as the body would be squeezed below its floor, so a tap anywhere on the row's text plays the take instead of toggling Pick or Keep — which is what a 320px row did while the 44px targets sat across its centre. The pill is the take's headline score: the listener's rating when they gave one, otherwise the highest-ranked automatic score the take actually carries, so a take that only some scorers have reached still shows what is known instead of nothing. `utils/scores.ts` owns that ranking as one table (`SCORE_METRICS`: rating, lyrics sung, dynamics, quality, enjoyment, coherence — never BPM, which names a tempo rather than a judgement) together with each metric's label and how it is written out, and both take surfaces read it: the row shows the first metric a take carries, `NowPlayingTake`'s Scores grid lists every one of them under the same names and in the same order (plus BPM, which colours itself from its deviation rather than from a threshold). The panel writes each score on the scorer's own scale ("87%", "8.15"); the pill, which shows a single unlabelled number, puts every metric on the same 0–100 scale (a 0–10 score ×10, rounded) — an 8.15 beside an 87 would read as the worse take — while `scoreColor` keeps judging the raw value against its own threshold. Settings and Admin use that same compact media: a one-control section/tab selector and stacked action rows, so every control stays reachable at 320px without sideways scroll.

**One click rule for rows (issue #140).** A row click opens what the row
stands for; a ▶ beside it only plays. A song row opens the editor — in the
album interior it carries a ▶ that plays that song's pick, while the rail's
rows carry no ▶ at all. A take row — the editor's takes list, a playlist
interior, the rail's playlist rows — plays the take *and* shows Now Playing on
This take, because judging a take is what a take row is for. `stores/player.ts`
holds that as one action, `playTakeRow`, which every take row reaches through
its own start of playback (`playTakeAndShowNowPlaying` for a generation in the
editor, `playPlaylistEntryAndShowNowPlaying` for an entry of the open
playlist). **A row body never stops the music**: the take a row stands for is
left running and a paused one resumes where it stands, so clicking the row that
is already loaded only brings up the panel. Pausing belongs to the transport
and to a ▶ that stands for the playing take — the playlist row's, which calls
`playPlaylistEntry`; the editor's take rows have none, and the Co-Writer
`TakeStrip`'s play chip (`playTake`) plays without ever opening Now Playing.
The docked panel is what makes the rule affordable on desktop — the take is
judged beside the playlist rather than over it; below the dock threshold Now
Playing takes the screen as before. Share pages stay play-only: a public listener has no editor and no
judging panel. "Go to song" inside Now Playing remains the one bridge from
what is playing into the editor.

Now Playing (`NowPlaying.svelte`) has two surfaces and one instance, mounted by `routes/+layout.svelte`: **docked**, a `NOW_PLAYING_DOCKED_WIDTH_PX` (400px) flex column of the desktop `.shell-row` beside the rail and the workspace, and **full**, the modal surface covering the viewport. `stores/player.ts` owns which one shows — `nowPlayingSurface: 'closed' | 'docked' | 'full'`, with `nowPlayingOpen` derived from it — and `openNowPlaying` / `closeNowPlaying` stay the only entry points; `expandNowPlaying` / `dockNowPlaying` switch between the two desktop surfaces and remember the choice in `stores/playbackSettings.ts` (`nowPlayingDesktopSurface`, defaulting to docked), so the next open lands where the listener last was. Whether a docked panel fits is one fact, `nowPlayingDockable`, which the layout reports by reading `NOW_PLAYING_STACKED_MEDIA` as "cannot dock" — below the stacking breakpoint `NOW_PLAYING_STACKED_MAX_PX` (1099), or any coarse pointer, and there is no panel. Docking briefly needed a threshold of its own (1440) because the editor read the viewport: giving the panel 400px pushed a take row's Pick/Keep/… actions outside `main`, which is `overflow: hidden`, so they became unreachable rather than scrollable (browser gate, 2026-08-23). Since #185 the editor answers to its own width instead, so the cost of docking is a column it folds, and one width decides both — wide enough for Now Playing's three columns is wide enough to stand them beside the workspace. Losing the room turns a docked panel into the full surface rather than closing it. Now Playing opens from `PlayerBar`'s Now Playing button (which also closes the rail drawer) or by clicking a take row — `TakesList`, the playlist interior, the rail's playlist rows — which opens it straight on the This-take judging panel instead of the Queue panel — the panel request is the same `nowPlayingPanel` store, read once by `NowPlaying` on mount since the layout remounts it fresh on every open. `NowPlaying` wraps `NowPlayingFrame.svelte` — the surface shell, cover/transport/shuffle column, and lyrics column, driven by props plus `audioPlayer` directly — and supplies its own two-tab (Queue / This take) right panel via a snippet; the share surface supplies a queue-only right panel to the same frame instead.

The frame's `surface` prop is what separates the two. Full is `role="dialog"`, `aria-modal`, focus-trapped, and carries the transport (progress, shuffle, prev/next, play). Docked is `role="complementary"` with no `aria-modal`, no focus trap and **no transport at all** — the transport bar stays visible beside it and keeps carrying seek, shuffle, prev/next and play, so there is never a second player. Escape follows from that: the full surface is modal and answers the key itself through `escapeNowPlaying` (back to the docked panel wherever one fits, otherwise closed), while the docked panel deliberately reaches the global level-up in `utils/escape-level-up.ts`, which gained a `'now-playing'` level above song/collection/wall. Closing hands focus back to the transport bar's Now Playing button; because the full surface hides that bar, `registerNowPlayingTrigger` delivers the pending focus when the bar remounts rather than focusing a detached element. The frame refocuses itself on every surface change, since expanding or collapsing rebuilds the controls the listener was on. The frame itself knows nothing about whether a bar is showing: its full surface simply reserves `var(--player-height)` at the bottom, which is zero in the app and 88px on a share page. Three columns at ≥1100px — cover/transport, the lyrics column, the right panel — stack into one column with the right panel as a bottom sheet below that width or on coarse pointers; the sheet seeds its open state once per mount, so a take-row click still lands on the This-take sheet instead of a closed trigger labelled "Queue". The Queue panel (`NowPlayingQueue.svelte`, whose one optional `takePool` prop pairs the selected pool with its handler, so a queue can neither offer a picker that chooses nothing nor hide a pool it is built from; it is given by the library queue alone, and the panel is told what is playing by `contextLabel` rather than being handed the queue context to interpret — which is what keeps the share surface from importing the app's player store) renders `stores/player.ts#buildQueueViewModel`, a pure projection of the active queue context (library/album takes or a playlist's entries) into ordered rows labelled `vN · take k` with current/up-next; the pool trio `Picks → + Keeps → All takes` (`stores/playbackSettings.ts`, stored `keeps` migrates to `mix`) shows only for the library context. Clicking a row calls `jumpToQueueIndex`. The This-take panel (`NowPlayingTake.svelte`) is Now Playing's only write surface: pick/keep/rate/pin-seed/re-score route through `stores/takeActions.ts`, the single mutation owner for a take's judged state, shared with the editor's `TakesList`/`TakeMenu` — pick/keep/rate/pin-seed via `contexts/generation-actions.ts#takeActionsFor`, re-score by calling `rescore` directly, since Now Playing has no such context and a second path to the same mutation is exactly what #132 removed. `rescore` (issue #132) posts `POST /api/generations/{id}/score` and hands the job to `stores/jobs.ts#trackJob`; the job's own completion refreshes the song, which is what puts the recomputed scores and `whisper_cues` on the take. Because the server does not deduplicate scoring jobs, the take is marked as re-scoring from the moment the request leaves rather than from the moment a job comes back, and `rescoringTakeIds` unions those in-flight requests with the tracked `score` jobs — every surface reads it for the pending state and to refuse a second run. The entry itself sits in the editor take's `…` menu and, always available, next to pin-seed in the This-take panel: a take scored before word timestamps has segment-only cues, so re-scoring is what buys per-line timing even when cues already exist. Repaint and Cover are named actions directly on every editor take row and in This take; they set the source and mode in `stores/recipe.ts`, then the Now Playing entry closes the panel and navigates to the song. A Repaint or Cover result names its source take, linking to it while the source exists; the closed Recipe chip and Generate button name the active mode, and the open panel says that it uses the current editor lyrics and style. `SongDetailView` applies `pendingSource` only once its `song_id` matches the song actually open, opens Recipe in the chosen mode, and drops it if the dirty-draft guard's confirm is cancelled instead of applying it to the song the user stayed on. Archived takes cannot be sources; cover-source authorization remains in the existing panel and API flow. It resolves the playing generation against `songList` component-locally (`$derived` + `$effect` calling `ensureGenerationsLoaded`) and stays absent until resolved. Sung-vs-lyrics deviations tokenise both texts with `utils/lyrics-normalize.ts` (the #45 contract) and diff them word-wise via `utils/diff.ts#computeDiffByKey`. Normalization casefolds — not merely lowercases — so a German "Straße" and a Whisper transcript's "strasse" register as the same token (issue #133); JS has no native `casefold()`, so the module hand-covers the small set of Unicode full-case-folding entries (German eszett, Greek final sigma) that diverge from `toLowerCase()` for text this product's lyrics can plausibly contain.

The lyrics column (`NowPlayingLyrics.svelte`) follows playback once the playing take carries `whisper_cues` (#45, contract confirmed on #52, word timestamps added on #142). `utils/lyrics-align.ts#alignLyricsToCues` takes one of two paths, chosen by what the take was scored with. **Word path** — a take scored with word timestamps carries a word stream (`cue.words`); lyric lines are walked in order and each takes the best-matching run of still-unconsumed words. The interval is then trimmed to the words of that run which take part in a matching block against the line, so a line always starts on its own first sung word even when the run had to begin on foreign words. The search window starts `WORD_STREAM_LOOKAHEAD` (24) words past the previous match and grows a step at a time until the take offers a reading of the line or the stream ends, so a long adlibbed or mistranscribed stretch cannot hide the lines behind it; assignment stays forward-only. A run is handed to a line only while no other line still in play reads that run just as well (#52's rival rule, applied to lines): in play means from the floor onwards — every line the take has not moved past, above this one as well as below, the same set the cue window path competes over — so a group of lines too alike to tell apart leaves the run to none of them instead of to whichever comes last. A line carrying the same text is never a rival, since the take simply sings those words again. The converse is checked too: every phrase that contains the run — the run extended to the left, to the right, or both, so a line may be the opening, the tail or an interior slice of it — is read back, and any line further down that reads such a phrase at `MIN_RATIO` and better than this line does has a claim on those words; if taking them here would leave that line with no rendition of its own, this line steps aside — that is what stops a line from swallowing the opening of a line below it, adjacent or not, while a line that has a rendition elsewhere never blocks it. Successive renditions of identical or nested neighbouring lines are therefore handed out in order rather than treated as a tie. **Cue window fallback** — a take scored before word timestamps carries only segment cues, and a segment follows breathing pauses rather than line breaks (the Nachtstrom take: 33 segments over 56 lines), so cues are walked in playback order and each takes the best-matching run of up to `MAX_WINDOW_LINES` (3) still-unconsumed lines. Every line of that run carries the whole cue span and they light together: nothing in such a take says where inside a cue one line ends and the next begins, and #45 forbids inventing it — only a re-score (#132) buys real per-line timing. Both paths share one accept rule: text is normalised by `utils/lyrics-normalize.ts`'s token rules, lines are split on `/\r?\n/` and blank plus `[section]`-marker lines never align, a lyric line of at most `VERBATIM_MAX_TOKENS` (2) words is only lit where the transcript carries exactly that text (a character ratio cannot tell "yeah" from a sung "year"), the winner must clear `MIN_RATIO` (0.72), and it must beat every rival by `AMBIGUITY_MARGIN` (0.12) — a rival being a candidate that overlaps neither the winner nor any repeat of it, those repeats being read off the stream rather than off the candidates the search happened to collect. A repeat is a run of the same length that reads the winner back; where the lyrics carry a line more than once, `REPEAT_MIN_RATIO` (0.88) tolerates the slips Whisper makes between two renditions of it ("…until the mornin" against "…until the morning"), and of several renditions a line takes the earliest still in reach, leaving the later ones to the lines below. For a line the lyrics carry once, and for lyric lines themselves in the cue window path, only word-for-word repetition counts — two readings that close are the ambiguity #45 refuses to guess at, and near-identical lyric lines are different lines, not transcript slips. Overlapping candidates are one rendition seen through a shifted window, and a repeat of the same words is not independent evidence of where a line was sung, nor is a shifted window around such a repeat; a chorus line is therefore never blocked by its own repeats and monotone consumption decides which rendition each of them takes. A differently-worded reading elsewhere in the take does rival it. Anything short of the rule leaves the line dark; a missed highlight is a gap, a wrong one is a lie. Similarity is `utils/sequence-matcher.ts`'s `SequenceMatcher`, a faithful TypeScript port of Python's `difflib.SequenceMatcher` (including the ≥200-char autojunk popular-element filter). `scripts/lyric_alignment_golden.py` is the reference: it holds both the Python-computed ratios and a Python reference implementation of both alignment paths, and `lyrics-align.fixtures.json` pins the TypeScript side to its intervals fixture by fixture, including the cases that must stay dark. Alignment no longer runs on the main thread: `services/lyricsAlignment.svelte.ts` owns one worker and hands it one take at a time (`utils/lyrics-align.worker.ts` is transport only, the pure `alignLyricsToCues` is unchanged), the column shows static text until the answer for the take now playing arrives, later takes supersede earlier ones, and a worker that cannot load falls back to aligning on the main thread — the same on the share surface, whose `$state`-held cues are snapshotted before they cross the boundary. `activeLyricLineIndices` returns every line covering `audioPlayer.currentTime` and none in a gap, and the first of them is scrolled into view (instant under `prefers-reduced-motion`, smooth otherwise). Lyrics longer than the column scroll inside it; the box fades its bottom edge while more text follows and drops the fade once the last line is reached, so the docked panel's cut through a line reads as "scroll for the rest" rather than as broken text, and `scroll-padding` keeps the line that follows the audio out of the faded strip. Cues and transcript come from the take resolved against `songList` (`playingGeneration`, not `info`, per the #45 amendment), so a thin library-pool item stays on static lyrics until `ensureGenerationsLoaded` fills in its real `whisper_cues`; a take with `whisper_text` but no cues at all (scored before #44 landed) shows a "Lyrics aren't synced for this take." note alongside the static text — the column states what is true and nothing more, since it renders for a public listener too; the contextual "Re-score this take to follow the lyrics." shortcut for that state lives in the owner-only This-take panel, next to its always-available Re-score entry. `SharedCollection.svelte` passes the playing take's cues to the same `NowPlayingFrame` prop (`SharePlayback.currentCues`, read off the share payload rather than off a stream manifest, so lyrics follow in both classic and stream mode), so a public listener gets the same following lyrics as the app — there is no share-only lyrics path. Because a share stream's manifest redacts `lyrics` (`queue_streams.py#public_queue_stream_manifest`), the frame takes the text from a `lyricsText` prop, symmetric to `lyricsCues`, whenever `info` cannot carry it. A take scored before word timestamps still falls back to static text exactly as in the app; the share surface just never offers re-score, which is an owner action — the lyrics column it shares with the app carries no action at all.

The public share pages (`/share/[slug]`, `/share/playlist/[slug]`,
`/share/song/[slug]`, `/share/gen/[slug]`) render on the same collection
surface as the logged-in app instead of a hand-rolled listening UI: each
`+page.svelte` fetches its `/shared/*` payload, adapts it with
`lib/share/sharedCollection.ts` (`fromSharedAlbum`/`fromSharedPlaylist`/
`fromSharedSong`/`fromSharedGeneration` → one `SharedCollectionView`; a song
or take share becomes a one-track collection; `playableTracks()` drops rows
whose `audio_url` is `null` — a listener sees a finished album, not disabled
"--" rows), and renders `lib/components/share/SharedCollection.svelte`. The
four `/shared/*` payload shapes are not described twice:
`scripts/generate_types.py` emits `SharedAlbumPayload`,
`SharedAlbumSongPayload`, `SharedSongPayload`, `SharedGenerationPayload`,
`SharedPlaylistPayload` and `SharedPlaylistEntryPayload` into
`lib/api/types.ts` from the Pydantic share models, and
`sharedCollection.ts` re-exports those types instead of keeping its own
copies — a new field on a share response reaches the surface through one
contract. Each payload carries its take's `generation_id`,
`audio_duration`, lyrics and `whisper_cues` (the same fields Now Playing
reads from a generation payload, assembled by
`api_models/songs.py#share_pick_media`) and nothing else: no transcript,
no scores, no sibling takes, no owner — pinned by an exact-key-set test
in `tests/test_sharing.py`. A `SharedTrack` therefore knows its own
duration, lyrics and cues without a stream manifest.

`SharedCollection.svelte` composes `CollectionHeaderFrame` (read-only, no `…` menu),
`TransportBarFrame`, and `NowPlayingFrame` with a queue-only right panel, plus
`SharedFooter.svelte` (Powered by · Impressum · Datenschutz ·
Nutzungsbedingungen, its `LegalContent` overlay carrying `aria-modal` for the
Escape contract above). Playback is owned by `lib/share/sharePlayback.svelte.ts`
(`SharePlayback`), never `stores/player.ts` — a `share-import-boundary.test.ts`
grep gate enforces that nothing under `lib/share/`, `lib/components/share/`,
or the four share routes runtime-imports `stores/player`, `navigation`,
`editor`, `takeActions`, or `auth`. `SharePlayback` drives the shared
`audioPlayer` singleton directly: stream mode reuses `audioPlayer.loadStream()`
against a manifest the page fetches (`fetchSharedAlbumStream`/
`fetchSharedPlaylistStream`; song/take shares have no stream endpoint and stay
classic), classic per-track playback uses `audioPlayer.loadUrl(info, url)` —
the URL-owning sibling of `load()` that lets classic share recovery/probing
work against a `/shared/.../audio/...` URL instead of the app's
`/audio/{mp3_path}` convention. `SharePlayback.start()` installs its own
`AudioPlayerCallbacks` via `audioPlayer.swapCallbacks()` (`onAuthLost: null`,
`onCurrentChange` only resyncing its own queue position — never the app's
media-session metadata or `windowEnded` store) and `stop()` calls
`audioPlayer.restoreCallbacks()` then `audioPlayer.unload()`, so a logged-in
tab that navigates into a share route and back never carries share state (or
loses the app's callbacks) into the app. Shuffle on share is share-local
(never touches `queueShuffleEnabled`) and, per product decision, switches
playback to per-track `loadUrl` over a shuffled permutation while enabled,
returning to stream mode when disabled. Rows and the queue show a duration
in both modes — from the stream manifest while one is in play, otherwise
from the payload's `audio_duration` — and Now Playing follows the lyrics in
both, because `SharedCollection` hands the frame the playing track's own
lyrics and cues (`lyricsText`/`lyricsCues`) rather than relying on `info`,
whose `lyrics` a public stream manifest redacts. A take scored without
`whisper_cues` renders static lyrics, the same fallback the app uses.

### Backend (`src/songmaker_cli/`)

| Layer | Responsibility | Key files |
|-------|---------------|-----------|
| HTTP | FastAPI app, CORS, security headers, body size limit, gzip compression (JSON/text/JS by Content-Type, never binary media or a `Content-Range` response, proper `Accept-Encoding` q-value negotiation), SPA fallback | `server.py`, `middleware/gzip.py` |
| Auth | Session dependencies, login/setup/logout, password change, brute-force protection | `middleware/auth.py`, `auth_api.py`, `auth.py` |
| API | REST endpoints split by domain: albums, songs, generations, playlists, library search/shares, LoRAs, live co-writer chat, legacy chat, settings, admin | `api.py` (aggregator), `album_api.py`, `song_api.py`, `generation_api.py`, `playlist_api.py`, `library_api.py`, `lora_api.py`, `conversation_api.py`, `chat_api.py` (legacy), `settings_api.py`, `admin_api.py` |
| Helpers | Shared access checks, rate limiting, slug generation | `api_helpers.py` |
| Models | Pydantic request/response with `from_orm()` | `api_models/` |
| Jobs | Background generation + scoring runners | `jobs/` (package: `_runtime.py`, `generation.py`, `scoring.py`, `model_lifecycle.py`) |
| Worker | arq-based job queues (music + scoring), scheduler dispatch | `music_worker.py`, `scoring_worker.py`, `worker_base.py`, `scheduler.py`, `arq_pool.py` |
| ACE-Step worker pool | Peer containers serving ACE-Step over HTTP/SSE | `src/acestep_worker/` (top-level package, separate from `songmaker_cli`) |
| Generation post-process | Decode worker WAV → splice → master → MP3 | `generate.py`, `jobs/generation.py:post_process_generation` |
| Config | ACE-Step config building (merges defaults + user + song params) | `config.py` |
| DB | SQLAlchemy ORM models, query functions, engine init | `db/` |
| Scoring | Fault-isolated pipeline: text accuracy, dynamics, BPM, silence, spectral, aesthetics, coherence | `scoring/` |
| Co-writer | Dispatches the selected Claude, Grok, or Codex provider; the judge is configured separately | `cowriter/dispatch.py`, `cowriter/catalog.py`, `cowriter/*_adapter.py` |
| Conversation | Conversation-scoped co-writer turns, history, and durable memory | `conversation_api.py` |
| MCP | Claude's stdio tool server plus shared tool schemas and in-process execution for Grok/Codex | `mcp_server/`, `cowriter/tools.py` |
| CLI | Thin HTTP client to the same API | `main.py`, `cli_client.py` |

The Co-Writer dispatcher owns provider transport choice. Claude turns use its
MCP-enabled CLI; Grok chooses its subscription CLI when the mounted
`auth.json` carries a token and otherwise uses `XAI_API_KEY`; Codex chooses
its subscription CLI when the mounted `.codex/auth.json` contains a nonempty
`tokens.access_token`, otherwise `OPENAI_API_KEY`. A selected Grok or Codex
CLI failure remains on that path for the turn. Their adapters convert bounded
CLI streams to chat events; the Codex transport's security and stream-gate
contract is documented in `docs/security.md`.

### Engine packages (`src/`)

| Package | Purpose |
|---------|---------|
| `acestep_engine` | HTTP client for the ACE-Step server (generate, poll, model info) |
| `audio_engine` | Mastering chain (multiband compression, stereo widening, LUFS normalization, MP3 encoding), WAV I/O |

## Data Model

```
User (username, role: admin|user, bcrypt hash)
  ├── Album (title, artist, share_slug?, is_shared — owned via created_by)
  │     └── Song (title, slug — unique per album, track_number, share_slug?, is_shared)
  │           ├── Version (lyrics, prompt, BPM, key, duration, generation_params)
  │           ├── Generation (MP3, seed, status, whisper_text, whisper_cues?, model_mode, share_slug?, is_shared)
  │           │     ├── Score (scorer, value JSON)
  │           │     └── Rating (0-100, notes)
  │           └── ChatMessage (role, content — per-song conversation history)
  ├── CowriterUserMemory (durable co-writer notes; survives new conversations)
  ├── ResourceEventCursor (per-user monotonic high-water mark)
  ├── ResourceEvent (30-day durable invalidation history; historical IDs, no resource FK)
  ├── Job (type, status, progress, error, queue_position)
  └── AuditLog (action, resource_type, resource_id, detail)

Also: UserSession, LoginAttempt, Playlist (slug — globally unique, share_slug?, is_shared), PlaylistEntry,
      GenerationPreset, AvailableModel, RateLimitSetting,
      Conversation / ConversationSummary / ChatMessage (global co-writer thread),
      CowriterSongMemory, CowriterAlbumMemory
```

PostgreSQL with connection pooling. SQLAlchemy ORM. Alembic migrations. Redis is a required dependency — the server will refuse to start if Redis is unreachable.

### Resource event ledger

Every successfully persisted generation from the generation job or reimport path
writes one `generation.created` row in the same transaction. A per-user cursor is
incremented with `UPDATE … RETURNING`, so PostgreSQL serializes concurrent writers
without a process-local lock. The event stores immutable song and generation IDs;
they deliberately are not foreign keys, so retained history survives later resource
deletion. User deletion cascades both cursor and events.

The web-server lifecycle owns a named hourly cleanup task. Events older than 30 days
are deleted while the cursor high-water mark remains intact, allowing the replay
transport to detect retention gaps. Redis is not an authority or publisher for this
ledger.

### Web background loops

| Loop | Cadence | Owner and result |
| --- | --- | --- |
| `provider_status_refresh` | 30 seconds | The co-writer catalog refreshes each provider's reachability and model snapshot. One provider failure is logged without stopping the sweep; `/health` reports the loop through the shared registry. |

The first provider refresh is the loop's first tick after lifespan startup, not a
synchronous boot probe. Settings requests read the last snapshot only; an empty
snapshot is `unverified` with no probe timestamp.

`GET /api/resource-events/stream` is the authenticated read side. Its auth check and
handshake use one function-local DB session that closes before the response begins;
polls use separate short sessions. A fresh stream sends `hello` with `id: H`. A
reconnect reasserts its existing cursor with `hello` and `id: L`, replays only
`L < sequence <= H`, then becomes
live. Missing retained history, an internal sequence hole, or `L > H` produces one
`resync` at `H`. Heartbeats are SSE comments. Every connection ends after at most 60
seconds so native EventSource reconnect rechecks the session. Sequence and high-water
JSON fields are decimal strings, matching SSE IDs without JavaScript precision loss.

The library page is the sole frontend owner of that stream. Each mount — including
return from settings — opens a native `EventSource`, waits for `hello`, and runs
history restore inside a new snapshot epoch. Events after the epoch watermark are
buffered until the snapshot merges, then the owner is `live`. Targeted
`generation.created` invalidations update the selected song, loaded browse songs,
and loaded search hits through explicit adapters; events for songs that are still
in flight stay queued until those songs enter the loaded set. Browse and album
list writes keep already-loaded takes when a later summary would otherwise wipe
them. History restore
awaits every expanded album before the snapshot is ready so those tracks are in
the loaded set for the buffer flush. Window `focus` and document `visibilitychange`
revalidate the selected song and any failed refresh, not the whole browse page —
a 200-song library would otherwise exceed the 120/min IP limiter. Missed takes for
other loaded songs arrive through EventSource replay. Song fetches run with bounded
concurrency. A 404 drops the song from the loaded set instead of retrying forever.
The open song editor reloads only when the selected song id changes or the user
explicitly applies a fresh song, including after deleting the version on screen.
A live refresh error stays visible across the 60-second reconnect and is retried
on the next `hello`; a later successful fetch clears Retry.
Generation jobs no longer fetch the song themselves. The job tab still shows its
success toast; other tabs update silently. Bootstrap failures retry a bounded
number of times, then surface one accessible Retry status rather than hanging on
`Loading...`. Unmount, logout, and 401/403 on `EventSource.onerror` close the
stream.

## API Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/albums?offset=0&limit=50` | user | List the caller's albums (`q` title contains, `sort=newest\|oldest\|title`). `has_more` is explicit. |
| GET | `/api/songs?offset=0&limit=50` | user | List the caller's songs (`album_id`, `q`, `sort`). `has_more` is explicit. |
| GET | `/api/library/search` | user | Keyset search of the caller's album and song titles. `q` required; `next_cursor` is null iff `has_more` is false. Invalid or mismatched cursors are 422. |
| GET | `/api/library/pool-queue` | user | Ordered playable Mix/Picks/Keeps/All takes (`pool`, `shuffle`, `start_generation_id`) without ffmpeg concat. Same membership as `POST /api/queue-streams/library`. Shares the queue-stream per-user rate limit (429; 503 if Redis is down). Empty pool 422; foreign start 404. |
| GET | `/api/resource-events/stream` | user | User-exact `generation.created` SSE with fresh baseline, bounded replay, gap resync, comment heartbeats, and 60-second reauthentication boundary. |
| POST | `/api/albums` | user | Create album |
| GET/POST/DELETE | `/api/albums/{id}/cover` | user | Read, upload/replace, or remove the album cover (JPEG/PNG; ownership 404) |
| GET/POST/DELETE | `/api/songs/{id}/cover` | user | Read, upload/replace, or remove the song's own cover (JPEG/PNG; ownership 404). JSON `cover` is the song file or null — never the parent album's URLs. |
| DELETE | `/api/albums/{id}` | user | Delete album (cascade: songs, generations, files) |
| GET/PUT | `/api/songs/{id}` | user | Get/update song |
| PUT | `/api/songs/{id}/album` | user | Move song to different album |
| POST | `/api/songs` | user | Create song in album |
| POST | `/api/songs/{id}/generate` | user | Submit generation job (→ music queue) |
| GET | `/api/songs/{id}/last-failed-generation` | user | The song's last generate/repaint/cover job if it's still a failure -- `null` once a newer job (any status) or a newer non-archived take supersedes it. Ownership 404. Hydrates the take-list failure banner on page load/reopen; live SSE always wins over it. |
| POST | `/api/generations/{id}/score` | user | Submit scoring job (→ scoring queue) |
| POST | `/api/generations/{id}/rate` | user | Rate a generation |
| POST | `/api/generations/{id}/pick` | user | Pick best generation |
| GET | `/api/jobs/{id}` | user | Poll job status (includes queue_position) |
| POST | `/api/jobs/{id}/cancel` | user | Cancel a queued or running job (409 if not active). Terminal; later progress/finalize cannot overwrite. Does not stop in-flight GPU inference. |
| POST | `/api/songs/{id}/chat` | user | Send chat message (multi-turn, rate-limited) |
| GET | `/api/songs/{id}/chat` | user | Load chat history |
| DELETE | `/api/songs/{id}/chat` | user | Clear chat history |
| GET | `/api/chat/recent` | user | Songs with active chats |
| POST | `/api/chat/turn` | user | Co-writer turn — SSE stream of assistant text, tool calls, and a final event with persisted messages. Injects current song, durable memory, server-resolved @-mentions, and the relevant take's whisper/pick/keep/scores (`current_generation_id`). Unknown mention or generation IDs 404; a take for the wrong song or a non-playable take is 422. Provider is the persisted studio setting (`claude`, `grok`, or `codex`); missing credentials fail that provider by name. If the client aborts a non-terminal turn, its job immediately becomes `FAILED` with `error_type` `cancelled` and `Turn cancelled by the client.`; its heartbeat stops. A terminal job is left unchanged. |
| GET | `/api/settings/cowriter` | user | Co-writer provider, selected model, and live model catalogs from each provider or CLI; when the active saved or default value is a genuine model ID for that provider, it belongs to the valid set and is appended at the end without changing provider order. A `models_errors` map names why an unreachable provider's catalog came back empty (not only the saved provider's) |
| PUT | `/api/settings/cowriter` | admin | Persist co-writer provider, model, and history-tail budget. Only an exact, complete persisted provider/model pair makes a save unchanged; a fresh, partial, empty, or retired stored pair is a change. A change requires that provider to be `configured` for the co-writer surface and validates the model against its live catalog; the active saved or default value, when a genuine model ID for that provider, belongs to the valid set and is appended at the end without changing provider order. A budget-only save against an exact persisted pair is never blocked by a temporarily unreachable provider or catalog. |
| GET | `/api/settings/judge` | user | `lyrical_coherence` judge provider, selected model, and live model catalogs per provider; when the active saved or default value is a genuine model ID for that provider, it belongs to the valid set and is appended at the end without changing provider order. `models_errors` has the same shape as the co-writer response |
| PUT | `/api/settings/judge` | admin | Persist judge provider and model. Every save requires that provider to be `configured` for the judge surface and validates the model against its live catalog, including a request equal to the persisted pair; the active saved or default value, when a genuine model ID for that provider, belongs to the valid set and is appended at the end without changing provider order. A fresh or retired stored pair is safely replaceable. |
| GET | `/api/settings/providers` | admin | Provider reachability per `cowriter` and `judge` surface. `configured` means a turn can run on that surface; the other states name the missing API key, CLI login, or dependency. The agent-CLI runner caches its probes for `CLI_LOGIN_STATUS_CACHE_SECONDS`. |
| GET | `/api/memory` | user | Durable co-writer memory (`?song_id=` adds song + album scopes) |
| PUT | `/api/memory/user` | user | Replace user-scope co-writer memory |
| PUT | `/api/memory/songs/{id}` | user | Replace song-scope co-writer memory |
| PUT | `/api/memory/albums/{id}` | user | Replace album-scope co-writer notes |
| GET | `/api/capabilities` | user | Feature flags |
| * | `/api/admin/*` | admin | User CRUD, sessions, audit log, ACE-Step control |
| * | `/api/auth/*` | public | Login, logout, setup, password change |
| GET | `/health` | public | Per-worker status, DB, Redis, ACE-Step, queue depths |
| GET | `/metrics` | public | Job stats, HTTP counters, VRAM usage (Prometheus) |
| POST/DELETE | `/api/albums/{id}/share` | user | Enable/revoke album sharing |
| POST/DELETE | `/api/songs/{id}/share` | user | Enable/revoke song sharing |
| POST/DELETE | `/api/generations/{id}/share` | user | Enable/revoke generation sharing |
| POST/DELETE | `/api/playlists/{id}/share` | user | Enable/revoke playlist sharing |
| GET | `/shared/{slug}` | public | Read-only album JSON (no auth, rate-limited). `cover` is present only while shared and the file exists. |
| GET | `/shared/song/{slug}` | public | Read-only song JSON (no auth, rate-limited). `cover` is present only while shared and the **song** file exists. |
| GET | `/shared/gen/{slug}` | public | Read-only generation JSON (no auth, rate-limited) |
| GET | `/shared/playlist/{slug}` | public | Read-only playlist JSON (no auth, rate-limited) |
| GET | `/shared/{slug}/cover` | public | Stream the shared album cover after the same share-slug gate as album JSON |
| GET | `/shared/song/{slug}/cover` | public | Stream the shared song's own cover after the song share-slug gate. 404 when the song has no file of its own, even if the album has one. |
| GET | `/shared/{slug}/audio/{file}` | public | Stream shared album audio after filename allowlist validation |
| GET | `/shared/song/{slug}/audio/{file}` | public | Stream shared song audio after filename allowlist validation |
| GET | `/shared/gen/{slug}/audio/{file}` | public | Stream shared generation audio after filename allowlist validation |
| GET | `/shared/playlist/{slug}/audio/{file}` | public | Stream shared playlist audio after filename allowlist validation |
| POST | `/api/songs/{id}/reimport` | user | Upload MP3/WAV to reimport into a song |
| GET | `/audio/{owner_id}/{file}` | user | Serve audio files (MP3/WAV, ownership-checked by user ID) |

## Generation Flow

```
POST /api/songs/{id}/generate  (optional: {"model": "sft"} for model validation)
  → rate limit check (per-user, advisory lock)
  → ownership check
  → model validation (if specified — reject 409 if active model doesn't match)
  → create Job record + audit log entry
  → enqueue to arq (Redis-backed, music queue)
  → music worker: run_generation_job()
    → pick then atomically Lua-admit one online acestep-worker for the full take series
      → LoRA hold: keep the Job queued and defer a fresh ARQ envelope
    → build config (model defaults + admin defaults + preset + song params)
      → POST /load_model if the target mode is not loaded
      → POST /generate and consume /tasks/{id}/stream SSE until done
    → read worker WAV from the shared audio volume
    → persist Generation + per-user `generation.created` event atomically
    → decode → splice if repaint → master (multiband compress, LUFS normalize) → MP3
    → create Generation record in DB
  → Job status: completed

Cancel (POST /api/jobs/{id}/cancel) sets status=cancelled and completed_at.
`update_job_status` is a no-op once the job is already terminal, so progress
callbacks and finalize cannot revive a cancelled job. The generation runner
stops before setup, before each variant, after the worker returns, and before
persist. Queued cancelled jobs are skipped by `check_job_still_valid`.
In-flight ACE-Step GPU work is not interrupted (issue #30 Phase 2).
```

## Scoring Flow

The parent-hosted lyrical-coherence judge owns one provider budget and carries
it through the configured judge-provider call. Every configuration enforces a
minimum five-second timeout because the Claude one-shot path may need that
much for its tool-free CLI preflight; only that Claude path performs the
tool-surface probe. Grok and Codex use the compatible API path directly.
The five-second timeout is the provider floor; the bounded cleanup margin
(SIGTERM grace plus post-SIGKILL wait) belongs only to the
`agent_cli.run_cli_bounded` probe, while Grok/Codex use HTTP timeouts, the
Claude API uses its SDK timeout, the Claude-CLI judge uses
`subprocess.run(timeout)`, and the outer judge boundary is the Thread-Watchdog
`timeout+1s` (`pipeline.py:223-229`). The scorer watchdog has only a small
final-safety headroom. A provider timeout is a judge failure:
child scores are retained, but the scoring job ends `partial` with
`judge_error`, never `completed`.

```
POST /api/generations/{id}/score
  → rate limit check (per-user, advisory lock)
  → ownership check
  → create Job record + audit log entry
  → enqueue to arq (Redis-backed, scoring queue)
  → scoring worker: run_scoring_job(device=SCORING_DEVICE)
    → ScorerProcess.score() dispatches to a long-lived subprocess:
      Subprocess calls run_scoring_pipeline() with parallel execution:
        GPU scorers (audiobox) run sequentially
        CPU scorers (text_accuracy via faster-whisper, emotional_dynamics,
          bpm_accuracy, silence_detection, spectral_quality) run concurrently
        Each scorer fault-isolated: one failure does not block others
      Parent kills subprocess on timeout (SIGKILL), freeing GPU memory
    → parent judges lyrical_coherence on the returned result, through the
      configured judge provider (Claude/Grok/Codex, #315), reading the
      transcript from its text_accuracy value
    → merge scores + whisper_text + whisper_cues into DB
  → Job status: completed, or partial when the judge itself failed
    (e.g. its provider has no credential) — never a silent completed
```

**Every scorer reports its own outcome.** `SongScores.runs` carries one
`ScorerRun` per requested scorer — `ok`, `failed`, `timed_out`, or `skipped`
(with the reason, e.g. lyrical_coherence when text_accuracy produced no
transcript). Persisting replaces exactly the `output_keys` of the scorers that
came back `ok`, so a scorer that timed out or failed leaves the value it stored
in an earlier run untouched; a whole run of failures changes nothing. The job
log line names every scorer's outcome. Before #161 the run replaced the entire
score blob, so one slow scorer erased the previous result.

**Scorers that call an external service run in the parent.** `ScorerSpec.host`
says which process owns a scorer. The scorer child loads third-party model
weights and is spawned with `SECRET_ENV_KEYS` scrubbed, so it never holds a
credential: `lyrical_coherence` is `ScorerHost.PARENT`, the child's registry
refuses to register it, and `jobs/scoring.py` asks the child only for the
child-hosted scorers and then calls `judge_lyrical_coherence()` itself on the
`SongScores` that came back. `TextAccuracyScore.transcript` is the single owner
of the transcribed text — the judge reads it and `Generation.whisper_text`
stores it. The judge produces an ordinary `ScorerRun` under its own
`SCORER_TIMEOUT_SECONDS` budget, so `ok` / `failed` / `skipped` / `timed_out`
and the merge rules apply to it exactly as to a child scorer: a judge-provider outage
leaves the stored `lyrical_coherence` untouched. `PipelineConfig` therefore
carries no secret (issue #176; see docs/security.md).

**Timeouts are per scorer.** `SCORER_TIMEOUT_SECONDS` (120) is the default
budget; `TEXT_ACCURACY_TIMEOUT_SECONDS` (300) gives Whisper its own, because a
cold model load counts against it. Each budget is a ceiling, not a target: a
scorer that blows it is abandoned, not waited for, so the run keeps moving with
that scorer's stored value. Abandoned is not stopped, though — that scorer's
thread still holds the child's models and GPU memory, so a run in which a
*child-hosted* scorer timed out recycles the scorer subprocess once its values
are persisted (`ScorerProcess.recycle()`), and the next request pays a model
reload for a clean child. A parent-hosted scorer over budget leaves its thread
in the worker parent instead, where recycling the child would reclaim nothing.
The recycle is prompt GPU reclaim, not the guarantee: `ScorerProcess` marks
such a child tainted under its request lock and never hands it to another
request, so a job cancelled before it could recycle changes nothing. The outer
subprocess watchdog covers the child's single concurrent phase — its slowest
scorer budget plus headroom — and never drops below
`SCORING_PIPELINE_TIMEOUT_SECONDS`. If it fired first the subprocess would be
SIGKILLed and even the values the run did produce would be lost.
`ARQ_JOB_TIMEOUT` must stay above the whole job: the child watchdog plus the
parent's coherence budget, which is spent after the child returns.

`whisper_cues` is a JSON list of `{start, end, text}` from faster-whisper segments (start/end in seconds), each optionally carrying `words`, the same shape one level finer, from `word_timestamps=True` (#142). `null` means never scored or a legacy row; a list (including `[]`) means text_accuracy ran and stored whatever usable cues it produced. A cue without `words` was scored before word timestamps existed and gets them only through a re-score (#132) — the key is omitted rather than stored as `null`, so those rows keep their original shape. `whisper_text` is the same cue texts joined with newlines. Missing timings are not invented.

## Worker Architecture

```
                         ┌─ arq:queue:music ──→ Music Worker(s)
  API ─→ route by type ──┤
                         └─ arq:queue:scoring → Scoring Worker(s)

  Chat runs inline in the API process (no arq queue).
  Client cancellation follows the `POST /api/chat/turn` contract.
```

**Music worker** (`music_worker.py`):
- Thin orchestrator — no GPU, no ACE-Step process. Dispatches generation jobs
  to acestep-worker peer containers via the scheduler (`scheduler.py`).
- Handles `generate`, `load_model_on_worker`, `download_model_on_worker`, and
  `train_lora` tasks
- `max_jobs=2` (concurrent SSE consumers; the actual generation runs on the
  acestep-worker)
- Cron: audits orphaned audio files and applies file-expiry cleanup. The
  `generate` and `lora_training` job types are recovered on MusicWorker
  startup and shutdown.
- Post-processes worker WAV → mastered MP3 → DB row in `asyncio.to_thread`

**Scoring worker** (`scoring_worker.py`):
- Owns scorer subprocess (Whisper, AudioBox, audio scorers); judges lyrical
  coherence itself through the configured judge provider, so no secret enters the subprocess
- Handles `score` tasks
- Device configurable via `SCORING_DEVICE` env var (`cpu` or `cuda`)
- `max_jobs=1` (default, configurable via `SCORING_MAX_JOBS`)

**Shared infrastructure** (`worker_base.py`):
- DB singleton with thread-safe initialization
- Path helpers (`_audio_dir`, `_data_dir`)
- Timeout constants, terminal status set
- Common startup, shutdown, and restart recovery for every named worker job
  type. MusicWorker executes the model jobs `generate`, `lora_training`,
  `load_model_on_worker`, and `download_model_on_worker`; the ACE-Step worker
  performs their HTTP model-serving portion. The scoring worker owns `score`.
- A worker restart terminalizes only `RUNNING` jobs for every type. Queued
  work remains in arq for a replacement worker to claim after a deploy.
- Shutdown recovery uses a Redis advisory lock, then disposes the DB pool.
- Orphaned file audit (`audit_orphaned_files()`) — logs disk files with no DB record

**Stale-job recovery** (web process — #446, #456): The lifecycle loop is the
one periodic owner for every job type: `chat`, `generate`, `score`,
`lora_training`, `load_model_on_worker`, and `download_model_on_worker`. It
reads ephemeral worker signals and passes their `alive`, `dead`, or `unknown`
value into the single generic `recover_stale_jobs_by_age_and_type()` DB rule;
the query layer never reads Redis. A queued job with a known-dead execution
worker fails as `No worker alive for this job type` after its signal's grace.
The queued-age guard fails a job as `Queued too long` only when the signal is
unknown. Running jobs still use `heartbeat_at`. Worker
startup/shutdown recovery is separate: it records that a worker process
restarted, rather than deciding whether a still-running job is stale. An
active job type without a policy-table row is a loop failure and is exposed by
`/health`; it is never silently skipped.
The request path supplies the same Redis-derived liveness map before it
reclaims a submitting user's stale jobs, so admission and lifecycle recovery
apply the same queued-job rule.

The liveness owner maps each type to the signal that can execute it. It writes
the last observed `alive` state for each signal to Redis with a seven-day TTL.
When the ephemeral signal disappears, a missing signal within the 300-second
restart grace after the last observation is `alive`; only a longer absence can
be `dead`. The grace covers a
container restart: ACE-Step's 30-second healthcheck start period and the
Music/Scoring workers' 120-second Docker Compose healthcheck period, plus image
start and reserve. An empty ACE-Step registry is `unknown` only when it has
never been observed; with a newer observation, it is `alive`.

- `generate`, `load_model_on_worker`, and `download_model_on_worker` use the
  MusicWorker and registered ACE-Step worker together: MusicWorker executes the
  job and ACE-Step performs its HTTP model-serving portion. They are `alive`
  only when both signals are alive. A dead MusicWorker signal makes the
  combined signal `dead`; a missing or unknown MusicWorker signal leaves it
  `unknown`, so it uses the #446 age guard. ACE-Step's 15-second heartbeat TTL
  makes its current state disappear; it is not the restart grace. `dead` is
  only declared after the observing web process itself has run longer than the
  grace, measured from the observer process start time.
- `lora_training` uses the music arq worker health key, and `score` uses the
  scoring arq worker health key. A live ACE-Step signal does not prove the
  MusicWorker is live; that case remains `unknown` and uses the appropriate
  age/full-queue guard.
- `chat` runs in the web process rather than a worker queue, so it has no
  worker liveness signal and queued chat can only use the age guard.
  A client-aborted chat turn follows the `POST /api/chat/turn` cancellation
  contract rather than waiting for the running-job heartbeat reaper.

- `STALE_JOB_THRESHOLDS` in `constants.py` is the single policy table:

  | Type | signal | restart grace | unknown queued age | alive queued bound | running heartbeat |
  | --- | --- | ---: | ---: | ---: | ---: |
  | `chat` | none | none | 900 s | n/a | 180 s |
  | `lora_training` | music | 300 s | 1100 s | max queue depth × 300 s | 300 s |
  | `score` | scoring | 300 s | 1100 s | max queue depth × 600 s | 600 s |
  | `generate` | music + ACE-Step | 300 s | 1100 s | max queue depth × 760 s | 760 s |
  | `load_model_on_worker` | music + ACE-Step | 300 s | 1100 s | max queue depth × 1300 s | 1300 s |
  | `download_model_on_worker` | music + ACE-Step | 300 s | 1100 s | max queue depth × 180 s | 180 s |

  A `dead` signal fails queued work immediately after the grace already
  applied by the reader. An `unknown` signal uses the #446 queued-age guard.
  An `alive` signal ignores that age guard and only fails after a complete
  queue could have consumed one running-heartbeat window per allowed queue
  position. At the default depth 100, generate's bound is 76,000 seconds
  (about 21 hours). Running jobs still use `heartbeat_at`.

  Generation uses three ordered clocks: ACE-Step's 600-second poll window,
  the scheduler's 630-second SSE read timeout (poll window plus 30-second
  margin), and arq's 1000-second job timeout as the final safeguard. Before
  the first SSE event, a cold worker can spend 600 seconds loading a model,
  30 seconds accepting generation, and 10 seconds connecting the stream. The
  760-second generate reaper threshold is therefore the longer of that
  640-second first-event window and the read timeout, plus one 120-second
  reaper tick; it is not a second timeout mechanism. `TaskStore.subscribe()`
  immediately sends its current event when the stream connects, and the
  scheduler heartbeats on every received event, so that initial event refreshes
  the heartbeat and the first-event and read windows do not concatenate.

  LoRA training uses its own `LORA_TRAINING_JOB_TIMEOUT` (3600 seconds by
  default), while the MusicWorker's global `ARQ_JOB_TIMEOUT` remains the
  generation limit. Its five-second worker progress poll is ordered below the
  300-second LoRA reaper threshold, which is ordered below the LoRA arq timeout.
  Every TaskStore progress event follows the shared SSE path and refreshes the
  job heartbeat; the reaper therefore only terminalizes a training job after
  progress has stopped for its threshold, not because its total age exceeds a
  generation run.

  The 630-second scheduler SSE read timeout applies to generation, download,
  and LoRA task streams through their shared `DispatchOptions()`. On a cold
  generate path, the 640-second window before the initial event plus a later
  630-second silent-read window exceeds arq's 1000-second timeout, so arq
  remains the final mechanism: it cancels or fails the local Music-Worker job
  and closes its subscription. It does not remotely cancel the ACE-Step task,
  which can continue running after that local job ends.

  `download_model_on_worker()` refreshes its job heartbeat through both
  `_on_progress` and `_on_heartbeat` for every consumed SSE event. The worker
  emits download progress from its 2-second poll. `DOWNLOAD_MAX_ATTEMPTS`
  bounds retries after failed streams; it is not a total-runtime bound. A load
  request has no progress stream, so its 1300-second heartbeat bound covers
  the 960-second HTTP request timeout with margin.

- `stale_job_reaper_loop()` ticks every `JOB_REAPER_INTERVAL_SECONDS` (2
  minutes), behind the same
  single-flight Redis lock idiom as `session_sync_loop` / `score_backfill_loop`
  so only one web replica reaps a given tick.
- A queued job reports `No worker alive for this job type — please retry.`
  when its known-dead execution worker exceeded its grace, or `Queued too long — please retry.`
  when it exceeded the age guard. A running one reports `Heartbeat lost — please retry.`
  The request path applies that same rule only to the submitting user's jobs just before
  active-job limits, so a job that crosses a threshold between lifecycle ticks cannot cause a
  spurious 429.
- The reaper terminalizes each stale candidate with a conditional update on its read status and
  heartbeat, so a concurrent heartbeat or terminal completion wins instead of being overwritten.
- `reconcile_crashed_loras()` runs once at web startup and after the web
  reaper; MusicWorker calls the same job-owned reconciliation after it
  terminalizes a `lora_training` job. The path locks one active LoRA candidate
  with `skip_locked`, commits its FAILED status and one audit entry in that
  transaction, then removes its working files. Only a LoRA whose training job
  is missing or terminal is a candidate; a still-RUNNING job's LoRA waits for
  the lifecycle reaper to terminalize it (heartbeat threshold plus one tick).
  A second process finds no
  unlocked candidate to clean up.

**Backwards-compatible shim** (`worker.py`):
- Imports tasks from music_worker and scoring_worker
- Runs both on the legacy `arq:queue` queue
- Logs a deprecation warning on startup

### Adding a new modality

1. Write task function (e.g. `generate_image()`)
2. Add queue constant (`ARQ_IMAGE_QUEUE_NAME`)
3. Add health check function (`is_image_worker_healthy()`)
4. Add API routing (`pool.enqueue_job("generate_image", ..., _queue_name=...)`)
5. Create worker module (`image_worker.py` with `ImageWorkerSettings`)
6. Add Docker Compose service

No existing code changes needed.

## VRAM Management

```
ACE-Step models:  ~6-12 GB VRAM each (varies by mode), live in acestep-worker containers
faster-whisper:   ~3 GB VRAM on GPU, runs on CPU when SCORING_DEVICE=cpu
AudioBox:         ~1 GB VRAM on GPU, runs on CPU when SCORING_DEVICE=cpu
```

ACE-Step VRAM is owned by `acestep-worker-N` containers, one per GPU. Each worker
holds an LRU cache of loaded models bounded by `VRAM_BUDGET_GB` and reports
its current usage via heartbeat. The music-worker has no GPU access at all.

| Deployment | acestep-worker | Scoring worker | Notes |
|-----------|---------------|----------------|-------|
| Single GPU, 24 GB | GPU 0 (1 container) | CPU | LRU cache holds 1-2 models |
| Single GPU, 48 GB+ | GPU 0 (1 container) | GPU 0 | Larger LRU cache + scoring on same GPU |
| Two GPUs | GPU 0 + GPU 1 (2 containers) | GPU 0 or CPU | Scheduler picks least-busy |

## Key Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Single code path | CLI → API → DB | No duplication between CLI and web |
| Pydantic from_orm() | Response models serialize ORM objects | No manual dict layer to maintain |
| Worker split | Separate arq queues per job type | Independent scaling, device config per worker |
| Scoring subprocess | Long-lived child process, killed on timeout | Real cleanup via SIGKILL, GPU memory freed immediately |
| Scoring isolation | try/except per scorer | One crash doesn't block others |
| Session auth | Cookies + Redis cache | Revocable, HttpOnly, Redis-first reads. Redis TTL is authoritative for session expiry; DB synced every 5 min as backup |
| Redis required | Fail-fast at startup, fail-closed rate limiting | Server won't start without Redis; if Redis drops mid-operation, IP rate limiting returns 503 |
| Album ownership | `created_by` on Album | Songs inherit access; sharing via secret UUID slug |
| PostgreSQL | Connection pooling, concurrent writes | Required alongside Redis |
| ACE-Step as subprocess | Separate server, managed lifecycle | Clean VRAM release, independent restarts |
| Typed API contract | `api_models/` ↔ `types.ts` | Backend and frontend stay in sync |

## Monitoring

Prometheus + Grafana stack in `docker-compose.yml`. Prometheus scrapes `/metrics` every 15s. Grafana on port 3000 with a pre-provisioned dashboard.

Exported metrics: `songmaker_http_requests_total`, `songmaker_http_request_duration_milliseconds_total`, `songmaker_active_sessions`, `songmaker_jobs_total`, `songmaker_job_duration_seconds`, `songmaker_last_job_failure_timestamp_seconds` (0 while nothing has ever failed), `songmaker_queue_depth{queue="music"|"scoring"}`, `songmaker_acestep_workers_total{status=...}`, `songmaker_acestep_worker_loaded_models`, `songmaker_acestep_worker_queue_depth`, `songmaker_acestep_worker_vram_used_gigabytes`, `songmaker_acestep_worker_vram_total_gigabytes` (the last two come from each acestep-worker's own heartbeat — `songmaker-web` itself has no GPU access and cannot produce a VRAM number of its own), `songmaker_background_loop_consecutive_failures{loop=...}`, and `songmaker_background_loop_alive{loop=...}`.

Health endpoint at `/health` reports:
- `music_worker`: running/stopped
- `scoring_worker`: running/stopped
- `music_queue_depth`, `scoring_queue_depth`: jobs waiting per queue
- `background_loops`: each registered loop's `ok`, `failing`, or `dead` state, consecutive-failure count, and latest error
- `db`, `redis`, `acestep`: component health. An ACE-Step worker only counts as online (`songmaker_cli.acestep_state.worker_is_online`, the one function every caller — `/health`, `/metrics`, the scheduler's worker picker, the generate/repaint/cover preflight, the admin worker pool and model registry — goes through) if its heartbeat both exists in Redis *and* reports `gpu_healthy: true` — a worker whose GPU has gone away (NVML present but unreachable: a driver/GPU mismatch, a vanished device) keeps heartbeating just fine, so heartbeat presence alone is not enough (issue #367). A heartbeat missing the `gpu_healthy` key entirely counts as **not** online — fail-closed, since this is a single-host deployment where every container is rebuilt in one `docker compose up --build`; a lenient default would only ever hide an old or broken worker build forever. That deploy has no ordering guarantee between `songmaker-web` and the acestep-worker — they share no `depends_on`, so which finishes building and starts first is not assured — and `docker compose up -d --wait` can run for up to `COMPOSE_UP_WAIT_TIMEOUT_SECONDS` (20 minutes) on a cold cache. The worker publishes its first heartbeat immediately on start, so the mixed-version window is normally seconds; the worst case is however long the new worker container takes to start, not a fixed bound. For the deployment this project runs — a single host, one operator watching the deploy — that worst case is acceptable to simply wait out: every caller above honestly reports "no worker online" for as long as the window lasts, rather than guessing. A staged or ordered rollout that shortens the window is a separate concern, not one this single-machine deployment needs solved here.
- `status`: "ok" or "degraded" (degraded if both workers down, DB down, Redis down, or `acestep` is unhealthy). The HTTP status code stays 200 even when degraded or a background loop is dead: a 503 here would fail `songmaker-web`'s own Docker healthcheck over a *different* container's GPU going away, and auto-deploy's `--wait` would then refuse every deploy for the exact duration of the outage a fix is meant to end. `songmaker_acestep_workers_total{status="online"} == 0` and `songmaker_background_loop_alive == 0 or songmaker_background_loop_consecutive_failures >= 3` (issue #333) carry alerts instead — the Docker healthcheck answers "is this container alive", not "is the fleet healthy".

### Alerting (issue #333)

Two independent sources feed one email address (`ALERT_EMAIL_TO` in `.env`, sent from the operator's own SMTP account — `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`):

1. **systemd.** `scripts/alert.sh <subject> <body>` sends one email via curl's built-in SMTP client (`--ssl-reqd smtp://…` — no sendmail/msmtp install needed). It reads its five config values exclusively from `.env` and fails loudly (non-zero exit, named reason on stderr) if any are missing or the send itself fails; it never reports success it didn't achieve. The template unit `scripts/songmaker-alert@.service` runs it; `songmaker.service` (boot autostart) and `songmaker-autodeploy.service` (the pull-based deploy timer) both declare `OnFailure=songmaker-alert@%n.service`. `songmaker-autodeploy.service` ticks every ~2 minutes and routinely refuses to deploy for entirely expected reasons (the operator working on a branch other than `main` in this checkout, a dirty tree) — its own `fail_tick()` helper only lets the unit register as failed (and so trigger `OnFailure=`) on the tick that crosses its consecutive-failure ALERT threshold (default 3 attempts in a row), and then on the first tick at least `ALERT_REPEAT_SECONDS` (default 3600) after the previous escalation while the streak continues. So a transient blip is silent, a single crossing pages once, and an outage nobody fixes keeps paging hourly rather than every two minutes — the same rule damps the busy counter's warning line. The two halves of that rule are measured in different units on purpose. "Three attempts in a row failed" is what separates a transient blip (a migration `lock_timeout` the next tick retries) from an outage, and elapsed time cannot tell those apart. The repetition, though, is a promise to the operator in wall-clock hours, and a tick is not a fixed two minutes: a systemd timer starts no second run while the previous one is still going, so a tick that waits out `COMPOSE_UP_WAIT_TIMEOUT_SECONDS` occupies twenty minutes — counting ticks for the repetition turned "again in an hour" into "again in ten hours" on exactly the slow, broken ticks the alarm exists for. The escalation times live next to the counters in the git admin directory and are cleared whenever the streak resets, so a fresh outage escalates on its own crossing tick instead of waiting out the previous one's hour. A failure/success/failure flapper still resets the counter and can stay under the threshold indefinitely: this counts *consecutive* failures deliberately — a deploy that succeeds in between is a deploy that worked, and the running stack itself is what Prometheus watches. `songmaker.service` runs only at boot and uses `RestartMode=direct`, so its intermediate restart attempts skip the failed state entirely and `OnFailure=` fires exactly once, when the restart budget (`StartLimitBurst`) is spent. Both `scripts/install-autostart.sh` and `scripts/install-autodeploy.sh` install `songmaker-alert@.service` alongside their own unit (idempotent — running either, or both, converges on one installed copy).
2. **Prometheus.** `monitoring/rules/alert.rules.yml` (native Prometheus rule syntax, checkable with `promtool check rules` independent of any UI) defines four alerts, wired in via `rule_files:` in `monitoring/prometheus.yml`: no online ACE-Step worker for 10 minutes (`songmaker_acestep_workers_total{status="online"} == 0`, for: 10m — this is the exact metric that sat correct and unwatched for six days during issue #252), the scrape target down for 5 minutes (`up{job="songmaker"} == 0`), any job failure within a 15-minute window (`time() - songmaker_last_job_failure_timestamp_seconds < 900`), and a background loop that is dead or has failed three consecutive ticks (`songmaker_background_loop_alive == 0 or songmaker_background_loop_consecutive_failures >= 3`, for: 5m). The job-failure alert reads a *timestamp*, not a failure count, because every counter-shaped answer needs history the alarm may not have: the per-type `songmaker_jobs_total{status="failed"}` series only comes into existence with the first failure of a type, and even an always-exported total reads 1 on Prometheus' very first sample when the failure happened between `songmaker-web` becoming healthy and the first scrape of it — `increase()` finds no rise across a series' first sample either way, so exactly the first failure of a fresh stack went unalerted. A timestamp is complete in a single sample, and it also survives a future cleanup that deletes failed jobs — the value moves backwards, where a counter would look like a reset. Both job-failure histories and the background-loop cases are pinned by `monitoring/alert.rules.test.yml`, run against the real rule file by Prometheus' own `promtool test rules` in CI (the `alert-rules` job). Delivery is a small `alertmanager` container (`monitoring/alertmanager.yml.template`, `rule_files:`'s paired `alerting: alertmanagers:` target) using Alertmanager's own built-in SMTP `email_configs` — the same five `.env` values as `scripts/alert.sh`. `monitoring/alertmanager-entrypoint.sh` substitutes the four non-secret ones into the config at container start (Alertmanager's config format has no `${VAR}` substitution of its own) and refuses to start if any is missing, same as `alert.sh`. Each value crosses two languages on the way in and is escaped for both: the template puts it in a single-quoted YAML scalar, where the only escape is a doubled apostrophe (without it an ordinary address like `o'connor@example.com` closes the scalar early), and the substitution itself is `sed`, where `&`, `\` and `|` are syntax. A value carrying a line break has no correct spelling inside a one-line quoted scalar at all and is refused by name. The rendered file is then validated by Alertmanager's own parser (`amtool check-config`, which ships in the image) *before* the daemon is exec'd, so a config it could not read fails once with the reason on stderr instead of crash-looping with it buried. The password is not among them: it is mounted as a Docker secret and read by Alertmanager itself via `smtp_auth_password_file`, so it appears in no environment, no `docker inspect` output, no process argument and no generated config — and it never passes through a text substitution that a `&` or a backslash in a generated app password would silently corrupt. `scripts/alert.sh` hands curl the same credentials on a file descriptor (`--config`) rather than in `--user`, for the same reason. This was chosen over both alternatives considered: Grafana's own native alerting would mean maintaining the same four thresholds a second time in Grafana's own rule schema (duplication, not "one alarm channel"); a webhook from Alertmanager back into `scripts/alert.sh` would need a listening receiver process for no benefit over Alertmanager's built-in email receiver, which additionally groups/dedups (`group_wait`/`group_interval`/`repeat_interval` in the template) so a flapping alert re-sends at most once an hour instead of once per Prometheus evaluation.

Prometheus mounts the complete `monitoring` directory read-only at `/etc/prometheus`, so neither its configuration nor its rules is pinned to a replaced host-file inode. The rules live exclusively in `monitoring/rules/`; when `monitoring/prometheus.yml` or `monitoring/rules/alert.rules.yml` changed from the recorded deployed SHA, `auto-deploy.sh` finds the Compose Prometheus container and sends it `HUP`. It then waits for the loopback-only readiness endpoint and compares the configured alert-rule count with `/api/v1/rules`' count restricted to `/etc/prometheus/rules/alert.rules.yml`. Lifecycle HTTP endpoints are disabled, so a Compose-network peer cannot use an unauthenticated `POST /-/quit` or reload endpoint. A reload, readiness, API, or count failure is logged after the deploy is booked and does not increment its failure counter.

The two sources are a **fallback for each other, not a deduplication**: they share one inbox and roughly one cadence, but nothing correlates them. Alertmanager's `repeat_interval` and `auto-deploy.sh`'s `ALERT_REPEAT_SECONDS` are both an hour, out of phase, so one incident visible to both — a failing deploy that also takes the stack down — will arrive as two mails per hour rather than one. That is the intended trade: the incident this exists for (issue #252) is exactly the kind where one of the two channels is itself broken.

A missing or incomplete alert configuration therefore blocks a deploy rather than passing unnoticed: `alertmanager` has a healthcheck and would otherwise crash-loop while `docker compose up --wait` waited on it forever — with the auto-deploy tick holding its lock, so no later tick would run and nothing would ever be alerted. `auto-deploy.sh` checks the five values (through `scripts/alert-config.sh`, which owns that list for both scripts) before it pulls or builds, and bounds the container-readiness wait with `--wait-timeout`.

Dashboard: `songmaker_acestep_workers_total{status="online"}` has its own stat panel (red at 0, green otherwise) in the Overview row — the metric that would have shown the six-day outage now has somewhere a human glances.

## Operational Scripts

One-off data scripts (`scripts/backfill_audio_durations.py`, `scripts/migrate_generation_params.py`, and future ones) live in `scripts/`, which the web image copies whole (`Dockerfile`). They run inside the `songmaker-web` container, where `DATABASE_URL` and the audio volume are mounted:

```
docker compose exec songmaker-web /app/.venv/bin/python scripts/<name>.py --help
```

Use `/app/.venv/bin/python`, not bare `python`. The web container's `PATH` resolves `python` to the package-less system interpreter that `python:3.12-slim` ships with — the app's dependencies live only in the `uv`-managed venv at `/app/.venv`, the same path every worker Dockerfile's `ENTRYPOINT` addresses directly rather than relying on `PATH`. Each script's module docstring documents its own dry-run/apply flags.

## Backup & Restore

`scripts/backup.sh` dumps PostgreSQL + copies the audio Docker volume to `BACKUP_DIR` (default `/mnt/backup/songmaker`). `scripts/restore.sh` restores both. `scripts/backup-list.sh` lists snapshots. See [scripts/BACKUP.md](../scripts/BACKUP.md) for setup instructions.

DB and audio must be backed up and restored together — one without the other leaves orphaned records or unreachable files.

Album covers live as files on that same audio volume (`covers/{album_id}/` for original plus card and detail derivatives). Song covers live beside them at `song-covers/{song_id}/` — not under `covers/songs/`, because an album slug can be `songs`. They are not stored as Base64 in PostgreSQL; the album or song row only stores `cover_key`. Authenticated song JSON advertises `cover` only from that song's key; display inheritance of album art is a UI concern. Backup/restore of the audio volume therefore includes covers with no extra volume.

## Auto-Deploy

A merge to `main` goes live without a manual `git pull && docker compose up` (issue #298). The host runs a **pull-based systemd timer** — `scripts/songmaker-autodeploy.timer` fires `scripts/songmaker-autodeploy.service` (`scripts/auto-deploy.sh`) every ~2 minutes — deliberately not a self-hosted CI runner (a permanent externally-triggered agent on the host) and not a webhook (a new inbound endpoint behind the tunnel). CI is green on every merge by process, so "origin/main moved" already means deployable; the script does not re-run tests.

Each tick, in order, and non-blocking (`flock -n`, a run already in flight logs a debug line and exits 0):

1. **Read HEAD, fetch, read remote HEAD.** `git rev-parse HEAD` (works detached too), `git fetch origin main`, `git rev-parse origin/main`. Neither read depends on which branch is checked out, so both happen before the branch guard. A failure at any of the three (most likely a persistently broken `git fetch`, e.g. a dead SSH key on the host) bumps the failure counter like every other refusal below, not just a log line — a stuck fetch is the most likely way this whole mechanism goes silently stale, so it has to be able to reach the consecutive-failure ALERT too.
2. **Up to date?** Judged against what is actually **running**, not just what is checked out: a `deployed.sha` file (state directory, see below) is written only after a successful `docker compose up -d --wait`, in `record_success`. "Nothing to deploy" means `HEAD == origin/main` **and** `deployed.sha == HEAD` — not `HEAD == origin/main` alone. A tick that pulled and built but deferred the recreate (jobs still active, or a build/up failure) already sits on the new `HEAD`; without the second condition, every following tick would see "local == remote" and treat the still-stale running containers as nothing to deploy, forever. The very first tick that ever runs (no `deployed.sha` file yet — a fresh install) **adopts** the current `HEAD` as already-deployed instead of deploying: it writes the file, logs "adopted running state `<sha>`" at info, and exits — this keeps `install-autodeploy.sh`'s `enable --now` harmless on an already-running stack, at the cost that a checkout installed while behind `main` stays on that stale commit until the operator deploys it once by hand. Both cases log at debug/info priority only, so this ~2-minute steady-state tick doesn't spam an unfiltered journal (`journalctl -t songmaker-autodeploy -p info` stays quiet on every ordinary tick). This shortcut runs **before** the branch guard below: an operator sitting on an experiment branch with nothing actually pending to deploy must not get a loud line every ~2 minutes for no reason.
3. **On the deploy branch?** `git symbolic-ref --short HEAD` must equal the configured deploy branch (`main` by default). Reached only once step 2 has established that something is actually pending — but that condition is reached, not avoided, as soon as HEAD doesn't match the deployed state of `origin/main`, which on a work branch is essentially always. A detached HEAD or a non-deploy branch therefore fires this guard on essentially every tick for as long as the operator stays there, not as a rare edge case; to avoid a `prio=err` journal line every ~2 minutes for hours, it only re-logs at `err` when the reason actually changes (a small "last guard reason" file in the state directory below), otherwise at debug. The consecutive-failure counter still bumps on every single tick regardless of which level it logged at, so the ALERT threshold is unaffected by this damping — it touches nothing either way.
4. **Safe to touch?** A dirty working tree (`git status --porcelain`, itself checked for a failed exit code rather than trusted blindly) or a diverged (non-fast-forwardable) local `main` stops here with a loud (`prio=err`) journal line and touches nothing — the host's checkout is also the operator's manual workspace.
5. **Idle?** Before the pull, a job guard checks `jobs.status IN ('queued', 'running')` via a `timeout`-bounded `docker compose exec postgres psql` (the DB round-trip gets a short timeout; the CLAUDE.md never-`timeout`-compose rule is about the image build, not this query). Active jobs defer the deploy to the next tick. An unreachable database fails **closed** (no deploy), not open.
6. **Pull, then build.** `git pull --ff-only` then `docker compose build` — no `timeout` wrapper (see the Docker section of `CLAUDE.md`; a cold-cache rebuild legitimately takes 8-15 minutes). Both stream straight to the process's own stdout/stderr (journaled under the unit by systemd) rather than being captured into a variable — a failed build can print far more output than a single `logger` invocation can safely carry as one argument; only a short `log_err` line with the exit code goes through `logger`. The build alone does not touch a running container.
7. **Recheck, preserve rollback images, then recreate.** The job guard from step 5 runs again immediately before `docker compose up -d --wait` (no `--build`, image is already built), the one step that actually recreates the acestep-worker and music-worker containers (incident 2026-08-30 18:31, a redeploy mid-generation dropped every active stream). Before that recreate, the tick reads Compose's JSON config without interpolating `.env` values and tags each currently running service with a `build:` section as its one `<project>-<service>:previous` rollback generation; `<project>` is the Compose config's own name. This rollback tagging needs `jq` on the host for the config's name and build-service list. If `jq` is unavailable, an idle tick remains successful; a pending deploy follows the ordinary deploy-refusal path, including its consecutive-failure alerting. A deploy deferred here logs "deferred after build" and exits 0; the next tick finds `HEAD == origin/main` already true but `deployed.sha` still stale (step 2), so it skips straight past the branch/dirty/diverged guards to the job check and, once jobs clear, the (now-cached, fast) build and the recreate — the residual window a job can start and still collide with a recreate is seconds, not the build's 8-15 minutes, and a tick that keeps deferring here does not get stuck forever behind a false "up to date".
8. **Bounded Docker cleanup.** After a successful recreate, the tick deletes dangling images older than 48 hours while preserving newer dangling images and all tagged images, and prunes builder cache older than that threshold with `--all`; both commands have a 10-minute timeout. Cleanup never rolls back a successful deployment: an error or timeout is logged at `err` with its command and exit code, while the completed deployment stays booked and the tick exits 0. The operational boundary and rollback procedure are in `docs/security.md`.

Two independent consecutive-tick counters distinguish "this is actually broken" from "this is just busy": a hard refusal (wrong branch, dirty tree, diverged), a fail-closed DB check, or a `pull`/`build`/`up` failure bumps the **failure** counter — only the Nth in a row (default 3) escalates to an emphatic `prio=err` "N ticks in a row deferred/failed, reason: …" line. A deferral because jobs are active (before or after the build) bumps a separate **busy-deferral** counter instead — a normal generation queue or an hours-long `lora_training` job legitimately keeps jobs active for a long time, so this one needs a much higher threshold (default 30 ticks) and a quieter `prio=warning` "deploy deferred on N ticks in a row, M jobs still active" line, not a page-worthy error. Both lines count ticks and say so; only the *repetition* of an escalation is measured in wall-clock time (see Alerting above). Both counters reset only on an actual deploy (record_success) or a genuine 'nothing to deploy' tick (step 2).

The lock file, the failure counter, the busy-deferral counter, and `deployed.sha` all live inside the checkout's own git **admin directory** — resolved at runtime via `git rev-parse --absolute-git-dir`, not assumed to be `$REPO_ROOT/.git`. For a normal checkout that resolves to exactly `$REPO_ROOT/.git`; run from a linked worktree (`git worktree add`), `$REPO_ROOT/.git` is itself a *file* pointing at the real admin dir elsewhere, and redirecting straight at a path under that file would kill the shell before it logs anything — hence the resolution step instead of a hardcoded path. There is deliberately no systemd `StateDirectory`: that would be a second location the unit's own tick and a manual shell run would silently diverge onto, instead of both sharing the one path every caller for a given checkout already agrees on. Not under a systemd-managed `RuntimeDirectory` either, for the same reason a unit-scoped runtime dir would give the systemd-run tick and a manual run two different lock inodes, defeating the mutual exclusion the lock exists for. A corrupted counter or `deployed.sha` file resets/re-verifies itself with a loud journal line instead of silently misbehaving; a `deployed.sha` write that reads back as anything other than what was just written is itself treated as a failed deploy, not a successful one.

Install once with `sudo ./scripts/install-autodeploy.sh` (requires Docker Compose v2 and `jq` for pre-recreate rollback tagging; the installer verifies `jq` before it installs anything; root-guarded, idempotent, derives `WorkingDirectory`/`User` from the invoking checkout and operator like `scripts/install-autostart.sh`, and refuses a checkout path containing `%` or whitespace — either breaks systemd's own unit-file parsing before the deploy logic ever runs). Unlike the boot-autostart unit, this installer enables **and starts** the timer immediately — arming a ~2-minute schedule is harmless because every tick goes through the guards above before touching the stack, unlike starting `songmaker.service` directly (which unconditionally runs `docker compose up -d`). Its very first-ever tick only adopts the current `HEAD` as already-deployed (see step 2) rather than deploying, so `enable --now` never surprises a running stack — if the checkout was behind `main` at install time, deploy once by hand afterward. Installing is not the acceptance step: `journalctl -t songmaker-autodeploy -n 5` after the first tick (within 2 minutes) is, confirming the timer actually fired rather than trusting `systemctl enable --now`'s exit code alone — the installer's closing output prints this exact command. If a tick died before it ever reached `logger` (rare — e.g. the shell itself failed to start), the tag-filtered view is empty by construction; `journalctl -u songmaker-autodeploy.service -n 20` (unit-filtered, not tag-filtered) still shows it.

Unattended deploy means unattended migration too: the `migrate` compose service (`alembic upgrade head`) is part of every `docker compose up`, so a merge that adds a new required `.env` variable without also adding it on the host brings up a broken stack with nobody watching the terminal to catch it before a user does. The operator's safety net is `journalctl -t songmaker-autodeploy` (and the consecutive-failure ALERT above), not a human running `docker compose up` by hand and reading the scrollback.

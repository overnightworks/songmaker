# Songmaker Architecture

## Overview

```
                    ┌─────────────────────────────────────┐
                    │        SvelteKit Frontend            │
                    │  Song editor, player, Claude chat,   │
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
                 PostgreSQL    Redis    Claude API
                 (all data)   (queues,  (chat, scoring)
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
consumes the worker's task SSE stream until `done`. The music-worker then
post-processes the worker's WAV (decode → splice → master → MP3 → DB
insert) and the job completes. See [acestep.md](acestep.md) for the
worker API surface.

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
  ├── apply repaint/cover overrides        ├── spawn scorer subprocess
  ├── scheduler.dispatch_generation:       ├── Whisper transcription
  │   ├── pick acestep-worker              ├── AudioBox aesthetics
  │   ├── INCR queue_depth (Redis)         ├── BPM, dynamics, silence, spectral
  │   ├── /load_model + /generate (HTTP)   ├── lyrical coherence (Claude)
  │   ├── consume SSE → task done          ├── save scores to DB
  │   └── DECR queue_depth (finally)       └── Job status: completed
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
  POST /songs/{id}/chat
  (multi-turn: loads history from DB,
   sends full messages array to Claude,
   stores user + assistant messages)
```

## Layers

### Frontend (`frontend/`)

SvelteKit single-page app. All state in Svelte stores.

The app shell is one navigation, not modes. A left `Rail` (264px, inline on
wide layouts, behind a drawer with a 46px trigger strip on ≤768px or any
coarse pointer) holds: the brand (a second Library link, same target as the
"Library" link below it that carries the live album/playlist count), the
context of the single open collection, and a bottom Settings link plus a user
row (username, theme toggle, Logout — inline, no popup menu;
`shell/UserRow.svelte`).
The rail context (`RailContext.svelte`) shows the open collection's header —
cover initials, title — as a button that opens that collection's interior
(`openAlbum`/`openPlaylist`, replacing history instead of pushing when a song
inside it is already open, i.e. "back to the collection"; marked
`aria-current="page"` while the interior is the visible surface) so a song
editor never needs the Library link to get back to its album. Below the
header: the open album's tracks (with a takes/pick summary per row) or the
open playlist's entries — an equalizer marks the one actually playing, a
left-accent border marks the selected/current row — and a placeholder line
when no collection is open. There is no Studio/Listen mode split and no third
library tab for
Shared; `LibraryWall.svelte` (the main-area library browser) filters by chips
`Albums · Playlists · Shared` instead, backed by `libraryFilter` in
`stores/libraryContext.ts`. Share inventory is the same complete server list
of the current user's public slugs (`GET /api/library/shares`) as before,
just reached via the Shared chip; membership, `N`, and the DELETE endpoints
are unchanged.

The single source of navigation truth for "what collection is open" is the
leaf store `stores/collection.ts` (`openCollection: {kind: 'album'|'playlist',
id} | null`), which nothing but `openAlbum`/`openPlaylist`/history restore in
`stores/navigation.ts` and `loadPlaylistDetail` in `stores/playlists.ts`
write. `playlists.ts`'s `selectedPlaylistId` is derived from it, not
independently writable. Opening a song — whatever the entry point (rail row,
search hit, `?song=` deep link, history restore) — always leaves the rail
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

`PlayerBar` is transport-only: prev/play/next, a 44px cover, title/subtitle,
the seek bar, and a "Now Playing" word-button with an up-chevron that opens
the existing `NowPlaying` overlay. The transport chrome and visualizer live in `TransportBarFrame.svelte`, a
presentational component driven by props plus the `audioPlayer` singleton
directly (never a store) — `PlayerBar` supplies the app's idle-state copy,
store-derived prev/next, and its own media-session position/playback-state
wiring; the share surface's `SharedCollection.svelte` drives the same frame
from its own `SharePlayback` owner instead, with no media-session wiring of
its own. `idlePlayTarget` (in `stores/player.ts`)
now takes the single `openCollection` instead of the old
`albumId`/`songId`/`playlist` tuple, so a song open inside an album keeps
that album as the idle Play target instead of falling back to the library
pool. Shuffle and per-track queue-skip feedback (`QueueStreamFeedback`) live
inside the `NowPlaying` surface, not the bar; the take-pool picker moved there
too (see below). At ≤640px viewport width or any coarse pointer, the bar collapses to
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
| Routes | Pages: main view, login, setup, settings, public share pages (`share/[slug]`, `share/playlist`/`song`/`gen`) | `src/routes/` |
| Components | Editor (`components/editor/`: `EditorHeader`, `SongMenu`, `RecipeChips`, `RecipePanel`, `EditorStacked`, `WriteColumn`, `TakeStrip`, `TakesList`, `TakeMenu`, `EditorSheet`), `ConfirmDialog` (generic Save/Discard/Cancel-style confirm), PlayerBar/`TransportBarFrame`, `NowPlaying`/`NowPlayingFrame`/`NowPlayingQueue`/`NowPlayingTake`, LibraryWall, `CollectionHeader`/`CollectionHeaderFrame`/Menu, shell/Rail, CoWriterPanel, `components/share/` (`SharedCollection`, `SharedFooter`), etc. | `src/lib/components/` |
| Stores | Reactive state: player, collection, libraryContext, navigation, editor, recipe, filter, jobs, auth, settings, ui | `src/lib/stores/` |
| API client | Typed HTTP client, mirrors `songmaker_cli.api_models` | `src/lib/api/client.ts`, `types.ts` |

The API client and `types.ts` are the frontend's contract with the backend. When `src/songmaker_cli/api_models/` changes, `types.ts` must match.

Frequent studio actions (theme toggle, pick/keep, playlist reorder/remove, new album/playlist, playlist-picker add) share the `[data-hitbox='frequent']` primitive in `frontend/src/lib/styles/hitbox.ts`. The visible glyph or inset face stays compact; the control's hitbox is 24×24px on a fine pointer and 44×44px when any pointer is coarse (including hybrid mouse+touch devices). PlayerBar and the share surface's transport/Now Playing frames are out of this primitive's scope.

A selected song stays on `SongDetailView`, which composes the `components/editor/` set (epic #98 slice 2). One header row (`EditorHeader`) is identical in every state: cover, editable title, and `SongMenu` (Share song / Rename / Add to playlist / Delete song) on the left; the two independent, stackable views `Co-Writer` and `Recipe` as toggles, a divider, and the single `Generate` action on the right — never a second toolbar row, never a duplicate model/count control next to Generate. `RecipeChips` (Model · Takes · BPM · Duration · Key · Voice · Seed · LM · DIT · Repaint) sit under the header and expand into `RecipePanel`'s Sound / Text / Reproduce groups with a Preset row on top; model, takes-per-generate, and any repaint/cover source are session state in `stores/recipe.ts`; version-scoped edits (lyrics, prompt, BPM, duration, key, generation params) stay in `stores/editor.ts`. Below that, `subscribeCompactLayout` (the same single switch used everywhere else) decides the Write/Takes layout: desktop shows `WriteColumn` and `TakesList` as two simultaneous columns with no tab switcher; compact shows a `Write | Takes` tab pair, defaulting to Takes. Turning on Co-Writer replaces the Write/Takes area with `WriteColumn`'s Co-Writer mode (Chat + Lyrics + a `TakeStrip` of ★/♥-badged takes side by side on desktop, Chat | Lyrics tabs with no take strip on mobile) regardless of the Write/Takes tab; on compact it opens as an `EditorSheet` instead, so the `Write | Takes` tabs stay reachable underneath. When Co-Writer and Recipe are both open on desktop, the full `RecipePanel` would push the chat column below the fold, so `RecipeChips`' expansion renders `EditorStacked` instead — one summary row per group (Sound/Text/Reproduce) with an "Edit" button that swaps in the full panel on demand. `TakesList` groups takes by version (newest first), shows a draft banner when the draft differs from the latest saved version, and a generating row while a `generate` job runs, labelled with the version actually generating (`song.version_count`, not the draft's next-version number); each take's `TakeMenu` (`role="menu"`, `data-escape-overlay`) opens with "Take · vN · k" as its first row, and each version group header has a "Delete version…" action (`handleDeleteVersion`, with its takes, behind a confirm). Clicking a take row plays it and opens Now Playing straight on its judging panel (`stores/player.ts#playTakeAndShowNowPlaying`; see the Now Playing section below). A take clicked from the Co-Writer `TakeStrip` always just plays — it never opens Now Playing. Generate is enabled from the draft (unsaved lyrics/prompt), not the last-saved song, so a freshly written song can generate before its first save; `handleSave` and `handleDeleteVersion` in `stores/editor.ts` fail loud (reject instead of swallowing) so a caller — Generate, the song menu's "Save version", or the unsaved-draft guard below — never proceeds past a failed save. Switching or leaving a song with a dirty draft (a rail row, previous/next, the breadcrumb, Escape, or the Library link — all routed through `stores/navigation.ts`) is guarded: the navigation is parked in `pendingDirtyNavigation` until `SongDetailView` resolves a Save / Discard / Cancel confirm (`ConfirmDialog.svelte`, a generic two-or-three-action dialog). `guardDirtyNavigation` in `stores/navigation.ts` is the sole gatekeeper for this — every entry point that changes `selectedSongId` (`selectSong`, `selectNeighborSong`, `backToCollection`, `openLibraryWall`, `revealPlayingSong`) routes through it rather than re-implementing the check inline. Browser Back/Forward is the one exception: `popstate` fires after the history entry has already changed, so there is no pending navigation left to cancel back into — a dirty draft is auto-saved instead before the popstate state is applied, with a failed save surfacing a toast but never blocking the already-committed navigation. Opening a song from the album interior (the track list, no song open yet) always pushes, since the visible surface changes from the list to the song editor. Once a song is open, selecting another song already inside the open collection (list clicks, previous/next) replaces the current song history entry and keeps the active Write/Takes tab; selecting a song outside the open collection (a search hit, a deep link) pushes, since the rail context changes with it. Back from the second track of an opened album therefore lands on the album, not the wall. Back leaves the song for the rail's open collection (`backToCollection`), or the wall if none is open. Go to song from Now Playing opens the song and pins the rail context to its album, then opens Takes on the playing generation. Take rows wrap pick/keep onto their own row so seed text does not paint under the rating. Settings and Admin use that same compact media: a one-control section/tab selector and stacked action rows, so every control stays reachable at 320px without sideways scroll.

Now Playing (`NowPlaying.svelte`) is a full-screen surface over the transport-only player bar, opened from `PlayerBar`'s Now Playing button (which also closes the rail drawer) or by clicking a take row in `TakesList`, which opens it straight on the This-take judging panel instead of the Queue panel. Both paths flip the same `stores/player.ts` request state (`nowPlayingOpen`, `nowPlayingPanel`), read once by `NowPlaying` on mount since PlayerBar remounts it fresh on every open. `NowPlaying` wraps `NowPlayingFrame.svelte` — the dialog shell, focus trap, cover/transport/shuffle column, and lyrics column, driven by props plus `audioPlayer` directly — and supplies its own two-tab (Queue / This take) right panel via a snippet; the share surface supplies a queue-only right panel to the same frame instead. Three columns at ≥1100px — cover/transport, the lyrics column, the right panel — stack into one column with the right panel as a bottom sheet below that width or on coarse pointers; the sheet seeds its open state once per mount, so a take-row click still lands on the This-take sheet instead of a closed trigger labelled "Queue". The Queue panel (`NowPlayingQueue.svelte`, `pool`/`onChoosePool` optional so a non-library queue context can omit the pool trio) renders `stores/player.ts#buildQueueViewModel`, a pure projection of the active queue context (library/album takes or a playlist's entries) into ordered rows labelled `vN · take k` with current/up-next; the pool trio `Picks → + Keeps → All takes` (`stores/playbackSettings.ts`, stored `keeps` migrates to `mix`) shows only for the library context. Clicking a row calls `jumpToQueueIndex`. The This-take panel (`NowPlayingTake.svelte`) is Now Playing's only write surface: pick/keep/rate/pin-seed route through `stores/takeActions.ts`, the single mutation owner for a take's judged state, shared with the editor's `TakesList`/`TakeMenu` via `contexts/generation-actions.ts#takeActionsFor`. "Use as reference" hands the take to `stores/recipe.ts`'s `pendingSource`, closes Now Playing, and navigates to the song (`stores/navigation.ts#revealPlayingSong`); `SongDetailView` only applies `pendingSource` once its `song_id` matches the song actually open, opening the Recipe panel on it as a repaint source, and drops it if the dirty-draft guard's confirm is cancelled instead of applying it to the song the user stayed on. It resolves the playing generation against `songList` component-locally (`$derived` + `$effect` calling `ensureGenerationsLoaded`) and stays absent until resolved. Sung-vs-lyrics deviations tokenise both texts with `utils/lyrics-normalize.ts` (the #45 contract) and diff them word-wise via `utils/diff.ts#computeDiffByKey`. Normalization casefolds — not merely lowercases — so a German "Straße" and a Whisper transcript's "strasse" register as the same token (issue #133); JS has no native `casefold()`, so the module hand-covers the small set of Unicode full-case-folding entries (German eszett, Greek final sigma) that diverge from `toLowerCase()` for text this product's lyrics can plausibly contain.

The lyrics column (`NowPlayingLyrics.svelte`) follows playback once the playing take carries `whisper_cues` (#45, contract confirmed on #52, word timestamps added on #142). `utils/lyrics-align.ts#alignLyricsToCues` takes one of two paths, chosen by what the take was scored with. **Word path** — a take scored with word timestamps carries a word stream (`cue.words`); lyric lines are walked in order and each takes the best-matching run of still-unconsumed words. The interval is then trimmed to the words of that run which take part in a matching block against the line, so a line always starts on its own first sung word even when the run had to begin on foreign words. The search window starts `WORD_STREAM_LOOKAHEAD` (24) words past the previous match and grows a step at a time until the take offers a reading of the line or the stream ends, so a long adlibbed or mistranscribed stretch cannot hide the lines behind it; assignment stays forward-only. Neighbouring lines that claim the same words are resolved as a pair — a line that is the opening of the next one must win by `AMBIGUITY_MARGIN` to keep those words, and when neither wins both stay dark. **Cue window fallback** — a take scored before word timestamps carries only segment cues, and a segment follows breathing pauses rather than line breaks (the Nachtstrom take: 33 segments over 56 lines), so cues are walked in playback order and each takes the best-matching run of up to `MAX_WINDOW_LINES` (3) still-unconsumed lines. Every line of that run carries the whole cue span and they light together: nothing in such a take says where inside a cue one line ends and the next begins, and #45 forbids inventing it — only a re-score (#132) buys real per-line timing. Both paths share one accept rule: text is normalised by `utils/lyrics-normalize.ts`'s token rules, lines are split on `/\r?\n/` and blank plus `[section]`-marker lines never align, a lyric line of at most `VERBATIM_MAX_TOKENS` (2) words is only lit where the transcript carries exactly that text (a character ratio cannot tell "yeah" from a sung "year"), the winner must clear `MIN_RATIO` (0.72), and it must beat every rival by `AMBIGUITY_MARGIN` (0.12) — a rival being a candidate that overlaps neither the winner nor any word-for-word repeat of the winner's text. Overlapping candidates are one rendition seen through a shifted window, and a repeat of the same words is not independent evidence of where a line was sung, nor is a shifted window around such a repeat; a chorus line is therefore never blocked by its own repeats and monotone consumption decides which rendition each of them takes. A differently-worded reading elsewhere in the take does rival it. Anything short of the rule leaves the line dark; a missed highlight is a gap, a wrong one is a lie. Similarity is `utils/sequence-matcher.ts`'s `SequenceMatcher`, a faithful TypeScript port of Python's `difflib.SequenceMatcher` (including the ≥200-char autojunk popular-element filter). `scripts/lyric_alignment_golden.py` is the reference: it holds both the Python-computed ratios and a Python reference implementation of both alignment paths, and `lyrics-align.fixtures.json` pins the TypeScript side to its intervals fixture by fixture, including the cases that must stay dark. `activeLyricLineIndices` returns every line covering `audioPlayer.currentTime` and none in a gap, and the first of them is scrolled into view (instant under `prefers-reduced-motion`, smooth otherwise). Cues and transcript come from the take resolved against `songList` (`playingGeneration`, not `info`, per the #45 amendment), so a thin library-pool item stays on static lyrics until `ensureGenerationsLoaded` fills in its real `whisper_cues`; a take with `whisper_text` but no cues at all (scored before #44 landed) shows a "Re-score this take to follow the lyrics." hint alongside the static text. `SharedCollection.svelte` never passes cues to `NowPlayingFrame`, so the public share surface always renders the static fallback.

The public share pages (`/share/[slug]`, `/share/playlist/[slug]`,
`/share/song/[slug]`, `/share/gen/[slug]`) render on the same collection
surface as the logged-in app instead of a hand-rolled listening UI: each
`+page.svelte` fetches its `/shared/*` payload, adapts it with
`lib/share/sharedCollection.ts` (`fromSharedAlbum`/`fromSharedPlaylist`/
`fromSharedSong`/`fromSharedGeneration` → one `SharedCollectionView`; a song
or take share becomes a one-track collection; `playableTracks()` drops rows
whose `audio_url` is `null` — a listener sees a finished album, not disabled
"--" rows), and renders `lib/components/share/SharedCollection.svelte`. That
component composes `CollectionHeaderFrame` (read-only, no `…` menu),
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
returning to stream mode when disabled. Classic-mode rows show no duration
and Now Playing shows the no-lyrics empty state — an accepted gap tracked by
issue #128 to add `audio_duration`/`lyrics`/`generation_id` to the share
payloads.

### Backend (`src/songmaker_cli/`)

| Layer | Responsibility | Key files |
|-------|---------------|-----------|
| HTTP | FastAPI app, CORS, security headers, body size limit, SPA fallback | `server.py` |
| Auth | Session dependencies, login/setup/logout, password change, brute-force protection | `middleware/auth.py`, `auth_api.py`, `auth.py` |
| API | REST endpoints split by domain: albums, songs, generations, playlists, library search/shares, LoRAs, chat, settings, admin | `api.py` (aggregator), `album_api.py`, `song_api.py`, `generation_api.py`, `playlist_api.py`, `library_api.py`, `lora_api.py`, `chat_api.py`, `settings_api.py`, `admin_api.py` |
| Helpers | Shared access checks, rate limiting, slug generation | `api_helpers.py` |
| Models | Pydantic request/response with `from_orm()` | `api_models/` |
| Jobs | Background generation + scoring runners | `jobs/` (package: `_runtime.py`, `generation.py`, `scoring.py`, `model_lifecycle.py`) |
| Worker | arq-based job queues (music + scoring), scheduler dispatch | `music_worker.py`, `scoring_worker.py`, `worker_base.py`, `scheduler.py`, `arq_pool.py` |
| ACE-Step worker pool | Peer containers serving ACE-Step over HTTP/SSE | `src/acestep_worker/` (top-level package, separate from `songmaker_cli`) |
| Generation post-process | Decode worker WAV → splice → master → MP3 | `generate.py`, `jobs/generation.py:post_process_generation` |
| Config | ACE-Step config building (merges defaults + user + song params) | `config.py` |
| DB | SQLAlchemy ORM models, query functions, engine init | `db/` |
| Scoring | Fault-isolated pipeline: text accuracy, dynamics, BPM, silence, spectral, aesthetics, coherence | `scoring/` |
| Claude | API + CLI backends for chat and lyrical coherence | `claude/provider.py` |
| CLI | Thin HTTP client to the same API | `main.py`, `cli_client.py` |

### Engine packages (`src/`)

| Package | Purpose |
|---------|---------|
| `acestep_engine` | HTTP client for the ACE-Step server (generate, poll, model info) |
| `audio_engine` | Mastering chain (multiband compression, stereo widening, LUFS normalization, MP3 encoding), WAV I/O |

## Data Model

```
User (username, role: admin|user, bcrypt hash)
  ├── Album (title, artist, share_slug?, is_shared — owned via created_by)
  │     └── Song (title, track_number, share_slug?, is_shared)
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

Also: UserSession, LoginAttempt, Playlist (share_slug?, is_shared), PlaylistEntry,
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
| POST | `/api/generations/{id}/score` | user | Submit scoring job (→ scoring queue) |
| POST | `/api/generations/{id}/rate` | user | Rate a generation |
| POST | `/api/generations/{id}/pick` | user | Pick best generation |
| GET | `/api/jobs/{id}` | user | Poll job status (includes queue_position) |
| POST | `/api/jobs/{id}/cancel` | user | Cancel a queued or running job (409 if not active). Terminal; later progress/finalize cannot overwrite. Does not stop in-flight GPU inference. |
| POST | `/api/songs/{id}/chat` | user | Send chat message (multi-turn, rate-limited) |
| GET | `/api/songs/{id}/chat` | user | Load chat history |
| DELETE | `/api/songs/{id}/chat` | user | Clear chat history |
| GET | `/api/chat/recent` | user | Songs with active chats |
| POST | `/api/chat/turn` | user | Co-writer turn — SSE stream of assistant text, tool calls, and a final event with persisted messages. Injects current song, durable memory, server-resolved @-mentions, and the relevant take's whisper/pick/keep/scores (`current_generation_id`). Unknown mention or generation IDs 404; a take for the wrong song or a non-playable take is 422. Provider is the persisted studio setting (`claude`, `grok`, or `codex`); missing credentials fail that provider by name. |
| GET | `/api/settings/cowriter` | user | Co-writer provider, selected model, and live model catalogs from each provider or CLI |
| PUT | `/api/settings/cowriter` | admin | Persist co-writer provider and a model id that exists in that provider's live catalog |
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
    → build config (model defaults + admin defaults + preset + song params)
    → scheduler.dispatch_generation()
      → pick an online acestep-worker
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
        Deferred CPU scorers (lyrical_coherence) wait for shared_data from GPU
        Each scorer fault-isolated: one failure does not block others
      Parent kills subprocess on timeout (SIGKILL), freeing GPU memory
    → save scores + whisper_text + whisper_cues to DB
  → Job status: completed
```

`whisper_cues` is a JSON list of `{start, end, text}` from faster-whisper segments (start/end in seconds), each optionally carrying `words`, the same shape one level finer, from `word_timestamps=True` (#142). `null` means never scored or a legacy row; a list (including `[]`) means text_accuracy ran and stored whatever usable cues it produced. A cue without `words` was scored before word timestamps existed and gets them only through a re-score (#132) — the key is omitted rather than stored as `null`, so those rows keep their original shape. `whisper_text` is the same cue texts joined with newlines. Missing timings are not invented.

## Worker Architecture

```
                         ┌─ arq:queue:music ──→ Music Worker(s)
  API ─→ route by type ──┤
                         └─ arq:queue:scoring → Scoring Worker(s)

  Chat runs inline in the API process (no arq queue).
```

**Music worker** (`music_worker.py`):
- Thin orchestrator — no GPU, no ACE-Step process. Dispatches generation jobs
  to acestep-worker peer containers via the scheduler (`scheduler.py`).
- Handles `generate` and `load_model_on_worker` tasks
- `max_jobs=2` (concurrent SSE consumers; the actual generation runs on the
  acestep-worker)
- Cron: recovers stale generate jobs every 2 minutes, audits orphaned audio files
- Post-processes worker WAV → mastered MP3 → DB row in `asyncio.to_thread`

**Scoring worker** (`scoring_worker.py`):
- Owns scorer subprocess (Whisper, AudioBox, Claude coherence)
- Handles `score` tasks
- Device configurable via `SCORING_DEVICE` env var (`cpu` or `cuda`)
- `max_jobs=1` (default, configurable via `SCORING_MAX_JOBS`)
- Cron: recovers stale score jobs every 2 minutes

**Shared infrastructure** (`worker_base.py`):
- DB singleton with thread-safe initialization
- Path helpers (`_audio_dir`, `_data_dir`)
- Timeout constants, terminal status set
- Common startup (logging configuration, stale-job recovery)
- Common shutdown (per-type stale recovery with Redis advisory lock, DB disposal)
- Orphaned file audit (`audit_orphaned_files()`) — logs disk files with no DB record

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

Exported metrics: `songmaker_http_requests_total`, `songmaker_http_request_duration_milliseconds_total`, `songmaker_active_sessions`, `songmaker_jobs_total`, `songmaker_job_duration_seconds`, `songmaker_queue_depth`, `songmaker_gpu_vram_megabytes`.

Health endpoint at `/health` reports:
- `music_worker`: running/stopped
- `scoring_worker`: running/stopped
- `music_queue_depth`, `scoring_queue_depth`: jobs waiting per queue
- `db`, `redis`, `acestep`: component health
- `status`: "ok" or "degraded" (degraded if both workers down, DB down, or Redis down)

## Backup & Restore

`scripts/backup.sh` dumps PostgreSQL + copies the audio Docker volume to `BACKUP_DIR` (default `/mnt/backup/songmaker`). `scripts/restore.sh` restores both. `scripts/backup-list.sh` lists snapshots. See [scripts/BACKUP.md](../scripts/BACKUP.md) for setup instructions.

DB and audio must be backed up and restored together — one without the other leaves orphaned records or unreachable files.

Album covers live as files on that same audio volume (`covers/{album_id}/` for original plus card and detail derivatives). Song covers live beside them at `song-covers/{song_id}/` — not under `covers/songs/`, because an album slug can be `songs`. They are not stored as Base64 in PostgreSQL; the album or song row only stores `cover_key`. Authenticated song JSON advertises `cover` only from that song's key; display inheritance of album art is a UI concern. Backup/restore of the audio volume therefore includes covers with no extra volume.

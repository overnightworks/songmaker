# Target UI — Library · Editor · Now Playing

Concept note for Epic [#98](https://github.com/FlexOr2/songmaker/issues/98). Confirmed by the operator on 2026-08-22 as the target design; this folder makes it readable without opening the original Claude Design canvas (builder agents cannot open `claude.ai` links).

## Purpose

The target UI replaces the current Studio/Listen mode split with one navigation and no modes. Three surfaces, each with a single job: **Library** (find an album, playlist, or song), **Editor** (write lyrics/prompt, generate, judge takes), **Now Playing** (listen full-screen, judge a take in depth). The left rail is navigation only — `Library`, the context block of whatever album/playlist is open (its tracks, an equalizer marker on the playing song), and Settings/User at the bottom. The rail carries no actions, no Studio/Listen toggle, and no separate "Shared" entry (Shared is a filter chip on the Library wall instead).

## Boards → surface → slice

| Board (`.html`) | Surface | Slice issue |
|---|---|---|
| `Main.html` | Library shell (rail + wall + open album/playlist detail) | [#99](https://github.com/FlexOr2/songmaker/issues/99) |
| `WallA.html` | Library wall (Albums · Playlists · Shared chips, sort, search) | [#99](https://github.com/FlexOr2/songmaker/issues/99) |
| `Mobile390.html` | Library shell, mobile width | [#99](https://github.com/FlexOr2/songmaker/issues/99) |
| `MobileLibrary.html` | Library wall, mobile | [#99](https://github.com/FlexOr2/songmaker/issues/99) |
| `MobileDrawer.html` | Rail as a drawer, mobile | [#99](https://github.com/FlexOr2/songmaker/issues/99) |
| `Editor.html` | Editor, Write tab, Recipe collapsed to chips | [#100](https://github.com/FlexOr2/songmaker/issues/100) |
| `EditorCoWriter.html` | Editor, Co-Writer mode of the Write column | [#100](https://github.com/FlexOr2/songmaker/issues/100) |
| `EditorRecipe.html` | Editor, Recipe panel expanded (Sound / Text / Reproduce) | [#100](https://github.com/FlexOr2/songmaker/issues/100) |
| `EditorStacked.html` | Editor, Co-Writer + Recipe stacked (both toggles on) | [#100](https://github.com/FlexOr2/songmaker/issues/100) |
| `MobileEditor.html` | Editor, mobile (Write \| Takes tabs) | [#100](https://github.com/FlexOr2/songmaker/issues/100) |
| `MobileTakes.html` | Editor, Takes tab, mobile | [#100](https://github.com/FlexOr2/songmaker/issues/100) |
| `MobileCoWriter.html` | Editor, Co-Writer sheet, mobile | [#100](https://github.com/FlexOr2/songmaker/issues/100) |
| `MobileRecipe.html` | Editor, Recipe sheet, mobile | [#100](https://github.com/FlexOr2/songmaker/issues/100) |
| `NowPlaying.html` | Now Playing, full screen | [#101](https://github.com/FlexOr2/songmaker/issues/101) |
| `NowPlayingJudge.html` | Now Playing, own-take judging panel (scores, deviations, ★/♥, seed) | [#101](https://github.com/FlexOr2/songmaker/issues/101) |
| `NowPlayingMobile.html` | Now Playing, mobile | [#101](https://github.com/FlexOr2/songmaker/issues/101) |
| `NowPlayingDocked.html` | Now Playing docked beside the editor, desktop | [#140](https://github.com/FlexOr2/songmaker/issues/140) |

Slice order: #99 (shell) first, then #100 (Editor) and #101 (Now Playing) in parallel, then [#102](https://github.com/FlexOr2/songmaker/issues/102) (acceptance: cross-surface browser evidence, deadweight audit, docs update, closes the epic).

## Locked-in rules

Decisions from the epic body (2026-08-22), translated to English:

- **Rail** is navigation only: `Library` · context block of the open album/playlist (tracks, equalizer marker on the playing song) · Settings/User at the bottom. No actions in the rail, no Studio/Listen toggle, no standalone Shared entry.
- **Library wall**: chips `Albums · Playlists · Shared` (Shared is a filter), a sort dropdown, search. Album and playlist open the same context block and the same detail page.
- **Action model**: actions live on the object (tile, row, header) — this reopens the #93 decision "Play only in the player." Only the primary action is ever visible on an object; everything else sits in that object's `…` menu, whose first row names the object. Share is never a standalone icon.

  | Object | Primary action (visible) | `…` menu first row |
  |---|---|---|
  | Album | Play | "Share album" |
  | Playlist | Play | "Share playlist" |
  | Song | Generate | "Share song (its pick)" |
  | Take | ★ Pick / ♥ Keep | "Share take" |

  Rail rows carry no actions. No help text under Recipe chips (hover + tooltip only).
- **Player bar** is transport-only: Shuffle · Prev · Play · Next · Cover · Title · Progress · "Now Playing". The pool trio lives in Now Playing's Queue panel, not the bar. (Shuffle moved to the bar in #141; the bar's "Now Playing" is a disclosure toggle for the docked panel and a dialog trigger for the full surface — #140.)
- **Pool** is one inclusivity scale: `Picks` (default) → `+ Keeps` → `All takes`. "Keeps-only" is dropped; the API value `mix` (Pick ∪ Keep) stays and now means `+ Keeps`.
- **Editor**: tabs Write | Takes. Recipe collapses to labeled chips (Model · Takes · BPM · Duration · Key · Voice · Seed · LM · DiT · Repaint); expands into Sound / Text / Reproduce with a preset row on top. Takes render compact (Play · Version · Score · ★/♥ · Duration), grouped by version, with a draft banner. Version chips and the take inspector are dropped. Co-Writer is a mode of the Write column (Chat | Lyrics tabs); takes there collapse into strips with ★/♥ badges.
- **Views vs. Action**: one header row, identical across every Editor state. Left: title/subtitle with the object's actions next to it (Share, `…` menu). Right: the views Co-Writer · Recipe (independent, stackable toggles), a divider, then the single action Generate. No second toolbar row. Model and takes-per-generate are Recipe settings (chips under the title, Sound group in the panel) — never duplicated next to the Generate button. Settings → Generation owns presets/defaults; the Recipe panel's top row is "Preset: Default ▾ · Save as preset" to apply one. Mobile: views become icons at the top (opening sheets), the action is a fixed bottom bar.
- **Now Playing** (revised by #140, 2026-08-23): two surfaces, one instance. From 1440px up (`NOW_PLAYING_DOCK_MIN_PX` — the width at which the editor can spare 400px without pushing its take actions out of reach; #185 lowers it) it **docks** as a 400px column beside the rail and the editor — cover, running lyrics, Queue / This take — and neither covers the workspace nor traps focus. "Expand" grows it to the full screen; Escape shrinks it back, then closes it. The chosen mode is remembered. Below that threshold, or on a coarse pointer, it is full screen as before. Cover, running lyrics (static here; live sync comes from #45), queue with the Picks/+Keeps/All-takes pool trio, and Shuffle. For the user's own takes: scores, sung-vs-lyrics deviations, ★/♥, seed pinning, reference. Now Playing has no write functions.
- **One player, never two** (#140): the docked panel has no transport of its own — the bar beside it keeps seek, shuffle, prev/next and play. The full surface carries the only transport, and the bar is hidden underneath it on desktop and mobile alike.
- **Mobile**: rail becomes a drawer; Editor tabs are Write | Takes; Recipe and Co-Writer open as sheets; a 64px bar; Now Playing is full screen. No third tab, no third column anywhere.
- **Copy and icons**: all UI copy is English. Icons are reserved for Play, Share, Search, Delete, and the `…` menu — navigation is always a word, never an icon alone.

## Viewing a board

Each `.html` file is self-contained (inline styles, Google Fonts via `@import`) — open it directly:

```bash
open plans/target-ui/Editor.html   # or your platform's file opener
```

For a reproducible screenshot, use Playwright at the two reference widths: desktop 1440×900, mobile 390×844 (or 320 for the narrowest supported width per the epic's "Done when").

## Lifecycle

This folder is deleted once Epic #98 closes (per the repo's plan-writing convention — concept notes for in-flight work are removed when the tracking issue closes).

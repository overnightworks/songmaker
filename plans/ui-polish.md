# UI Polish Plan

## Goal

Professional, consistent UI across the entire app: proper sizing via rem, clear action hierarchy with icons, consistent layout in every view, multi-select for bulk operations.

## Principles

- **One knob for sizing**: `html { font-size: 15px }` — change this one value to scale everything. All sizes in rem.
- **Action hierarchy**: List views are for scanning — minimal actions. Detail views show everything. No hidden overflow menus.
- **Consistent everywhere**: Same patterns in every view — song, album, playlist, generation, chat, shared/public pages.
- **No icon library**: Inline SVG component (`Icon.svelte`), paths sourced from Lucide (MIT). Zero dependencies.

---

## Phase 1: Sizing — rem migration + bump

Touch every component in one pass. For each file: convert hardcoded px font-sizes to rem, bump sizes, increase spacing.

### 1a. Global baseline (`app.css`)

Set root font-size:
```css
html { font-size: 15px; }
```

Update CSS custom properties to rem:
```
--btn-font-size: 0.93rem       (was 0.85rem ≈ 13.6px → now 14px)
--btn-font-size-sm: 0.8rem     (was 0.75rem ≈ 12px → same)
--btn-padding-pill: 0.55rem 1.3rem
--btn-padding-sm: 0.25rem 0.7rem
--input-font-size: 1rem         (was 0.85rem → now 15px, fixes iOS zoom)
--input-padding: 0.6rem 0.8rem  (was 0.5rem 0.7rem)
--row-gap: 0.6rem               (was 8px)
```

Add new token:
```
--label-font-size: 0.8rem       (12px — all uppercase labels use this)
```

Mobile breakpoint (max-width: 768px) — keep bumping to slightly larger for touch:
```
--btn-font-size: 1rem
--input-font-size: 1.07rem
--input-padding: 0.65rem 0.85rem
```

### 1b. Component-by-component conversion

Target sizes (at 15px root):

| Role | rem | Actual | Used for |
|---|---|---|---|
| Tiny label | 0.7rem | 10.5px | Score labels, seed text, model badges |
| Label | var(--label-font-size) = 0.8rem | 12px | Field labels, section titles, version headers |
| Small body | 0.87rem | 13px | Tab buttons, back button, params, secondary text |
| Body | 1rem | 15px | Input text, textarea text, chat messages, lyrics |
| Large | 1.2rem | 18px | Generation heading, score values, rating number |
| Title | 1.73rem | 26px | Song title, album title |

**Components to convert** (every `<style>` block):

| Component | Key changes |
|---|---|
| `SongDetailView.svelte` | Song title 22px→1.73rem, tabs 11px→0.87rem, back btn 11px→0.87rem, status 11px→0.75rem |
| `SongEditor.svelte` | Labels 10px→var(--label-font-size), inputs 13px→1rem, lyrics 14px→1rem, gaps 10px→1rem, label-input gap 4px→0.4rem |
| `ParamControls.svelte` | Labels 10px→var(--label-font-size), inputs 12px→1rem, grid gap 8px→0.7rem |
| `GenerationSettings.svelte` | Toggle 10px→var(--label-font-size), ref-label 10px→var(--label-font-size), override badge 9px→0.6rem, body gap 8px→0.7rem |
| `GenerationsList.svelte` | Version header 10px→var(--label-font-size), gen-name 13px→0.93rem, seed 10px→0.7rem, model badge 9px→0.6rem |
| `GenerationDetail.svelte` | Heading 18px→1.2rem, section-title 11px→var(--label-font-size), score-label 9px→0.7rem, score-value 18px→1.2rem, rating-label 9px→0.7rem, rating-number 18px→1.2rem, params 11px→0.87rem, notes 12px→1rem, whisper 13px→0.87rem |
| `AlbumDetailView.svelte` | Title 22px→1.73rem, subtitle 12px→0.87rem, back btn 11px→0.87rem |
| `PlaylistDetailView.svelte` | Same pattern as album |
| `PresetChips.svelte` | Chip text 10px→0.75rem, padding 2px 8px→0.2rem 0.6rem, mode tag 8px→0.55rem |
| `VersionTimeline.svelte` | Labels and markers — convert all px font-sizes to rem |
| `PlayerBar.svelte` | Track title, time display, controls — convert all |
| `SongList.svelte` | Search, list items — convert all |
| `SongNode.svelte` | Song name, gen count — convert all |
| `AlbumNode.svelte` | Album name, song count — convert all |
| `ClaudeChat.svelte` | Header 13px→0.87rem, recent items 11px→0.75rem, mention tags 10px→0.7rem |
| `ChatInput.svelte` | Input 12px→1rem, send btn 16px→1.07rem |
| `MessageList.svelte` | Messages 12px→1rem (chat text is way too small right now), apply-btn 10px→0.7rem |
| `SharedPlayer.svelte` | Track title 13px→0.87rem, detail 10px→0.7rem, time 12px→0.8rem |
| `ShareButton.svelte` | Icon size 14px→0.93rem |
| Share route pages | Already mostly rem — convert remaining px (play-indicator 14px, spinner 14px) |
| `LyricsDiff.svelte` | Convert any px font-sizes |
| `CoverDialog.svelte` | Convert any px font-sizes |
| `RepaintDialog.svelte` | Convert any px font-sizes |
| `CreateForm.svelte` | Convert any px font-sizes |

Also convert padding/gap values that should scale with text. Keep in px: border-radius, border-width, box-shadow, icon dimensions (use the `size` prop on Icon component instead).

---

## Phase 2: Layout consistency

### 2a. Detail panels — all views

Every detail/content panel gets:
```css
max-width: 1200px;
/* no margin: 0 auto — left-aligned */
padding: 1.2rem 1.5rem calc(var(--player-height) + 1.2rem);
```

Apply to:
- `SongDetailView.svelte` `.detail-panel` — currently `max-width: 1000px; margin: 0 auto`; remove centering, widen
- `SongDetailView.svelte` `.detail-panel.chat-active` — remove the max-width override, keep overflow rule
- `AlbumDetailView.svelte` — add max-width if missing
- `PlaylistDetailView.svelte` — add max-width if missing
- `routes/settings/+layout.svelte` `.settings-content` — check and align

### 2b. Padding consistency

Ensure all detail panels use the same padding pattern. Currently SongDetailView has `16px 20px`, mobile `12px 12px`. Convert to rem, unify across views.

---

## Phase 3: Icon system + action buttons

### 3a. Create `Icon.svelte`

`lib/components/Icon.svelte`:
- Props: `name: string`, `size: number = 16`, `class?: string`
- Inline SVG, `viewBox="0 0 24 24"`, `stroke="currentColor"`, `fill="none"` (Lucide style)
- Inherits color from parent

Icons needed:

| Name | Visual | Used for |
|---|---|---|
| `trash` | Trash can | Delete anything |
| `heart` | Heart outline | Keep (inactive) |
| `heart-filled` | Heart solid | Keep (active) |
| `star` | Star outline | Pick (inactive) |
| `star-filled` | Star solid | Pick (active) |
| `list-plus` | List + plus | Add to playlist |
| `refresh-cw` | Circular arrows | Re-score |
| `paintbrush` | Brush | Repaint |
| `layers` | Stacked layers | Cover |
| `pencil` | Pencil | Rename |
| `link` | Chain link | Share (active) |
| `share` | Arrow up-right | Share (inactive) |
| `check` | Checkmark | Confirm state |
| `play` | Triangle | Play button |
| `pause` | Two bars | Pause button |
| `skip-forward` | Skip | Player next |
| `skip-back` | Skip back | Player prev |
| `fast-forward` | Fast forward | Player seek |
| `rewind` | Rewind | Player seek back |
| `pin` | Pin | Pinned seed |
| `x` | X mark | Close/clear/remove |
| `check-square` | Checked checkbox | Multi-select (selected) |
| `square` | Empty checkbox | Multi-select (unselected) |
| `chevron-up` | Up arrow | Move up in list |
| `chevron-down` | Down arrow | Move down in list |

### 3b. Create `ActionButton.svelte`

`lib/components/ActionButton.svelte`:
- Props: `icon: string`, `activeIcon?: string`, `label: string` (title tooltip), `active?: boolean`, `destructive?: boolean`, `confirm?: boolean`, `showLabel?: boolean` (default false), `disabled?: boolean`, `onclick: () => void`
- Renders: `<button title={label}>` → `<Icon>` + optional text label
- `showLabel: true` → icon + text (for detail views)
- `showLabel: false` → icon only (for list views)
- `active: true` → uses `activeIcon` if provided, highlighted border/color
- Confirm pattern: first click → icon swaps to `check`, border turns red. Second click within 3s → execute. Auto-reset on timeout or click-outside.
- Destructive styling: hover turns red

### 3c. Action hierarchy — what goes where

**Generation list card** (compact, for scanning):

```
[▶ Play]  Gen16 ★ seed:882640419 ♡  sft     [scores if any]
```

Minimal. Play button, gen info with pick star and keep heart as inline indicators/toggles. Click the card → detail view for all actions. No action buttons, no overflow menu on the card itself.

Pick (star) and Keep (heart) are tiny inline toggles within the gen-info area, not separate button elements — they're state indicators you can click, not action buttons.

**Generation detail view** (spacious — icon+text, grouped by intent):

```
GENERATION 16                                                    v13  seed:882640419
[★ Album Pick] [♡ Keep]     [🖌 Repaint] [📑 Cover]     [🔄 Score] [📋 Playlist] [🔗 Share] [🗑 Delete]
──── state ────               ── create ──                ──────────── manage ─────────────────
```

Three visual groups separated by wider gaps or a subtle divider:
1. **State toggles**: Pick, Keep — these describe what this generation IS
2. **Creation actions**: Repaint, Cover — these create new audio from this generation
3. **Management**: Score, Add to Playlist, Share, Delete — organizational

All visible with icon+text. No overflow. Destructive (Delete) last with confirm pattern.

**Song header**:

```
Left:  SONG TITLE  Artist
Right: [Generate ×1] [📋 Playlist] [🔗 Share] [🗑 Delete Song]
```

Generate stays as the prominent gradient pill button. Playlist, Share, Delete as icon-only ActionButtons with title tooltips. Delete uses confirm pattern. No Clean Up button — replaced by multi-select in Phase 5.

**Album header**:

```
Left:  ALBUM TITLE  subtitle
Right: [▶ Play Album] [📋 Playlist] [🔗 Share] [🗑 Delete Album]
```

Same pattern. No Clean Up — multi-select handles this.

**Playlist header**:

```
Left:  PLAYLIST TITLE  N tracks
Right: [▶ Play] [🔗 Share] [✏️ Rename] [🗑 Delete]
```

### 3d. Migrate each view

**`GenerationDetail.svelte`**:
- Remove OverflowMenu import and usage
- Replace Pick/Keep text buttons with `<ActionButton icon="star" activeIcon="star-filled" active={gen.is_picked} showLabel />`
- Add Repaint, Cover as visible ActionButtons with `showLabel`
- Add Re-Score, Add to Playlist, Share, Delete as visible ActionButtons with `showLabel`
- PlaylistPicker anchors to the playlist ActionButton
- Visual grouping: three flex groups with 1.5rem gap between groups, 0.5rem within groups

**`GenerationsList.svelte`**:
- Simplify cards: remove Score/Repaint/Cover text buttons entirely
- Pick star and Keep heart become small inline toggles in the gen-info area (not ActionButton — just small clickable icons within the text flow)
- Remove OverflowMenu entirely — no `...` on cards
- Cards are clickable → detail view for all actions
- Mobile: same layout, cards already simple enough

**`SongDetailView.svelte`**:
- Remove OverflowMenu import and usage
- Remove Clean Up button (replaced by multi-select in Phase 5)
- Replace with ActionButtons: Playlist (list-plus), Share, Delete (trash, confirm+destructive)

**`AlbumDetailView.svelte`**:
- Remove OverflowMenu
- Remove Clean Up button
- Replace with ActionButtons: Playlist (list-plus), Share, Delete (trash, confirm+destructive)

**`PlaylistDetailView.svelte`**:
- Remove OverflowMenu
- Replace with ActionButtons: Rename (pencil), Delete (trash, confirm+destructive)
- Replace ↑/↓/× text buttons in playlist entries with Icon components (chevron-up, chevron-down, x)

**`ShareButton.svelte`**:
- Replace emoji glyphs with `<Icon name="link" />` (shared) / `<Icon name="share" />` (not shared)
- Keep toggle logic

**`PlayerBar.svelte`**:
- Replace text characters (▶, ⏸, ⏮, ⏭, ⏪, ⏩) with Icon components

### 3e. Delete `OverflowMenu.svelte`

No longer used anywhere. Delete the file.

### 3f. Add icons to share route pages

Replace text-based play indicators in share route `+page.svelte` files with `<Icon>` components.

---

## Phase 4: Edit tab layout

### 4a. Reorder fields

In `SongEditor.svelte`, non-diff branch:
```
Current:  Style Prompt → BPM/Duration/Key → GenerationSettings → Lyrics
New:      Style Prompt → BPM/Duration/Key → Lyrics → GenerationSettings
```

### 4b. Auto-expand Generation Settings

In `GenerationSettings.svelte`:
- `<details>` → `<details open>`
- Keep collapsible — user can close it, but default is open

---

## Phase 5: Multi-select + bulk delete

Replaces the old Clean Up button with a transparent, user-controlled selection system.

### 5a. Selection store

Create `lib/stores/selection.ts`:
- `selectedIds: Writable<Set<string>>` — set of selected generation IDs
- `selectionMode: Writable<boolean>` — whether multi-select is active
- Helper functions:
  - `toggleSelection(id: string)` — add/remove from set
  - `selectAll(ids: string[])` — select multiple
  - `selectAllUnkept(generations: GenerationItem[])` — select all where `!is_picked && !is_kept` (this is what Clean Up used to do, but now the user sees exactly what's selected)
  - `clearSelection()` — empty set and exit selection mode
  - `enterSelectionMode()` / `exitSelectionMode()`

### 5b. Selection UI in GenerationsList

**Entering selection mode**: Long-press (touch) or Ctrl+Click (desktop) on any generation card activates selection mode. When selection mode is active:

- Each card shows a checkbox (left side, before play button): `<Icon name="check-square" />` or `<Icon name="square" />`
- Clicking a card toggles its selection (instead of navigating to detail)
- Play button still works (separate click target)
- Selected cards get a subtle highlight (accent border or background tint)

**Selection toolbar**: When `selectedIds.size > 0`, a sticky bar appears at the bottom of the generation list (above the player bar):

```
[☐ Select All Unkept]  N selected  [🗑 Delete Selected]  [✕ Cancel]
```

- **Select All Unkept**: Selects all generations where `!is_picked && !is_kept`. This replaces the old Clean Up — same logic, but the user sees exactly what will be affected and can deselect individuals before deleting.
- **Delete Selected**: Confirm pattern — first click turns to "Confirm delete N?" with red styling, second click executes. Calls bulk delete endpoint.
- **Cancel**: Clears selection, exits selection mode.

### 5c. Backend: bulk delete endpoint

Add to `generation_api.py`:
- `POST /api/generations/bulk-delete` — accepts `{ generation_ids: string[] }`
- Validates ownership of all generations
- Deletes all in one transaction
- Returns `{ deleted: number, paths: string[] }` for file cleanup

Add to `db/queries/generations.py`:
- `bulk_delete_generations(session, generation_ids, user_id)` — ownership check + delete

Add to `api_models.py`:
- `BulkDeleteRequest` — Pydantic model with `generation_ids: list[str]`
- `BulkDeleteResponse` — `deleted: int`

Add to frontend `client.ts`:
- `bulkDeleteGenerations(ids: string[]): Promise<{ deleted: number }>`

Run `python scripts/generate_types.py` to regenerate TypeScript types.

### 5d. Remove Clean Up

- Remove `cleanupSong` from `client.ts` (or keep as deprecated — check if used elsewhere)
- Remove `cleanup_song` endpoint from `song_api.py`
- Remove Clean Up button from `SongDetailView.svelte` (already done in Phase 3)
- Remove Clean Up button from `AlbumDetailView.svelte` (already done in Phase 3)
- Keep `cleanup_song` DB query function for now — could be used by admin/CLI

### 5e. Tests

- Test `bulk_delete_generations` query function: ownership check, deletion, path collection
- Test `POST /api/generations/bulk-delete` endpoint: auth, validation, success, partial ownership (should reject entirely, not partial delete)
- Test frontend selection store: toggle, selectAll, selectAllUnkept, clear

---

## Phase 6: Full verification

- `cd frontend && pnpm check && pnpm lint`
- `ruff check src/ tests/`
- `pytest tests/ -n auto -q --cov=songmaker_cli --cov-report=term-missing`
- Visual check every view:
  - Song detail: all 3 tabs (Generations, Edit, Co-Writer)
  - Generation list: normal mode + selection mode
  - Generation detail: all action groups
  - Album detail
  - Playlist detail
  - Settings pages
  - Shared/public pages (gen, song, album, playlist)
  - Player bar
  - Mobile breakpoint (768px): selection mode, action buttons, card layout
- Test `html { font-size }` at 14px, 15px, 17px — verify proportional scaling
- Verify confirm-on-click pattern works
- Verify multi-select: enter via long-press/ctrl+click, select all unkept, delete, cancel

---

## Files touched (complete)

| File | What changes |
|---|---|
| **Frontend** | |
| `app.css` | Root font-size, token conversion to rem, new --label-font-size |
| `SongEditor.svelte` | Rem conversion, size bumps, reorder fields |
| `ParamControls.svelte` | Rem conversion, size bumps |
| `GenerationSettings.svelte` | Rem conversion, auto-expand |
| `GenerationsList.svelte` | Rem, simplified cards (play+pick+keep only), multi-select UI |
| `GenerationDetail.svelte` | Rem, full grouped action bar with icon+text, remove overflow |
| `SongDetailView.svelte` | Rem, layout (max-width+align), icon ActionButtons, remove clean up |
| `AlbumDetailView.svelte` | Rem, layout, icon ActionButtons, remove clean up |
| `PlaylistDetailView.svelte` | Rem, layout, icon ActionButtons, icon entry controls |
| `PresetChips.svelte` | Rem conversion |
| `VersionTimeline.svelte` | Rem conversion |
| `PlayerBar.svelte` | Rem conversion, Icon components for controls |
| `SongList.svelte` | Rem conversion |
| `SongNode.svelte` | Rem conversion |
| `AlbumNode.svelte` | Rem conversion |
| `ClaudeChat.svelte` | Rem conversion |
| `ChatInput.svelte` | Rem conversion, input size bump |
| `MessageList.svelte` | Rem conversion, message text bump |
| `SharedPlayer.svelte` | Rem conversion, Icon components |
| `ShareButton.svelte` | Icon components, rem |
| `LyricsDiff.svelte` | Rem conversion |
| `CoverDialog.svelte` | Rem conversion |
| `RepaintDialog.svelte` | Rem conversion |
| `CreateForm.svelte` | Rem conversion |
| Share route pages (4) | Convert remaining px, Icon for play indicators |
| `client.ts` | Add `bulkDeleteGenerations`, remove `cleanupSong` |
| **New** `Icon.svelte` | Inline SVG icon component |
| **New** `ActionButton.svelte` | Reusable action button with confirm pattern |
| **New** `stores/selection.ts` | Multi-select state management |
| **Delete** `OverflowMenu.svelte` | No longer used |
| **Backend** | |
| `generation_api.py` | Add bulk-delete endpoint |
| `db/queries/generations.py` | Add `bulk_delete_generations` |
| `api_models.py` | Add `BulkDeleteRequest`, `BulkDeleteResponse` |
| `song_api.py` | Remove cleanup endpoint |
| Generated `types.ts` | Regenerated via `generate_types.py` |
| **Tests** | |
| `tests/test_generation_api.py` | Bulk delete tests |
| `tests/test_generations_queries.py` | Query function tests |

## Not in scope

- Color scheme changes
- Font family changes
- Sidebar layout changes (already solid)
- New features (reference audio upload, style tags, etc.)
- Generate button relocation (separate UX decision)

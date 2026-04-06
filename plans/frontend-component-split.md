# Frontend Component Split (Phase 2) + Component Test Scaffolding

> **Status: READY** — Highest-leverage frontend work. Every other frontend D-item depends on this.

## Problem

After [shipped page-decomposition](https://github.com/FlexOr2/songmaker/commit/918d5c3), `+page.svelte` shrunk from 1470 → 254 lines. Good. But the work it absorbed grew into a second generation of god components, and **there are still zero component tests** (only stores and utils are tested).

| Component | Lines | Mixes |
|---|---|---|
| [`GenerationView.svelte`](../frontend/src/lib/components/GenerationView.svelte) | **845** | Score display, rating UI, action bar, playlist picker, delete confirmation, job tracking |
| [`SongDetailView.svelte`](../frontend/src/lib/components/SongDetailView.svelte) | **802** | Tab routing, editor, generation list, version timeline, sharing, repaint/cover dialogs |
| [`SongEditor.svelte`](../frontend/src/lib/components/SongEditor.svelte) | **701** | Lyrics, prompt, params, model selection |
| [`ClaudeChat.svelte`](../frontend/src/lib/components/ClaudeChat.svelte) | **687** | Message history, mention parsing, context building, songmaker block diffing, apply UI |

**Trajectory matters more than absolute size.** Each new feature lands in the existing 700-line file because that's where the relevant context is. Without component tests, splitting becomes too risky to justify. In six months these are 1500-line files. Stop the bleed now.

## Goal

1. Set up Vitest **component testing** scaffolding (currently only `.test.ts` files for stores/utils are configured).
2. Split `GenerationView.svelte` first as the proof-of-concept. Establish the pattern.
3. Then propagate to the other three on a "no new component over 300 lines" rule.

## Phase 0: Vitest component test scaffolding (~half day)

**Current state:**
- `vitest.config.ts` has `include: ['src/**/*.test.ts']` — excludes `.svelte.test.ts`
- jsdom environment is set up
- No `@testing-library/svelte` dependency
- No example component test exists

**Changes:**

1. **Add deps:**
   ```bash
   cd frontend && pnpm add -D @testing-library/svelte @testing-library/jest-dom @testing-library/user-event
   ```
   Note Svelte 5 compatibility — `@testing-library/svelte` v5+ supports Svelte 5 runes. Verify against the installed Svelte version before adding.

2. **Update `vitest.config.ts`:**
   ```ts
   include: ['src/**/*.test.ts', 'src/**/*.svelte.test.ts'],
   ```
   Add to `coverage.include`: `'src/lib/components/**/*.svelte'`.

3. **Update `src/tests/setup.ts`** to import `@testing-library/jest-dom/vitest` so `expect(el).toBeInTheDocument()` etc. work.

4. **Write one example test** — `src/lib/components/Toast.svelte.test.ts` or similar small existing component. This is the "does the harness even work" smoke test. Must run and pass before any split work begins.

5. **CI:** `pnpm test` already runs in `.github/workflows/ci.yml`. No CI changes needed once tests are discoverable.

**Exit criteria for Phase 0:** `pnpm test` discovers and runs at least one `.svelte.test.ts` file successfully.

## Phase 1: Split `GenerationView.svelte` (~1 day)

**Why first:** Largest (845 lines), most concerns mixed, most user-facing impact when broken, and the cleanest natural seams.

**Target structure:**

```
GenerationView.svelte                ~150 lines  layout shell + data fetching
├── ScoreDisplay.svelte              ~150 lines  scores grid, whisper text, copy buttons
├── RatingForm.svelte                ~120 lines  star input + notes textarea + save
├── GenerationActions.svelte         ~200 lines  pick/keep/delete/share/playlist/repaint/cover/pin buttons
└── GenerationHeader.svelte          ~100 lines  title, breadcrumb, model badge, seed pin
```

Plus tests:

```
GenerationView.svelte.test.ts        — integration: renders all children, fetches gen
ScoreDisplay.svelte.test.ts          — props in, expected score cells out
RatingForm.svelte.test.ts            — interaction: type notes, click stars, submit fires
GenerationActions.svelte.test.ts     — interaction: each button calls expected store/API mock
GenerationHeader.svelte.test.ts      — props in, expected DOM out
```

**Extraction rules:**

- **Pass data, not callbacks where possible.** Children read from stores directly (`generations`, `currentUser`) instead of receiving 12 callback props. The shipped `generation-actions` context (from page-decomposition) already exists for actions — use it.
- **No new state.** Local state stays in `GenerationView.svelte` and is passed down. Children are presentational where possible.
- **CSS moves with the component.** No shared CSS file, no `:global()`. Duplicate ~10 lines of header styling between Header and Actions if needed.
- **Tests assert behavior, not implementation.** "Clicking 'Keep' calls the keep action" not "the button has class `keep-btn`."

**Order:**

1. Create empty child components with frontmatter and prop interfaces
2. Move score display markup + CSS → write `ScoreDisplay.svelte.test.ts` → green
3. Move rating form markup + CSS → write `RatingForm.svelte.test.ts` → green
4. Move actions markup + CSS → write `GenerationActions.svelte.test.ts` → green
5. Move header markup + CSS → write `GenerationHeader.svelte.test.ts` → green
6. `GenerationView.svelte` should be ≤200 lines, mostly composition + data flow
7. Write `GenerationView.svelte.test.ts` as integration smoke test
8. Manual QA: load a generation, click every button, verify scores render, verify rating saves

**Verification:**

```bash
cd frontend && pnpm check && pnpm lint && pnpm test
```

**Don't ship if:** any child component is over 250 lines, any test mocks more than 3 modules, or `GenerationView.svelte` is still over 200 lines.

## Phase 2: `ClaudeChat.svelte` (~1.5 days)

**Why second:** Worst correctness risk (custom regex parsing of `songmaker` blocks), highest complexity per line, biggest UX win when stable.

**Suggested split:**

```
ClaudeChat.svelte                    ~150 lines  layout, scroll, input box
├── MessageList.svelte               ~120 lines  message rendering, auto-scroll
├── MessageBubble.svelte             ~150 lines  one message + apply UI for songmaker blocks
├── MentionInput.svelte              ~150 lines  textarea with @-mention autocomplete
└── ChatContextBuilder (utility)     ~100 lines  pure function, songId+mentions → context payload
```

Critical: **`ChatContextBuilder` becomes a pure utility in `lib/utils/chat-context.ts`** (note: `chat-context.test.ts` already exists, indicating some logic was already extracted — verify and extend). Pure functions are testable without DOM. The existing test suite for it stays.

**Tests for `MessageBubble.svelte.test.ts` must cover:**
- Plain message renders text
- Message with one `songmaker` block shows apply button
- Apply button click invokes the apply handler with parsed payload
- Malformed block does not crash, shows fallback

## Phase 3: `SongEditor.svelte` (~1 day)

```
SongEditor.svelte                    ~150 lines  layout shell, save button, dirty tracking
├── LyricsEditor.svelte              ~150 lines  textarea + character count + save shortcuts
├── PromptEditor.svelte              ~100 lines  prompt textarea + style hints
└── GenerationParamsForm.svelte      ~250 lines  all the sliders/dropdowns for ACE-Step params
```

`GenerationParamsForm` is the largest child by design — it's a wide form, hard to subdivide further without ceremony.

## Phase 4: `SongDetailView.svelte` (~1 day)

This one is hardest because it's a tab router. Suggested:

```
SongDetailView.svelte                ~200 lines  tab bar + tab body switch + header
├── SongHeader.svelte                ~100 lines  title, breadcrumb, share, delete
├── (tab bodies are existing children — SongEditor, ClaudeChat, GenerationsList)
```

Most of the 802 lines are already child components — the work here is extracting the header and trimming the tab-switching glue. May come in under target without much effort.

## Rules going forward (for the whole frontend)

Add to a `frontend/CONTRIBUTING.md` or extend `CLAUDE.md` once Phase 1 is green:

- **No new component over 300 lines.** Hard limit. PR review rejects bigger files.
- **No new component without a test file.** Even if the test is a single render smoke test.
- **Extract pure logic to `lib/utils/`.** Anything that doesn't touch the DOM goes there and is unit-tested with the existing harness.
- **Stores stay flat.** Don't create per-component stores; existing `lib/stores/*.ts` are the canonical state.

## Risks

- **Svelte 5 + `@testing-library/svelte` compatibility.** Verify before committing to the dep. If incompatible, fall back to Playwright component tests (more setup, but works).
- **CSS leakage.** Extracted children with their own `<style>` blocks are scoped per Svelte's default — should be fine, but eyeball the rendered output for missing styles.
- **Reactive subscriptions.** A child reading from a store works the same as the parent reading and passing down, but `$derived`/`$effect` boundaries shift. Test that data flows still update in response to store changes.
- **Diff size.** Phase 1 alone is ~1000 lines moved + 400 lines of new tests. Reviewer needs the same "moved-only" hint as the jobs split.
- **Breaking existing manual workflows.** Some users (you) have muscle memory for where buttons are. Visual regression risk. Manual QA after each phase is non-negotiable.

## Success criteria

- Vitest component test harness is wired up and running in CI
- `GenerationView.svelte` ≤ 200 lines, with 4 children each ≤ 250 lines and each tested
- ≥ 80% line coverage on the new component files
- The "no new component over 300 lines" rule is documented somewhere a future agent will read
- Manual QA passes after each phase

## Out of scope

- Visual redesign (functional split only)
- New features in any of these components
- Refactoring `lib/stores/` (separate concern; addressed in `frontend-store-races.md` if/when written)
- E2E tests (covered separately by `mobile-and-testing.md`)
- Backend changes

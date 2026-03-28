# UI Polish — Hallucination Theme Deep Pass

> **Status: COMPLETE** — All 6 phases implemented.

## Goal

Make the entire app feel like a cohesive hallucination experience. The login page sets the bar — the app interior should match that energy, just subtler so it stays usable for daily work.

## Current State

Done:
- Login page: animated background, glitching logo, waveform bars, floating glows
- Header/player: gradient borders (red → purple)
- Buttons: gradient backgrounds with purple glow on hover
- Tabs, toasts, sidebar: basic accent color applied
- Favicon: glitched "H" SVG

Still plain/mismatched:
- Player bar waveform (wavesurfer.js) — flat red, no gradient
- Picked star (★) — yellow, doesn't fit the red/purple theme
- Score indicators — yellow "ok" color clashes
- Album/song backgrounds — flat dark, no depth
- No subtle animations in the main app (login page has them, app doesn't)
- Share page — still basic, no hallucination vibe
- Settings pages — completely unstyled default

## Phase 1: Player Bar Overhaul

The player is always visible — it's the most seen component.

- [x] Wavesurfer colors: `waveColor` → dark purple, `progressColor` → red-to-purple gradient (wavesurfer.js supports gradient via canvas)
- [x] Play button: gradient border that rotates/animates while playing
- [x] Track info: song title gets subtle glow when playing
- [x] Nav buttons (⏮ ⏪ ⏩ ⏭): replace emoji with SVG icons or styled text that matches theme
- [x] Loading spinner: purple-to-red gradient spin instead of flat red

### Wavesurfer Gradient Implementation

```typescript
// wavesurfer.js supports CanvasGradient for progressColor
const ctx = document.createElement('canvas').getContext('2d');
const gradient = ctx.createLinearGradient(0, 0, waveContainer.clientWidth, 0);
gradient.addColorStop(0, '#ff3220');
gradient.addColorStop(1, '#a020f0');
// Pass gradient as progressColor in WaveSurfer.create()
```

## Phase 2: Color System Cleanup

The yellow (--score-ok, picked stars) clashes with the red/purple hallucination theme.

- [x] Replace `--score-ok: #ff4` (yellow) with a warm amber/orange that blends: `#f0a030` or similar
- [x] Picked star (★): change from yellow to a pulsing purple-gold gradient, or a glowing accent color
- [x] "Shared" badge on albums: currently green border, consider accent purple
- [x] Score "ok" background: warm dark instead of yellow-green
- [x] Review all hardcoded hex colors in components (search for `#1a2a1a`, `#1a1a2a`, etc.) — replace with CSS variables for consistency

## Phase 3: Subtle Ambient Animation

Add depth without being distracting. These should be barely noticeable — felt, not seen.

- [x] Main app background: very subtle, slow-moving gradient noise (CSS only, no JS) — like a dark nebula
- [x] Sidebar: faint grid pattern matching login page (opacity 0.02, very subtle)
- [x] Active song: slow breathing glow on the purple border (2-3s cycle)
- [x] Generate button while generating: pulse animation
- [x] Empty states ("No generations", "Select a song"): replace text with small waveform animation from login page

### CSS-only Background Approach

```css
.app-body::before {
  content: '';
  position: fixed;
  inset: 0;
  background: radial-gradient(ellipse at 20% 50%, rgba(160, 32, 240, 0.03), transparent 70%),
              radial-gradient(ellipse at 80% 50%, rgba(255, 50, 32, 0.02), transparent 70%);
  pointer-events: none;
  z-index: 0;
}
```

## Phase 4: Share Page

The public share page is the first thing non-users see. It should impress.

- [x] Add the login page's background effects (grid, floating glows) but toned down
- [x] Album title: glitch effect like the login logo
- [x] Track list: hover glow effect
- [x] Now-playing bar: gradient progress instead of flat red
- [x] "Powered by Hallucinai" footer: subtle gradient text

## Phase 5: Settings Pages

Currently unstyled — feels like a different app.

- [x] Settings sidebar: match main app sidebar style
- [x] Form inputs: match login page input style (dark background, glow on focus)
- [x] Save/action buttons: gradient style matching rest of app
- [x] Section headings: Oswald uppercase with accent color

## Phase 6: Micro-interactions

Small details that make it feel polished:

- [x] Button clicks: subtle scale down (transform: scale(0.97)) on active
- [x] Song selection: brief purple flash/highlight on click
- [x] Generation complete toast: confetti/sparkle effect? (maybe too much — test it)
- [x] Hover on generation rows: subtle purple left-border preview before selection
- [x] Focus rings: purple glow instead of browser default blue outline

## Technical Notes

- All animations should respect `prefers-reduced-motion` — wrap in `@media (prefers-reduced-motion: no-preference)`
- Keep CSS-only where possible — no JS animation libraries
- Wavesurfer gradient needs canvas API (see Phase 1 code snippet)
- Test on mobile (375px) — animations should be disabled or minimal to save battery
- The `--accent: #a020f0` CSS variable is already defined globally in `app.css`

## Files to Touch

| Phase | Files |
|-------|-------|
| 1 | `PlayerBar.svelte` |
| 2 | `app.css`, `SongNode.svelte`, `AlbumNode.svelte`, `GenerationDetail.svelte` |
| 3 | `+layout.svelte`, `+page.svelte`, `SongList.svelte` |
| 4 | `share/[slug]/+page.svelte` |
| 5 | `settings/+layout.svelte`, all settings pages |
| 6 | `app.css` (global), individual components |

## Priority

Phase 1 (player) → Phase 2 (colors) → Phase 3 (ambient) → Phase 4 (share) → Phase 6 (micro) → Phase 5 (settings, lowest priority)

## Constraints

- Must stay usable — no animation that distracts from editing lyrics or reading scores
- Performance: no layout thrashing, use `transform` and `opacity` only for animations
- Don't break existing tests
- Run `pnpm check && pnpm test` after each phase
- Test on `localhost:5173` (dev server), deploy to Docker when happy

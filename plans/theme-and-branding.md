# Light Theme + APP_NAME Constant

> **Status: IMPLEMENTED**

## Problem

1. "Hallucinai" is hardcoded in 14 places across backend and frontend. Not a constant.
2. Only a dark theme exists. No way to switch to light mode.
3. PlayerBar visualizer uses hardcoded RGB values — can't adapt to any theme.

## Goal

1. Single `APP_NAME` constant used everywhere (except legal prose/emails — those stay hardcoded with a comment).
2. Dark/light theme toggle that persists in localStorage.
3. Architecture supports adding more themes by just adding a CSS variable block.
4. PlayerBar visualizer reads colors from CSS variables so it adapts to the active theme.

---

## Part 1: APP_NAME Constant

### Backend

Add to `constants.py`:
```python
APP_NAME = "Hallucinai"
```

Use in `server.py`:
```python
from songmaker_cli.constants import APP_NAME
app = FastAPI(title=APP_NAME, ...)
```

### Frontend

New file `frontend/src/lib/constants.ts`:
```ts
export const APP_NAME = 'Hallucinai';
```

### Files to update (import + use `APP_NAME`)

| File | Usage |
|---|---|
| `routes/+layout.svelte` | `<title>`, brand text, `data-text` attr |
| `routes/login/+page.svelte` | Logo `<h1>`, `data-text` attr |
| `routes/setup/+page.svelte` | `<h1>` |
| `routes/legal/+page.svelte` | `<title>` |
| `routes/share/[slug]/+page.svelte` | `<title>`, "Powered by" link |
| `routes/settings/+layout.svelte` | "Back to Hallucinai" link |

### Files NOT updated (legal content)

`LegalContent.svelte` keeps hardcoded "Hallucinai" and "legal@hallucinai.de" — legal text must not be templated. Add a comment at the top:
```svelte
<!-- APP_NAME: if the app name changes, update the legal text below and the email addresses manually -->
```

---

## Part 2: Theme System Architecture

### How it works

1. **CSS variables in `:root`** — the dark theme (current default, unchanged)
2. **`[data-theme="light"]` selector** — overrides the same variables for light mode
3. **Adding a new theme** = adding `[data-theme="mytheme"]` block in `app.css`. Nothing else changes.
4. **Theme store** in `ui.ts` — reads/writes `localStorage`, applies `data-theme` attribute to `<html>`
5. **Toggle button** in the header bar (sun/moon icon)

### Theme store (`lib/stores/ui.ts`)

```ts
export type Theme = 'dark' | 'light';

const STORAGE_KEY = 'theme';

function getInitialTheme(): Theme {
    if (typeof window === 'undefined') return 'dark';
    return (localStorage.getItem(STORAGE_KEY) as Theme) ?? 'dark';
}

export const theme = writable<Theme>(getInitialTheme());

export function toggleTheme(): void {
    theme.update(t => {
        const next = t === 'dark' ? 'light' : 'dark';
        localStorage.setItem(STORAGE_KEY, next);
        document.documentElement.dataset.theme = next;
        return next;
    });
}

export function initTheme(): void {
    const t = getInitialTheme();
    document.documentElement.dataset.theme = t;
    theme.set(t);
}
```

### Preventing flash of wrong theme (`app.html`)

Inline script in `<head>` that runs before paint:
```html
<script>
    (function() {
        var t = localStorage.getItem('theme') || 'dark';
        document.documentElement.dataset.theme = t;
    })();
</script>
```

### Light theme CSS variables (`app.css`)

```css
[data-theme="light"] {
    --primary: #d41a0a;
    --accent: #7a18c0;
    --bg: #f4f4f6;
    --surface: #ffffff;
    --surface-hover: #ebebed;
    --border: #d0d0d4;
    --text: #1a1a1e;
    --text-muted: #555;
    --text-dim: #999;
    --text-light: #333;
    --score-good-bg: #e0f5e0;
    --score-good: #1e7a1e;
    --score-ok-bg: #fef3e0;
    --score-ok: #b07000;
    --score-bad-bg: #fde8e8;
    --score-bad: #c02020;
    --success: #1e7a1e;
}
```

### Theme toggle in header (`+layout.svelte`)

Add a button between username and Settings link:
```svelte
<button class="theme-toggle" onclick={toggleTheme} aria-label="Toggle theme">
    {$theme === 'dark' ? '☀' : '☾'}
</button>
```

---

## Part 3: PlayerBar Visualizer Adaptation

### Problem

The canvas draw code has hardcoded RGB values like `rgba(255, 50, 32, ...)` and `rgba(160, 32, 240, ...)`. These are the primary/accent colors baked into JS.

### Solution

Add CSS variables with individual RGB components that JS can read:

```css
:root {
    --viz-primary-r: 255;
    --viz-primary-g: 50;
    --viz-primary-b: 32;
    --viz-accent-r: 160;
    --viz-accent-g: 32;
    --viz-accent-b: 240;
}

[data-theme="light"] {
    --viz-primary-r: 212;
    --viz-primary-g: 26;
    --viz-primary-b: 10;
    --viz-accent-r: 122;
    --viz-accent-g: 24;
    --viz-accent-b: 192;
}
```

In `PlayerBar.svelte`, read these once when the visualizer starts (and on theme change):

```ts
interface VizColors {
    pr: number; pg: number; pb: number;  // primary RGB
    ar: number; ag: number; ab: number;  // accent RGB
}

function readVizColors(): VizColors {
    const s = getComputedStyle(document.documentElement);
    return {
        pr: parseInt(s.getPropertyValue('--viz-primary-r')),
        pg: parseInt(s.getPropertyValue('--viz-primary-g')),
        pb: parseInt(s.getPropertyValue('--viz-primary-b')),
        ar: parseInt(s.getPropertyValue('--viz-accent-r')),
        ag: parseInt(s.getPropertyValue('--viz-accent-g')),
        ab: parseInt(s.getPropertyValue('--viz-accent-b')),
    };
}
```

Then replace all hardcoded RGB values in `drawVisualizer()` with interpolations between `c.pr/pg/pb` and `c.ar/ag/ab` (same math, just variable colors).

The colors are re-read when the visualizer loop starts, so a theme switch while paused takes effect on next play.

---

## Part 4: Hardcoded Colors in Page Styles

Several pages have hardcoded hex/rgba colors in their `<style>` blocks that duplicate CSS variables. These need updating for the light theme to apply.

### New CSS variables needed

| Variable | Dark value | Light value | Used for |
|---|---|---|---|
| `--bg-deep` | `#050508` | `#e8e8ec` | Login page background |
| `--card-bg` | `rgba(13,13,13,0.85)` | `rgba(255,255,255,0.85)` | Login card, player bar |
| `--header-bg` | `#0a0a0a` | `#f0f0f2` | Header bar, player bar, now-playing bar |
| `--glow-primary` | `rgba(255,50,32,0.03)` | `rgba(212,26,10,0.04)` | Ambient background glows |
| `--glow-accent` | `rgba(160,32,240,0.03)` | `rgba(122,24,192,0.04)` | Ambient background glows |

### Pages to update

| Page | What changes |
|---|---|
| `login/+page.svelte` | `#050508` → `var(--bg-deep)`, card bg, input bg, glow colors, grid lines |
| `setup/+page.svelte` | Minimal — already uses CSS vars mostly |
| `share/[slug]/+page.svelte` | `#0a0a0a` in now-playing bar → `var(--header-bg)`, grid/glow colors |
| `+layout.svelte` | `#0a0a0a` in top-bar/play-btn → `var(--header-bg)`, glow rgba values |
| `PlayerBar.svelte` | Player bar bg → `var(--card-bg)`, inline style box-shadow uses viz colors |
| `settings/+layout.svelte` | Grid background rgba → `var(--glow-accent)` |

---

## File Change Summary

| File | Changes |
|---|---|
| `src/songmaker_cli/constants.py` | Add `APP_NAME` |
| `src/songmaker_cli/server.py` | Import + use `APP_NAME` |
| `frontend/src/lib/constants.ts` | New: `APP_NAME` export |
| `frontend/src/app.css` | Light theme vars, viz RGB vars, new surface vars |
| `frontend/src/app.html` | Flash-prevention script, `data-theme` |
| `frontend/src/lib/stores/ui.ts` | Theme store + toggle + init |
| `frontend/src/routes/+layout.svelte` | APP_NAME, theme toggle, CSS var fixes |
| `frontend/src/routes/login/+page.svelte` | APP_NAME, CSS var fixes |
| `frontend/src/routes/setup/+page.svelte` | APP_NAME |
| `frontend/src/routes/legal/+page.svelte` | APP_NAME |
| `frontend/src/routes/share/[slug]/+page.svelte` | APP_NAME, CSS var fixes |
| `frontend/src/routes/settings/+layout.svelte` | APP_NAME, CSS var fixes |
| `frontend/src/lib/components/LegalContent.svelte` | Comment about manual update |
| `frontend/src/lib/components/PlayerBar.svelte` | Read viz colors from CSS vars, CSS var fixes |

---

## Testing

- `ruff check src/ tests/` — backend lint
- `cd frontend && pnpm check && pnpm lint` — frontend checks
- Visual: toggle theme on every page (login, main, settings, share, legal) and verify no invisible text, broken contrast, or ugly artifacts
- Verify PlayerBar visualizer colors match theme in both modes
- Verify localStorage persistence across refresh
- Verify no flash of wrong theme on page load

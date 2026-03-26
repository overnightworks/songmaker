# Settings Page Consolidation

## Problem

Global settings are scattered across three unrelated locations:

1. **Claude API key** — hidden behind an emoji button in the chat panel header. Once set, no visible way to clear it. Users don't know it exists until they open the chat.
2. **Generation global defaults** — buried inside the "Generation Settings" accordion on the song editor. An admin-only feature disguised as a per-song control.
3. **Account / Admin** — proper pages at `/settings/account` and `/settings/users`, but with no shared navigation (each has a hardcoded "Back" link and a link to the other).

The result: two settings pages that don't know about each other, and two settings that aren't pages at all.

## Target Architecture

### Route structure

```
/settings              → redirects to /settings/account
/settings/account      → password change (existing, restyled)
/settings/generation   → global defaults + presets (NEW, admin-only)
/settings/integrations → Claude API key + connection status (NEW)
/settings/users        → admin user CRUD (existing, restyled)
```

### Shared layout

```
/settings/+layout.svelte
├── Sidebar nav (Account, Generation, Integrations, Admin)
├── Highlights current route
├── Admin-only items hidden for regular users
└── "Back to Songmaker" link at top
```

All settings pages render inside this layout. The sidebar is always visible (no hamburger — settings pages aren't used on mobile during song creation).

### Component changes

| Current location | What moves | Where it goes |
|---|---|---|
| `ClaudeChat.svelte` key-input section | API key input + clear button + status | `/settings/integrations` |
| `ClaudeChat.svelte` | Remove key-toggle button, show "Configure in Settings" link if no key | Chat panel (simplified) |
| `GenerationSettings.svelte` "Edit global defaults" button + DefaultsEditor | Global defaults editing | `/settings/generation` |
| `GenerationSettings.svelte` PresetManager saved-presets list | Preset management (save/delete/set-default) | `/settings/generation` |
| `GenerationSettings.svelte` | Keep: toggle, param controls, preset chips (quick-load), save-as-preset form | Song editor (simplified) |
| `+layout.svelte` nav links | Account, Admin links | Settings layout sidebar |

### New pages

#### `/settings/integrations`

- Claude API key input (text, not password — user should see what they typed)
- Clear button (visible when key is set)
- Connection status: test the key on save, show "Connected" / "Invalid key" / "Using server CLI"
- ACE-Step server status (read from `/health` endpoint — model loaded, VRAM usage)
- Read-only, no admin requirement

#### `/settings/generation` (admin-only)

- Model tabs (Turbo / SFT) with ParamControls for each
- Save/reset buttons per model
- Preset management table: name, model, is_default, actions (set default, delete)
- Uses existing `DefaultsEditor` and `PresetManager` components (already extracted)

### Navigation

Top bar changes:
- Replace `Account` and `Admin` links with single `Settings` link
- Settings layout sidebar handles the sub-navigation

### What stays in the song editor

`GenerationSettings.svelte` keeps:
- Expand/collapse toggle with "custom" badge
- Preset quick-load chips (compact, no management UI)
- ParamControls for per-song overrides
- "Reset to defaults" button
- "Save as preset" inline form (convenience shortcut)

It loses:
- "Edit global defaults" button + DefaultsEditor panel
- Full preset list with delete/set-default actions

## Key Decisions

- **No settings store** — each page fetches its own data on mount. Settings pages are rarely visited; caching adds complexity for no benefit.
- **API key stays in localStorage** — it's per-browser, not per-user. No backend endpoint needed.
- **Settings layout is a Svelte layout route** — `routes/settings/+layout.svelte` wraps all settings pages. Existing pages (`account`, `users`) get restyled automatically.
- **Mobile: settings pages stack vertically** — sidebar becomes a horizontal tab bar on narrow screens. Not critical to get perfect — settings are a desktop workflow.

## Steps

1. Create `routes/settings/+layout.svelte` with sidebar nav
2. Create `routes/settings/integrations/+page.svelte`
3. Create `routes/settings/generation/+page.svelte` (reuse DefaultsEditor + PresetManager)
4. Restyle `routes/settings/account/+page.svelte` to remove standalone nav
5. Restyle `routes/settings/users/+page.svelte` to remove standalone nav
6. Simplify `GenerationSettings.svelte` — remove defaults editor and preset management
7. Simplify `ClaudeChat.svelte` — remove API key input, add "Configure in Settings" link
8. Update `+layout.svelte` top bar — single "Settings" link replaces Account/Admin
9. Run `pnpm check && pnpm lint && pnpm test`

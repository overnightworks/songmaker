# E2E Testing

> **Status: NOT STARTED** — Mobile layout is done. E2E test infrastructure not set up yet.

## Goal

Automated E2E tests that catch auth, ownership, and UI regressions across desktop and mobile viewports.

---

## Phase 1: Playwright Setup + Auth Tests

### Setup

```bash
cd frontend
pnpm add -D @playwright/test
npx playwright install chromium
```

### Playwright Config

```typescript
// playwright.config.ts
export default defineConfig({
  testDir: './e2e',
  use: {
    baseURL: 'http://localhost:8080',
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1280, height: 720 } } },
    { name: 'mobile', use: { viewport: { width: 375, height: 667 } } },
  ],
  webServer: {
    command: 'cd .. && songmaker server --port 8080',
    port: 8080,
    reuseExistingServer: true,
  },
});
```

### Test Structure

```
frontend/e2e/
├── auth.spec.ts        # Login, setup, logout, route guards
├── albums.spec.ts      # Create album, ownership isolation, sharing
├── songs.spec.ts       # Create song, edit (versions), generate trigger
├── player.spec.ts      # Play, next/prev, album play
├── admin.spec.ts       # User CRUD, sessions, job recovery
├── mobile.spec.ts      # Key flows at 375px viewport
└── helpers/
    └── auth.ts         # Login/setup helpers, test user factory
```

### Auth Tests (`auth.spec.ts`)

- [ ] `/setup` shown when no users exist → create admin → redirected to `/`
- [ ] `/login` with valid credentials → sees album list
- [ ] `/login` with wrong password → error message shown
- [ ] Brute-force lockout after 5 attempts → 429 toast
- [ ] Logout → redirected to `/login`
- [ ] Protected routes (`/`, `/settings/*`) redirect to `/login` when unauthenticated
- [ ] Regular user can't access `/settings/users`

### Test Helpers

```typescript
// e2e/helpers/auth.ts
async function setupAdmin(page, username, password) {
  await page.goto('/setup');
  await page.fill('input[autocomplete="username"]', username);
  await page.fill('input[autocomplete="new-password"]', password);
  await page.fill('input[placeholder*="Confirm"]', password);
  await page.click('button[type="submit"]');
  await page.waitForURL('/');
}

async function login(page, username, password) {
  await page.goto('/login');
  await page.fill('input[autocomplete="username"]', username);
  await page.fill('input[autocomplete="current-password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForURL('/');
}
```

---

## Phase 2: Ownership + CRUD Tests

### Album Ownership (`albums.spec.ts`)

- [ ] User A creates album → sees it in sidebar
- [ ] User B logs in → does NOT see User A's album
- [ ] Admin logs in → sees all albums
- [ ] Album sharing: enable → copy share URL → verify `/share/{slug}` loads
- [ ] Album delete → songs and generations gone

### Song Editing (`songs.spec.ts`)

- [ ] Create song in album → appears in sidebar
- [ ] Edit lyrics → new version created (version count increases)
- [ ] Version timeline shows history
- [ ] Delete version → removed from timeline

---

## Phase 3: Player + Mobile Tests

### Player (`player.spec.ts`)

- [ ] Click play on generation → player bar appears with waveform
- [ ] Next/prev generation buttons cycle through generations
- [ ] Next/prev song skips songs with no generations
- [ ] Play Album starts from first song's picked generation
- [ ] Player hidden when nothing selected

### Mobile (`mobile.spec.ts`)

- [ ] Hamburger menu opens/closes sidebar
- [ ] Song selection closes sidebar on mobile
- [ ] Chat panel opens as overlay
- [ ] Player controls usable at 375px
- [ ] Login and setup forms work on mobile
- [ ] Settings pages scrollable on mobile

---

## Phase 4: CI Integration (future)

- [ ] Run Playwright in GitHub Actions on PR
- [ ] Requires test database (SQLite is fine for E2E)
- [ ] Requires Redis (use GitHub Actions service container)
- [ ] ACE-Step not needed — generation tests mock or skip the GPU path
- [ ] Screenshot comparison for visual regression (optional)

---

## Priority Order

1. Playwright setup + auth tests (catch security regressions)
2. Ownership + CRUD tests (catch permission bugs)
3. Player + mobile tests (catch UI regressions)
4. CI integration (automate everything)

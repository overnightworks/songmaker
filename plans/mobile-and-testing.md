# Mobile Polish + E2E Testing

> **Status: PARTIALLY DONE** — basic mobile layout works (chat overlay, sidebar toggle). E2E tests not started.

## Goal

Production-quality mobile experience + automated E2E tests that catch regressions across devices and auth flows.

---

## Phase 1: Mobile Layout Polish

### Known Issues

- Chat panel: no close button, input barely visible at bottom
- Detail panel (song editor): not optimized for small screens
- Generation settings: 3-column grid doesn't fit on mobile
- New Song form: needs mobile layout
- Touch targets: some buttons too small (< 44px)
- Player bar: nav buttons cramped on small screens

### Device Matrix

| Device | Width | Priority |
|--------|-------|----------|
| iPhone SE | 375px | High (smallest common) |
| Android small | 360px | High |
| iPhone 14/15 | 390px | High |
| iPad Mini | 768px | Medium (tablet breakpoint) |
| iPad | 1024px | Low (already works) |

### Implementation

- [ ] Chat panel: add close button (X), ensure input is above keyboard
- [ ] Detail panel: stack layout on mobile (full-width, scrollable)
- [ ] Generation settings: single-column grid on mobile
- [ ] Version timeline: horizontal scroll or collapsible on mobile
- [ ] Player bar: collapse track info, keep controls + waveform
- [ ] All interactive elements: min 44px touch targets
- [ ] New Song / New Album forms: full-width on mobile
- [ ] Test on all 4 device widths above

---

## Phase 2: Playwright E2E Tests

### Setup

```bash
cd frontend
pnpm add -D @playwright/test
npx playwright install chromium
```

### Test Structure

```
frontend/e2e/
├── auth.spec.ts        # Login, setup, logout, route guards
├── albums.spec.ts      # Create album, ownership isolation
├── songs.spec.ts       # Create song, edit, versions
├── player.spec.ts      # Play, next/prev, album play
├── admin.spec.ts       # User CRUD, sessions, ACE-Step panel
├── mobile.spec.ts      # All flows at 375px viewport
└── fixtures/
    └── auth.ts         # Login helper, seeded test users
```

### Test Scenarios

#### Auth (`auth.spec.ts`)
- [ ] Setup page shown when no users exist
- [ ] Create admin account → redirected to /
- [ ] Login with valid credentials → sees albums
- [ ] Login with wrong password → error message
- [ ] Brute-force lockout after 5 attempts → 429 message
- [ ] Logout → redirected to /login
- [ ] Protected routes redirect to /login when unauthenticated
- [ ] Regular user can't access /settings/users

#### Album Ownership (`albums.spec.ts`)
- [ ] User A creates album → sees it
- [ ] User B logs in → does NOT see User A's album
- [ ] Admin logs in → sees all albums
- [ ] User creates album + song + generates → all visible
- [ ] User can't access other user's audio files

#### Player (`player.spec.ts`)
- [ ] Click play on generation → player bar appears
- [ ] Next/prev generation buttons work
- [ ] Next/prev song skips empty songs
- [ ] Play Album starts from first song
- [ ] Player hidden when nothing playing

#### Mobile (`mobile.spec.ts`)
- [ ] Hamburger menu opens/closes sidebar
- [ ] Song selection closes sidebar
- [ ] Chat panel opens as full-screen overlay
- [ ] Chat panel has close button
- [ ] Player controls usable at 375px
- [ ] Login form works on mobile
- [ ] Admin panel scrollable on mobile

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
    { name: 'tablet', use: { viewport: { width: 768, height: 1024 } } },
  ],
  webServer: {
    command: 'SESSION_SECRET=test songmaker server --port 8080',
    port: 8080,
    reuseExistingServer: true,
  },
});
```

### Test Fixtures

```typescript
// e2e/fixtures/auth.ts
async function loginAs(page, username, password) {
  await page.goto('/login');
  await page.fill('[autocomplete="username"]', username);
  await page.fill('[autocomplete="current-password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForURL('/');
}

async function setupAdmin(page, username, password) {
  await page.goto('/setup');
  await page.fill('[autocomplete="username"]', username);
  // ... fill password + confirm
  await page.click('button[type="submit"]');
  await page.waitForURL('/');
}
```

---

## Phase 3: CI Integration (Future)

- [ ] Run Playwright in GitHub Actions on PR
- [ ] Screenshot comparison for visual regression
- [ ] Lighthouse audit for mobile performance

---

## Priority Order

1. Mobile layout fixes (immediate visual impact)
2. Playwright auth + ownership tests (catch security regressions)
3. Playwright mobile tests (prevent layout regressions)
4. CI integration (automate everything)

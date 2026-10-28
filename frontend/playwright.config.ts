import { defineConfig } from '@playwright/test';
import { DESKTOP_VIEWPORT, MOBILE_VIEWPORT, ONLY_IN_SHELL, type Shell } from './e2e/helpers';
import { BASE_URL, STORAGE_STATE_FILE } from './e2e/seed';

// Playwright matches a project's grep against the title path and the tags
// joined by spaces, so the tag must stand between spaces or at an end: a
// title or a longer tag that merely contains it never decides the shell.
function taggedOnlyIn(shell: Shell): RegExp {
	return new RegExp(`(?:^|\\s)${ONLY_IN_SHELL[shell]}(?:\\s|$)`);
}

export default defineConfig({
	testDir: './e2e',
	globalSetup: './e2e/global-setup.ts',
	// One stack, one IP rate-limit window, one seeded library: running the two
	// shells back to back keeps the run's request cost additive and measurable
	// instead of a burst that trips the app's own 429 guard.
	fullyParallel: false,
	workers: 1,
	forbidOnly: Boolean(process.env.CI),
	retries: process.env.CI ? 1 : 0,
	reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
	use: {
		baseURL: BASE_URL,
		storageState: STORAGE_STATE_FILE,
		// The worker would answer a stubbed request from its own cache or the real
		// server; a spec that proves worker behaviour opts back in with
		// test.use({ serviceWorkers: 'allow' }).
		serviceWorkers: 'block',
		trace: 'on-first-retry',
		screenshot: 'only-on-failure',
		video: 'off'
	},
	projects: [
		{
			name: 'desktop' satisfies Shell,
			grepInvert: taggedOnlyIn('mobile'),
			use: { browserName: 'chromium', viewport: DESKTOP_VIEWPORT }
		},
		{
			name: 'mobile' satisfies Shell,
			grepInvert: taggedOnlyIn('desktop'),
			use: {
				browserName: 'chromium',
				viewport: MOBILE_VIEWPORT,
				isMobile: true,
				hasTouch: true
			}
		}
	]
});

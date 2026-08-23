import { defineConfig } from '@playwright/test';
import { DESKTOP_VIEWPORT, MOBILE_VIEWPORT, type Shell } from './e2e/helpers';
import { BASE_URL, STORAGE_STATE_FILE } from './e2e/seed';

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
		trace: 'on-first-retry',
		screenshot: 'only-on-failure',
		video: 'off'
	},
	projects: [
		{
			name: 'desktop' satisfies Shell,
			use: { browserName: 'chromium', viewport: DESKTOP_VIEWPORT }
		},
		{
			name: 'mobile' satisfies Shell,
			use: {
				browserName: 'chromium',
				viewport: MOBILE_VIEWPORT,
				isMobile: true,
				hasTouch: true
			}
		}
	]
});

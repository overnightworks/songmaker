import { defineConfig } from '@playwright/test';
import { BASE_URL, STORAGE_STATE_FILE } from './e2e/seed';

// The flows drive the desktop layout; below 1099px Now Playing stacks and
// below 768px the whole shell turns compact (see lib/constants.ts).
const DESKTOP_VIEWPORT = { width: 1440, height: 900 };

export default defineConfig({
	testDir: './e2e',
	globalSetup: './e2e/global-setup.ts',
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
			name: 'desktop',
			use: { browserName: 'chromium', viewport: DESKTOP_VIEWPORT }
		}
	]
});

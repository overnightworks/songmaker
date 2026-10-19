import { expect, test } from '@playwright/test';

// The two fixed legal addresses are public: a browser without cookies reads
// the section the path names and stays on that address (edge#110, #1709).
const WIDTHS = [390, 1440];
const ADDRESSES = [
	{ path: '/impressum', heading: 'Impressum' },
	{ path: '/impressum#hopin', heading: 'Impressum' },
	{ path: '/datenschutz', heading: 'Datenschutzerklärung' },
	{ path: '/datenschutz#hopin', heading: 'Datenschutzerklärung' }
];

test.describe('the public legal addresses', () => {
	test.use({ storageState: { cookies: [], origins: [] } });

	for (const width of WIDTHS) {
		for (const { path, heading } of ADDRESSES) {
			test(`${path} shows ${heading} without sign-in at ${width}px`, async ({ page }) => {
				await page.setViewportSize({ width, height: 900 });

				await page.goto(path);

				await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible();
				const { pathname } = new URL(page.url());
				expect(pathname).toBe(path.split('#')[0]);
			});
		}
	}
});

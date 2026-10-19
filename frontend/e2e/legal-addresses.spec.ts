import { expect, test } from '@playwright/test';
import { FlowGuard } from './helpers';

/**
 * 1709: a public legal page makes no API request on a fresh visit; the
 * signed-out shell never checks the session there.
 */
const LEGAL_ADDRESS_FLOW_API_REQUEST_BUDGET = 0;
const ADDRESSES = [
	{ address: '/impressum', heading: 'Impressum' },
	{ address: '/impressum#hopin', heading: 'Impressum' },
	{ address: '/datenschutz', heading: 'Datenschutzerklärung' },
	{ address: '/datenschutz#hopin', heading: 'Datenschutzerklärung' },
	{ address: '/legal#datenschutz', heading: 'Datenschutzerklärung' }
];

test.describe('the public legal addresses', () => {
	test.use({ storageState: { cookies: [], origins: [] } });

	let guard: FlowGuard;

	test.beforeEach(({ page }) => {
		guard = new FlowGuard(page);
	});

	test.afterEach(() => {
		guard.assertClean();
		guard.assertWithinBudget(LEGAL_ADDRESS_FLOW_API_REQUEST_BUDGET);
	});

	for (const { address, heading } of ADDRESSES) {
		test(`${address} shows ${heading} without sign-in`, async ({ page }) => {
			await page.goto(address);

			await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible();
			await expect(page.getByRole('button', { name: 'Back', exact: true })).toBeInViewport();
			expect(new URL(page.url()).pathname).toBe(address.split('#')[0]);
		});
	}
});

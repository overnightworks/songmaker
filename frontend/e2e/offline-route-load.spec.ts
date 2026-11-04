// A section whose page code is not loaded yet, opened while offline, says the page needs the
// network instead of a server error, and opens by itself once the network is back (#2139).
// The default blocked service worker keeps the chunk from being precached, so the import fails.

import { expect, test } from '@playwright/test';

import { loseNetwork, regainNetwork, shellOf, workspace } from './helpers';

const BACK_ONLINE_MS = 10_000;
// The router's own report of the chunk it could not fetch; FlowGuard would fail the flow on it.
const EXPECTED_CONSOLE_ERROR = /Unable to preload CSS|ERR_INTERNET_DISCONNECTED/;
const OFFLINE_WORDS = 'This page needs the network. It opens by itself when you are back online.';

test('a section opened offline shows the offline state and opens by itself after reconnect', async ({
	page,
	context
}, testInfo) => {
	const unexpectedErrors: string[] = [];
	page.on('console', (message) => {
		if (message.type() === 'error' && !EXPECTED_CONSOLE_ERROR.test(message.text())) {
			unexpectedErrors.push(message.text());
		}
	});
	page.on('pageerror', (error) => unexpectedErrors.push(error.message));
	await page.goto('/settings');
	// The desktop's /settings redirects into its first section; an offline click made before the
	// redirect would be overridden by it.
	if (shellOf(testInfo) === 'desktop') await expect(page).toHaveURL(/\/settings\/generation$/);
	const referencesLink = page.locator('a[href="/settings/references"]:visible');
	await expect(referencesLink).toBeVisible();

	await loseNetwork(page, context);
	await referencesLink.click();

	await expect(page.getByRole('alert').filter({ hasText: OFFLINE_WORDS })).toBeVisible();
	await expect(page.getByText('500')).toHaveCount(0);
	await expect(page.getByText('Internal Error')).toHaveCount(0);

	await regainNetwork(page, context);

	await expect(workspace(page).getByRole('heading', { name: 'References' })).toBeVisible({
		timeout: BACK_ONLINE_MS
	});
	await expect(page.getByRole('alert').filter({ hasText: OFFLINE_WORDS })).toHaveCount(0);
	expect(unexpectedErrors).toEqual([]);
});

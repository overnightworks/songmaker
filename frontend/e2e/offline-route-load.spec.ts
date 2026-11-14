// A section whose page code is not loaded yet, opened while offline, says the page needs the
// network instead of a server error, and opens by itself once the network is back.
// The default blocked service worker keeps the chunk from being precached, so the import fails.

import { expect, test } from './coverage-test';

import { words } from '../src/lib/words/en';
import { FlowGuard, loseNetwork, regainNetwork, shellOf, workspace } from './helpers';

const BACK_ONLINE_MS = 10_000;

test('a section opened offline shows the offline state and opens by itself after reconnect', async ({
	page,
	context
}, testInfo) => {
	const guard = new FlowGuard(page, { losesNetworkOnPurpose: true });
	await page.goto('/settings');
	// The desktop's /settings redirects into its first section; an offline click made before the
	// redirect would be overridden by it.
	if (shellOf(testInfo) === 'desktop') await expect(page).toHaveURL(/\/settings\/generation$/);
	const referencesLink = page.locator('a[href="/settings/references"]:visible');
	await expect(referencesLink).toBeVisible();

	await page.evaluate(() => {
		(window as Window & { stayedInPage?: boolean }).stayedInPage = true;
	});
	await loseNetwork(page, context);
	await referencesLink.click();

	await expect(
		page.getByRole('alert').filter({ hasText: words['routeError.offline'] })
	).toBeVisible();
	await expect(page.getByRole('heading', { name: '500', exact: true })).toHaveCount(0);
	await expect(page.getByText('Internal Error', { exact: true })).toHaveCount(0);

	await regainNetwork(page, context);

	await expect(
		workspace(page).getByRole('heading', { name: words['settingsSections.references'] })
	).toBeVisible({
		timeout: BACK_ONLINE_MS
	});
	await expect(
		page.getByRole('alert').filter({ hasText: words['routeError.offline'] })
	).toHaveCount(0);
	// A full reload would also show References, but would drop the marker.
	expect(
		await page.evaluate(() => (window as Window & { stayedInPage?: boolean }).stayedInPage)
	).toBe(true);
	guard.assertClean();
});

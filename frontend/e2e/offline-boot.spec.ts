import { expect, test, type Page } from '@playwright/test';
import { HOME_PATH, offlineStrip, waitForServiceWorkerControl } from './helpers';
import { readSeededLibrary } from './seed';

// Every flow here proves what the service worker answers offline.
test.use({ serviceWorkers: 'allow' });

/** The kit's look as the offline page shows it: both faces loadable from the shell cache, the token set. */
async function offlineLook(page: Page) {
	return page.evaluate(async () => {
		// check() is false for a declared face the page has not used yet, so ask the shell cache to load both.
		await Promise.all([
			document.fonts.load('700 16px Oswald'),
			document.fonts.load('400 16px "Open Sans"')
		]);
		return {
			displayFace: document.fonts.check('700 16px Oswald'),
			bodyFace: document.fonts.check('400 16px "Open Sans"'),
			background: getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()
		};
	});
}

for (const address of ['root', 'album'] as const) {
	test(`1160-F42-boot: an offline reload at the ${address} address shows the app's offline strip in the kit's faces and colours`, async ({
		page,
		context
	}) => {
		const path = address === 'root' ? HOME_PATH : `/album/${readSeededLibrary().songPhoneAlbumId}`;
		await page.goto(path);
		await waitForServiceWorkerControl(page);
		await context.setOffline(true);

		const response = await page.reload();

		expect(response?.ok()).toBe(true);
		expect(new URL(page.url()).pathname).toBe(path);
		await expect(offlineStrip(page)).toBeVisible();
		await expect
			.poll(() => offlineLook(page))
			.toEqual({
				displayFace: true,
				bodyFace: true,
				background: '#0d0d0d'
			});
	});
}

test('1160-F42-boot: an online health navigation still shows the server response after installation', async ({
	page
}) => {
	await page.goto(HOME_PATH);
	await waitForServiceWorkerControl(page);

	const response = await page.goto('/health');

	expect(response?.ok()).toBe(true);
	expect(response?.headers()['content-type']).toContain('application/json');
	expect(await response?.json()).toMatchObject({
		status: expect.stringMatching(/^(ok|degraded)$/)
	});
});

test('1859_R1: a browser holding offline copies from the old build loses them when the service worker takes over, and still boots offline', async ({
	page,
	context
}) => {
	const retiredCacheName = 'offline-streams';
	const snapshotId = 'old-build-snapshot';
	await page.goto('/health');
	await page.evaluate(
		async ({ cacheName, id }) => {
			const cache = await caches.open(cacheName);
			for (const path of [
				`/offline/stream/${id}`,
				`/offline/manifest/${id}`,
				`/offline/meta/playlist/${id}`
			]) {
				await cache.put(path, new Response('old copy'));
			}
		},
		{ cacheName: retiredCacheName, id: snapshotId }
	);

	await page.goto(HOME_PATH);
	await waitForServiceWorkerControl(page);

	await expect
		.poll(() => page.evaluate(async () => (await caches.keys()).sort()))
		.toEqual([expect.stringMatching(/^app-shell-/)]);
	await context.setOffline(true);
	const response = await page.reload();
	expect(response?.ok()).toBe(true);
	await expect(offlineStrip(page)).toBeVisible();
});

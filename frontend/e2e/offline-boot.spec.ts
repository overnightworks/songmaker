import { expect, test } from '@playwright/test';
import { HOME_PATH, offlineStrip, waitForServiceWorkerControl } from './helpers';
import { readSeededLibrary } from './seed';

for (const address of ['root', 'album'] as const) {
	test(`1160-F42-boot: an offline reload at the ${address} address shows the app's offline strip`, async ({
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

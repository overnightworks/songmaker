import { expect, test } from '@playwright/test';

import { seedVoiceTake } from './seed';

test('a musician creates a voice and adds an upload and one of their own takes at desktop and 375px', async ({
	page,
	request,
	isMobile
}, testInfo) => {
	if (isMobile) await page.setViewportSize({ width: 375, height: 844 });
	const source = await seedVoiceTake(request);
	const voiceName = `E2E Voice ${Date.now().toString(36)}`;

	await page.goto('/settings/voices');
	await page.getByRole('button', { name: 'New Voice', exact: true }).click();
	await page.getByPlaceholder('Voice name (e.g. My Tenor)').fill(voiceName);
	await page.getByRole('button', { name: 'Create', exact: true }).click();

	const voice = page.locator('.lora-card').filter({ hasText: voiceName });
	await expect(voice).toBeVisible();
	await expect(voice.getByText('No samples yet. Add at least 3 to train.')).toBeVisible();

	await voice.getByRole('button', { name: 'Use a take', exact: true }).click();
	const ownTakes = voice.getByRole('region', { name: 'Your takes', exact: true });
	const sourceTake = ownTakes.locator('li').filter({ hasText: source.songTitle });
	await expect(sourceTake).toContainText('Take 1');
	await sourceTake.getByRole('button', { name: 'Use as sample', exact: true }).click();

	const sampleFields = voice.locator('.sample-list textarea');
	await expect(sampleFields.nth(0)).toHaveValue(source.caption);
	await expect(sampleFields.nth(1)).toHaveValue(source.lyrics);

	const upload = voice.locator('.drop-zone');
	await upload.locator('input[type="file"]').setInputFiles('e2e/fixtures/take.mp3');
	await upload.locator('textarea').nth(0).fill('uploaded e2e caption');
	await upload.locator('textarea').nth(1).fill('uploaded e2e lyrics');
	await upload.getByRole('button', { name: 'Add sample', exact: true }).click();
	await expect(voice.locator('.sample-list li')).toHaveCount(2);

	if (isMobile) {
		await expect
			.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
			.toBe(true);
	}
	await page.screenshot({ path: testInfo.outputPath('voices.png'), fullPage: true });
});

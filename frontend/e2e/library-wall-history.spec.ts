import { expect, test, type Page } from '@playwright/test';
import {
	expectLibraryWallLoaded,
	FlowGuard,
	LIBRARY_PATH,
	LIBRARY_URL,
	openSettingsSection,
	openSettingsSectionFromSearch,
	shellOf,
	wallBody,
	workspace
} from './helpers';
import { readSeededLibrary } from './seed';
import { scrollWallTo } from './wall-scroll';

async function wallBounds(page: Page) {
	return wallBody(page).evaluate(async (body) => {
		await document.fonts.ready;
		const measure = () => ({
			scrollTop: Math.round(body.scrollTop),
			scrollHeight: body.scrollHeight,
			clientHeight: body.clientHeight
		});
		let previous = measure();
		for (;;) {
			await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
			const current = measure();
			if (
				current.scrollTop === previous.scrollTop &&
				current.scrollHeight === previous.scrollHeight &&
				current.clientHeight === previous.clientHeight
			)
				return current;
			previous = current;
		}
	});
}

for (const position of ['halfway', 'bottom'] as const) {
	test(`Back from Settings restores the wall at ${position}`, async ({ page }, testInfo) => {
		const guard = new FlowGuard(page);
		const library = readSeededLibrary();
		await page.goto(LIBRARY_PATH);
		await expect(
			wallBody(page).getByRole('button', { name: `Open album ${library.albumTitle}`, exact: true })
		).toBeVisible();
		await expectLibraryWallLoaded(page);
		const loaded = await wallBounds(page);
		expect(loaded.scrollHeight - loaded.clientHeight, JSON.stringify(loaded)).toBeGreaterThan(0);
		const leftAt = await scrollWallTo(page, position);
		const departed = await wallBounds(page);
		expect(departed.scrollTop, JSON.stringify(departed)).toBe(leftAt);
		const lastAlbum = wallBody(page)
			.getByRole('button', { name: /^Open album / })
			.last();
		const lastAlbumName = await lastAlbum.getAttribute('aria-label');
		if (!lastAlbumName) throw new Error('The final album must have an accessible name');
		if (position === 'bottom') {
			expect(departed.scrollTop, JSON.stringify(departed)).toBe(
				departed.scrollHeight - departed.clientHeight
			);
			await expect(lastAlbum).toBeInViewport({ ratio: 1 });
		}

		const shell = shellOf(testInfo);
		if (shell === 'mobile') await openSettingsSectionFromSearch(page, 'Voices');
		else await openSettingsSection(page, shell, 'Voices');
		await expect(page).toHaveURL(/\/settings\/voices$/);
		await expect(
			workspace(page).getByRole('heading', { name: 'My Voices', exact: true })
		).toBeVisible();
		await page.goBack();

		await expect(page).toHaveURL(LIBRARY_URL);
		await expectLibraryWallLoaded(page);
		await expect.poll(() => wallBounds(page)).toEqual(departed);
		if (position === 'bottom') {
			await expect(lastAlbum).toHaveAttribute('aria-label', lastAlbumName);
			await expect(lastAlbum).toBeInViewport({ ratio: 1 });
			const restored = await wallBounds(page);
			expect(
				restored.scrollHeight - restored.clientHeight - restored.scrollTop,
				JSON.stringify(restored)
			).toBe(0);
		}
		expect(await wallBounds(page)).toEqual(departed);
		guard.assertClean();
	});
}

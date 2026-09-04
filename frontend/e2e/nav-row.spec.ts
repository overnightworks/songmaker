import { expect, test } from '@playwright/test';
import { FlowGuard, nameStartingWith, workspace } from './helpers';
import { readSeededLibrary } from './seed';

function expectedSongSlug(title: string): string {
	return title.toLowerCase().replace(/\s+/g, '-');
}

test('the album row and its instant filter stay above a song and take on desktop', async ({
	page,
	isMobile
}) => {
	test.skip(Boolean(isMobile), 'This flow sets its own desktop-sized viewport');
	await page.setViewportSize({ width: 1440, height: 900 });
	const guard = new FlowGuard(page);
	const library = readSeededLibrary();
	const albumAddress = `/album/${library.albumId}`;
	const songAddress = `${albumAddress}/${expectedSongSlug(library.pickedSongTitle)}`;
	const surface = workspace(page);

	await page.goto(albumAddress);
	await surface.getByRole('button', { name: nameStartingWith(library.pickedSongTitle) }).click();
	await expect(page).toHaveURL(songAddress);

	const filter = surface.getByLabel('Filter albums by name');
	await expect(filter).toBeVisible();
	await filter.fill(library.albumTitle);
	await expect(
		surface.getByRole('button', { name: nameStartingWith(library.albumTitle) })
	).toBeVisible();

	await surface.getByRole('button', { name: 'Collapse albums' }).click();
	await expect(filter).toHaveCount(0);
	await expect(surface.getByText(`${library.albumTitle} · 3 songs`, { exact: true })).toBeVisible();

	await page.goto(`${songAddress}/take/1`);
	await expect(surface.getByRole('button', { name: 'Expand albums' })).toBeVisible();
	guard.assertClean();
});

test('a 375 px song or take starts with its album row collapsed until expanded', async ({
	page,
	isMobile
}) => {
	test.skip(!isMobile, 'This flow belongs to the mobile shell');
	await page.setViewportSize({ width: 375, height: 844 });
	await page.addInitScript(() => localStorage.removeItem('libraryRowOpen'));
	const guard = new FlowGuard(page);
	const library = readSeededLibrary();
	const albumAddress = `/album/${library.albumId}`;
	const songAddress = `${albumAddress}/${expectedSongSlug(library.pickedSongTitle)}`;
	const surface = workspace(page);

	await page.goto(albumAddress);
	await surface.getByRole('button', { name: nameStartingWith(library.pickedSongTitle) }).click();
	await expect(page).toHaveURL(songAddress);
	await expect(surface.getByRole('button', { name: 'Expand albums' })).toBeVisible();
	await expect(surface.getByLabel('Filter albums by name')).toHaveCount(0);

	await surface.getByRole('button', { name: 'Expand albums' }).click();
	await expect(surface.getByLabel('Filter albums by name')).toBeVisible();

	await page.goto(`${songAddress}/take/1`);
	await expect(surface.getByRole('button', { name: 'Collapse albums' })).toBeVisible();
	guard.assertClean();
});

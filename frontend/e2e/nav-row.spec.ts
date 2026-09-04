import { expect, test } from '@playwright/test';
import { boundingBoxes, FlowGuard, MOBILE_VIEWPORT, nameStartingWith, workspace } from './helpers';
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
	const collapsedSummaryLabel = `${library.albumTitle} · ${library.albumSongCount} songs`;
	const surface = workspace(page);

	await page.goto(albumAddress);
	const albumRow = surface.locator('.library-row-scrim');
	await expect(albumRow).toBeVisible();
	const [albumRowBox] = await boundingBoxes(albumRow);
	await surface.getByRole('button', { name: nameStartingWith(library.pickedSongTitle) }).click();
	await expect(page).toHaveURL(songAddress);
	const songRow = surface.locator('.library-row-scrim');
	await expect(songRow).toBeVisible();
	const [songRowBox] = await boundingBoxes(songRow);
	expect(songRowBox.x).toBeCloseTo(albumRowBox.x, 1);
	expect(songRowBox.y).toBeCloseTo(albumRowBox.y, 1);
	expect(songRowBox.width).toBeCloseTo(albumRowBox.width, 1);

	const filter = surface.getByLabel('Filter albums by name');
	await expect(filter).toBeVisible();
	await filter.fill(library.albumTitle);
	await expect(
		surface.getByRole('button', { name: nameStartingWith(library.albumTitle) })
	).toBeVisible();

	const collapseAlbums = surface.getByRole('button', { name: 'Collapse albums' });
	await expect(collapseAlbums).toBeVisible();
	await expect(collapseAlbums).toBeInViewport();
	await collapseAlbums.click();
	await expect(filter).toHaveCount(0);
	const collapsedSummary = surface.getByText(collapsedSummaryLabel, { exact: true });
	const expandAlbums = surface.getByRole('button', { name: 'Expand albums' });
	await expect(collapsedSummary).toBeVisible();
	await expect(expandAlbums).toBeVisible();
	await expect(expandAlbums).toBeInViewport();

	await page.goto(`${songAddress}/take/1`);
	const takeRow = surface.locator('.library-row-scrim');
	await expect(takeRow).toBeVisible();
	const [takeRowBox] = await boundingBoxes(takeRow);
	expect(takeRowBox.x).toBeCloseTo(songRowBox.x, 1);
	expect(takeRowBox.y).toBeCloseTo(songRowBox.y, 1);
	expect(takeRowBox.width).toBeCloseTo(songRowBox.width, 1);
	await expect(takeRow.getByText(collapsedSummaryLabel, { exact: true })).toBeVisible();
	await expect(takeRow.getByRole('button', { name: 'Expand albums' })).toBeInViewport();
	guard.assertClean();
});

test('a mobile song or take starts with its album row collapsed until expanded', async ({
	page,
	isMobile
}) => {
	test.skip(!isMobile, 'This flow belongs to the mobile shell');
	await page.setViewportSize(MOBILE_VIEWPORT);
	await page.addInitScript(() => {
		// Init scripts run on every document navigation. Clear the stored choice
		// only for this test's first document, so opening the row remains a
		// persisted browser preference when the test moves on to the take.
		if (sessionStorage.getItem('navRowPreferenceReset') === 'true') return;
		localStorage.removeItem('libraryRowOpen');
		sessionStorage.setItem('navRowPreferenceReset', 'true');
	});
	const guard = new FlowGuard(page);
	const library = readSeededLibrary();
	const albumAddress = `/album/${library.albumId}`;
	const songAddress = `${albumAddress}/${expectedSongSlug(library.pickedSongTitle)}`;
	const collapsedSummaryLabel = `${library.albumTitle} · ${library.albumSongCount} songs`;
	const surface = workspace(page);

	await page.goto(albumAddress);
	await surface.getByRole('button', { name: nameStartingWith(library.pickedSongTitle) }).click();
	await expect(page).toHaveURL(songAddress);
	const collapsedSummary = surface.getByText(collapsedSummaryLabel, { exact: true });
	const expandAlbums = surface.getByRole('button', { name: 'Expand albums' });
	await expect(collapsedSummary).toBeVisible();
	await expect(expandAlbums).toBeVisible();
	await expect(expandAlbums).toBeInViewport();
	await expect(surface.getByLabel('Filter albums by name')).toHaveCount(0);

	await expandAlbums.click();
	await expect(surface.getByLabel('Filter albums by name')).toBeVisible();
	const collapseAlbums = surface.getByRole('button', { name: 'Collapse albums' });
	await expect(collapseAlbums).toBeInViewport();

	await page.goto(`${songAddress}/take/1`);
	await expect(surface.getByText(collapsedSummaryLabel, { exact: true })).toBeVisible();
	await expect(collapseAlbums).toBeVisible();
	await expect(collapseAlbums).toBeInViewport();
	guard.assertClean();
});

test('Settings keeps the shared shell without an album row', async ({ page }) => {
	const guard = new FlowGuard(page);

	await page.goto('/settings/voices');

	await expect(workspace(page)).toBeVisible();
	await expect(workspace(page).locator('.library-row-scrim')).toHaveCount(0);
	guard.assertClean();
});

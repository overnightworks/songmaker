import { expect, test, type Locator, type Page } from '@playwright/test';
import {
	RAIL_DRAWER_LABEL,
	RAIL_DRAWER_OPEN_LABEL,
	RAIL_LIBRARY_NAV_LABEL,
	RAIL_NAV_LABEL,
	RAIL_SEARCH_LABEL
} from '../src/lib/constants';
import { boundingBoxes, FlowGuard, MOBILE_VIEWPORT, nameStartingWith, workspace } from './helpers';
import { readSeededLibrary } from './seed';

function expectedSongSlug(title: string): string {
	return title.toLowerCase().replace(/\s+/g, '-');
}

async function openRail(page: Page, mobile: boolean): Promise<Locator> {
	if (mobile) await page.getByRole('button', { name: RAIL_DRAWER_OPEN_LABEL }).click();
	const scope = mobile ? page.getByRole('dialog', { name: RAIL_DRAWER_LABEL }) : page;
	return scope.getByRole('navigation', { name: RAIL_NAV_LABEL });
}

test('the single rail search narrows the known tree and keeps the open album on desktop and 375 px', async ({
	page,
	isMobile
}) => {
	await page.setViewportSize(isMobile ? { width: 375, height: 812 } : { width: 1440, height: 900 });
	const guard = new FlowGuard(page);
	const library = readSeededLibrary();
	const surface = workspace(page);

	await page.goto(`/album/${library.albumId}`);
	await expect(surface.getByRole('heading', { name: library.albumTitle })).toBeVisible();

	const rail = await openRail(page, Boolean(isMobile));
	const search = rail.getByRole('searchbox', { name: RAIL_SEARCH_LABEL });
	await expect(search).toHaveCount(1);
	await expect(surface.locator('.search')).toHaveCount(0);

	await search.fill(library.secondAlbumSongTitle);
	const libraryTree = rail.getByRole('navigation', { name: RAIL_LIBRARY_NAV_LABEL });
	await expect(
		libraryTree.getByRole('button', { name: nameStartingWith(library.albumTitle) })
	).toBeVisible();
	await expect(
		libraryTree.getByRole('button', { name: nameStartingWith(library.secondAlbumSongTitle) })
	).toBeVisible();

	await search.press('Escape');
	await expect(search).toHaveValue('');
	if (isMobile) await expect(page.getByRole('dialog', { name: RAIL_DRAWER_LABEL })).toBeVisible();
	await expect(
		libraryTree.getByRole('button', { name: nameStartingWith('All albums') })
	).toBeVisible();
	guard.assertClean();
});

test('the album row stays above a song and take on desktop', async ({ page, isMobile }) => {
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

	const collapseAlbums = surface.getByRole('button', { name: 'Collapse albums' });
	await expect(collapseAlbums).toBeVisible();
	await expect(collapseAlbums).toBeInViewport();
	await collapseAlbums.click();
	const collapsedSummary = surface.getByText(collapsedSummaryLabel, { exact: true });
	const expandAlbums = surface.getByRole('button', { name: 'Expand albums' });
	await expect(collapsedSummary).toBeVisible();
	await expect(expandAlbums).toBeVisible();

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
	await expect(surface.getByLabel('Filter albums by name')).toHaveCount(0);

	await expandAlbums.click();
	await expect(surface.getByRole('button', { name: 'Collapse albums' })).toBeInViewport();

	await page.goto(`${songAddress}/take/1`);
	await expect(surface.getByText(collapsedSummaryLabel, { exact: true })).toBeVisible();
	await expect(surface.getByRole('button', { name: 'Collapse albums' })).toBeInViewport();
	guard.assertClean();
});

test('Settings keeps the shared shell without an album row', async ({ page }) => {
	const guard = new FlowGuard(page);

	await page.goto('/settings/voices');

	await expect(workspace(page)).toBeVisible();
	await expect(workspace(page).locator('.library-row-scrim')).toHaveCount(0);
	guard.assertClean();
});

import { expect, test, type Locator, type Page } from '@playwright/test';
import {
	RAIL_DRAWER_LABEL,
	RAIL_DRAWER_OPEN_LABEL,
	RAIL_NAV_LABEL,
	RAIL_SEARCH_LABEL
} from '../src/lib/constants';
import { FlowGuard, nameStartingWith, workspace } from './helpers';
import { readSeededLibrary } from './seed';

function expectedSongSlug(title: string): string {
	return title.toLowerCase().replace(/\s+/g, '-');
}

async function openRail(page: Page, mobile: boolean): Promise<Locator> {
	if (mobile) await page.getByRole('button', { name: RAIL_DRAWER_OPEN_LABEL }).click();
	const scope = mobile ? page.getByRole('dialog', { name: RAIL_DRAWER_LABEL }) : page;
	return scope.getByRole('navigation', { name: RAIL_NAV_LABEL });
}

test('the rail search finds a server song and closes the drawer on desktop and 375 px', async ({
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
	await expect(rail.locator('[aria-label="Library results"]')).toBeVisible();
	await rail.getByRole('button', { name: nameStartingWith(library.secondAlbumSongTitle) }).click();
	await expect(surface.getByRole('heading', { name: library.secondAlbumSongTitle })).toBeVisible();
	if (isMobile) await expect(page.getByRole('dialog', { name: RAIL_DRAWER_LABEL })).toBeHidden();
	guard.assertClean();
});

test('album, song, and take content begin at their breadcrumb headers on desktop and 375 px', async ({
	page,
	isMobile
}) => {
	await page.setViewportSize(isMobile ? { width: 375, height: 812 } : { width: 1440, height: 900 });
	const guard = new FlowGuard(page);
	const library = readSeededLibrary();
	const albumAddress = `/album/${library.albumId}`;
	const songAddress = `${albumAddress}/${expectedSongSlug(library.pickedSongTitle)}`;
	const surface = workspace(page);

	await page.goto(albumAddress);
	await expect(surface.locator(':scope > .detail-panel > .collection-header')).toBeVisible();
	await expect(surface.getByRole('navigation', { name: 'Breadcrumb' })).toBeVisible();
	await expect(surface.locator('.library-row-scrim')).toHaveCount(0);

	await surface.getByRole('button', { name: nameStartingWith(library.pickedSongTitle) }).click();
	await expect(page).toHaveURL(songAddress);
	await expect(surface.locator(':scope > .detail-panel > .detail-header')).toBeVisible();
	if (isMobile) {
		await expect(surface.locator('.mobile-album-line')).toBeVisible();
		await expect(surface.locator('.detail-header [aria-label="Breadcrumb"]')).toHaveCount(0);
	} else {
		await expect(surface.getByRole('navigation', { name: 'Breadcrumb' })).toBeVisible();
	}
	await expect(surface.locator('.library-row-scrim')).toHaveCount(0);

	await page.goto(`${songAddress}/take/1`);
	await expect(surface.locator(':scope > .detail-panel > .detail-header')).toBeVisible();
	if (isMobile) {
		await expect(surface.locator('.mobile-album-line')).toBeVisible();
		await expect(surface.locator('.detail-header [aria-label="Breadcrumb"]')).toHaveCount(0);
	} else {
		await expect(surface.getByRole('navigation', { name: 'Breadcrumb' })).toBeVisible();
	}
	await expect(surface.locator('.library-row-scrim')).toHaveCount(0);

	guard.assertClean();
});

test('the 375 px album line skips songs without losing its URL or focus', async ({
	page,
	isMobile
}) => {
	test.skip(!isMobile, 'The compact album line only renders on mobile.');
	await page.setViewportSize({ width: 375, height: 812 });
	const guard = new FlowGuard(page);
	const library = readSeededLibrary();
	const surface = workspace(page);
	const firstSongAddress = `/album/${library.albumId}/${expectedSongSlug('Opening Move')}`;
	const secondSongAddress = `/album/${library.albumId}/${expectedSongSlug('Second Wind')}`;

	await page.goto(`/album/${library.albumId}`);
	await expect(surface.getByRole('heading', { name: library.albumTitle })).toBeVisible();
	await surface.getByRole('button', { name: nameStartingWith(library.pickedSongTitle) }).click();
	await expect(page).toHaveURL(firstSongAddress);
	const line = surface.locator('.mobile-album-line');
	await expect(line).toBeVisible();
	await expect(line).toContainText(`${library.albumTitle} · ${library.albumSongCount} songs`);
	await expect(line.locator('.album-line-cover')).toBeVisible();
	await expect(surface.locator('.detail-header [aria-label="Breadcrumb"]')).toHaveCount(0);
	await expect(surface.locator('.library-row-scrim')).toHaveCount(0);

	const next = line.getByRole('button', { name: 'Next song' });
	await next.focus();
	await expect(next).toBeFocused();
	await next.click();
	await expect(page).toHaveURL(secondSongAddress);
	await expect(next).toBeFocused();
	await expect(line).toBeVisible();
	guard.assertClean();
});

test('Settings keeps the shared shell without an album row', async ({ page }) => {
	const guard = new FlowGuard(page);

	await page.goto('/settings/voices');

	await expect(workspace(page)).toBeVisible();
	await expect(workspace(page).locator('.library-row-scrim')).toHaveCount(0);
	guard.assertClean();
});

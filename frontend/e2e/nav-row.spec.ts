import { expect, test, type Locator, type Page } from '@playwright/test';
import {
	RAIL_DRAWER_LABEL,
	RAIL_DRAWER_OPEN_LABEL,
	RAIL_NAV_LABEL,
	RAIL_SEARCH_CLEAR_LABEL,
	RAIL_SEARCH_LABEL
} from '../src/lib/constants';
import { FlowGuard, appBar, nameStartingWith, workspace } from './helpers';
import { readSeededLibrary } from './seed';

function expectedSongSlug(title: string): string {
	return title.toLowerCase().replace(/\s+/g, '-');
}

async function openRail(page: Page, mobile: boolean): Promise<Locator> {
	if (mobile) await page.getByRole('button', { name: RAIL_DRAWER_OPEN_LABEL }).click();
	const scope = mobile ? page.getByRole('dialog', { name: RAIL_DRAWER_LABEL }) : page;
	return scope.getByRole('navigation', { name: RAIL_NAV_LABEL });
}

const PHONE_SEARCH_BAR_PX = 44;
const PHONE_RESULT_ROW_MIN_PX = 48;
const QUERY_MATCHING_EVERY_SEEDED_ALBUM = 'E2E';

async function expectPhoneBarHeight(rail: Locator, mobile: boolean): Promise<void> {
	if (!mobile) return;
	const bar = await rail.locator('.rail-search').boundingBox();
	expect(bar?.height).toBe(PHONE_SEARCH_BAR_PX);
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
	const search = rail.getByRole('combobox', { name: RAIL_SEARCH_LABEL });
	await expect(search).toHaveCount(1);
	await expect(surface.locator('.search')).toHaveCount(0);

	await search.fill(library.secondAlbumSongTitle);
	await expect(rail.getByRole('group', { name: 'Songs' })).toBeVisible();
	await rail.getByRole('option', { name: nameStartingWith(library.secondAlbumSongTitle) }).click();
	const songHeading = isMobile ? appBar(page) : surface;
	await expect(
		songHeading.getByRole('heading', { name: library.secondAlbumSongTitle })
	).toBeVisible();
	if (isMobile) await expect(page.getByRole('dialog', { name: RAIL_DRAWER_LABEL })).toBeHidden();
	guard.assertClean();
});

test('the rail search tells an album from its songs and finds a settings page in one bar at desktop and 390 px', async ({
	page,
	isMobile
}) => {
	await page.setViewportSize(isMobile ? { width: 390, height: 844 } : { width: 1440, height: 900 });
	const guard = new FlowGuard(page);
	const library = readSeededLibrary();

	await page.goto(`/album/${library.albumId}`);
	const rail = await openRail(page, Boolean(isMobile));
	const search = rail.getByRole('combobox', { name: RAIL_SEARCH_LABEL });
	await expectPhoneBarHeight(rail, Boolean(isMobile));

	await search.fill(QUERY_MATCHING_EVERY_SEEDED_ALBUM);
	const albumResults = rail.getByRole('group', { name: 'Albums' });
	await expect(albumResults).toBeVisible();
	await expectPhoneBarHeight(rail, Boolean(isMobile));
	if (isMobile) {
		const row = await albumResults.getByRole('option').first().boundingBox();
		expect(row?.height).toBeGreaterThanOrEqual(PHONE_RESULT_ROW_MIN_PX);
	}

	await search.fill(library.albumTitle);
	await expect(search).toHaveCSS('box-shadow', 'none');
	const albums = rail.getByRole('group', { name: 'Albums' });
	await expect(
		albums.getByRole('option', { name: nameStartingWith(library.albumTitle) })
	).toContainText('Album ·');
	await expect(rail.getByRole('button', { name: RAIL_SEARCH_CLEAR_LABEL })).toBeVisible();

	await search.fill('gen');
	const generation = rail
		.getByRole('group', { name: 'Pages' })
		.getByRole('option', { name: nameStartingWith('Generation') });
	await expect(generation).toContainText('Page · Settings');

	await rail.getByRole('button', { name: RAIL_SEARCH_CLEAR_LABEL }).click();
	await expect(search).toHaveValue('');
	await expect(search).toBeFocused();
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
	if (isMobile) {
		// The layout's own app bar carries the song header at compact widths
		// (PhoneAppBar.svelte, mounted outside <main>); SongDetailView renders
		// neither .detail-header nor .mobile-album-line there any more.
		await expect(
			appBar(page).getByRole('heading', { name: library.pickedSongTitle })
		).toBeVisible();
		await expect(surface.locator('.detail-header')).toHaveCount(0);
		await expect(surface.locator('.mobile-album-line')).toHaveCount(0);
	} else {
		await expect(surface.locator(':scope > .detail-panel > .detail-header')).toBeVisible();
		await expect(surface.getByRole('navigation', { name: 'Breadcrumb' })).toBeVisible();
	}
	await expect(surface.locator('.library-row-scrim')).toHaveCount(0);

	await page.goto(`${songAddress}/take/1`);
	if (isMobile) {
		await expect(
			appBar(page).getByRole('heading', { name: library.pickedSongTitle })
		).toBeVisible();
		await expect(surface.locator('.detail-header')).toHaveCount(0);
		await expect(surface.locator('.mobile-album-line')).toHaveCount(0);
	} else {
		await expect(surface.locator(':scope > .detail-panel > .detail-header')).toBeVisible();
		await expect(surface.getByRole('navigation', { name: 'Breadcrumb' })).toBeVisible();
	}
	await expect(surface.locator('.library-row-scrim')).toHaveCount(0);

	guard.assertClean();
});

test('Settings keeps the shared shell without an album row', async ({ page }) => {
	const guard = new FlowGuard(page);

	await page.goto('/settings/voices');

	await expect(workspace(page)).toBeVisible();
	await expect(workspace(page).locator('.library-row-scrim')).toHaveCount(0);
	guard.assertClean();
});

// Back closes whatever is open (#1006, slice #1114): an overlay owns one
// history entry on top of the page it covers, so Back closes it and leaves
// that page as it was, and only the next Back moves the library. Leaving the
// overlay by navigating from it takes its entry along: one Back afterwards
// returns to the page it was opened over.
//
// One table, one row per overlay and way of leaving it: the phone's rail
// drawer and, on the desktop, the full Now Playing surface, which Back docks
// to the side panel as Escape does.

import { expect, test, type Locator, type Page } from '@playwright/test';
import {
	collectionPlayLabel,
	NOW_PLAYING_LABEL,
	RAIL_DRAWER_LABEL,
	RAIL_DRAWER_OPEN_LABEL,
	RAIL_LIBRARY_LABEL,
	RAIL_SETTINGS_LABEL
} from '../src/lib/constants';
import { NOW_PLAYING_EXPAND_LABEL } from '../src/lib/constants/now-playing';
import { FlowGuard, openLibraryWall, openRailNav, shellOf, workspace, type Shell } from './helpers';
import { readSeededLibrary, seedPlaylist, type SeededPlaylist } from './seed';

const SETTINGS_SECTION = 'Voices';

interface Pages {
	wall: Locator;
	playlist: Locator;
	playlistAddress: string;
}

type LibraryPage = 'wall' | 'playlist';

interface OverlayRow {
	name: string;
	shell: Shell;
	open: (page: Page, playlist: SeededPlaylist) => Promise<void>;
	leave: (page: Page, playlist: SeededPlaylist) => Promise<void>;
	expectLeft: (page: Page, pages: Pages, playlist: SeededPlaylist) => Promise<void>;
	backReaches: LibraryPage;
}

function railDrawer(page: Page): Locator {
	return page.getByRole('dialog', { name: RAIL_DRAWER_LABEL });
}

async function openRailDrawer(page: Page): Promise<void> {
	await page.getByRole('button', { name: RAIL_DRAWER_OPEN_LABEL }).click();
	await expect(railDrawer(page)).toBeVisible();
}

async function expandNowPlaying(page: Page, playlist: SeededPlaylist): Promise<void> {
	const [playing] = playlist.songTitles;
	await workspace(page)
		.getByRole('button', { name: collectionPlayLabel('playlist'), exact: true })
		.click();
	await page
		.getByRole('contentinfo')
		.getByRole('button', { name: NOW_PLAYING_LABEL, exact: true })
		.click();
	const docked = page.getByRole('complementary', { name: playing });
	await docked.getByRole('button', { name: NOW_PLAYING_EXPAND_LABEL, exact: true }).click();
	await expect(page.getByRole('dialog', { name: playing })).toBeVisible();
}

async function expectPlaylistStands(page: Page, pages: Pages): Promise<void> {
	await expect(pages.playlist).toBeVisible();
	expect(page.url()).toBe(pages.playlistAddress);
}

async function expectReached(page: Page, pages: Pages, reached: LibraryPage): Promise<void> {
	if (reached === 'playlist') {
		await expectPlaylistStands(page, pages);
		return;
	}
	await expect(pages.wall).toBeVisible();
	await expect(page).toHaveURL(/\/$/);
}

const OVERLAY_ROWS: OverlayRow[] = [
	{
		name: 'Back closes the phone rail drawer and keeps the playlist',
		shell: 'mobile',
		open: openRailDrawer,
		leave: async (page) => {
			await page.goBack();
		},
		expectLeft: async (page, pages) => {
			await expect(railDrawer(page)).toBeHidden();
			await expectPlaylistStands(page, pages);
		},
		backReaches: 'wall'
	},
	{
		name: 'a row tap in the phone rail drawer leaves one Back to the playlist',
		shell: 'mobile',
		open: openRailDrawer,
		leave: async (page) => {
			await openLibraryWall(page, 'mobile');
		},
		expectLeft: async (_page, pages) => {
			await expect(pages.wall).toBeVisible();
		},
		backReaches: 'playlist'
	},
	{
		name: 'a Settings link in the phone rail drawer leaves one Back to the playlist',
		shell: 'mobile',
		open: openRailDrawer,
		leave: async (page) => {
			const rail = await openRailNav(page, 'mobile');
			await rail.getByRole('button', { name: RAIL_SETTINGS_LABEL }).click();
			await rail.getByRole('link', { name: SETTINGS_SECTION, exact: true }).click();
		},
		expectLeft: async (page) => {
			await expect(page).toHaveURL(/\/settings\/voices$/);
			await expect(railDrawer(page)).toBeHidden();
		},
		backReaches: 'playlist'
	},
	{
		name: 'Back docks the full Now Playing on the desktop and keeps the playlist',
		shell: 'desktop',
		open: expandNowPlaying,
		leave: async (page) => {
			await page.goBack();
		},
		expectLeft: async (page, pages, playlist) => {
			const [playing] = playlist.songTitles;
			await expect(page.getByRole('complementary', { name: playing })).toBeVisible();
			await expect(page.getByRole('dialog', { name: playing })).toBeHidden();
			await expectPlaylistStands(page, pages);
		},
		backReaches: 'wall'
	}
];

test.describe('Back closes the open overlay first', () => {
	for (const row of OVERLAY_ROWS) {
		test(row.name, async ({ page, request }, testInfo) => {
			test.skip(shellOf(testInfo) !== row.shell, `The row belongs to the ${row.shell} shell.`);
			const guard = new FlowGuard(page);
			const playlist = await seedPlaylist(request, readSeededLibrary());
			const surface = workspace(page);
			await page.goto('/');
			const wall = surface.getByRole('heading', { name: RAIL_LIBRARY_LABEL });
			await expect(wall).toBeVisible();
			await surface
				.locator('.library-wall .tile-grid')
				.locator('.wall-tile-body')
				.filter({ hasText: playlist.title })
				.click();
			const playlistHeading = surface.getByRole('heading', { name: playlist.title });
			await expect(playlistHeading).toBeVisible();
			const pages: Pages = { wall, playlist: playlistHeading, playlistAddress: page.url() };

			await row.open(page, playlist);
			await row.leave(page, playlist);
			await row.expectLeft(page, pages, playlist);

			await page.goBack();
			await expectReached(page, pages, row.backReaches);
			guard.assertClean();
		});
	}
});

import { expect, test, type Locator, type Page } from '@playwright/test';
import {
	collectionPlayLabel,
	NOW_PLAYING_LABEL,
	PLAYLIST_ENTRY_OPEN_SONG_LABEL,
	playlistEntryOverflowLabel,
	RAIL_DRAWER_LABEL,
	RAIL_DRAWER_OPEN_LABEL,
	RAIL_LIBRARY_LABEL,
	RAIL_SETTINGS_LABEL,
	SONG_MENU_LABEL,
	TAKE_OVERFLOW_LABEL
} from '../src/lib/constants';
import {
	NOW_PLAYING_EXPAND_LABEL,
	NOW_PLAYING_RIGHT_PANEL_LABEL,
	takeRowLabel
} from '../src/lib/constants/now-playing';
import {
	appBar,
	FlowGuard,
	nameStartingWith,
	openLibraryWall,
	openRailNav,
	shellOf,
	workspace,
	type Shell
} from './helpers';
import { readSeededLibrary, seedPlaylist, type SeededPlaylist } from './seed';

const SETTINGS_SECTION = 'Voices';
const SETTINGS_SECTION_HEADING = 'My Voices';
const SONG_ADDRESS = /\/album\/[^/]+\/[^/]+/;
// The base library's songs each carry one reimported take, their first.
const SEEDED_TAKE_NUMBER = 1;

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
	afterwards: (page: Page, pages: Pages, playlist: SeededPlaylist) => Promise<void>;
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

function firstSong(playlist: SeededPlaylist): string {
	const [first] = playlist.songTitles;
	return first;
}

function songBar(page: Page, shell: Shell): Locator {
	return shell === 'mobile' ? appBar(page) : workspace(page);
}

async function expectSongStands(page: Page, shell: Shell, title: string): Promise<void> {
	await expect(songBar(page, shell).getByRole('heading', { name: title })).toBeVisible();
	await expect(page).toHaveURL(SONG_ADDRESS);
}

async function openEntryMenu(page: Page, playlist: SeededPlaylist): Promise<void> {
	await workspace(page)
		.getByRole('button', { name: playlistEntryOverflowLabel(firstSong(playlist)) })
		.click();
	await expect(workspace(page).getByRole('menu')).toBeVisible();
}

async function openSongFromEntryMenu(page: Page): Promise<void> {
	await workspace(page).getByRole('menuitem', { name: PLAYLIST_ENTRY_OPEN_SONG_LABEL }).click();
}

async function openSongsTakes(page: Page, playlist: SeededPlaylist): Promise<Locator> {
	await openEntryMenu(page, playlist);
	await openSongFromEntryMenu(page);
	await expectSongStands(page, 'mobile', firstSong(playlist));
	await page.getByRole('tab', { name: /Takes/ }).click();
	return page.getByRole('tabpanel');
}

function takeSheet(page: Page): Locator {
	return page.getByRole('dialog', { name: NOW_PLAYING_RIGHT_PANEL_LABEL });
}

async function goBack(page: Page): Promise<void> {
	await page.goBack();
}

function songMenuRow(shell: Shell): OverlayRow {
	return {
		name: `Back closes the song menu ${shell === 'mobile' ? 'from the phone app bar' : 'on the desktop'} and keeps the song`,
		shell,
		open: async (page, playlist) => {
			await openEntryMenu(page, playlist);
			await openSongFromEntryMenu(page);
			await expectSongStands(page, shell, firstSong(playlist));
			await songBar(page, shell).getByRole('button', { name: SONG_MENU_LABEL }).click();
			await expect(page.getByRole('dialog', { name: SONG_MENU_LABEL })).toBeVisible();
		},
		leave: goBack,
		expectLeft: async (page, _pages, playlist) => {
			await expect(page.getByRole('dialog', { name: SONG_MENU_LABEL })).toBeHidden();
			await expectSongStands(page, shell, firstSong(playlist));
		},
		afterwards: backReaches('playlist')
	};
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

function backReaches(reached: LibraryPage): OverlayRow['afterwards'] {
	return async (page, pages) => {
		await page.goBack();
		await expectReached(page, pages, reached);
	};
}

async function backThenForwardReturnsToSettings(page: Page): Promise<void> {
	await page.goBack();
	await page.goForward();
	await expect(page).toHaveURL(/\/settings\/voices$/);
	await expect(page.getByRole('heading', { name: SETTINGS_SECTION_HEADING })).toBeVisible();
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
		afterwards: backReaches('wall')
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
		afterwards: backReaches('playlist')
	},
	{
		name: 'a Settings link in the phone rail drawer closes it, and Back then Forward return to Settings',
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
		afterwards: backThenForwardReturnsToSettings
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
		afterwards: backReaches('wall')
	},
	{
		name: 'a playlist entry menu item that opens the song leaves one Back to the playlist',
		shell: 'mobile',
		open: openEntryMenu,
		leave: openSongFromEntryMenu,
		expectLeft: async (page, _pages, playlist) => {
			await expectSongStands(page, 'mobile', firstSong(playlist));
		},
		afterwards: backReaches('playlist')
	},
	{
		name: 'Back closes the take menu and keeps the song',
		shell: 'mobile',
		open: async (page, playlist) => {
			const takes = await openSongsTakes(page, playlist);
			await takes.getByRole('button', { name: TAKE_OVERFLOW_LABEL, exact: true }).first().click();
			await expect(page.getByRole('menu')).toBeVisible();
		},
		leave: goBack,
		expectLeft: async (page, _pages, playlist) => {
			await expect(page.getByRole('menu')).toBeHidden();
			await expectSongStands(page, 'mobile', firstSong(playlist));
		},
		afterwards: backReaches('playlist')
	},
	songMenuRow('mobile'),
	songMenuRow('desktop'),
	{
		name: 'Back over Now Playing closes the This take sheet first, and the next Back closes Now Playing',
		shell: 'mobile',
		open: async (page, playlist) => {
			const takes = await openSongsTakes(page, playlist);
			await takes
				.getByRole('button', { name: nameStartingWith(takeRowLabel(SEEDED_TAKE_NUMBER)) })
				.click();
			await expect(page.getByRole('dialog', { name: firstSong(playlist) })).toBeVisible();
			await expect(takeSheet(page)).toBeVisible();
		},
		leave: goBack,
		expectLeft: async (page, _pages, playlist) => {
			await expect(takeSheet(page)).toBeHidden();
			await expect(page.getByRole('dialog', { name: firstSong(playlist) })).toBeVisible();
		},
		afterwards: async (page, _pages, playlist) => {
			await page.goBack();
			await expect(page.getByRole('dialog', { name: firstSong(playlist) })).toBeHidden();
			await expectSongStands(page, 'mobile', firstSong(playlist));
		}
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
			await expect(page).toHaveURL(/\/playlist\//);
			const pages: Pages = { wall, playlist: playlistHeading, playlistAddress: page.url() };

			await row.open(page, playlist);
			await row.leave(page, playlist);
			await row.expectLeft(page, pages, playlist);

			await row.afterwards(page, pages, playlist);
			guard.assertClean();
		});
	}
});

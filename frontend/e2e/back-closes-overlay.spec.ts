import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import {
	COLLECTION_MENU_LABEL,
	collectionPlayLabel,
	DIALOG_CANCEL_LABEL,
	EDITOR_TAB_EDIT_LABEL,
	EDITOR_UNSAVED_TITLE,
	NOW_PLAYING_GO_TO_SONG,
	NOW_PLAYING_LABEL,
	openNowPlayingLabel,
	PLAYLIST_ENTRY_OPEN_SONG_LABEL,
	playlistEntryOverflowLabel,
	RAIL_DRAWER_LABEL,
	RAIL_DRAWER_OPEN_LABEL,
	RAIL_LIBRARY_LABEL,
	RAIL_LIBRARY_NAV_LABEL,
	RAIL_SETTINGS_LABEL,
	SONG_MENU_ADD_TO_PLAYLIST_LABEL,
	SONG_MENU_LABEL,
	TAKE_DELETE_LABEL,
	TAKE_DELETE_TITLE_TEMPLATE,
	TAKE_OVERFLOW_LABEL,
	TRANSPORT_PAUSE_LABEL
} from '../src/lib/constants';
import {
	NOW_PLAYING_EXPAND_LABEL,
	NOW_PLAYING_RIGHT_PANEL_LABEL,
	nowPlayingSheetCloseLabel,
	takeRowLabel
} from '../src/lib/constants/now-playing';
import {
	appBar,
	containing,
	csrfHeaders,
	FlowGuard,
	nameStartingWith,
	openLibraryWall,
	openRailNav,
	openSettingsFromAccountMenu,
	openSettingsSectionFromDrawerSearch,
	playlistEntryRows,
	shellOf,
	workspace,
	type Shell
} from './helpers';
import { readSeededLibrary, runMarker, seedPlaylist, type SeededPlaylist } from './seed';

const SETTINGS_SECTION = 'Voices';
const SETTINGS_SECTION_HEADING = 'My Voices';
const SONG_ADDRESS = /\/album\/[^/]+\/[^/]+/;
// The base library's songs each carry one reimported take, their first.
const SEEDED_TAKE_NUMBER = 1;
const PLAYLIST_PICKER_LABEL = 'Add to Playlist';
const SHARE_WARNING_LABEL = 'Missing from the share page';
const DRAFT_LINE = 'a line nobody saved';

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

async function openTakeSheetOverNowPlaying(page: Page, playlist: SeededPlaylist): Promise<void> {
	const takes = await openSongsTakes(page, playlist);
	await takes
		.getByRole('button', { name: nameStartingWith(takeRowLabel(SEEDED_TAKE_NUMBER)) })
		.click();
	await expect(page.getByRole('dialog', { name: firstSong(playlist) })).toBeVisible();
	await expect(takeSheet(page)).toBeVisible();
}

// The sheet has no close button of its own: its dimmed backdrop closes it.
// Now Playing's header stays above the backdrop, so the tap lands on the
// strip of backdrop just above the sheet.
async function tapBesideTakeSheet(page: Page): Promise<void> {
	const backdrop = page.getByRole('button', {
		name: nowPlayingSheetCloseLabel(NOW_PLAYING_RIGHT_PANEL_LABEL)
	});
	const [backdropBox, sheetBox] = await Promise.all([
		backdrop.boundingBox(),
		takeSheet(page).boundingBox()
	]);
	if (!backdropBox || !sheetBox) throw new Error('The This take sheet is not on screen');
	await backdrop.click({ position: { x: 8, y: sheetBox.y - backdropBox.y - 8 } });
}

async function goBack(page: Page): Promise<void> {
	await page.goBack();
}

async function pressEscape(page: Page): Promise<void> {
	await page.keyboard.press('Escape');
}

async function openSong(page: Page, shell: Shell, playlist: SeededPlaylist): Promise<void> {
	await openEntryMenu(page, playlist);
	await openSongFromEntryMenu(page);
	await expectSongStands(page, shell, firstSong(playlist));
}

// The phone lists takes under their tab; the desktop shows them beside the lyrics.
async function songsTakes(page: Page, shell: Shell): Promise<Locator> {
	if (shell === 'desktop') return workspace(page);
	await page.getByRole('tab', { name: /Takes/ }).click();
	return page.getByRole('tabpanel');
}

function seededTakeRow(takes: Locator): Locator {
	return takes.getByRole('button', { name: nameStartingWith(takeRowLabel(SEEDED_TAKE_NUMBER)) });
}

function deleteConfirm(page: Page): Locator {
	return page.getByRole('dialog', {
		name: TAKE_DELETE_TITLE_TEMPLATE.replace('{number}', String(SEEDED_TAKE_NUMBER))
	});
}

async function openDeleteConfirm(
	page: Page,
	shell: Shell,
	playlist: SeededPlaylist
): Promise<void> {
	await openSong(page, shell, playlist);
	const takes = await songsTakes(page, shell);
	await takes.getByRole('button', { name: TAKE_OVERFLOW_LABEL, exact: true }).first().click();
	await page.getByRole('menuitem', { name: TAKE_DELETE_LABEL, exact: true }).click();
	await expect(deleteConfirm(page)).toBeVisible();
}

function deleteConfirmRow(shell: Shell): OverlayRow {
	return {
		name: `Back cancels the delete confirmation ${shell === 'mobile' ? 'on the phone' : 'on the desktop'}: the take stays`,
		shell,
		open: (page, playlist) => openDeleteConfirm(page, shell, playlist),
		leave: goBack,
		expectLeft: async (page, _pages, playlist) => {
			await expect(deleteConfirm(page)).toBeHidden();
			await expectSongStands(page, shell, firstSong(playlist));
			await expect(seededTakeRow(await songsTakes(page, shell))).toBeVisible();
		},
		afterwards: backReaches('playlist')
	};
}

function lyricsField(page: Page): Locator {
	return page.getByRole('textbox', { name: /^Lyrics/ });
}

function unsavedDraftDialog(page: Page): Locator {
	return page.getByRole('dialog', { name: EDITOR_UNSAVED_TITLE });
}

// Escape takes the song one level up to its collection, which a dirty draft
// holds back with the unsaved-draft dialog.
async function leaveWithADirtyDraft(page: Page, playlist: SeededPlaylist): Promise<string> {
	await openSong(page, 'mobile', playlist);
	await page.getByRole('tab', { name: EDITOR_TAB_EDIT_LABEL, exact: true }).click();
	const lyrics = lyricsField(page);
	const saved = await lyrics.inputValue();
	await lyrics.fill(`${saved}\n${DRAFT_LINE}`);
	await lyrics.blur();
	await page.keyboard.press('Escape');
	await expect(unsavedDraftDialog(page)).toBeVisible();
	return saved;
}

function unsavedDraftRow(): OverlayRow {
	let savedLyrics = '';
	return {
		name: 'Back on the unsaved-draft dialog keeps editing: the song stays with its draft',
		shell: 'mobile',
		open: async (page, playlist) => {
			savedLyrics = await leaveWithADirtyDraft(page, playlist);
		},
		leave: goBack,
		expectLeft: async (page, _pages, playlist) => {
			await expect(unsavedDraftDialog(page)).toBeHidden();
			await expectSongStands(page, 'mobile', firstSong(playlist));
			await expect(lyricsField(page)).toHaveValue(new RegExp(`${DRAFT_LINE}$`));
		},
		afterwards: async (page, pages, playlist) => {
			await lyricsField(page).fill(savedLyrics);
			await backReaches('playlist')(page, pages, playlist);
		}
	};
}

function playlistPicker(page: Page): Locator {
	return page.getByRole('dialog', { name: PLAYLIST_PICKER_LABEL });
}

const PLAYLIST_PICKER_ROW: OverlayRow = {
	name: 'Back closes the playlist picker from the song menu and adds nothing',
	shell: 'mobile',
	open: async (page, playlist) => {
		await openSong(page, 'mobile', playlist);
		await appBar(page).getByRole('button', { name: SONG_MENU_LABEL }).click();
		await page
			.getByRole('dialog', { name: SONG_MENU_LABEL })
			.getByRole('button', { name: SONG_MENU_ADD_TO_PLAYLIST_LABEL })
			.click();
		await expect(playlistPicker(page)).toBeVisible();
	},
	leave: goBack,
	expectLeft: async (page, _pages, playlist) => {
		await expect(playlistPicker(page)).toBeHidden();
		await expectSongStands(page, 'mobile', firstSong(playlist));
	},
	afterwards: async (page, pages, playlist) => {
		await backReaches('playlist')(page, pages, playlist);
		await expect(playlistEntryRows(page)).toHaveCount(playlist.songTitles.length);
	}
};

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

function settingsHeading(page: Page): Locator {
	return page.getByRole('heading', { name: SETTINGS_SECTION_HEADING });
}

async function expectSettingsStands(page: Page): Promise<void> {
	await expect(page).toHaveURL(/\/settings\/voices$/);
	await expect(settingsHeading(page)).toBeVisible();
}

function openVoicesFromDrawerSearch(page: Page): Promise<void> {
	return openSettingsSectionFromDrawerSearch(page, SETTINGS_SECTION);
}

async function openVoicesSettings(page: Page, shell: Shell): Promise<void> {
	if (shell === 'mobile') {
		await openVoicesFromDrawerSearch(page);
	} else {
		const rail = await openRailNav(page, shell);
		await rail.getByRole('button', { name: RAIL_SETTINGS_LABEL }).click();
		await rail.getByRole('link', { name: SETTINGS_SECTION, exact: true }).click();
	}
	await expectSettingsStands(page);
}

// Issue #1165: Back leaves Settings for the playlist it was opened over, with
// the playlist on screen, and Forward shows Settings again.
async function backThenForwardReturnsToSettings(page: Page, pages: Pages): Promise<void> {
	await page.goBack();
	await expectPlaylistStands(page, pages);
	await expect(settingsHeading(page)).toBeHidden();
	await page.goForward();
	await expectSettingsStands(page);
	await expect(pages.playlist).toBeHidden();
}

const OVERLAY_ROWS: OverlayRow[] = [
	{
		name: 'Back closes the phone rail drawer and keeps the playlist',
		shell: 'mobile',
		open: openRailDrawer,
		leave: goBack,
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
		name: 'a Settings page found in the phone rail drawer closes it, and Back then Forward return to Settings',
		shell: 'mobile',
		open: openRailDrawer,
		leave: openVoicesFromDrawerSearch,
		expectLeft: async (page) => {
			await expectSettingsStands(page);
			await expect(railDrawer(page)).toBeHidden();
		},
		afterwards: backThenForwardReturnsToSettings
	},
	{
		name: 'Back docks the full Now Playing on the desktop and keeps the playlist',
		shell: 'desktop',
		open: expandNowPlaying,
		leave: goBack,
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
	deleteConfirmRow('mobile'),
	deleteConfirmRow('desktop'),
	{
		name: 'Cancel on the delete confirmation leaves one Back to the playlist',
		shell: 'mobile',
		open: (page, playlist) => openDeleteConfirm(page, 'mobile', playlist),
		leave: async (page) => {
			await deleteConfirm(page)
				.getByRole('button', { name: DIALOG_CANCEL_LABEL, exact: true })
				.click();
		},
		expectLeft: async (page, _pages, playlist) => {
			await expect(deleteConfirm(page)).toBeHidden();
			await expectSongStands(page, 'mobile', firstSong(playlist));
		},
		afterwards: backReaches('playlist')
	},
	unsavedDraftRow(),
	PLAYLIST_PICKER_ROW,
	{
		name: 'Back over Now Playing closes the This take sheet first, and the next Back closes Now Playing',
		shell: 'mobile',
		open: openTakeSheetOverNowPlaying,
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
	},
	// Issue #1219: the sheet's own close steps back off its entry while the
	// Back pressed right after it is underway; each landing says by its entry
	// which layers it left, so the Back closes Now Playing and nothing more.
	{
		name: 'a tap beside the This take sheet plus an immediate Back closes one layer more and keeps the song',
		shell: 'mobile',
		open: openTakeSheetOverNowPlaying,
		leave: async (page) => {
			await tapBesideTakeSheet(page);
			await page.goBack();
		},
		expectLeft: async (page, _pages, playlist) => {
			await expect(takeSheet(page)).toBeHidden();
			await expect(page.getByRole('dialog', { name: firstSong(playlist) })).toBeHidden();
			await expectSongStands(page, 'mobile', firstSong(playlist));
		},
		afterwards: backReaches('playlist')
	}
];

function wallTiles(page: Page): Locator {
	return workspace(page).locator('.library-wall .tile-grid');
}

// A fresh playlist, opened from the wall the way a person does: one entry for
// the wall, one for the playlist.
async function openSeededPlaylist(
	page: Page,
	request: APIRequestContext
): Promise<{ playlist: SeededPlaylist; pages: Pages }> {
	const playlist = await seedPlaylist(request, readSeededLibrary());
	const surface = workspace(page);
	await page.goto('/');
	const wall = surface.getByRole('heading', { name: RAIL_LIBRARY_LABEL });
	await expect(wall).toBeVisible();
	await wallTiles(page).locator('.wall-tile-body').filter({ hasText: playlist.title }).click();
	const playlistHeading = surface.getByRole('heading', { name: playlist.title });
	await expect(playlistHeading).toBeVisible();
	await expect(page).toHaveURL(/\/playlist\//);
	return { playlist, pages: { wall, playlist: playlistHeading, playlistAddress: page.url() } };
}

// Escape closes what Back closes (#1182): every row where Back closes an
// overlay runs again with Escape in its place, and leaves the same history.
function escapeInsteadOfBack(row: OverlayRow): OverlayRow {
	return { ...row, name: row.name.replace(/^Back/, 'Escape'), leave: pressEscape };
}

const ESCAPE_ROWS = OVERLAY_ROWS.filter((row) => row.leave === goBack).map(escapeInsteadOfBack);

test.describe('Back and Escape close the open overlay first', () => {
	for (const row of [...OVERLAY_ROWS, ...ESCAPE_ROWS]) {
		test(row.name, async ({ page, request }, testInfo) => {
			test.skip(shellOf(testInfo) !== row.shell, `The row belongs to the ${row.shell} shell.`);
			const guard = new FlowGuard(page);
			const { playlist, pages } = await openSeededPlaylist(page, request);

			await row.open(page, playlist);
			await row.leave(page, playlist);
			await row.expectLeft(page, pages, playlist);

			await row.afterwards(page, pages, playlist);
			guard.assertClean();
		});
	}
});

// Issue #1165: Settings is a page of its own, and Back and Forward move
// between it and the library page it was opened over -- after a reload too.
test.describe('Back and Forward between the library and Settings', () => {
	test('Back from Settings returns to the playlist left, and Forward to Settings', async ({
		page,
		request
	}, testInfo) => {
		const guard = new FlowGuard(page);
		const { pages } = await openSeededPlaylist(page, request);

		await openVoicesSettings(page, shellOf(testInfo));

		await backThenForwardReturnsToSettings(page, pages);
		guard.assertClean();
	});

	// The phone's account menu is a history layer of its own, and choosing
	// Settings in it steps off that layer before Settings opens.
	test('Back from Settings opened in the phone account menu returns to the playlist, and Forward to Settings', async ({
		page,
		request
	}, testInfo) => {
		test.skip(shellOf(testInfo) !== 'mobile', 'The account menu belongs to the mobile shell.');
		const guard = new FlowGuard(page);
		const { pages } = await openSeededPlaylist(page, request);
		await openSettingsFromAccountMenu(page);
		const settingsIndex = page.getByRole('heading', { name: RAIL_SETTINGS_LABEL, exact: true });
		await expect(page).toHaveURL(/\/settings$/);
		await expect(settingsIndex).toBeVisible();

		await page.goBack();

		await expectPlaylistStands(page, pages);
		await expect(settingsIndex).toBeHidden();

		await page.goForward();

		await expect(page).toHaveURL(/\/settings$/);
		await expect(settingsIndex).toBeVisible();
		await expect(pages.playlist).toBeHidden();
		guard.assertClean();
	});

	test('after a reload on the playlist, Back from Settings returns to it', async ({
		page,
		request
	}, testInfo) => {
		const guard = new FlowGuard(page);
		const { pages } = await openSeededPlaylist(page, request);
		await page.reload();
		await expectPlaylistStands(page, pages);

		await openVoicesSettings(page, shellOf(testInfo));
		await page.goBack();

		await expectPlaylistStands(page, pages);
		await expect(settingsHeading(page)).toBeHidden();
		guard.assertClean();
	});

	test('after a reload on the playlist, Back shows the wall it was opened from', async ({
		page,
		request
	}) => {
		const guard = new FlowGuard(page);
		const { pages } = await openSeededPlaylist(page, request);
		await page.reload();
		await expectPlaylistStands(page, pages);

		await page.goBack();

		await expectReached(page, pages, 'wall');
		await expect(pages.playlist).toBeHidden();
		guard.assertClean();
	});

	test('Back from Settings onto the wall leaves focus out of its tiles', async ({
		page
	}, testInfo) => {
		const guard = new FlowGuard(page);
		await page.goto('/');
		const wall = workspace(page).getByRole('heading', { name: RAIL_LIBRARY_LABEL });
		await expect(wall).toBeVisible();
		await openVoicesSettings(page, shellOf(testInfo));

		await page.goBack();

		await expect(wall).toBeVisible();
		await expect(page).toHaveURL(/\/$/);
		await expect(wallTiles(page).locator(':focus')).toHaveCount(0);
		guard.assertClean();
	});

	test('the phone drawer left open over a reload is gone, and one Back reaches the wall', async ({
		page,
		request
	}, testInfo) => {
		test.skip(shellOf(testInfo) !== 'mobile', 'The drawer belongs to the mobile shell.');
		const guard = new FlowGuard(page);
		const { pages } = await openSeededPlaylist(page, request);
		await openRailDrawer(page);

		await page.reload();

		await expect(railDrawer(page)).toBeHidden();
		await expectPlaylistStands(page, pages);
		// The library steps off the drawer's own entry by itself once it runs.
		await expect
			.poll(() => page.evaluate(() => JSON.stringify(history.state).includes('"layer"')))
			.toBe(false);
		await page.goBack();
		await expectReached(page, pages, 'wall');
		guard.assertClean();
	});
});

// Issue #1165: the library shows a song the moment it opens, before the
// router has loaded the song's route. Back pressed then must still step once,
// onto the album -- the race is one of milliseconds, so the song opens more
// than once, each time pressed as soon as it shows.
const SONG_OPENS = 4;

test('one Back right after a song opens from its album returns to the album', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const library = readSeededLibrary();
	const surface = workspace(page);
	await page.goto('/');
	await wallTiles(page).locator('.wall-tile-body').filter({ hasText: library.albumTitle }).click();
	const album = surface.getByRole('heading', { name: library.albumTitle });
	await expect(album).toBeVisible();
	const albumAddress = page.url();
	const song = songBar(page, shellOf(testInfo)).getByRole('heading', {
		name: library.pickedSongTitle
	});
	const songRow = surface.getByRole('button', { name: nameStartingWith(library.pickedSongTitle) });

	for (let open = 1; open <= SONG_OPENS; open += 1) {
		await songRow.click();
		await expect(song).toBeVisible();

		await page.goBack();

		await expect(album).toBeVisible();
		expect(page.url()).toBe(albumAddress);
	}
	guard.assertClean();
});

// Issue #1165: a crossing the phone opens out of a history layer -- an album
// tapped in the rail drawer, Go to song in Now Playing -- is written behind
// the layer's step back. Back pressed as soon as the page shows must still
// step once, onto the playlist underneath, and not past it -- the race is one
// of milliseconds, so each crossing is opened and left many times.
const QUEUED_CROSSINGS = 20;
const PHONE_LAYERS_ONLY = 'The drawer and the full Now Playing are phone layers.';
async function openAlbumFromRailDrawer(page: Page, albumTitle: string): Promise<void> {
	const rail = await openRailNav(page, 'mobile');
	const libraryGroup = rail.getByRole('button', { name: nameStartingWith(RAIL_LIBRARY_LABEL) });
	if ((await libraryGroup.getAttribute('aria-expanded')) === 'false') await libraryGroup.click();
	await rail
		.getByRole('navigation', { name: RAIL_LIBRARY_NAV_LABEL })
		.getByRole('listitem')
		.filter({ hasText: albumTitle })
		.getByRole('button', { name: containing(albumTitle) })
		.click();
}

async function goToPlayingSong(page: Page, title: string): Promise<void> {
	await page
		.getByRole('contentinfo')
		.getByRole('button', { name: openNowPlayingLabel(title) })
		.click();
	const nowPlaying = page.getByRole('dialog', { name: title });
	await nowPlaying.getByRole('button', { name: NOW_PLAYING_GO_TO_SONG, exact: true }).click();
}

test.describe('one Back right after a crossing out of a phone layer', () => {
	test('an album tapped in the rail drawer returns to the playlist', async ({
		page,
		request
	}, testInfo) => {
		test.skip(shellOf(testInfo) !== 'mobile', PHONE_LAYERS_ONLY);
		const guard = new FlowGuard(page);
		const { pages } = await openSeededPlaylist(page, request);
		const library = readSeededLibrary();
		const album = workspace(page).getByRole('heading', { name: library.albumTitle });

		for (let open = 1; open <= QUEUED_CROSSINGS; open += 1) {
			await openAlbumFromRailDrawer(page, library.albumTitle);
			await expect(album).toBeVisible();

			await page.goBack();

			await expectPlaylistStands(page, pages);
		}
		guard.assertClean();
	});

	test('Go to song in Now Playing returns to the playlist', async ({ page, request }, testInfo) => {
		test.skip(shellOf(testInfo) !== 'mobile', PHONE_LAYERS_ONLY);
		const guard = new FlowGuard(page);
		const { playlist, pages } = await openSeededPlaylist(page, request);
		await workspace(page)
			.getByRole('button', { name: collectionPlayLabel('playlist'), exact: true })
			.click();
		// Paused, so the seeded three-second take stays the playing song.
		await page
			.getByRole('contentinfo')
			.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true })
			.click();

		for (let open = 1; open <= QUEUED_CROSSINGS; open += 1) {
			await goToPlayingSong(page, firstSong(playlist));
			await expectSongStands(page, 'mobile', firstSong(playlist));

			await page.goBack();

			await expectPlaylistStands(page, pages);
		}
		guard.assertClean();
	});
});

interface CreatedAlbum {
	id: string;
}

async function postAsSession<T>(page: Page, url: string, data: unknown): Promise<T> {
	const response = await page.request.post(url, { data, headers: await csrfHeaders(page) });
	expect(response.ok(), `POST ${url} failed: ${await response.text()}`).toBeTruthy();
	return (await response.json()) as T;
}

// Sharing marks the album shared, so each attempt shares an album of its own
// whose one song has no take -- the case the share warning names.
async function seedAlbumWithoutTakes(page: Page): Promise<{ id: string; title: string }> {
	const title = `E2E Share Warning Album ${runMarker()}`;
	const album = await postAsSession<CreatedAlbum>(page, '/api/albums', { title });
	await postAsSession(page, '/api/songs', {
		title: `E2E Song Without A Take ${runMarker()}`,
		album_id: album.id,
		lyrics: 'No take was ever made of this.',
		prompt: 'calm test tone'
	});
	return { id: album.id, title };
}

async function deleteAlbum(page: Page, albumId: string): Promise<void> {
	const response = await page.request.delete(`/api/albums/${albumId}`, {
		headers: await csrfHeaders(page)
	});
	expect(
		response.ok(),
		`DELETE /api/albums/${albumId} failed: ${await response.text()}`
	).toBeTruthy();
}

test('Back closes the share warning on the phone and keeps the album', async ({
	page
}, testInfo) => {
	test.skip(shellOf(testInfo) !== 'mobile', 'The row belongs to the mobile shell.');
	const guard = new FlowGuard(page);
	await page.goto('/');
	const album = await seedAlbumWithoutTakes(page);
	try {
		await page.goto(`/album/${album.id}`);
		const albumHeading = workspace(page).getByRole('heading', { name: album.title });
		await expect(albumHeading).toBeVisible();
		const albumAddress = page.url();

		await page.getByRole('button', { name: COLLECTION_MENU_LABEL, exact: true }).click();
		await page.getByRole('dialog', { name: COLLECTION_MENU_LABEL }).locator('.share-btn').click();
		const warning = page.getByRole('dialog', { name: SHARE_WARNING_LABEL });
		await expect(warning).toBeVisible();

		await page.goBack();
		await expect(warning).toBeHidden();
		await expect(albumHeading).toBeVisible();
		expect(page.url()).toBe(albumAddress);

		await page.goBack();
		await expect(page).not.toHaveURL(albumAddress);
		guard.assertClean();
	} finally {
		await deleteAlbum(page, album.id);
	}
});

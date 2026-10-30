import { openSearchSheet, phoneSearchResult, searchSheet } from './phone-search';
import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import {
	mockPlaylist,
	playlistPayload,
	PLAYLIST_API,
	PLAYLIST_URL
} from './share-playlist-fixtures';
import {
	COLLECTION_MENU_LABEL,
	COLLECTION_MENU_SHARE_LABEL,
	collectionActionLabel,
	DIALOG_CANCEL_LABEL,
	EDITOR_TAB_EDIT_LABEL,
	EDITOR_UNSAVED_TITLE,
	NOW_PLAYING_GO_TO_SONG,
	NOW_PLAYING_LABEL,
	openNowPlayingLabel,
	playlistEntryOverflowLabel,
	PLAYLISTS_PAGE_LABEL,
	LIBRARY_PAGE_LABEL,
	RAIL_LIBRARY_NAV_LABEL,
	RAIL_SEARCH_LABEL,
	RAIL_SETTINGS_LABEL,
	SONG_MENU_ADD_TO_PLAYLIST_LABEL,
	SONG_MENU_LABEL,
	TAKE_DELETE_LABEL,
	TAKE_DELETE_TITLE_TEMPLATE,
	TAKE_OVERFLOW_LABEL,
	TRANSPORT_PAUSE_LABEL,
	TRANSPORT_PLAY_LABEL,
	songEditorOpenLabel
} from '../src/lib/constants';
import {
	NOW_PLAYING_EXPAND_LABEL,
	NOW_PLAYING_RIGHT_PANEL_LABEL,
	nowPlayingSheetCloseLabel,
	takeRowLabel
} from '../src/lib/constants/now-playing';
import {
	accountCircle,
	accountMenu,
	appBar,
	containing,
	sameOriginHeaders,
	FlowGuard,
	nameStartingWith,
	ONLY_IN_SHELL,
	openRailNav,
	openSettingsSectionFromSearch,
	playlistEntryRows,
	shellOf,
	standsOnLayerEntry,
	workspace,
	type Shell,
	HOME_PATH,
	LIBRARY_PATH,
	LIBRARY_URL
} from './helpers';
import {
	deleteVoiceProofData,
	readSeededLibrary,
	runMarker,
	seedPlaylist,
	seedVoiceDrafts,
	type SeededPlaylist
} from './seed';

const PLAY_PLAYLIST_LABEL = collectionActionLabel(TRANSPORT_PLAY_LABEL, 'playlist');

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

async function expandNowPlaying(page: Page, playlist: SeededPlaylist): Promise<void> {
	const [playing] = playlist.songTitles;
	await workspace(page).getByRole('button', { name: PLAY_PLAYLIST_LABEL, exact: true }).click();
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

// The entry's ✎ is the one way from a playlist row to its song (#1383).
async function openSongFromEntryPencil(page: Page, playlist: SeededPlaylist): Promise<void> {
	await workspace(page)
		.getByRole('button', { name: songEditorOpenLabel(firstSong(playlist)) })
		.click();
}

async function openSongsTakes(page: Page, playlist: SeededPlaylist): Promise<Locator> {
	await openSongFromEntryPencil(page, playlist);
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
	await openSongFromEntryPencil(page, playlist);
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

function takeMenu(page: Page): Locator {
	return page.getByRole('dialog', { name: TAKE_OVERFLOW_LABEL, exact: true });
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
	await takeMenu(page).getByRole('button', { name: TAKE_DELETE_LABEL, exact: true }).click();
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
			await openSongFromEntryPencil(page, playlist);
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
	await expect(page).toHaveURL(/\/playlists$/);
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

function openVoicesFromSearch(page: Page): Promise<void> {
	return openSettingsSectionFromSearch(page, SETTINGS_SECTION);
}

async function openVoicesSettings(page: Page, shell: Shell): Promise<void> {
	if (shell === 'mobile') {
		await openVoicesFromSearch(page);
	} else {
		const rail = await openRailNav(page, shell);
		await rail.getByRole('button', { name: RAIL_SETTINGS_LABEL }).click();
		await rail.getByRole('link', { name: SETTINGS_SECTION, exact: true }).click();
	}
	await expectSettingsStands(page);
}

// The desktop rail's library list, with its group expanded.
async function railLibrary(page: Page, shell: Shell): Promise<Locator> {
	const rail = await openRailNav(page, shell);
	const libraryGroup = rail.getByRole('button', { name: nameStartingWith(LIBRARY_PAGE_LABEL) });
	if ((await libraryGroup.getAttribute('aria-expanded')) === 'false') await libraryGroup.click();
	return rail.getByRole('navigation', { name: RAIL_LIBRARY_NAV_LABEL });
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
		name: 'defect:#1583: a Settings page found in the Search sheet closes it, and Back then Forward return to Settings',
		shell: 'mobile',
		open: async (page) => {
			await openSearchSheet(page);
		},
		leave: openVoicesFromSearch,
		expectLeft: async (page) => {
			await expectSettingsStands(page);
			await expect(searchSheet(page)).toBeHidden();
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
		name: "a playlist entry's ✎ tapped while its menu is open leaves one Back to the playlist",
		shell: 'mobile',
		open: openEntryMenu,
		leave: openSongFromEntryPencil,
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
			await expect(takeMenu(page)).toBeVisible();
		},
		leave: goBack,
		expectLeft: async (page, _pages, playlist) => {
			await expect(takeMenu(page)).toBeHidden();
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

function wallTileNamed(page: Page, title: string): Locator {
	return wallTiles(page).locator('.wall-tile-body').filter({ hasText: title });
}

// A fresh playlist, opened from the Playlists page the way a person does: one
// entry for the page, one for the playlist.
async function openSeededPlaylist(
	page: Page,
	request: APIRequestContext
): Promise<{ playlist: SeededPlaylist; pages: Pages }> {
	const playlist = await seedPlaylist(request, readSeededLibrary());
	const surface = workspace(page);
	await page.goto('/playlists');
	const wall = surface.getByRole('heading', { name: PLAYLISTS_PAGE_LABEL });
	await expect(wall).toBeVisible();
	await wallTileNamed(page, playlist.title).click();
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
	// Each row belongs to one shell, and only that shell's project runs it.
	for (const row of [...OVERLAY_ROWS, ...ESCAPE_ROWS]) {
		test(row.name, { tag: ONLY_IN_SHELL[row.shell] }, async ({ page, request }) => {
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

	// The phone's search sheet is a history layer of its own, and choosing a
	// page in it steps off that layer before the page opens (#1354 rule 26).
	test(
		'Back from Voices chosen in the phone search sheet returns to the playlist, and Forward to Voices',
		{ tag: ONLY_IN_SHELL.mobile },
		async ({ page, request }) => {
			const guard = new FlowGuard(page);
			const { pages } = await openSeededPlaylist(page, request);
			const sheet = await openSearchSheet(page);
			await sheet.getByRole('combobox', { name: RAIL_SEARCH_LABEL }).fill(SETTINGS_SECTION);
			await sheet
				.getByRole('group', { name: 'Pages' })
				.getByRole('option', { name: nameStartingWith(SETTINGS_SECTION) })
				.click();
			await expect(searchSheet(page)).toBeHidden();
			await expectSettingsStands(page);

			await page.goBack();

			await expectPlaylistStands(page, pages);
			await expect(settingsHeading(page)).toBeHidden();

			await page.goForward();

			await expectSettingsStands(page);
			await expect(pages.playlist).toBeHidden();
			guard.assertClean();
		}
	);

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
		await page.goto(LIBRARY_PATH);
		const wall = workspace(page).getByRole('heading', { name: LIBRARY_PAGE_LABEL });
		await expect(wall).toBeVisible();
		await openVoicesSettings(page, shellOf(testInfo));

		await page.goBack();

		await expect(wall).toBeVisible();
		await expect(page).toHaveURL(LIBRARY_URL);
		await expect(wallTiles(page).locator(':focus')).toHaveCount(0);
		guard.assertClean();
	});

	// Search is a phone layer.
	test(
		'1354_rule_30 1354_rule_31: the search sheet left open over a reload on the playlist is gone, and one Back reaches the wall',
		{ tag: ONLY_IN_SHELL.mobile },
		async ({ page, request }) => {
			const guard = new FlowGuard(page);
			const { pages } = await openSeededPlaylist(page, request);
			await openSearchSheet(page);
			await expect.poll(() => standsOnLayerEntry(page)).toBe(true);

			await page.reload();

			await expect(searchSheet(page)).toBeHidden();
			await expectPlaylistStands(page, pages);
			// The library steps off the sheet's own entry by itself once it runs.
			await expect.poll(() => standsOnLayerEntry(page)).toBe(false);
			await page.goBack();
			await expectReached(page, pages, 'wall');
			guard.assertClean();
		}
	);

	// The Search sheet closes before Settings pushes its destination entry.
	test(
		'defect:#1583: Search to Settings pushes one entry over the playlist, and Back returns to it',
		{ tag: ONLY_IN_SHELL.mobile },
		async ({ page, request }) => {
			const guard = new FlowGuard(page);
			const { pages } = await openSeededPlaylist(page, request);
			const entriesOnPlaylist = await page.evaluate(() => history.length);

			await openVoicesFromSearch(page);
			await expectSettingsStands(page);
			expect(await page.evaluate(() => history.length)).toBe(entriesOnPlaylist + 1);

			await page.goBack();

			await expectPlaylistStands(page, pages);
			await expect(searchSheet(page)).toBeHidden();
			guard.assertClean();
		}
	);
});

// Issue #1006 (H3): a library page opened over another of the same kind is
// written without loading its route, so Back from Settings onto it would load
// the route of the page under it. The history entry wins: Back shows the page
// left, at its own address.
test.describe('Back from Settings onto a page opened over another of its kind', () => {
	test('1354_37a_A3: album A, album B, Settings, Back shows album B at its address', async ({
		page
	}, testInfo) => {
		const shell = shellOf(testInfo);
		const guard = new FlowGuard(page);
		const library = readSeededLibrary();
		const surface = workspace(page);
		const albumA = surface.getByRole('heading', { name: library.albumTitle });
		const albumB = surface.getByRole('heading', { name: library.secondAlbumTitle });
		await page.goto(`/album/${library.albumId}`);
		await expect(albumA).toBeVisible();
		const albumAAddress = page.url();
		await openAlbumFromNavigation(page, shell, library.secondAlbumTitle);
		await expect(albumB).toBeVisible();
		await expect(page).not.toHaveURL(albumAAddress);
		const albumBAddress = page.url();

		await openVoicesSettings(page, shell);
		await page.goBack();

		await expect(albumB).toBeVisible();
		await expect(albumA).toBeHidden();
		expect(page.url()).toBe(albumBAddress);
		guard.assertClean();
	});

	test('1354_37a_A4: a song, the next song, Settings, Back shows the next song at its address', async ({
		page
	}, testInfo) => {
		const shell = shellOf(testInfo);
		const guard = new FlowGuard(page);
		const [song, nextSong] = readSeededLibrary().albumTracks;
		await page.goto(`/album/${readSeededLibrary().albumId}`);
		await workspace(page)
			.getByRole('button', { name: songEditorOpenLabel(song.songTitle) })
			.click();
		await expectSongStands(page, shell, song.songTitle);
		const songAddress = page.url();
		if (shell === 'mobile') {
			await (
				await phoneSearchResult(
					page,
					'Songs',
					nextSong.songTitle,
					nameStartingWith(nextSong.songTitle)
				)
			).click();
		} else {
			await (
				await railLibrary(page, shell)
			)
				.getByRole('button', { name: nameStartingWith(nextSong.songTitle) })
				.click();
		}
		await expectSongStands(page, shell, nextSong.songTitle);
		await expect(page).not.toHaveURL(songAddress);
		const nextSongAddress = page.url();

		await openVoicesSettings(page, shell);
		await page.goBack();

		await expectSongStands(page, shell, nextSong.songTitle);
		expect(page.url()).toBe(nextSongAddress);
		guard.assertClean();
	});
});

// Issue #1006 (H5): the first Back from Settings loads the album's route, and a
// second Back pressed while it loads lands on the wall -- 30 ms after it, or
// in the same task, where the router takes the second for shallow routing and
// abandons the first. However quickly the two follow, the screen shows the
// page the address names, and the album's own entry stays for Forward; the
// race is one of milliseconds, so the two Backs are pressed many times.
const DOUBLE_BACKS = 8;

async function pressBackTwice(page: Page, gapMs: number): Promise<void> {
	await page.evaluate(async (gap) => {
		history.back();
		await new Promise((resolve) => setTimeout(resolve, gap));
		history.back();
	}, gapMs);
}

for (const gapMs of [30, 0]) {
	test(`two Backs ${gapMs} ms apart from Settings show the wall at its address and keep the album for Forward`, async ({
		page
	}, testInfo) => {
		const guard = new FlowGuard(page);
		const library = readSeededLibrary();
		const surface = workspace(page);
		const wall = surface.getByRole('heading', { name: LIBRARY_PAGE_LABEL });
		const album = surface.getByRole('heading', { name: library.albumTitle });
		await page.goto(LIBRARY_PATH);
		await wallTiles(page)
			.locator('.wall-tile-body')
			.filter({ hasText: library.albumTitle })
			.click();
		await expect(album).toBeVisible();
		const albumAddress = page.url();
		await openVoicesSettings(page, shellOf(testInfo));

		for (let attempt = 1; attempt <= DOUBLE_BACKS; attempt += 1) {
			await pressBackTwice(page, gapMs);

			await expect(wall, `the wall after the two Backs of attempt ${attempt}`).toBeVisible();
			await expect(page).toHaveURL(LIBRARY_URL);
			await expect(settingsHeading(page)).toBeHidden();
			await expect(album).toBeHidden();

			await page.goForward();

			await expect(album, `the album after Forward on attempt ${attempt}`).toBeVisible();
			expect(page.url()).toBe(albumAddress);

			await page.goForward();

			await expectSettingsStands(page);
		}
		guard.assertClean();
	});
}

// Both Backs in one task: the router hears the second before the first has
// loaded anything.
async function pressBackTwiceInOneTask(page: Page): Promise<void> {
	await page.evaluate(() => {
		history.back();
		history.back();
	});
}

// Issue #1006 (H5): from Settings opened over a song, the second of two Backs
// pressed in one task reaches the album while the router still loads the
// song's route, which it then abandons, and the router keeps the page of
// Settings under the album's route. The album shows at its own address, with
// the wall below it for Back, and Forward walks the album, the song and
// Settings again; the race is one of milliseconds, so the two Backs are
// pressed many times.
test('two Backs in one task from Settings over a song show the album at its address', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const library = readSeededLibrary();
	const shell = shellOf(testInfo);
	const surface = workspace(page);
	const wall = surface.getByRole('heading', { name: LIBRARY_PAGE_LABEL });
	const album = surface.getByRole('heading', { name: library.albumTitle });
	const song = songBar(page, shell).getByRole('heading', { name: library.pickedSongTitle });
	await page.goto(LIBRARY_PATH);
	await wallTiles(page).locator('.wall-tile-body').filter({ hasText: library.albumTitle }).click();
	await expect(album).toBeVisible();
	const albumAddress = page.url();
	await surface.getByRole('button', { name: songEditorOpenLabel(library.pickedSongTitle) }).click();
	await expect(song).toBeVisible();
	await openVoicesSettings(page, shell);

	for (let attempt = 1; attempt <= DOUBLE_BACKS; attempt += 1) {
		await pressBackTwiceInOneTask(page);

		await expect(album, `the album after the two Backs of attempt ${attempt}`).toBeVisible();
		await expect(page).toHaveURL(albumAddress);
		await expect(settingsHeading(page)).toBeHidden();

		await page.goBack();

		await expect(wall, `the wall below the album on attempt ${attempt}`).toBeVisible();
		await expect(page).toHaveURL(LIBRARY_URL);

		await page.goForward();

		await expect(album, `the album after Forward on attempt ${attempt}`).toBeVisible();
		await expect(page).toHaveURL(albumAddress);

		await page.goForward();

		await expect(song).toBeVisible();

		await page.goForward();

		await expectSettingsStands(page);
	}
	guard.assertClean();
});

// Issues #1165 and #1263: the library shows a song the moment it opens,
// before the router has loaded the song's route, and its address moves with
// it. Back pressed then must still step once, onto the album -- the race is
// one of milliseconds, so the song opens many times, each time read and
// pressed as soon as it shows.
const SONG_OPENS = 20;

test('one Back right after a song opens from its album returns to the album', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const library = readSeededLibrary();
	const surface = workspace(page);
	await page.goto(LIBRARY_PATH);
	await wallTiles(page).locator('.wall-tile-body').filter({ hasText: library.albumTitle }).click();
	const album = surface.getByRole('heading', { name: library.albumTitle });
	await expect(album).toBeVisible();
	const albumAddress = page.url();
	const song = songBar(page, shellOf(testInfo)).getByRole('heading', {
		name: library.pickedSongTitle
	});
	const songRow = surface.getByRole('button', {
		name: songEditorOpenLabel(library.pickedSongTitle)
	});

	for (let open = 1; open <= SONG_OPENS; open += 1) {
		await songRow.click();
		await expect(song).toBeVisible();
		expect(page.url(), `the song's address on open ${open}`).toMatch(SONG_ADDRESS);

		await page.goBack();

		await expect(album).toBeVisible();
		expect(page.url(), `the album's address after Back ${open}`).toBe(albumAddress);
	}
	guard.assertClean();
});

// Issue #1165: a crossing the phone opens out of a history layer -- an album
// selected in Search, Go to song in Now Playing -- is written behind
// the layer's step back. Back pressed as soon as the page shows must still
// step once, onto the playlist underneath, and not past it -- the race is one
// of milliseconds, so each crossing is opened and left many times.
const QUEUED_CROSSINGS = 20;
async function openAlbumFromNavigation(
	page: Page,
	shell: Shell,
	albumTitle: string
): Promise<void> {
	if (shell === 'mobile') {
		await (
			await phoneSearchResult(page, 'Albums', albumTitle, nameStartingWith(albumTitle))
		).click();
		return;
	}
	await (
		await railLibrary(page, shell)
	)
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

// Search and the full Now Playing are phone layers.
test.describe(
	'one Back right after a crossing out of a phone layer',
	{ tag: ONLY_IN_SHELL.mobile },
	() => {
		test('1354_37a_A3: an album selected in Search returns to the playlist', async ({
			page,
			request
		}) => {
			const guard = new FlowGuard(page);
			const { pages } = await openSeededPlaylist(page, request);
			const library = readSeededLibrary();
			const album = workspace(page).getByRole('heading', { name: library.albumTitle });

			for (let open = 1; open <= QUEUED_CROSSINGS; open += 1) {
				await openAlbumFromNavigation(page, 'mobile', library.albumTitle);
				await expect(album).toBeVisible();

				await page.goBack();

				await expectPlaylistStands(page, pages);
			}
			guard.assertClean();
		});

		test('Go to song in Now Playing returns to the playlist', async ({ page, request }) => {
			const guard = new FlowGuard(page);
			const { playlist, pages } = await openSeededPlaylist(page, request);
			await workspace(page).getByRole('button', { name: PLAY_PLAYLIST_LABEL, exact: true }).click();
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
	}
);

interface CreatedAlbum {
	id: string;
}

async function postAsSession<T>(page: Page, url: string, data: unknown): Promise<T> {
	const response = await page.request.post(url, { data, headers: await sameOriginHeaders(page) });
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
		headers: await sameOriginHeaders(page)
	});
	expect(
		response.ok(),
		`DELETE /api/albums/${albumId} failed: ${await response.text()}`
	).toBeTruthy();
}

// This flow belongs to the mobile shell.
test(
	'Back closes the share warning on the phone and keeps the album',
	{ tag: ONLY_IN_SHELL.mobile },
	async ({ page }) => {
		const guard = new FlowGuard(page);
		await page.goto(HOME_PATH);
		const album = await seedAlbumWithoutTakes(page);
		try {
			await page.goto(`/album/${album.id}`);
			const albumHeading = workspace(page).getByRole('heading', { name: album.title });
			await expect(albumHeading).toBeVisible();
			const albumAddress = page.url();

			await page.getByRole('button', { name: COLLECTION_MENU_LABEL, exact: true }).click();
			await page
				.getByRole('dialog', { name: COLLECTION_MENU_LABEL })
				.getByRole('button', { name: COLLECTION_MENU_SHARE_LABEL, exact: true })
				.click();
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
	}
);

// The phone's account circle lives on the Library (#1354 rule 27), and its
// menu is a history layer of its own there: Back closes it and keeps the wall.
test(
	'Back closes the account menu on the Library and the address stays',
	{ tag: ONLY_IN_SHELL.mobile },
	async ({ page }) => {
		const guard = new FlowGuard(page);
		await page.goto(LIBRARY_PATH);
		const wall = workspace(page).getByRole('heading', { name: LIBRARY_PAGE_LABEL });
		await expect(wall).toBeVisible();
		await accountCircle(page).click();
		await expect(accountMenu(page)).toBeVisible();

		await page.goBack();

		await expect(accountMenu(page)).toBeHidden();
		await expect(wall).toBeVisible();
		await expect(page).toHaveURL(LIBRARY_URL);
		guard.assertClean();
	}
);

// Issue #1331: the history controller runs on every page, so Back closes the
// topmost overlay on Settings and on a share page before it leaves the page.
test.describe('Back closes the open overlay outside the library', () => {
	const VOICE_DELETE_TITLE = 'Delete voice?';

	async function openVoicesOverTheWall(page: Page, shell: Shell): Promise<void> {
		await page.goto(LIBRARY_PATH);
		await expect(workspace(page).getByRole('heading', { name: LIBRARY_PAGE_LABEL })).toBeVisible();
		await openVoicesSettings(page, shell);
	}

	async function voiceNamed(request: APIRequestContext, voiceId: string): Promise<string> {
		const response = await request.get(`/api/loras/${voiceId}`);
		expect(response.ok()).toBe(true);
		return ((await response.json()) as { name: string }).name;
	}

	test(
		'Back closes the search sheet on Voices and the address stays',
		{ tag: ONLY_IN_SHELL.mobile },
		async ({ page }) => {
			const guard = new FlowGuard(page);
			await openVoicesOverTheWall(page, 'mobile');
			await openSearchSheet(page);

			await page.goBack();

			await expect(searchSheet(page)).toBeHidden();
			await expectSettingsStands(page);
			guard.assertClean();
		}
	);

	test('Back cancels the voice delete confirmation: still on Voices, the voice listed', async ({
		page,
		request
	}, testInfo) => {
		const guard = new FlowGuard(page);
		const voiceIds = await seedVoiceDrafts(request, 1);
		try {
			const name = await voiceNamed(request, voiceIds[0]);
			await openVoicesOverTheWall(page, shellOf(testInfo));
			const card = page.locator('.lora-card').filter({ hasText: name });
			await card.getByRole('button', { name: 'Delete', exact: true }).click();
			const confirm = page
				.getByRole('dialog')
				.filter({ has: page.getByRole('heading', { name: VOICE_DELETE_TITLE, exact: true }) });
			await expect(confirm).toBeVisible();

			await page.goBack();

			await expect(confirm).toBeHidden();
			await expectSettingsStands(page);
			await expect(card.getByRole('button', { name: 'Delete', exact: true })).toBeVisible();
			guard.assertClean();
		} finally {
			await deleteVoiceProofData(request, voiceIds);
		}
	});

	test('playlist scrolling keeps transport reachable and browser Back intact', async ({
		browser
	}, testInfo) => {
		const shell = shellOf(testInfo);
		const { viewport, isMobile, hasTouch } = testInfo.project.use;
		const loggedOut = await browser.newContext({
			storageState: undefined,
			viewport,
			isMobile,
			hasTouch
		});
		const sharePage = await loggedOut.newPage();
		const guard = new FlowGuard(sharePage, {
			refusalsExpectedOn: [{ path: `${PLAYLIST_API}/stream`, statuses: [404] }]
		});
		try {
			await mockPlaylist(sharePage, playlistPayload(24));
			await sharePage.goto('/login');
			await sharePage.goto(PLAYLIST_URL);
			await sharePage
				.locator('.now-playing.page')
				.getByRole('button', { name: 'Play', exact: true })
				.click();
			const historyLength = await sharePage.evaluate(() => window.history.length);
			await sharePage
				.locator('.shared-page')
				.evaluate((element) => element.scrollTo(0, element.scrollHeight));
			const bar = sharePage.locator('footer.player-bar');
			await expect(sharePage.locator('.queue-row').last()).toBeInViewport();
			if (shell === 'mobile') {
				await bar.getByRole('button', { name: 'Back to the player' }).first().click();
			}
			await expect(
				sharePage.locator('.now-playing.page').getByRole('button', { name: 'Pause', exact: true })
			).toBeInViewport({ ratio: 1 });
			expect(await sharePage.evaluate(() => window.history.length)).toBe(historyLength);
			await expect(bar).toBeHidden();
			await expect(sharePage.getByRole('dialog')).toHaveCount(0);
			await sharePage.goBack();
			await expect(sharePage).toHaveURL(/\/login$/);
		} finally {
			try {
				guard.assertClean();
			} finally {
				await loggedOut.close();
			}
		}
	});

	// Search is a phone layer.
	test(
		'1354_37a_A3: an album selected in Search over Voices leaves one Back to Voices',
		{ tag: ONLY_IN_SHELL.mobile },
		async ({ page }) => {
			const guard = new FlowGuard(page);
			const library = readSeededLibrary();
			await openVoicesOverTheWall(page, 'mobile');

			await openAlbumFromNavigation(page, 'mobile', library.albumTitle);
			await expect(
				workspace(page).getByRole('heading', { name: library.albumTitle })
			).toBeVisible();
			await expect(searchSheet(page)).toBeHidden();

			await page.goBack();

			await expectSettingsStands(page);
			await expect(searchSheet(page)).toBeHidden();
			guard.assertClean();
		}
	);

	test(
		'the search sheet left open over a reload on Voices is gone, and one Back leaves the page',
		{ tag: ONLY_IN_SHELL.mobile },
		async ({ page }) => {
			const guard = new FlowGuard(page);
			await openVoicesOverTheWall(page, 'mobile');
			await openSearchSheet(page);
			await expect.poll(() => standsOnLayerEntry(page)).toBe(true);

			await page.reload();

			await expect(searchSheet(page)).toBeHidden();
			await expectSettingsStands(page);
			await expect.poll(() => standsOnLayerEntry(page)).toBe(false);
			await page.goBack();
			await expect(page).toHaveURL(LIBRARY_URL);
			guard.assertClean();
		}
	);
});

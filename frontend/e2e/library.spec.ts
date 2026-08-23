// The library flow an operator walks by hand: play the album pick, judge a
// take, put it on a playlist, reorder the playlist, shuffle, and open the
// public album link while logged out.
//
// Both shells walk the same steps. Where the compact shell differs — the rail
// becomes a drawer, the editor opens on Write, Now Playing's right panel
// becomes a sheet, the transport shrinks to one 64px row — the mobile
// expectation is spelled out instead of skipped.

import { expect, test, type Locator, type Page } from '@playwright/test';
import {
	collectionRowPlayLabel,
	EDITOR_TAB_TAKES_LABEL,
	EDITOR_TAB_WRITE_LABEL,
	HITBOX_FREQUENT_PX,
	LIBRARY_FILTER_LABELS,
	NOW_PLAYING_CLOSE,
	PLAYLIST_ENTRY_MOVE_DOWN_LABEL,
	PLAYLIST_ENTRY_REMOVE_LABEL,
	playlistEntryOverflowLabel,
	RAIL_DRAWER_LABEL,
	RAIL_DRAWER_OPEN_LABEL,
	RAIL_LIBRARY_LABEL,
	TAKE_OVERFLOW_LABEL,
	TAKE_PLAYLIST_LABEL,
	TRANSPORT_PAUSE_LABEL
} from '../src/lib/constants';
import {
	NOW_PLAYING_RIGHT_PANEL_LABEL,
	NOW_PLAYING_SHUFFLE_DISABLE_PREFIX,
	NOW_PLAYING_SHUFFLE_LABEL_PREFIX,
	NOW_PLAYING_TAKE_TAB
} from '../src/lib/constants/now-playing';
import {
	boundingBoxes,
	containing,
	FlowGuard,
	LIBRARY_FLOW_API_REQUEST_BUDGET,
	MOBILE_VIEWPORT,
	NARROW_VIEWPORT,
	nameStartingWith,
	playableRows,
	shellOf,
	workspace,
	type Shell
} from './helpers';
import { readSeededLibrary, seedPlaylist, type SeededPlaylist } from './seed';

// The compact transport drops prev/next and the seek timeline into Now Playing
// and keeps a single row this tall (see TransportBarFrame.svelte).
const MOBILE_TRANSPORT_HEIGHT_PX = 64;
// The album header promises its title a readable floor at any width — it wraps
// the action cluster onto its own row rather than shrinking the title past
// this (see .header-titles in CollectionHeaderFrame.svelte).
const HEADER_MIN_TITLE_PX = 160;

let guard: FlowGuard;
let playlist: SeededPlaylist;

test.beforeEach(async ({ page, request }) => {
	guard = new FlowGuard(page);
	// A fresh playlist per attempt: the flow reorders and prunes this one, so
	// a retry must not start from the previous attempt's order.
	playlist = await seedPlaylist(request, readSeededLibrary());
});

// After the flow, not at its end: a rate-limited or failed response usually
// shows up first as a click that finds nothing, and the guard's record is the
// real cause of that.
test.afterEach(() => {
	guard.assertClean();
});

/**
 * The album header has to survive the narrowest phone. What is pinned is the
 * floor the header promises its title (`.header-titles` in
 * CollectionHeaderFrame.svelte wraps the action cluster onto its own row
 * rather than shrinking the title past this) and the breadcrumb sitting on the
 * line below it — not that the rendered title is untruncated, which the
 * header's own ellipsis makes unmeasurable from outside.
 *
 * Both are addressed by role alone: the album surface carries exactly one
 * heading and one breadcrumb, and the rename control inside the heading owns
 * the heading's accessible name, so the album's own title cannot select it.
 */
async function expectHeaderReadsAtNarrowest(page: Page, albumTitle: string): Promise<void> {
	const surface = workspace(page);
	const title = surface.getByRole('heading');
	const breadcrumb = surface.getByRole('navigation');

	await page.setViewportSize(NARROW_VIEWPORT);
	await expect(title).toHaveText(albumTitle);
	await expect(breadcrumb).toHaveText(containing(albumTitle));
	await expect(
		breadcrumb.getByRole('button', { name: RAIL_LIBRARY_LABEL, exact: true })
	).toBeVisible();

	const [titleBox, breadcrumbBox] = await boundingBoxes(title, breadcrumb);
	expect(titleBox.width).toBeGreaterThanOrEqual(HEADER_MIN_TITLE_PX);
	expect(breadcrumbBox.y).toBeGreaterThanOrEqual(titleBox.y + titleBox.height);

	await page.setViewportSize(MOBILE_VIEWPORT);
}

/** The desktop editor already shows the takes; the compact one opens on Write. */
async function openTakes(page: Page, shell: Shell): Promise<void> {
	if (shell === 'desktop') return;
	await expect(page.getByRole('tab', { name: EDITOR_TAB_WRITE_LABEL })).toHaveAttribute(
		'aria-selected',
		'true'
	);
	await page.getByRole('tab', { name: nameStartingWith(EDITOR_TAB_TAKES_LABEL) }).click();
}

/** Compact Now Playing stacks, so the judging panel arrives as its own sheet. */
function judgingSheet(page: Page): Locator {
	return page.getByRole('dialog', { name: NOW_PLAYING_RIGHT_PANEL_LABEL });
}

/** Leaves Now Playing. On mobile its sheet takes the first Escape, the overlay the second. */
async function closeNowPlaying(page: Page, shell: Shell): Promise<void> {
	if (shell === 'desktop') {
		await page.getByRole('button', { name: NOW_PLAYING_CLOSE, exact: true }).click();
	} else {
		await page.keyboard.press('Escape');
		await expect(judgingSheet(page)).toBeHidden();
		await page.keyboard.press('Escape');
	}
	await expect(page.getByRole('tab', { name: NOW_PLAYING_TAKE_TAB })).toBeHidden();
}

/** Back to the wall — on mobile the rail is a drawer the header opens. */
async function openLibraryWall(page: Page, shell: Shell): Promise<void> {
	if (shell === 'desktop') {
		await workspace(page).getByRole('button', { name: RAIL_LIBRARY_LABEL, exact: true }).click();
		return;
	}
	await page.getByRole('button', { name: RAIL_DRAWER_OPEN_LABEL }).click();
	const drawer = page.getByRole('dialog', { name: RAIL_DRAWER_LABEL });
	// The rail's Library row carries the library summary after the label; the
	// wordmark above it is named "Library" and nothing else.
	await drawer.getByRole('button', { name: nameStartingWith(`${RAIL_LIBRARY_LABEL} `) }).click();
	await expect(drawer).toBeHidden();
}

/** The compact transport: one short row, with a thumb-sized play control. */
async function expectCompactTransport(transport: Locator): Promise<void> {
	const play = transport.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true });
	const [bar, playBox] = await boundingBoxes(transport, play);

	expect(bar.height).toBe(MOBILE_TRANSPORT_HEIGHT_PX);
	expect(playBox.width).toBeGreaterThanOrEqual(HITBOX_FREQUENT_PX);
	expect(playBox.height).toBeGreaterThanOrEqual(HITBOX_FREQUENT_PX);
}

test('plays the album pick, curates a playlist and serves the public album link', async ({
	page,
	browser
}, testInfo) => {
	const shell = shellOf(testInfo);
	const library = readSeededLibrary();
	const [firstPlaylistSong, secondPlaylistSong] = playlist.songTitles;
	const surface = workspace(page);

	await page.goto('/');
	await expect(surface.getByRole('heading', { name: LIBRARY_FILTER_LABELS.albums })).toBeVisible();

	await surface.getByRole('button', { name: nameStartingWith(library.albumTitle) }).click();
	if (shell === 'mobile') await expectHeaderReadsAtNarrowest(page, library.albumTitle);

	await surface
		.getByRole('button', { name: collectionRowPlayLabel(library.pickedSongTitle) })
		.click();

	const transport = page.getByRole('contentinfo');
	await expect(transport.getByText(library.pickedSongTitle)).toBeVisible();
	await expect(transport.getByText(library.takeLabel)).toBeVisible();
	// The pick is audible, not merely selected: the button offers to pause it.
	await expect(
		transport.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true })
	).toBeVisible();
	if (shell === 'mobile') await expectCompactTransport(transport);

	await surface.getByRole('button', { name: nameStartingWith(library.pickedSongTitle) }).click();
	await openTakes(page, shell);

	const takeRow = surface.getByRole('button', { name: library.takeLabel });
	await takeRow.click();
	await expect(page.getByRole('tab', { name: NOW_PLAYING_TAKE_TAB })).toHaveAttribute(
		'aria-selected',
		'true'
	);
	if (shell === 'mobile') await expect(judgingSheet(page)).toBeVisible();
	await closeNowPlaying(page, shell);

	await takeRow.getByRole('button', { name: TAKE_OVERFLOW_LABEL }).click();
	await surface.getByRole('menuitem', { name: TAKE_PLAYLIST_LABEL }).click();
	await surface.getByRole('button', { name: nameStartingWith(playlist.title) }).click();

	await openLibraryWall(page, shell);
	await surface.getByRole('radio', { name: LIBRARY_FILTER_LABELS.playlists }).click();
	await surface.getByRole('button', { name: nameStartingWith(playlist.title) }).click();

	const entryRows = playableRows(page);
	await expect(entryRows).toHaveText([
		containing(firstPlaylistSong),
		containing(secondPlaylistSong),
		containing(library.pickedSongTitle)
	]);

	await surface
		.getByRole('button', { name: playlistEntryOverflowLabel(firstPlaylistSong) })
		.click();
	await surface.getByRole('menuitem', { name: PLAYLIST_ENTRY_MOVE_DOWN_LABEL }).click();
	await expect(entryRows).toHaveText([
		containing(secondPlaylistSong),
		containing(firstPlaylistSong),
		containing(library.pickedSongTitle)
	]);

	await surface
		.getByRole('button', { name: playlistEntryOverflowLabel(library.pickedSongTitle) })
		.click();
	await surface.getByRole('menuitem', { name: PLAYLIST_ENTRY_REMOVE_LABEL }).click();
	await expect(entryRows).toHaveText([
		containing(secondPlaylistSong),
		containing(firstPlaylistSong)
	]);

	const shuffle = transport.getByRole('button', {
		name: nameStartingWith(NOW_PLAYING_SHUFFLE_LABEL_PREFIX, NOW_PLAYING_SHUFFLE_DISABLE_PREFIX)
	});
	await expect(shuffle).toHaveAttribute('aria-pressed', 'false');
	await shuffle.click();
	await expect(shuffle).toHaveAttribute('aria-pressed', 'true');

	// The public link is part of the flow, so it is opened on the same screen
	// the rest of the shell was driven on.
	const { viewport, isMobile, hasTouch } = testInfo.project.use;
	const loggedOut = await browser.newContext({
		storageState: undefined,
		viewport,
		isMobile,
		hasTouch
	});
	const sharePage = await loggedOut.newPage();
	const shareGuard = new FlowGuard(sharePage);
	await sharePage.goto(library.albumShareUrl);
	await expect(sharePage.getByRole('heading', { name: library.albumTitle })).toBeVisible();
	await expect(
		sharePage.getByRole('button', { name: nameStartingWith(library.pickedSongTitle) })
	).toBeVisible();
	shareGuard.assertClean();
	await loggedOut.close();

	console.log(`Library flow /api requests (${shell}): ${guard.apiRequestCount}`);
	guard.assertWithinBudget(LIBRARY_FLOW_API_REQUEST_BUDGET[shell]);
});

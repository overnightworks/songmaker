// The library flow an operator walks by hand: play the album pick, judge a
// take, put it on a playlist, reorder the playlist, shuffle, and open the
// public album link while logged out.
//
// Both shells walk the same playback and sharing steps. The desktop flow also
// curates a playlist through the detailed take list; on mobile, the Edit tab
// carries no take strip and the Takes tab is the one playback entry point.

import { phoneSearchResult } from './phone-search';
import { expect, test, type Locator, type Page } from '@playwright/test';
import {
	ACCOUNT_MENU_LOGOUT_LABEL,
	collectionActionLabel,
	COLLECTION_MENU_ADD_TO_PLAYLIST_LABEL,
	COLLECTION_MENU_LABEL,
	HITBOX_FREQUENT_PX,
	LIBRARY_WALL_ORDER_GROUP_LABEL,
	LIBRARY_WALL_ORDER_LABELS,
	type LibraryWallOrder,
	NOW_PLAYING_CLOSE,
	NOW_PLAYING_SWIPE_RISE_PX,
	openNowPlayingLabel,
	PLAYLIST_ENTRY_MOVE_DOWN_LABEL,
	PLAYLIST_ENTRY_REMOVE_LABEL,
	playlistEntryOverflowLabel,
	PLAYLISTS_PAGE_LABEL,
	PLAYLISTS_WALL_ORDER_GROUP_LABEL,
	LIBRARY_ALBUM_PAGE_SIZE,
	LIBRARY_PAGE_LABEL,
	RAIL_LIBRARY_NAV_LABEL,
	PLAYING_MARK_LABEL,
	RAIL_PLAYLISTS_NAV_LABEL,
	RAIL_SETTINGS_LABEL,
	TAKE_OVERFLOW_LABEL,
	TAKE_PLAYLIST_LABEL,
	TRANSPORT_PAUSE_LABEL,
	TRANSPORT_PLAY_LABEL,
	songEditorOpenLabel,
	wallHeadingLabel
} from '../src/lib/constants';
import { compareTitles } from '../src/lib/utils/recency';
import {
	nowPlayingFromLabel,
	NOW_PLAYING_RIGHT_PANEL_LABEL,
	NOW_PLAYING_SHUFFLE_DISABLE_PREFIX,
	NOW_PLAYING_SHUFFLE_LABEL_PREFIX,
	NOW_PLAYING_TAKE_TAB
} from '../src/lib/constants/now-playing';
import {
	accountCircle,
	accountMenu,
	appBar,
	boundingBoxes,
	containing,
	sameOriginHeaders,
	FlowGuard,
	LIBRARY_FLOW_API_REQUEST_BUDGET,
	MOBILE_VIEWPORT,
	NARROW_VIEWPORT,
	nameStartingWith,
	observePlayingAudio,
	ONLY_IN_SHELL,
	openLibraryWall,
	openPlaylistsPage,
	openRailNav,
	openSettingsSection,
	playlistEntryRows,
	RAIL_FLOW_API_REQUEST_BUDGET,
	shellOf,
	SUCCESSOR_TAKES_TEST_TIMEOUT_MS,
	workspace,
	listenRegion,
	type Shell,
	HOME_PATH,
	LIBRARY_PATH,
	LIBRARY_URL
} from './helpers';
import { archiveOwnedAlbum, readSeededLibrary, seedPlaylist, type SeededPlaylist } from './seed';

// The phone's mini player keeps previous · play · next in one row this tall;
// the seek timeline and shuffle live in Now Playing (see TransportBarFrame.svelte).
const MOBILE_TRANSPORT_HEIGHT_PX = 64;
// Frame A2 of docs/design/album-browsing.html: a phone's album and playlist row.
const PHONE_ROW_HEIGHT_PX = 62;
// The album header promises its title a readable floor at any width — it wraps
// the action cluster onto its own row rather than shrinking the title past
// this (see .header-titles in CollectionHeaderFrame.svelte).
const HEADER_MIN_TITLE_PX = 160;
// The header's line under the title: how many songs the page lists.
const SONG_COUNT = /^\d+ songs?$/;

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
 * rather than shrinking the title past this) and the song count sitting on the
 * line below it where the breadcrumb stood (#1354 rule 24) — not that the
 * rendered title is untruncated, which the header's own ellipsis makes
 * unmeasurable from outside.
 *
 * The title is addressed by role: the heading's accessible name is the album
 * title (see CollectionHeader.svelte's aria-label — issue #160), so it is
 * the name filter, not "the only heading in the surface", that selects it.
 */
async function expectHeaderReadsAtNarrowest(page: Page, albumTitle: string): Promise<void> {
	const surface = workspace(page);
	const title = surface.getByRole('heading', { name: albumTitle });
	const songCount = surface.locator('.collection-header').getByText(SONG_COUNT);

	await page.setViewportSize(NARROW_VIEWPORT);
	await expect(title).toHaveText(albumTitle);
	await expect(songCount).toBeVisible();
	await expect(surface.getByRole('navigation')).toHaveCount(0);

	const [titleBox, songCountBox] = await boundingBoxes(title, songCount);
	expect(titleBox.width).toBeGreaterThanOrEqual(HEADER_MIN_TITLE_PX);
	expect(songCountBox.y).toBeGreaterThanOrEqual(titleBox.y + titleBox.height);

	await page.setViewportSize(MOBILE_VIEWPORT);
}

/** Compact Now Playing stacks, so the judging panel arrives as its own sheet. */
function judgingSheet(page: Page): Locator {
	return page.getByRole('dialog', { name: NOW_PLAYING_RIGHT_PANEL_LABEL });
}

/**
 * The click rule (#140): a take row plays the take and shows it in Now Playing
 * on This take. The desktop shell docks the panel — a complementary landmark
 * named after the playing song, with the surface underneath it left in place —
 * while the compact shell has no room to dock and stacks into the judging
 * sheet.
 */
async function expectTakeShownInNowPlaying(
	page: Page,
	shell: Shell,
	playingSongTitle: string
): Promise<void> {
	await expect(page.getByRole('tab', { name: NOW_PLAYING_TAKE_TAB })).toHaveAttribute(
		'aria-selected',
		'true'
	);
	if (shell === 'desktop') {
		await expect(page.getByRole('complementary', { name: playingSongTitle })).toBeVisible();
		return;
	}
	await expect(judgingSheet(page)).toBeVisible();
}

/**
 * The one transport that is showing: beside the docked panel it stays in the
 * bar, while the full surface hides the bar and carries the transport itself
 * ("one player, never two").
 */
function shellTransport(page: Page, shell: Shell, playingSongTitle: string): Locator {
	return shell === 'desktop'
		? page.getByRole('contentinfo')
		: page.getByRole('dialog', { name: playingSongTitle });
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

async function openAlbumFromNavigation(page: Page, shell: Shell, title: string): Promise<void> {
	if (shell === 'mobile') {
		await (await phoneSearchResult(page, 'Albums', title, nameStartingWith(title))).click();
	} else {
		const rail = await openRailNav(page, shell);
		await railAlbumRow(rail, title)
			.getByRole('button', { name: containing(title) })
			.click();
	}
}

/**
 * The phone's ‹ (#1354 rule 25): named after the page it goes back to, and
 * the account circle only on the Library, with Sign out one tap away in it.
 */
async function backOnPhone(page: Page, to: string): Promise<void> {
	await appBar(page)
		.getByRole('button', { name: `Back to ${to}`, exact: true })
		.click();
}

async function expectAccountMenuOnTheLibrary(page: Page): Promise<void> {
	await accountCircle(page).click();
	await expect(
		accountMenu(page).getByRole('button', { name: ACCOUNT_MENU_LOGOUT_LABEL, exact: true })
	).toBeVisible();
	await page.keyboard.press('Escape');
	await expect(accountMenu(page)).toBeHidden();
}

// Settings has no second navigation column; the desktop rail and phone
// navigation return to the album (#263, #264).
async function expectSettingsRailRoundTrip(
	page: Page,
	shell: Shell,
	surface: Locator,
	albumTitle: string
): Promise<void> {
	if (shell === 'mobile') {
		await backOnPhone(page, LIBRARY_PAGE_LABEL);
		await expect(surface.getByRole('heading', { name: LIBRARY_PAGE_LABEL })).toBeVisible();
		await expectAccountMenuOnTheLibrary(page);
	}
	await openSettingsSection(page, shell, 'Voices');

	await expect(page).toHaveURL(/\/settings\/voices$/);
	if (shell === 'mobile') {
		await expect(accountCircle(page)).toHaveCount(0);
		await backOnPhone(page, RAIL_SETTINGS_LABEL);
		await expect(page).toHaveURL(/\/settings$/);
		await page.goForward();
		await expect(page).toHaveURL(/\/settings\/voices$/);
	}
	// The removed second column — the old `.settings-sidebar` — is gone, and
	// so is any other navigation landmark inside the content area; the rail
	// stays the one navigation on the page.
	await expect(page.locator('.settings-sidebar')).toHaveCount(0);
	await expect(surface.getByRole('navigation')).toHaveCount(0);

	if (shell === 'desktop') {
		// No gap for a second column: the content starts right where the rail ends.
		const [railBox, mainBox] = await boundingBoxes(await openRailNav(page, shell), surface);
		expect(Math.abs(mainBox.x - (railBox.x + railBox.width))).toBeLessThanOrEqual(2);
	}

	await openAlbumFromNavigation(page, shell, albumTitle);
	await expect(surface.getByRole('heading', { name: albumTitle })).toBeVisible();
}

/**
 * The phone's mini player (#1003, frame C2): one short row reading previous ·
 * play · next, play on the bar's exact centre line, and no shuffle of its own.
 * Beside the transport the bar is Now Playing's target up to its very edges
 * (#1067): the title's target runs from the left edge to previous, the empty
 * right side from next to the right edge.
 */
async function expectCompactTransport(transport: Locator, playingSongTitle: string): Promise<void> {
	const play = transport.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true });
	const previous = transport.getByRole('button', { name: 'Previous', exact: true });
	const next = transport.getByRole('button', { name: 'Next', exact: true });
	const titleTarget = transport.getByRole('button', {
		name: openNowPlayingLabel(playingSongTitle),
		exact: true
	});
	const rightSide = transport.locator('.phone-side').last();
	const [bar, playBox, previousBox, nextBox, titleBox, rightBox] = await boundingBoxes(
		transport,
		play,
		previous,
		next,
		titleTarget,
		rightSide
	);
	const edges = (box: { x: number; width: number }) => [
		Math.round(box.x),
		Math.round(box.x + box.width)
	];

	expect(bar.height).toBe(MOBILE_TRANSPORT_HEIGHT_PX);
	expect(playBox.width).toBeGreaterThanOrEqual(HITBOX_FREQUENT_PX);
	expect(playBox.height).toBeGreaterThanOrEqual(HITBOX_FREQUENT_PX);
	expect(Math.abs(playBox.x + playBox.width / 2 - (bar.x + bar.width / 2))).toBeLessThanOrEqual(1);
	expect(previousBox.x + previousBox.width).toBeLessThanOrEqual(playBox.x);
	expect(nextBox.x).toBeGreaterThanOrEqual(playBox.x + playBox.width);
	expect(edges(titleBox)).toEqual([edges(bar)[0], edges(previousBox)[0]]);
	expect(edges(rightBox)).toEqual([edges(nextBox)[1], edges(bar)[1]]);
	await expect(
		transport.getByRole('button', {
			name: nameStartingWith(NOW_PLAYING_SHUFFLE_LABEL_PREFIX, NOW_PLAYING_SHUFFLE_DISABLE_PREFIX)
		})
	).toHaveCount(0);
}

/** A real finger, not a mouse: the bar must keep the browser from scrolling. */
async function swipeUp(page: Page, from: { x: number; y: number }, rise: number): Promise<void> {
	const finger = await page.context().newCDPSession(page);
	const touch = (type: 'touchStart' | 'touchMove', y: number) =>
		finger.send('Input.dispatchTouchEvent', { type, touchPoints: [{ x: from.x, y }] });
	await touch('touchStart', from.y);
	for (const step of [0.25, 0.5, 0.75, 1]) await touch('touchMove', from.y - rise * step);
	await finger.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
	await finger.detach();
}

// A tap this close to the bar's edge lands in the strip that used to be
// padding and hit the footer (#1067).
const MINI_PLAYER_EDGE_TAP_PX = 3;
// Room enough to read a few letters of a cut title, not one glyph and an
// ellipsis (#1067 G3).
const MINI_PLAYER_NARROW_TITLE_MIN_PX = 60;

/**
 * Swiping the mini player up and tapping its outer edge both open Now
 * Playing (#1067); at 320 px play still sits on the centre line, the targets
 * still reach the edges, and the cover gives its room to the title.
 */
async function expectMiniPlayerOpensNowPlaying(
	page: Page,
	transport: Locator,
	playingSongTitle: string
): Promise<void> {
	const nowPlaying = page.getByRole('dialog', { name: playingSongTitle });
	const closeNowPlaying = async () => {
		await page.keyboard.press('Escape');
		await expect(nowPlaying).toBeHidden();
	};
	const cover = transport.locator('.track-cover');
	const title = transport.locator('.track-title');
	const [bar] = await boundingBoxes(transport);
	await expect(cover).toBeVisible();

	await swipeUp(
		page,
		{ x: bar.x + bar.width / 6, y: bar.y + bar.height / 2 },
		NOW_PLAYING_SWIPE_RISE_PX * 2
	);
	await expect(nowPlaying).toBeVisible();
	await closeNowPlaying();

	for (const x of [MINI_PLAYER_EDGE_TAP_PX, bar.width - MINI_PLAYER_EDGE_TAP_PX]) {
		await transport.tap({ position: { x, y: bar.height / 2 } });
		await expect(nowPlaying).toBeVisible();
		await closeNowPlaying();
	}

	await page.setViewportSize(NARROW_VIEWPORT);
	await expectCompactTransport(transport, playingSongTitle);
	await expect(cover).toHaveCount(0);
	const [narrowTitle] = await boundingBoxes(title);
	expect(narrowTitle.width).toBeGreaterThanOrEqual(MINI_PLAYER_NARROW_TITLE_MIN_PX);
	await page.setViewportSize(MOBILE_VIEWPORT);
}

test('1354_37b_64: plays the album pick, curates a playlist and serves the public album link', async ({
	page,
	browser
}, testInfo) => {
	const shell = shellOf(testInfo);
	const library = readSeededLibrary();
	const [firstPlaylistSong, secondPlaylistSong] = playlist.songTitles;
	const surface = workspace(page);

	await page.goto(LIBRARY_PATH);
	await expect(surface.getByRole('heading', { name: LIBRARY_PAGE_LABEL })).toBeVisible();

	await surface
		.locator('.library-wall .tile-grid')
		.locator('.wall-tile-body')
		.filter({ hasText: library.albumTitle })
		.click();
	await expect(surface.getByRole('heading', { name: library.albumTitle })).toBeVisible();
	if (shell === 'mobile') await expectHeaderReadsAtNarrowest(page, library.albumTitle);

	await expectSettingsRailRoundTrip(page, shell, surface, library.albumTitle);

	// One play language (#1003): the header's circle starts the album from its
	// top, shuffle lives in the player alone (#1354 rule 24), and a song box
	// carries no play glyph of its own -- tapping it plays the song, its ✎
	// opens it.
	await expect(surface.getByRole('button', { name: /shuffle/i })).toHaveCount(0);
	const pickedSongRow = surface.locator('.song-row').filter({ hasText: library.pickedSongTitle });
	const openPickedSong = pickedSongRow.getByRole('button', {
		name: songEditorOpenLabel(library.pickedSongTitle)
	});
	await expect(pickedSongRow.getByRole('button')).toHaveCount(2);
	await surface
		.getByRole('button', {
			name: collectionActionLabel(TRANSPORT_PLAY_LABEL, 'album'),
			exact: true
		})
		.click();

	const transport = page.getByRole('contentinfo');
	await expect(transport.getByText(library.pickedSongTitle)).toBeVisible();
	// The phone names where the music comes from; the desktop row names the take.
	await expect(
		transport.getByText(
			shell === 'mobile' ? nowPlayingFromLabel(library.albumTitle) : library.takeLabel
		)
	).toBeVisible();
	// The pick is audible, not merely selected: the button offers to pause it.
	await expect(
		transport.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true })
	).toBeVisible();
	if (shell === 'mobile') {
		await expectCompactTransport(transport, library.pickedSongTitle);
		await expectMiniPlayerOpensNowPlaying(page, transport, library.pickedSongTitle);
	}
	const playingMark = pickedSongRow.getByRole('img', { name: PLAYING_MARK_LABEL, exact: true });
	await expect(playingMark).toBeVisible();

	// While the album plays, its circle pauses it and the next tap resumes it
	// (#1082); the paused row keeps its mark, standing still.
	await surface
		.getByRole('button', {
			name: collectionActionLabel(TRANSPORT_PAUSE_LABEL, 'album'),
			exact: true
		})
		.click();
	await expect(
		transport.getByRole('button', { name: TRANSPORT_PLAY_LABEL, exact: true })
	).toBeVisible();
	await expect(playingMark).toBeVisible();
	await expect(playingMark.locator('span').first()).toHaveCSS('animation-name', 'none');
	await surface
		.getByRole('button', {
			name: collectionActionLabel(TRANSPORT_PLAY_LABEL, 'album'),
			exact: true
		})
		.click();
	await expect(
		transport.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true })
	).toBeVisible();
	await expect(transport.getByText(library.pickedSongTitle)).toBeVisible();

	await openPickedSong.click();
	if (shell === 'mobile') {
		const takesTab = surface.getByRole('tab', { name: /Takes/ });
		await expect(takesTab).toHaveCount(1);
		await takesTab.click();
	}
	const takeControl = surface.locator('.take-row').filter({ hasText: library.takeLabel });
	await expect(takeControl).toHaveCount(1);
	if (shell === 'desktop') {
		// The click rule (#140): a tap on the row body plays the take and shows
		// it in Now Playing on This take. A row body never stops the music, so
		// tapping the pick that's already playing only opens the panel, without
		// pausing it.
		await takeControl.getByRole('button', { name: nameStartingWith('Take') }).click();
		await expectTakeShownInNowPlaying(page, shell, library.pickedSongTitle);
		// The row body tap never touches play/pause: the pick that was already
		// playing is still playing after it.
		await expect(
			shellTransport(page, shell, library.pickedSongTitle).getByRole('button', {
				name: TRANSPORT_PAUSE_LABEL,
				exact: true
			})
		).toBeVisible();
		await closeNowPlaying(page, shell);
	} else {
		await expect(takeControl).toHaveClass(/playing/);
		await expect(
			takeControl.getByRole('button', { name: nameStartingWith(TRANSPORT_PAUSE_LABEL) })
		).toBeVisible();
	}

	if (shell === 'desktop') {
		const takeRow = surface.locator('.take-row').filter({ hasText: library.takeLabel });
		await takeRow.getByRole('button', { name: TAKE_OVERFLOW_LABEL }).click();
		await surface
			.getByRole('dialog', { name: TAKE_OVERFLOW_LABEL, exact: true })
			.getByRole('button', { name: TAKE_PLAYLIST_LABEL })
			.click();
		await surface.getByRole('button', { name: nameStartingWith(playlist.title) }).click();

		await openPlaylistsPage(page, shell);
		await surface
			.locator('.library-wall .tile-grid')
			.locator('.wall-tile-body')
			.filter({ hasText: playlist.title })
			.click();

		const entryRows = playlistEntryRows(page);
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

		// A playlist row plays in place (#1010, frame B2): the listener stays on
		// the playlist page and the bar, not Now Playing, carries the transport.
		// The click lands in the card's bottom-left padding, outside the title
		// text, because the whole card is the row's target.
		const playedCard = entryRows.last();
		const playedCardBox = await playedCard.boundingBox();
		if (!playedCardBox) throw new Error('Expected a visible playlist row');
		await playedCard.click({ position: { x: 4, y: playedCardBox.height - 4 } });
		await expect(
			transport.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true })
		).toBeVisible();
		await expect(page.getByRole('tab', { name: NOW_PLAYING_TAKE_TAB })).toHaveCount(0);
		await expect(surface.getByRole('heading', { name: playlist.title })).toBeVisible();
		await expect(entryRows).toHaveText([
			containing(secondPlaylistSong),
			containing(firstPlaylistSong)
		]);
		await expect(
			entryRows.last().getByRole('img', { name: PLAYING_MARK_LABEL, exact: true })
		).toBeVisible();
		await expect(
			entryRows.first().getByRole('img', { name: PLAYING_MARK_LABEL, exact: true })
		).toHaveCount(0);
	}

	// On the phone shuffle lives in Now Playing, opened from the mini player's title.
	if (shell === 'mobile') {
		await transport
			.getByRole('button', { name: openNowPlayingLabel(library.pickedSongTitle), exact: true })
			.click();
	}
	const shuffle = shellTransport(page, shell, library.pickedSongTitle).getByRole('button', {
		name: nameStartingWith(NOW_PLAYING_SHUFFLE_LABEL_PREFIX, NOW_PLAYING_SHUFFLE_DISABLE_PREFIX)
	});
	await expect(shuffle).toHaveAttribute('aria-pressed', 'false');
	await shuffle.click();
	await expect(shuffle).toHaveAttribute('aria-pressed', 'true');
	if (shell === 'mobile') {
		await page.keyboard.press('Escape');
		await expect(page.getByRole('dialog', { name: library.pickedSongTitle })).toBeHidden();
	}

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

// A card's border is the only part of it that is not its target (#1053).
const ROW_BORDER_PX = 1;

type RowEdge = 'top' | 'bottom' | 'left' | 'right';

/**
 * A phone row is one target (#1053): its target is the whole card inside the
 * border, at least a thumb high, and a tap on any of the card's edges --
 * away from its label and the rounded corners -- lands on it. The card is as
 * high as frame A2 draws it (#1082).
 */
async function tapRowEdge(row: Locator, target: Locator, edge: RowEdge): Promise<void> {
	const [rowBox, targetBox] = await boundingBoxes(row, target);
	expect(Math.round(rowBox.height)).toBe(PHONE_ROW_HEIGHT_PX);
	const insets = [
		targetBox.y - rowBox.y,
		rowBox.x + rowBox.width - (targetBox.x + targetBox.width),
		rowBox.y + rowBox.height - (targetBox.y + targetBox.height),
		targetBox.x - rowBox.x
	];
	expect(insets.map((inset) => Math.round(inset))).toEqual(Array(4).fill(ROW_BORDER_PX));
	expect(targetBox.height).toBeGreaterThanOrEqual(HITBOX_FREQUENT_PX);
	const inset = ROW_BORDER_PX + 1;
	const edgePositions: Record<RowEdge, { x: number; y: number }> = {
		top: { x: rowBox.width / 4, y: inset },
		bottom: { x: rowBox.width / 4, y: rowBox.height - inset },
		left: { x: inset, y: rowBox.height / 2 },
		right: { x: rowBox.width - inset, y: rowBox.height / 2 }
	};
	await row.tap({ position: edgePositions[edge] });
}

// The edge taps prove the touch target, which is the phone shell's.
test(
	'a phone row answers a tap on its edge, and a take held twice marks one row',
	{ tag: ONLY_IN_SHELL.mobile },
	async ({ page }, testInfo) => {
		test.setTimeout(SUCCESSOR_TAKES_TEST_TIMEOUT_MS);
		const shell = shellOf(testInfo);
		const library = readSeededLibrary();
		const surface = workspace(page);
		const albumHeading = surface.getByRole('heading', { name: library.albumTitle });

		await observePlayingAudio(page);
		await page.goto(LIBRARY_PATH);
		await surface
			.locator('.library-wall .tile-grid')
			.locator('.wall-tile-body')
			.filter({ hasText: library.albumTitle })
			.click();
		await expect(albumHeading).toBeVisible();

		// An album row plays its song from each edge and keeps the album page
		// (#1354 rule 22); taking two songs in turn shows every edge's tap land.
		// A tap repicks the queue: the player drops the takes it leaves and asks for
		// the tapped one anew, any of them possibly still arriving.
		const songBox = (title: string) => surface.locator('.song-row').filter({ hasText: title });
		const [firstTrack, secondTrack] = library.albumTracks;
		const albumTakes = library.albumTracks.map((track) => track.audioPath);
		for (const [index, edge] of (['top', 'bottom', 'left', 'right'] as const).entries()) {
			const [played, other] =
				index % 2 === 0 ? [firstTrack, secondTrack] : [secondTrack, firstTrack];
			const row = songBox(played.songTitle);
			await guard.abandoningTakes(index === 0 ? [] : albumTakes, played.audioPath, async () => {
				await tapRowEdge(
					row,
					row.getByRole('button', { name: nameStartingWith(played.songTitle) }),
					edge
				);
				await expect(row.getByRole('img', { name: PLAYING_MARK_LABEL, exact: true })).toBeVisible();
				await expect(
					songBox(other.songTitle).getByRole('img', { name: PLAYING_MARK_LABEL, exact: true })
				).toHaveCount(0);
				await expect(albumHeading).toBeVisible();
			});
		}

		// Adding the album puts the playlist's first take in it a second time.
		await surface.getByRole('button', { name: COLLECTION_MENU_LABEL, exact: true }).click();
		await surface
			.getByRole('button', { name: COLLECTION_MENU_ADD_TO_PLAYLIST_LABEL, exact: true })
			.click();
		const albumAdded = page.waitForResponse(
			(response) =>
				response.request().method() === 'POST' &&
				new URL(response.url()).pathname.endsWith('/entries/album')
		);
		await surface.getByRole('button', { name: nameStartingWith(playlist.title) }).click();
		expect((await albumAdded).ok()).toBe(true);

		await openPlaylistsPage(page, shell);
		await surface
			.locator('.library-wall .tile-grid')
			.locator('.wall-tile-body')
			.filter({ hasText: playlist.title })
			.click();
		const heldTwice = playlistEntryRows(page).filter({ hasText: playlist.songTitles[0] });
		await expect(heldTwice).toHaveCount(2);
		const heldTwiceTake = library.albumTracks.find(
			({ songTitle }) => songTitle === playlist.songTitles[0]
		);
		if (!heldTwiceTake) throw new Error('Expected the first playlist song to be in the album');

		// A playlist row plays from either edge, and only the copy that plays is marked.
		const pause = page
			.getByRole('contentinfo')
			.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true });
		for (const [edge, played, other] of [
			['top', 1, 0],
			['bottom', 0, 1]
		] as const) {
			const row = heldTwice.nth(played);
			await guard.abandoningTakes(albumTakes, heldTwiceTake.audioPath, async () => {
				await tapRowEdge(
					row,
					row.getByRole('button', { name: nameStartingWith(playlist.songTitles[0]) }),
					edge
				);
				await expect(pause).toBeVisible();
				await expect(row.getByRole('img', { name: PLAYING_MARK_LABEL, exact: true })).toBeVisible();
				await expect(
					heldTwice.nth(other).getByRole('img', { name: PLAYING_MARK_LABEL, exact: true })
				).toHaveCount(0);
			});
		}
	}
);

// Archives every album before reporting any failure, so one refusal leaves no
// later album behind.
async function archiveEvery(page: Page, albumIds: string[]): Promise<void> {
	const failures: unknown[] = [];
	for (const albumId of albumIds) {
		try {
			await archiveOwnedAlbum(page.request, albumId);
		} catch (error) {
			failures.push(error);
		}
	}
	if (failures.length > 0) {
		throw new AggregateError(failures, `Archiving ${failures.length} test albums failed`);
	}
}

// The browse loads 50 albums, newest first (LIBRARY_ALBUM_PAGE_SIZE); an album
// chosen in Search from beyond that page still opens under its own heading.
// Phone only: the desktop Rail is mounted on every page and pages in every
// album at once (RailLibraryGroup), so no desktop surface lacks the album. The
// cell starts on a playlist address, which never loads all albums.
test(
	'1354_37a: an album found in Search beyond the first browse page opens with its heading',
	{ tag: ONLY_IN_SHELL.mobile },
	async ({ page, request }) => {
		const surface = workspace(page);
		const runTag = `E2E Beyond Page ${Date.now()}`;
		const targetTitle = `${runTag} target`;
		const albumIds: string[] = [];
		await page.goto(HOME_PATH);
		const headers = await sameOriginHeaders(page);
		try {
			// The target is created first, so the newest-first browse puts it last.
			for (let index = 0; index <= LIBRARY_ALBUM_PAGE_SIZE; index++) {
				const title = index === 0 ? targetTitle : `${runTag} filler ${index}`;
				const response = await page.request.post('/api/albums', { headers, data: { title } });
				expect(response.ok()).toBe(true);
				albumIds.push((await response.json()).id);
			}
			const playlist = await seedPlaylist(request, readSeededLibrary());
			await page.goto(`/playlist/${playlist.slug}`);
			await expect(surface.getByRole('heading', { name: playlist.title })).toBeVisible();

			await (
				await phoneSearchResult(page, 'Albums', targetTitle, nameStartingWith(targetTitle))
			).click();

			await expect(surface.getByRole('heading', { name: targetTitle })).toBeVisible();
		} finally {
			await archiveEvery(page, albumIds);
		}
	}
);

test('1354_37b_64: an album with nothing to play dims its circle and leaves the running album playing on', async ({
	page
}, testInfo) => {
	const shell = shellOf(testInfo);
	const library = readSeededLibrary();
	const surface = workspace(page);
	const transport = page.getByRole('contentinfo');
	const albumCircle = surface.getByRole('button', {
		name: collectionActionLabel(TRANSPORT_PLAY_LABEL, 'album'),
		exact: true
	});

	await page.goto(`/album/${library.albumId}`);
	await albumCircle.click();
	await expect(transport.getByText(library.pickedSongTitle)).toBeVisible();

	// The second seeded album holds songs without a take (see seed.ts).
	await openAlbumFromNavigation(page, shell, library.secondAlbumTitle);
	await expect(surface.getByRole('heading', { name: library.secondAlbumTitle })).toBeVisible();

	await expect(albumCircle).toBeDisabled();
	await albumCircle.click({ force: true });

	await expect(
		transport.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true })
	).toBeVisible();
	if (shell === 'mobile') {
		await expect(transport.getByText(nowPlayingFromLabel(library.albumTitle))).toBeVisible();
	} else {
		await expect(
			transport.getByRole('button', {
				name: nameStartingWith(NOW_PLAYING_SHUFFLE_LABEL_PREFIX, NOW_PLAYING_SHUFFLE_DISABLE_PREFIX)
			})
		).toHaveAttribute('aria-pressed', 'false');
	}
	await expect(
		surface.getByRole('button', {
			name: collectionActionLabel(TRANSPORT_PAUSE_LABEL, 'album'),
			exact: true
		})
	).toHaveCount(0);
});

// An album opened by its address has nothing of the tab's own below it, so
// its ‹ writes the Library over it (#1354 rule 25): the wall shows in the
// album's place, and the tab holds no more entries than before (#1389).
test(
	'a directly opened album: ‹ shows the Library wall in its place',
	{ tag: ONLY_IN_SHELL.mobile },
	async ({ page }) => {
		const guard = new FlowGuard(page);
		const library = readSeededLibrary();
		const surface = workspace(page);
		const album = surface.getByRole('heading', { name: library.albumTitle });
		await page.goto(`/album/${library.albumId}`);
		await expect(album).toBeVisible();
		const tabLength = await page.evaluate(() => history.length);

		await backOnPhone(page, LIBRARY_PAGE_LABEL);

		await expect(page).toHaveURL(LIBRARY_URL);
		await expect(surface.getByRole('heading', { name: LIBRARY_PAGE_LABEL })).toBeVisible();
		await expect(album).toBeHidden();
		expect(await page.evaluate(() => history.length)).toBe(tabLength);
		await expect(accountCircle(page)).toBeVisible();
		guard.assertClean();
	}
);

/** One album's own one-target row inside the rail's LIBRARY group. */
function railAlbumRow(rail: Locator, albumTitle: string): Locator {
	return rail
		.getByRole('navigation', { name: RAIL_LIBRARY_NAV_LABEL })
		.getByRole('listitem')
		.filter({ hasText: albumTitle });
}

/**
 * A collapsed row's songs are not merely painted-and-clipped: `toBeVisible()`
 * only asks whether an element has its own non-empty box and no
 * `visibility: hidden`, so a song row clipped by an ancestor's zero-height
 * `overflow: hidden` (the grid-collapse trick `.album-songs` and
 * `.rail-group-panel` both use) still reports visible under it -- verified
 * against this exact markup while building #326: `getBoundingClientRect()`
 * on the row still returns its natural size even though the ancestor's own
 * rect is zero-height. `toBeInViewport()` uses the browser's own
 * IntersectionObserver, which -- unlike `toBeVisible()` -- does resolve
 * clipping through ancestors, so it is the one assertion that actually
 * distinguishes "collapsed" from "expanded" for this pattern. Scrolled into
 * view first so a row far down the seeded list (see RAIL_FILLER_ALBUM_COUNT
 * in seed.ts) is judged on its own collapse state, not on where the rail
 * happens to be scrolled.
 */
async function expectRailRowExpanded(row: Locator, song: Locator): Promise<void> {
	// The pinned Settings group can leave the tracks below a just-visible album
	// row outside the rail clip. The promise is that the expanded child can be
	// reached, so scroll the child into view rather than assuming both fit.
	await row.scrollIntoViewIfNeeded();
	await song.scrollIntoViewIfNeeded();
	await expect(song).toBeInViewport();
}

async function expectRailRowCollapsed(row: Locator, song: Locator): Promise<void> {
	await row.scrollIntoViewIfNeeded();
	await expect(song).not.toBeInViewport();
}

test(
	'1354_37a_A6 / 1354_65_A1 / 1354_65_A2: the one-target rail tree and pin promises hold in a real browser',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }, testInfo) => {
		const shell = shellOf(testInfo);
		const library = readSeededLibrary();
		const surface = workspace(page);

		// A cold playlist open, not a rail click: PLAYLISTS' own bare chevron has
		// no accessible name once a title click is wired (same RailGroup gap as
		// LIBRARY's), so like the album below, it only opens once a playlist is
		// already open (its own expandTrigger). Doing this before any album is
		// open also keeps LIBRARY collapsed for it -- avoiding the deep-scroll
		// edge this test found while building #326: with LIBRARY's own 30-plus
		// seeded rows already open, the browser's native scrollIntoView() can
		// leave the very last row straddling the scroll container's clip edge,
		// where the pinned Settings row intercepts the click.
		await page.goto(`/playlist/${playlist.slug}`);
		await expect(surface.getByRole('heading', { name: playlist.title })).toBeVisible();

		const rail = await openRailNav(page, shell);

		// The PLAYLISTS group, touched by a real browser for the first time
		// (#326 finding 1): entering it force-expands its own row, and a track
		// row inside it plays and judges the same way a library track does.
		const [firstPlaylistSongTitle] = playlist.songTitles;
		await rail
			.getByRole('navigation', { name: RAIL_PLAYLISTS_NAV_LABEL })
			.getByRole('button', { name: nameStartingWith(firstPlaylistSongTitle) })
			.click();
		await expectTakeShownInNowPlaying(page, shell, firstPlaylistSongTitle);
		await expect(
			shellTransport(page, shell, firstPlaylistSongTitle).getByRole('button', {
				name: TRANSPORT_PAUSE_LABEL,
				exact: true
			})
		).toBeVisible();
		await closeNowPlaying(page, shell);

		// A cold album open, not a wall click: the wall's default 'newest' sort
		// would otherwise chase the seeded filler albums below (see
		// RAIL_FILLER_ALBUM_COUNT in seed.ts), and this test is about the rail,
		// not the wall's own grid. Opening the address still sets openCollection
		// the same way a wall click does, which is what the rail reads. Neither
		// playing the playlist entry nor closing Now Playing navigated, so this
		// is the flow's second real navigation.
		await page.goto(`/album/${library.albumId}`);
		await expect(surface.getByRole('heading', { name: library.albumTitle })).toBeVisible();

		function firstAlbumRow(): Locator {
			return railAlbumRow(rail, library.albumTitle);
		}
		function firstAlbumSong(): Locator {
			return firstAlbumRow().getByRole('button', {
				name: nameStartingWith(library.pickedSongTitle)
			});
		}
		// Entering an album force-expands its own row without a row click,
		// and that force-expand is what pulled the whole LIBRARY group open too.
		await expectRailRowExpanded(firstAlbumRow(), firstAlbumSong());
		// #1354 rule 40: the word LIBRARY opens the covers, so no row of the list does.
		await expect(rail.getByRole('button', { name: nameStartingWith('All albums') })).toHaveCount(0);

		function secondAlbumRow(): Locator {
			return railAlbumRow(rail, library.secondAlbumTitle);
		}
		const secondAlbumButton = secondAlbumRow().getByRole('button', {
			name: containing(library.secondAlbumTitle)
		});
		function secondAlbumSong(): Locator {
			return secondAlbumRow().getByRole('button', {
				name: nameStartingWith(library.secondAlbumSongTitle)
			});
		}

		// An album row has one action: it opens that album and its tracks together.
		// Its caret is display only, so the old chevron-only destination is gone.
		await expect(secondAlbumButton).toHaveAttribute('aria-expanded', 'false');
		await expectRailRowCollapsed(secondAlbumRow(), secondAlbumSong());
		await secondAlbumButton.click();
		await expect(secondAlbumButton).toHaveAttribute('aria-expanded', 'true');
		// The one-slot rule is visible as well as navigable: opening one album
		// closes the former row and takes the surface to the selected album.
		await expectRailRowExpanded(secondAlbumRow(), secondAlbumSong());
		await expectRailRowCollapsed(firstAlbumRow(), firstAlbumSong());
		await expect(surface.getByRole('heading', { name: library.secondAlbumTitle })).toBeVisible();

		// The group header changes only the tree, and native keyboard activation
		// works in the real browser. The surface remains the selected album.
		const selectedAlbumUrl = page.url();
		const libraryGroupToggle = rail.getByRole('button', {
			name: nameStartingWith(LIBRARY_PAGE_LABEL)
		});
		await expect(libraryGroupToggle).toHaveAttribute('aria-expanded', 'true');
		await libraryGroupToggle.press('Enter');
		await expect(libraryGroupToggle).toHaveAttribute('aria-expanded', 'false');
		await libraryGroupToggle.press(' ');
		await expect(libraryGroupToggle).toHaveAttribute('aria-expanded', 'true');
		await expect(surface.getByRole('heading', { name: library.secondAlbumTitle })).toBeVisible();
		expect(page.url()).toBe(selectedAlbumUrl);

		// SETTINGS is the same kind of group header: both its visible text and
		// caret only disclose its children. Neither can choose an admin page.
		const settingsGroupToggle = rail.getByRole('button', {
			name: RAIL_SETTINGS_LABEL,
			exact: true
		});
		const settingsUrl = page.url();
		await settingsGroupToggle.locator('.group-title').click();
		await expect(settingsGroupToggle).toHaveAttribute('aria-expanded', 'true');
		expect(page.url()).toBe(settingsUrl);
		await settingsGroupToggle.locator('.caret').click();
		await expect(settingsGroupToggle).toHaveAttribute('aria-expanded', 'false');
		expect(page.url()).toBe(settingsUrl);

		// "Settings stays pinned below LIBRARY and PLAYLISTS" (#326 finding 6) as
		// a promise, not a CSS class assertion: seed.ts adds enough filler albums
		// that the rail's own list genuinely overflows, so this really scrolls
		// past content rather than measuring a page that never needed to scroll.
		const libraryGroupTitle = rail.getByRole('button', {
			name: nameStartingWith(LIBRARY_PAGE_LABEL)
		});
		const settingsToggle = rail.getByRole('button', { name: RAIL_SETTINGS_LABEL, exact: true });
		// defect:#1555: the album rows above left the rail scrolled wherever
		// they were judged, so the pin promise sets its own starting position
		// at the top of the Library list.
		await libraryGroupTitle.scrollIntoViewIfNeeded();
		await expect(libraryGroupTitle).toBeInViewport();
		await expect(settingsToggle).toBeInViewport();

		const railBox = await rail.boundingBox();
		if (!railBox) throw new Error('Expected the rail to render');
		await page.mouse.move(railBox.x + railBox.width / 2, railBox.y + railBox.height / 3);
		await page.mouse.wheel(0, 8000);

		// Proof this really scrolled, not a no-op: the top of the scrollable
		// region -- the LIBRARY group's own title -- has scrolled out of view.
		await expect(libraryGroupTitle).not.toBeInViewport();

		// The pin promise itself: Settings remains reachable while the Library
		// content has scrolled past. Its exact pixel position is an implementation
		// detail while the disclosure's height is animating.
		await expect(settingsToggle).toBeInViewport();
		await openLibraryWall(page, shell);
		// #1354 rule 40 (D1): the Library page leaves its own group unfolded and current.
		await expect(
			rail.getByRole('button', { name: nameStartingWith(LIBRARY_PAGE_LABEL) })
		).toHaveAttribute('aria-expanded', 'true');
		await expect(
			rail.getByRole('link', { name: nameStartingWith(LIBRARY_PAGE_LABEL) })
		).toHaveAttribute('aria-current', 'page');

		console.log(`Rail flow /api requests (${shell}): ${guard.apiRequestCount}`);
		guard.assertWithinBudget(RAIL_FLOW_API_REQUEST_BUDGET);
	}
);

/** Plays one of the attempt's playlist songs from that playlist, as the player reports it. */
async function listenInPlaylist(page: Page, seeded: SeededPlaylist): Promise<void> {
	const playlists = await page.request.get('/api/playlists');
	expect(playlists.status()).toBe(200);
	const listed = (await playlists.json()) as Array<{ id: string; slug: string }>;
	const played = listed.find((candidate) => candidate.slug === seeded.slug);
	if (!played) throw new Error(`Missing seeded playlist ${seeded.slug}`);
	const listen = await page.request.post(
		`/api/songs/${readSeededLibrary().listenReorderSongs.desktop.id}/listen`,
		{ headers: await sameOriginHeaders(page), data: { playlist_id: played.id } }
	);
	expect(listen.status()).toBe(200);
}

async function listenInSeededAlbum(page: Page): Promise<void> {
	const listen = await page.request.post(
		`/api/songs/${readSeededLibrary().listenReorderSongs.desktop.id}/listen`,
		{ headers: await sameOriginHeaders(page) }
	);
	expect(listen.status()).toBe(200);
}

test('1354_rule_7 1354_rule_13 1354_rule_14 1354_rule_31: the Library keeps phone counts and desktop listen timestamps under Last played and keeps the choice across reload, shows no Listen list, and leaves the one on Home alone', async ({
	page
}, testInfo) => {
	const surface = workspace(page);
	const orders = surface.getByRole('group', { name: LIBRARY_WALL_ORDER_GROUP_LABEL });
	const choice = (order: LibraryWallOrder) =>
		orders.getByRole('button', { name: LIBRARY_WALL_ORDER_LABELS[order], exact: true });
	const tiles = surface.locator('.library-wall .tile-grid .wall-tile-body');
	const firstLine = tiles.first().locator('.tile-subtitle');
	const listenTitles = listenRegion(page).locator('.library-row .tile-title');
	const library = readSeededLibrary();
	await listenInSeededAlbum(page);

	await page.goto(HOME_PATH);
	await expect(listenTitles.first()).toBeVisible();
	const listenOrder = await listenTitles.allTextContents();

	await page.goto(LIBRARY_PATH);
	await expect(orders.getByRole('button')).toHaveText([
		LIBRARY_WALL_ORDER_LABELS.title,
		LIBRARY_WALL_ORDER_LABELS.played
	]);
	await expect(choice('title')).toHaveAttribute('aria-pressed', 'true');
	await expect(tiles.filter({ hasText: library.albumTitle })).toHaveCount(1);
	await expect(tiles.filter({ hasText: playlist.title })).toHaveCount(0);
	const tileLabels = await tiles.evaluateAll((bodies) =>
		bodies.map((body) => body.getAttribute('aria-label') ?? '')
	);
	expect(tileLabels.every((label) => label.startsWith('Open album '))).toBe(true);
	await expect(listenTitles).toHaveCount(0);
	const alphabetical = await tiles.locator('.tile-title').allTextContents();
	expect(alphabetical).toEqual([...alphabetical].sort(compareTitles));
	const playedBox = await choice('played').boundingBox();
	expect(playedBox?.height).toBeGreaterThanOrEqual(HITBOX_FREQUENT_PX);

	// The seeded album holds the newest listen.
	await choice('played').click();
	await expect(tiles.first()).toContainText(library.albumTitle);
	await expect(firstLine).toHaveText(
		shellOf(testInfo) === 'mobile' ? SONG_COUNT : /^today \d\d:\d\d$/
	);
	await expect(listenTitles).toHaveCount(0);

	await page.reload();
	await expect(choice('played')).toHaveAttribute('aria-pressed', 'true');
	await expect(tiles.first()).toContainText(library.albumTitle);
	await expect(firstLine).toHaveText(
		shellOf(testInfo) === 'mobile' ? SONG_COUNT : /^today \d\d:\d\d$/
	);
	await expect(listenTitles).toHaveCount(0);

	await page.goto(HOME_PATH);
	await expect(listenTitles).toHaveText(listenOrder);
});

test(
	'1354_37a_A6: the rail lists albums and playlists in the order the Library and Playlists walls are switched to',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page, request }, testInfo) => {
		const shell = shellOf(testInfo);
		const surface = workspace(page);
		const tiles = surface.locator('.library-wall .tile-grid .wall-tile-body');
		const choice = (group: string, order: LibraryWallOrder) =>
			surface
				.getByRole('group', { name: group })
				.getByRole('button', { name: LIBRARY_WALL_ORDER_LABELS[order], exact: true });

		async function railOrderMatchingWall(railRows: string): Promise<string[]> {
			const rail = await openRailNav(page, shell);
			const wallTitles = () => tiles.locator('.tile-title').allTextContents();
			const railTitles = () => rail.locator(`${railRows} .row-title`).allTextContents();
			await expect.poll(async () => (await railTitles()).length).toBeGreaterThan(1);
			await expect
				.poll(async () => JSON.stringify(await railTitles()) === JSON.stringify(await wallTitles()))
				.toBe(true);
			return railTitles();
		}

		// Of two playlists, a listen in the one A–Z puts second brings it to the
		// front under Last played: the rail can only show that by leaving A–Z.
		const second = await seedPlaylist(request, readSeededLibrary());
		const [, laterInAlphabet] = [playlist, second].toSorted((a, b) =>
			compareTitles(a.title, b.title)
		);
		await listenInPlaylist(page, laterInAlphabet);

		await page.goto(LIBRARY_PATH);
		await expect(choice(LIBRARY_WALL_ORDER_GROUP_LABEL, 'title')).toHaveAttribute(
			'aria-pressed',
			'true'
		);
		const albums = await railOrderMatchingWall('.album-label');
		expect(albums).toEqual([...albums].sort(compareTitles));
		await page.goto('/playlists');
		const playlists = await railOrderMatchingWall('.playlist-label');
		expect(playlists).toEqual([...playlists].sort(compareTitles));

		await page.reload();
		await choice(PLAYLISTS_WALL_ORDER_GROUP_LABEL, 'played').click();
		await expect(tiles.first()).toContainText(laterInAlphabet.title);
		expect((await railOrderMatchingWall('.playlist-label'))[0]).toBe(laterInAlphabet.title);
		await page.goto(LIBRARY_PATH);
		await expect(choice(LIBRARY_WALL_ORDER_GROUP_LABEL, 'played')).toHaveAttribute(
			'aria-pressed',
			'true'
		);
		await railOrderMatchingWall('.album-label');
	}
);

/** Every playlist the server holds, by title in A–Z: the flows before this one seed their own. */
async function playlistTitlesInAlphabet(page: Page): Promise<string[]> {
	const response = await page.request.get('/api/playlists');
	expect(response.status()).toBe(200);
	const listed = (await response.json()) as Array<{ title: string }>;
	return listed.map((listedPlaylist) => listedPlaylist.title).toSorted(compareTitles);
}

// #1402: Playlists gets its own page, at its own address and from search,
// listing playlists alone in the one switch the Library uses (#1354 rules 7
// and 8, frame D3). On the phone it is a list the app opens on, so it carries
// no ‹, and a playlist opened with nothing before it returns there.
test('1354_37a_A6: the Playlists page opens by address and by search, lists only playlists in the one sort, and stays put on reload, Back and Forward', async ({
	page,
	request
}, testInfo) => {
	const shell = shellOf(testInfo);
	const library = readSeededLibrary();
	const second = await seedPlaylist(request, library);
	const [, laterInAlphabet] = [playlist, second].toSorted((a, b) =>
		compareTitles(a.title, b.title)
	);
	await listenInPlaylist(page, laterInAlphabet);
	const titles = await playlistTitlesInAlphabet(page);
	const surface = workspace(page);
	const heading = surface.getByRole('heading', {
		name: wallHeadingLabel(PLAYLISTS_PAGE_LABEL, titles.length),
		exact: true
	});
	const tiles = surface.locator('.library-wall .tile-grid .wall-tile-body');
	const choice = (order: LibraryWallOrder) =>
		surface
			.getByRole('group', { name: PLAYLISTS_WALL_ORDER_GROUP_LABEL })
			.getByRole('button', { name: LIBRARY_WALL_ORDER_LABELS[order], exact: true });
	const phoneBack = appBar(page).getByRole('button', { name: /^Back to / });

	async function expectPlaylistsStandFirst(title: string): Promise<void> {
		await expect(page).toHaveURL(/\/playlists$/);
		await expect(heading).toBeVisible();
		await expect(tiles.first()).toHaveAccessibleName(`Open playlist ${title}`);
		if (shell === 'mobile') {
			await expect(phoneBack).toHaveCount(0);
			await expect(accountCircle(page)).toBeVisible();
		}
	}

	await page.goto('/playlists');
	await expectPlaylistsStandFirst(titles[0]);
	await expect(choice('title')).toHaveAttribute('aria-pressed', 'true');
	expect(
		await tiles.evaluateAll((bodies) => bodies.map((body) => body.getAttribute('aria-label')))
	).toEqual(titles.map((title) => `Open playlist ${title}`));
	await expect(tiles.filter({ hasText: playlist.title }).locator('.tile-subtitle')).toHaveText(
		/^\d+ songs?$/
	);

	await choice('played').click();
	await expectPlaylistsStandFirst(laterInAlphabet.title);

	await page.reload();
	await expectPlaylistsStandFirst(laterInAlphabet.title);
	await expect(choice('played')).toHaveAttribute('aria-pressed', 'true');

	const album = surface.getByRole('heading', { name: library.albumTitle });
	await page.goto(`/album/${library.albumId}`);
	await expect(album).toBeVisible();
	await openPlaylistsPage(page, shell);
	await expectPlaylistsStandFirst(laterInAlphabet.title);

	await page.goBack();
	await expect(page).toHaveURL(new RegExp(`/album/${library.albumId}$`));
	await expect(album).toBeVisible();
	await expect(heading).toBeHidden();

	await page.goForward();
	await expectPlaylistsStandFirst(laterInAlphabet.title);
	await expect(album).toBeHidden();

	if (shell !== 'mobile') return;
	const fresh = await page.context().newPage();
	const freshGuard = new FlowGuard(fresh);
	await fresh.goto(`/playlist/${playlist.slug}`);
	const backToPlaylists = appBar(fresh).getByRole('button', {
		name: `Back to ${PLAYLISTS_PAGE_LABEL}`,
		exact: true
	});
	await expect(backToPlaylists).toHaveText(PLAYLISTS_PAGE_LABEL);
	const tabLength = await fresh.evaluate(() => history.length);

	await backToPlaylists.click();

	await expect(fresh).toHaveURL(/\/playlists$/);
	await expect(
		workspace(fresh).getByRole('heading', {
			name: wallHeadingLabel(PLAYLISTS_PAGE_LABEL, titles.length),
			exact: true
		})
	).toBeVisible();
	expect(await fresh.evaluate(() => history.length)).toBe(tabLength);
	await expect(appBar(fresh).getByRole('button', { name: /^Back to / })).toHaveCount(0);
	await expect(accountCircle(fresh)).toBeVisible();
	freshGuard.assertClean();
	await fresh.close();
});

test(
	'1354_37a_A6: #1354 rule 40: the word Library or Playlists opens its covers, the arrow only folds, and each page leaves its group current and unfolded',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }, testInfo) => {
		const shell = shellOf(testInfo);
		const surface = workspace(page);
		const groupWord = async (label: string) =>
			(await openRailNav(page, shell)).getByRole('link', { name: nameStartingWith(label) });
		const groupArrow = async (label: string) =>
			(await openRailNav(page, shell)).getByRole('button', { name: label, exact: true });

		await page.goto(LIBRARY_PATH);
		await expect(surface.getByRole('heading', { name: LIBRARY_PAGE_LABEL })).toBeVisible();
		await expect(await groupWord(LIBRARY_PAGE_LABEL)).toHaveAttribute('aria-current', 'page');
		await expect(await groupArrow(LIBRARY_PAGE_LABEL)).toHaveAttribute('aria-expanded', 'true');
		await expect(
			(await openRailNav(page, shell)).getByRole('button', { name: nameStartingWith('All albums') })
		).toHaveCount(0);

		await (await groupArrow(LIBRARY_PAGE_LABEL)).click();
		await expect(await groupArrow(LIBRARY_PAGE_LABEL)).toHaveAttribute('aria-expanded', 'false');
		await expect(page).toHaveURL(LIBRARY_URL);

		await (await groupWord(PLAYLISTS_PAGE_LABEL)).click();
		await expect(page).toHaveURL(/\/playlists$/);
		await expect(await groupWord(PLAYLISTS_PAGE_LABEL)).toHaveAttribute('aria-current', 'page');
		await expect(await groupArrow(PLAYLISTS_PAGE_LABEL)).toHaveAttribute('aria-expanded', 'true');

		await (await groupArrow(PLAYLISTS_PAGE_LABEL)).click();
		await expect(await groupArrow(PLAYLISTS_PAGE_LABEL)).toHaveAttribute('aria-expanded', 'false');
		await expect(page).toHaveURL(/\/playlists$/);

		await (await groupWord(LIBRARY_PAGE_LABEL)).click();
		await expect(page).toHaveURL(LIBRARY_URL);
		await expect(surface.getByRole('heading', { name: LIBRARY_PAGE_LABEL })).toBeVisible();
		await expect(await groupWord(LIBRARY_PAGE_LABEL)).toHaveAttribute('aria-current', 'page');
		await expect(await groupArrow(LIBRARY_PAGE_LABEL)).toHaveAttribute('aria-expanded', 'true');
	}
);

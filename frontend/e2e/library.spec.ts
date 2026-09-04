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
	APP_NAME,
	collectionRowPlayLabel,
	EDITOR_TAB_TAKES_LABEL,
	EDITOR_TAB_WRITE_LABEL,
	HITBOX_FREQUENT_PX,
	LIBRARY_FILTER_LABELS,
	NOW_PLAYING_CLOSE,
	PLAYLIST_ENTRY_MOVE_DOWN_LABEL,
	PLAYLIST_ENTRY_REMOVE_LABEL,
	playlistEntryOverflowLabel,
	RAIL_ALBUM_DISCLOSE_LABEL,
	RAIL_DRAWER_LABEL,
	RAIL_DRAWER_OPEN_LABEL,
	RAIL_LIBRARY_LABEL,
	RAIL_LIBRARY_NAV_LABEL,
	RAIL_NAV_LABEL,
	RAIL_PLAYLISTS_NAV_LABEL,
	RAIL_SETTINGS_LABEL,
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
	playlistEntryRows,
	RAIL_FLOW_API_REQUEST_BUDGET,
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
 * Both are addressed by role: the heading's accessible name is the album
 * title (see CollectionHeader.svelte's aria-label — issue #160), so it is
 * the name filter, not "the only heading in the surface", that selects it.
 */
async function expectHeaderReadsAtNarrowest(page: Page, albumTitle: string): Promise<void> {
	const surface = workspace(page);
	const title = surface.getByRole('heading', { name: albumTitle });
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

/** Back to the wall — on mobile the rail is a drawer the header opens. */
async function openLibraryWall(page: Page, shell: Shell): Promise<void> {
	if (shell === 'desktop') {
		await page
			.getByRole('navigation', { name: RAIL_NAV_LABEL })
			.getByRole('button', { name: APP_NAME, exact: true })
			.click();
		return;
	}
	await page.getByRole('button', { name: RAIL_DRAWER_OPEN_LABEL }).click();
	const drawer = page.getByRole('dialog', { name: RAIL_DRAWER_LABEL });
	// The LIBRARY group is a disclosure. Until its first child becomes the
	// wall target, the wordmark remains the rail's one Library shortcut.
	await drawer.getByRole('button', { name: APP_NAME, exact: true }).click();
	await expect(drawer).toBeHidden();
}

/**
 * The one navigation landmark (#263): on desktop it stands on its own, on
 * mobile it only exists once the header opens its drawer — a navigation to
 * a settings section closes that drawer again (`RailDrawer`'s
 * `afterNavigate`), so a caller that keeps interacting with the rail after
 * such a click must open it again.
 */
async function openRailNav(page: Page, shell: Shell): Promise<Locator> {
	if (shell === 'mobile') await page.getByRole('button', { name: RAIL_DRAWER_OPEN_LABEL }).click();
	return page.getByRole('navigation', { name: RAIL_NAV_LABEL });
}

/**
 * One navigation, no modes (#263): Settings is a disclosure inside the same
 * rail the album lives in, not a second column beside the content. Opening a
 * section is a real navigation (#265), and the rail's own album context row
 * is the way back — the "click back into the album" promise that made the
 * disclosure worth building in the first place (#264).
 */
async function expectSettingsRailRoundTrip(
	page: Page,
	shell: Shell,
	surface: Locator,
	albumTitle: string
): Promise<void> {
	let rail = await openRailNav(page, shell);
	await rail.getByRole('button', { name: RAIL_SETTINGS_LABEL }).click();
	await rail.getByRole('link', { name: 'Voices', exact: true }).click();

	await expect(page).toHaveURL(/\/settings\/voices$/);
	// The removed second column — the old `.settings-sidebar` — is gone, and
	// so is any other navigation landmark inside the content area; the rail
	// stays the one navigation on the page.
	await expect(page.locator('.settings-sidebar')).toHaveCount(0);
	await expect(surface.getByRole('navigation')).toHaveCount(0);

	if (shell === 'desktop') {
		// No gap for a second column: the content starts right where the rail ends.
		const [railBox, mainBox] = await boundingBoxes(rail, surface);
		expect(Math.abs(mainBox.x - (railBox.x + railBox.width))).toBeLessThanOrEqual(2);
	}

	rail = await openRailNav(page, shell);
	await rail.getByRole('button', { name: containing(albumTitle) }).click();
	await expect(surface.getByRole('heading', { name: albumTitle })).toBeVisible();
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
	await expect(surface.getByRole('heading', { name: library.albumTitle })).toBeVisible();
	if (shell === 'mobile') await expectHeaderReadsAtNarrowest(page, library.albumTitle);

	await expectSettingsRailRoundTrip(page, shell, surface, library.albumTitle);

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

	const takeRow = surface.locator('.take-row').filter({ hasText: library.takeLabel });
	await takeRow.locator('.take-summary').click();
	await expectTakeShownInNowPlaying(page, shell, library.pickedSongTitle);
	// A row body never stops the music: the take that was already playing when
	// the row was clicked is still playing after it.
	await expect(
		shellTransport(page, shell, library.pickedSongTitle).getByRole('button', {
			name: TRANSPORT_PAUSE_LABEL,
			exact: true
		})
	).toBeVisible();
	await closeNowPlaying(page, shell);

	await takeRow.getByRole('button', { name: TAKE_OVERFLOW_LABEL }).click();
	await surface.getByRole('menuitem', { name: TAKE_PLAYLIST_LABEL }).click();
	await surface.getByRole('button', { name: nameStartingWith(playlist.title) }).click();

	await openLibraryWall(page, shell);
	await surface.getByRole('radio', { name: LIBRARY_FILTER_LABELS.playlists }).click();
	await surface.getByRole('button', { name: nameStartingWith(playlist.title) }).click();

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

	// A playlist row is a take row: it plays and judges, the same click as in
	// the editor's takes list, and the playlist stays where it is.
	await entryRows
		.first()
		.getByRole('button', { name: nameStartingWith(secondPlaylistSong) })
		.click();
	await expectTakeShownInNowPlaying(page, shell, secondPlaylistSong);
	// The row played, it did not merely open: the transport that is showing
	// offers to pause the take the row stands for.
	await expect(
		shellTransport(page, shell, secondPlaylistSong).getByRole('button', {
			name: TRANSPORT_PAUSE_LABEL,
			exact: true
		})
	).toBeVisible();
	if (shell === 'desktop') {
		await expect(surface.getByRole('heading', { name: playlist.title })).toBeVisible();
	}
	await closeNowPlaying(page, shell);
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

/**
 * One album's own row inside the rail's LIBRARY group. Every album's chevron
 * shares the exact same accessible name (RAIL_ALBUM_DISCLOSE_LABEL — #326),
 * so a flow must narrow to the row that carries this album's title before it
 * can find that album's own chevron or its own songs.
 */
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
	await row.scrollIntoViewIfNeeded();
	await expect(song).toBeInViewport();
}

async function expectRailRowCollapsed(row: Locator, song: Locator): Promise<void> {
	await row.scrollIntoViewIfNeeded();
	await expect(song).not.toBeInViewport();
}

test('the rail disclosure and pin promises hold in a real browser', async ({ page }, testInfo) => {
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

	// Rebuilt after every click that navigates (#263): on mobile the drawer's
	// own afterNavigate hook closes it, so the rail's nav landmark stops
	// existing until openRailNav opens it again -- a locator built from an
	// earlier `rail` would silently match nothing rather than prove anything.
	let rail = await openRailNav(page, shell);

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

	rail = await openRailNav(page, shell);
	function firstAlbumRow(): Locator {
		return railAlbumRow(rail, library.albumTitle);
	}
	function firstAlbumSong(): Locator {
		return firstAlbumRow().getByRole('button', { name: nameStartingWith(library.pickedSongTitle) });
	}
	// Entering an album force-expands its own row without a chevron click,
	// and that force-expand is what pulled the whole LIBRARY group open too.
	await expectRailRowExpanded(firstAlbumRow(), firstAlbumSong());

	function secondAlbumRow(): Locator {
		return railAlbumRow(rail, library.secondAlbumTitle);
	}
	const secondAlbumChevron = secondAlbumRow().getByRole('button', {
		name: RAIL_ALBUM_DISCLOSE_LABEL,
		exact: true
	});
	function secondAlbumSong(): Locator {
		return secondAlbumRow().getByRole('button', {
			name: nameStartingWith(library.secondAlbumSongTitle)
		});
	}

	// The chevron alone toggles a closed album's tracks -- loaded on demand,
	// the first time it opens -- and never navigates (#326 finding 1).
	await expect(secondAlbumChevron).toHaveAttribute('aria-expanded', 'false');
	await expectRailRowCollapsed(secondAlbumRow(), secondAlbumSong());
	await secondAlbumChevron.click();
	await expect(secondAlbumChevron).toHaveAttribute('aria-expanded', 'true');
	// The promise jsdom cannot measure (#326 finding 3): the row really
	// renders, not merely carries data-open="true" -- .rail-group-panel's
	// grid-template-rows collapses a closed panel to zero height. Opening it
	// by its chevron alone -- not just by its label -- still enforces the
	// one-slot rule (#323): the album that was open closes too.
	await expectRailRowExpanded(secondAlbumRow(), secondAlbumSong());
	await expectRailRowCollapsed(firstAlbumRow(), firstAlbumSong());
	await expect(surface.getByRole('heading', { name: library.albumTitle })).toBeVisible();
	await expect(page).toHaveURL(new RegExp(`/album/${library.albumId}`));

	// The row's label is the navigation target (ruled sentence 5 of #302): a
	// list entry click goes directly into that album.
	await railAlbumRow(rail, library.secondAlbumTitle)
		.getByRole('button', { name: containing(library.secondAlbumTitle) })
		.click();
	await expect(surface.getByRole('heading', { name: library.secondAlbumTitle })).toBeVisible();

	// The group header changes only the tree, and native keyboard activation
	// works in the real browser. The surface remains the selected album.
	const selectedAlbumUrl = page.url();
	rail = await openRailNav(page, shell);
	const libraryGroupToggle = rail.getByRole('button', {
		name: nameStartingWith(RAIL_LIBRARY_LABEL)
	});
	await expect(libraryGroupToggle).toHaveAttribute('aria-expanded', 'true');
	await libraryGroupToggle.press('Enter');
	await expect(libraryGroupToggle).toHaveAttribute('aria-expanded', 'false');
	await libraryGroupToggle.press(' ');
	await expect(libraryGroupToggle).toHaveAttribute('aria-expanded', 'true');
	await expect(surface.getByRole('heading', { name: library.secondAlbumTitle })).toBeVisible();
	expect(page.url()).toBe(selectedAlbumUrl);

	// "Settings stays pinned below LIBRARY and PLAYLISTS" (#326 finding 6) as
	// a promise, not a CSS class assertion: seed.ts adds enough filler albums
	// that the rail's own list genuinely overflows, so this really scrolls
	// past content rather than measuring a page that never needed to scroll.
	rail = await openRailNav(page, shell);
	const libraryGroupTitle = rail.getByRole('button', {
		name: nameStartingWith(RAIL_LIBRARY_LABEL)
	});
	const settingsToggle = rail.getByRole('button', { name: RAIL_SETTINGS_LABEL, exact: true });
	await expect(libraryGroupTitle).toBeInViewport();
	await expect(settingsToggle).toBeInViewport();
	const [beforeSettingsBox] = await boundingBoxes(settingsToggle);

	const railBox = await rail.boundingBox();
	if (!railBox) throw new Error('Expected the rail to render');
	await page.mouse.move(railBox.x + railBox.width / 2, railBox.y + railBox.height / 3);
	await page.mouse.wheel(0, 8000);

	// Proof this really scrolled, not a no-op: the top of the scrollable
	// region -- the LIBRARY group's own title -- has scrolled out of view.
	await expect(libraryGroupTitle).not.toBeInViewport();

	// The pin promise itself: Settings never moved with the content that just
	// scrolled past it.
	const [afterSettingsBox] = await boundingBoxes(settingsToggle);
	expect(afterSettingsBox.y).toBeCloseTo(beforeSettingsBox.y, 0);
	await expect(settingsToggle).toBeInViewport();

	console.log(`Rail flow /api requests (${shell}): ${guard.apiRequestCount}`);
	guard.assertWithinBudget(RAIL_FLOW_API_REQUEST_BUDGET[shell]);
});

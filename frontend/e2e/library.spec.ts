// The desktop library flow an operator walks by hand: play the album pick,
// judge a take, put it on a playlist, reorder the playlist, shuffle, and open
// the public album link while logged out.

import { expect, test } from '@playwright/test';
import {
	collectionRowPlayLabel,
	LIBRARY_FILTER_LABELS,
	NOW_PLAYING_CLOSE,
	PLAYLIST_ENTRY_MOVE_DOWN_LABEL,
	PLAYLIST_ENTRY_REMOVE_LABEL,
	playlistEntryOverflowLabel,
	RAIL_LIBRARY_LABEL,
	TAKE_OVERFLOW_LABEL,
	TAKE_PLAYLIST_LABEL
} from '../src/lib/constants';
import {
	NOW_PLAYING_SHUFFLE_DISABLE_PREFIX,
	NOW_PLAYING_SHUFFLE_LABEL_PREFIX,
	NOW_PLAYING_TAKE_TAB
} from '../src/lib/constants/now-playing';
import {
	containing,
	FlowGuard,
	LIBRARY_FLOW_API_REQUEST_BUDGET,
	nameStartingWith,
	playableRows,
	TRANSPORT_PAUSE_LABEL,
	workspace
} from './helpers';
import { readSeededLibrary, seedPlaylist, type SeededPlaylist } from './seed';

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

test('plays the album pick, curates a playlist and serves the public album link', async ({
	page,
	browser
}) => {
	const library = readSeededLibrary();
	const [firstPlaylistSong, secondPlaylistSong] = playlist.songTitles;
	const surface = workspace(page);

	await page.goto('/');
	await expect(surface.getByRole('heading', { name: LIBRARY_FILTER_LABELS.albums })).toBeVisible();

	await surface.getByRole('button', { name: nameStartingWith(library.albumTitle) }).click();
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

	await surface.getByRole('button', { name: nameStartingWith(library.pickedSongTitle) }).click();
	const takeRow = surface.getByRole('button', { name: library.takeLabel });
	await takeRow.click();
	await expect(page.getByRole('tab', { name: NOW_PLAYING_TAKE_TAB })).toHaveAttribute(
		'aria-selected',
		'true'
	);
	await page.getByRole('button', { name: NOW_PLAYING_CLOSE, exact: true }).click();

	await takeRow.getByRole('button', { name: TAKE_OVERFLOW_LABEL }).click();
	await surface.getByRole('menuitem', { name: TAKE_PLAYLIST_LABEL }).click();
	await surface.getByRole('button', { name: nameStartingWith(playlist.title) }).click();

	await surface.getByRole('button', { name: RAIL_LIBRARY_LABEL, exact: true }).click();
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

	const loggedOut = await browser.newContext({ storageState: undefined });
	const sharePage = await loggedOut.newPage();
	const shareGuard = new FlowGuard(sharePage);
	await sharePage.goto(library.albumShareUrl);
	await expect(sharePage.getByRole('heading', { name: library.albumTitle })).toBeVisible();
	await expect(
		sharePage.getByRole('button', { name: nameStartingWith(library.pickedSongTitle) })
	).toBeVisible();
	shareGuard.assertClean();
	await loggedOut.close();

	console.log(`Desktop library flow /api requests: ${guard.apiRequestCount}`);
	guard.assertWithinBudget(LIBRARY_FLOW_API_REQUEST_BUDGET);
});

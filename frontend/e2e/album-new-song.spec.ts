// A new song is made at the end of the album's track list (#1172, #915 F3;
// frames V1 of docs/design/album-browsing.html §(i)): a quiet + New song row
// turns into the inline New song in <album> card, CREATE makes the song in
// that album and opens it, × and Back fold the card back into the row. The
// header row is Play · Shuffle · ⋯ only. The empty album is this run's own,
// created on the wire, so making its first song leaves the seeded album alone.

import { expect, test, type Locator, type Page, type TestInfo } from '@playwright/test';
import {
	ALBUM_NO_SONGS,
	COLLECTION_MENU_LABEL,
	collectionPlayLabel,
	collectionShuffleLabel,
	NEW_PLACE_CREATE_LABEL,
	NEW_SONG_CLOSE_LABEL,
	NEW_SONG_ROW_LABEL,
	NEW_SONG_TITLE_LABEL,
	newSongCardLabel
} from '../src/lib/constants';
import { appBar, boundingBoxes, csrfHeaders, FlowGuard, shellOf, workspace } from './helpers';
import { readSeededLibrary } from './seed';

/**
 * Sized before the first CI measurement from the album cold open (album-menu
 * measured 14 on desktop), one album create, one song create and the song
 * page's own loads; the CI log line below is the measurement to tighten it
 * against.
 */
const ALBUM_NEW_SONG_FLOW_API_REQUEST_BUDGET = 40;

/** The + New song row stands track-row high; subpixel layout may round either one. */
const ROW_HEIGHT_TOLERANCE_PX = 2;

let guard: FlowGuard;

test.beforeEach(({ page }) => {
	guard = new FlowGuard(page);
});

// eslint-disable-next-line no-empty-pattern -- Playwright requires the object-destructuring form even with no fixture named
test.afterEach(({}, testInfo) => {
	console.log(`Album-new-song flow /api requests (${testInfo.title}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(ALBUM_NEW_SONG_FLOW_API_REQUEST_BUDGET);
});

function newSongRow(page: Page): Locator {
	return workspace(page).getByRole('button', { name: NEW_SONG_ROW_LABEL, exact: true });
}

async function createEmptyAlbum(
	page: Page,
	testInfo: TestInfo
): Promise<{ id: string; title: string }> {
	const title = `Nightdrive ${shellOf(testInfo)} ${Date.now()}`;
	const response = await page.request.post('/api/albums', {
		headers: await csrfHeaders(page),
		data: { title, artist: '' }
	});
	expect(response.ok()).toBe(true);
	const album = (await response.json()) as { id: string };
	return { id: album.id, title };
}

test('a filled album ends its track list with + New song, under a header of Play · Shuffle · ⋯', async ({
	page
}) => {
	const library = readSeededLibrary();
	await page.goto(`/album/${library.albumId}`);
	const surface = workspace(page);
	await expect(surface.getByRole('heading', { name: library.albumTitle })).toBeVisible();

	const actions = surface.locator('.collection-header .header-actions').getByRole('button');
	await expect(actions).toHaveCount(3);
	await expect(actions.nth(0)).toHaveAccessibleName(collectionPlayLabel('album'));
	await expect(actions.nth(1)).toHaveAccessibleName(collectionShuffleLabel('album'));
	await expect(actions.nth(2)).toHaveAccessibleName(COLLECTION_MENU_LABEL);

	const rows = surface.locator('.item-list > *');
	await expect(rows.last().getByRole('button')).toHaveAccessibleName(NEW_SONG_ROW_LABEL);
	await expect(newSongRow(page)).toBeVisible();
	const [lastSong, row] = await boundingBoxes(rows.nth((await rows.count()) - 2), newSongRow(page));
	expect(row.y).toBeGreaterThanOrEqual(lastSong.y + lastSong.height);
	expect(Math.abs(row.height - lastSong.height)).toBeLessThanOrEqual(ROW_HEIGHT_TOLERANCE_PX);
});

test('an empty album makes its first song from + New song and opens it', async ({
	page
}, testInfo) => {
	await page.goto('/');
	const album = await createEmptyAlbum(page, testInfo);
	const songTitle = `Tidewater ${Date.now()}`;
	await page.goto(`/album/${album.id}`);
	const surface = workspace(page);
	await expect(surface.getByRole('heading', { name: album.title })).toBeVisible();
	await expect(surface.getByText(ALBUM_NO_SONGS, { exact: true })).toBeVisible();

	const card = surface.getByRole('form', { name: newSongCardLabel(album.title) });
	await newSongRow(page).click();
	await expect(card).toBeVisible();
	await expect(newSongRow(page)).toBeHidden();
	await expect(card.getByLabel(NEW_SONG_TITLE_LABEL)).toBeFocused();
	await card.getByRole('button', { name: NEW_SONG_CLOSE_LABEL }).click();
	await expect(card).toBeHidden();
	await expect(newSongRow(page)).toBeFocused();

	await newSongRow(page).click();
	await expect(card).toBeVisible();
	await page.goBack();
	await expect(card).toBeHidden();
	await expect(newSongRow(page)).toBeFocused();
	await expect(surface.getByRole('heading', { name: album.title })).toBeVisible();

	await newSongRow(page).click();
	await card.getByLabel(NEW_SONG_TITLE_LABEL).fill(songTitle);
	await card.getByRole('button', { name: NEW_PLACE_CREATE_LABEL }).click();

	await expect(page).toHaveURL(new RegExp(`/album/${album.id}/`));
	const songHeading = shellOf(testInfo) === 'mobile' ? appBar(page) : surface;
	await expect(songHeading.getByRole('heading', { name: songTitle })).toBeVisible();
});

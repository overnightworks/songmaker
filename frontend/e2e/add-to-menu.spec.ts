// Add to… is the one row that puts a take, a song or an album on a playlist,
// and it turns the open ⋯ popover into the picker at both widths: an existing
// playlist adds on a tap, and the New playlist… field creates and adds on Enter.

import { expect, test, type Locator, type Page } from './coverage-test';
import { words } from '../src/lib/words/en';
import { archiveOwnedAlbum, readSeededLibrary, seedPlaylist, seedTakeStripSong } from './seed';
import {
	containing,
	FlowGuard,
	nameStartingWith,
	playlistEntryRows,
	sameOriginHeaders,
	shellOf,
	workspace
} from './helpers';

const NEW_PLAYLIST_TITLE_PREFIX = 'E2E Add to';
const TAKE_SONG_TITLE = 'Add to take song';
const FLOW_API_REQUEST_BUDGET = 40;

let guard: FlowGuard;

test.beforeEach(({ page }) => {
	guard = new FlowGuard(page);
});

// eslint-disable-next-line no-empty-pattern -- Playwright requires the object-destructuring form even with no fixture named
test.afterEach(({}, testInfo) => {
	console.log(`Add-to flow /api requests (${testInfo.title}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(FLOW_API_REQUEST_BUDGET);
});

async function openAddToPicker(
	page: Page,
	trigger: Locator,
	menuLabel: string,
	addToLabel: string
): Promise<void> {
	await trigger.click();
	const menu = page.getByRole('dialog', { name: menuLabel, exact: true });
	await menu.getByRole('button', { name: nameStartingWith(addToLabel) }).click();
	await expect(menu.getByText(words['addToPicker.heading'], { exact: true })).toBeVisible();
}

test('album ⋯ › Add to… › a new playlist by Enter holds the album songs', async ({ page }) => {
	const library = readSeededLibrary();
	await page.goto(`/album/${library.albumId}`);
	const header = workspace(page).locator('.collection-header');
	await openAddToPicker(
		page,
		header.getByRole('button', { name: words['collectionMenu.label'], exact: true }),
		words['collectionMenu.label'],
		words['collectionMenu.addTo']
	);

	const title = `${NEW_PLAYLIST_TITLE_PREFIX} ${Date.now()}`;
	const created = page.waitForResponse(
		(response) => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/playlists'
	);
	await page.getByRole('textbox', { name: words['addToPicker.newPlaceholder'] }).fill(title);
	await page.keyboard.press('Enter');
	const { slug } = (await (await created).json()) as { slug: string };
	await expect(page.getByRole('dialog', { name: words['collectionMenu.label'] })).toBeHidden();

	await page.goto(`/playlist/${slug}`);
	const rows = playlistEntryRows(page);
	await expect(rows).toHaveCount(library.albumSongCount);
	for (const track of library.albumTracks) {
		await expect(rows.filter({ hasText: containing(track.songTitle) })).toHaveCount(1);
	}
});

test('take ⋯ › Add to… › an existing playlist holds that take', async ({ page, request }, testInfo) => {
	const library = readSeededLibrary();
	const playlist = await seedPlaylist(request, library, 0);
	const headers = await sameOriginHeaders(page);
	const album = await page.request.post('/api/albums', {
		headers,
		data: { title: `E2E Add to ${Date.now()}`, artist: '' }
	});
	expect(album.ok()).toBe(true);
	const { id: albumId } = (await album.json()) as { id: string };
	try {
		const songId = await seedTakeStripSong(albumId, TAKE_SONG_TITLE, 1);
		const song = await page.request.get(`/api/songs/${songId}`);
		const { slug } = (await song.json()) as { slug: string };
		await page.goto(`/album/${albumId}/${slug}`);
		if (shellOf(testInfo) === 'mobile') {
			await page.getByRole('tab', { name: words['songTabs.takes'] }).click();
		}
		await openAddToPicker(
			page,
			page.locator('.take-row').getByRole('button', { name: words['takeMenu.label'], exact: true }),
			words['takeMenu.label'],
			words['takeMenu.addTo']
		);
		await page.getByRole('button', { name: nameStartingWith(playlist.title) }).click();
		await expect(page.getByRole('dialog', { name: words['takeMenu.label'] })).toBeHidden();

		await page.goto(`/playlist/${playlist.slug}`);
		await expect(playlistEntryRows(page)).toHaveCount(1);
		await expect(playlistEntryRows(page).first()).toContainText(TAKE_SONG_TITLE);
	} finally {
		await archiveOwnedAlbum(page.request, albumId);
	}
});

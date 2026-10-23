// A take selection belongs to the song it was made on (#1824): leaving song A
// with takes ticked must not carry "n selected" to song B, where Delete
// Selected would remove A's takes for good. Desktop only: the selection
// toolbar and the Ctrl/⌘-click on a take's play control are the same on the
// phone's Takes tab, and the 1440 px cell is the one the item names.

import { expect, test, type Page } from '@playwright/test';
import { songEditorOpenLabel } from '../src/lib/constants';
import { csrfHeaders, FlowGuard, ONLY_IN_SHELL, workspace } from './helpers';
import { archiveOwnedAlbum, seedTakeStripSong } from './seed';

const TAKES_PER_SONG = 4;
const SELECTED_TAKE_COUNT = 2;
const SONG_A_TITLE = 'Selection song A';
const SONG_B_TITLE = 'Selection song B';
const TAKE_SELECTION_FLOW_API_REQUEST_BUDGET = 40;

let guard: FlowGuard;

test.beforeEach(({ page }) => {
	guard = new FlowGuard(page);
});

// eslint-disable-next-line no-empty-pattern -- Playwright requires the object-destructuring form even with no fixture named
test.afterEach(({}, testInfo) => {
	console.log(`Take-selection flow /api requests (${testInfo.title}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(TAKE_SELECTION_FLOW_API_REQUEST_BUDGET);
});

async function openSong(page: Page, title: string): Promise<void> {
	await workspace(page)
		.getByRole('button', { name: songEditorOpenLabel(title) })
		.click();
	await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
	await expect(page.locator('.take-row')).toHaveCount(TAKES_PER_SONG);
}

test(
	'1824 a selection made on one song is gone on another and leaves that song’s takes alone',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }) => {
		const headers = await csrfHeaders(page);
		const album = await page.request.post('/api/albums', {
			headers,
			data: { title: `E2E Take selection ${Date.now()}`, artist: '' }
		});
		expect(album.ok()).toBe(true);
		const { id: albumId } = (await album.json()) as { id: string };
		try {
			await seedTakeStripSong(albumId, SONG_A_TITLE, TAKES_PER_SONG);
			await seedTakeStripSong(albumId, SONG_B_TITLE, TAKES_PER_SONG);
			await page.goto(`/album/${albumId}`);

			await openSong(page, SONG_A_TITLE);
			const playControls = page.locator('.take-row .play-btn');
			for (let index = 0; index < SELECTED_TAKE_COUNT; index += 1)
				await playControls.nth(index).click({ modifiers: ['ControlOrMeta'] });
			const toolbar = page.locator('.selection-toolbar');
			await expect(toolbar).toContainText(`${SELECTED_TAKE_COUNT} selected`);

			await page.goBack();
			await openSong(page, SONG_B_TITLE);
			await expect(toolbar).toHaveCount(0);
			await expect(page.getByText(/\d+ selected/)).toHaveCount(0);

			await page.goBack();
			await openSong(page, SONG_A_TITLE);
			await expect(toolbar).toHaveCount(0);
		} finally {
			await archiveOwnedAlbum(page.request, albumId);
		}
	}
);

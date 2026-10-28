// A take selection belongs to one song (#1824): leaving song A with takes
// ticked must not carry "n selected" to song B, where Delete would remove A's
// takes for good. And Delete N asks first (#1844, S11): the dialog names the
// count, Cancel keeps the ticks and sends nothing, Delete removes exactly the
// ticked takes, read back through the API.
// Desktop only: the toolbar and the Ctrl/⌘-click on a take's play control are
// the same on the phone's Takes tab, and the 1440 px cell is the one the item
// names.

import { expect, test, type Page } from '@playwright/test';
import type { SongItem } from '../src/lib/api/types';
import { songEditorOpenLabel, TAKE_DELETE_MESSAGE } from '../src/lib/constants';
import {
	bulkDeleteLabel,
	bulkDeleteTitle,
	selectedCountLabel,
	TAKE_SELECT_ALL_UNKEPT_LABEL
} from '../src/lib/constants/now-playing';
import { sameOriginHeaders, FlowGuard, ONLY_IN_SHELL, workspace } from './helpers';
import { archiveOwnedAlbum, seedTakeStripSong } from './seed';

const TAKES_PER_SONG = 4;
const SELECTED_TAKE_COUNT = 2;
const SONG_A_TITLE = 'Selection song A';
const SONG_C_TITLE = 'Selection song C';
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

async function takeIdsOf(page: Page, songId: string): Promise<string[]> {
	const response = await page.request.get(`/api/songs/${songId}`);
	expect(response.ok()).toBe(true);
	return ((await response.json()) as SongItem).generations.map((take) => take.id);
}

test(
	'1824 a selection made on one song leaves no toolbar on another song',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }) => {
		const headers = await sameOriginHeaders(page);
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
		} finally {
			await archiveOwnedAlbum(page.request, albumId);
		}
	}
);

test(
	'1844 Delete N asks first, Cancel keeps the ticks and Delete removes exactly the ticked takes',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }) => {
		const headers = await sameOriginHeaders(page);
		const album = await page.request.post('/api/albums', {
			headers,
			data: { title: `E2E Bulk delete ${Date.now()}`, artist: '' }
		});
		expect(album.ok()).toBe(true);
		const { id: albumId } = (await album.json()) as { id: string };
		try {
			const songId = await seedTakeStripSong(albumId, SONG_C_TITLE, TAKES_PER_SONG);
			const before = await takeIdsOf(page, songId);
			expect(before).toHaveLength(TAKES_PER_SONG);
			await page.goto(`/album/${albumId}`);

			await openSong(page, SONG_C_TITLE);
			const rows = page.locator('.take-row');
			const tickedIds: string[] = [];
			for (let index = 0; index < SELECTED_TAKE_COUNT; index += 1) {
				tickedIds.push(((await rows.nth(index).getAttribute('id')) ?? '').replace('take-', ''));
				await rows
					.nth(index)
					.locator('.play-btn')
					.click({ modifiers: ['ControlOrMeta'] });
			}
			const toolbar = page.locator('.selection-toolbar');
			await expect(toolbar.locator(':scope > *')).toHaveText([
				TAKE_SELECT_ALL_UNKEPT_LABEL,
				selectedCountLabel(SELECTED_TAKE_COUNT),
				bulkDeleteLabel(SELECTED_TAKE_COUNT),
				'Cancel'
			]);

			const deleteButton = toolbar.getByRole('button', {
				name: bulkDeleteLabel(SELECTED_TAKE_COUNT),
				exact: true
			});
			const dialog = page.getByRole('dialog', { name: bulkDeleteTitle(SELECTED_TAKE_COUNT) });
			await deleteButton.click();
			await expect(dialog).toContainText(TAKE_DELETE_MESSAGE);
			await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
			await expect(dialog).toHaveCount(0);
			await expect(toolbar).toContainText(`${SELECTED_TAKE_COUNT} selected`);
			expect(await takeIdsOf(page, songId)).toEqual(before);

			await deleteButton.click();
			await dialog.getByRole('button', { name: 'Delete', exact: true }).click();
			await expect(rows).toHaveCount(TAKES_PER_SONG - SELECTED_TAKE_COUNT);
			await expect(toolbar).toHaveCount(0);
			expect((await takeIdsOf(page, songId)).sort()).toEqual(
				before.filter((id) => !tickedIds.includes(id)).sort()
			);
		} finally {
			await archiveOwnedAlbum(page.request, albumId);
		}
	}
);

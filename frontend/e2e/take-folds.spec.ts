// The takes of a song fold per version (#1843, S3): the latest version stands
// open, each earlier version is one row that unfolds in place, and a selection
// and a delete never include a take the person cannot see. Delete removes the
// audio for good, so every delete cell reads the survivors back through the API.
// The seeded song: v1 holds three takes, v2 (saved over it) two; a real Save
// makes v3, which folds v2.

import { expect, test, type Page, type Route } from '@playwright/test';
import type { SongItem } from '../src/lib/api/types';
import {
	EDITOR_SAVE_ACCESSIBLE_LABEL,
	EDITOR_TAB_EDIT_LABEL,
	EDITOR_TAB_TAKES_LABEL,
	songEditorOpenLabel,
	TAKE_DELETE_LABEL,
	TAKE_OVERFLOW_LABEL
} from '../src/lib/constants';
import {
	bulkDeleteLabel,
	bulkDeleteTitle,
	currentVersionHeadLabel,
	EARLIER_VERSIONS_LABEL,
	foldedGroupLabel,
	selectedCountLabel,
	TAKE_SELECT_ALL_UNKEPT_LABEL
} from '../src/lib/constants/now-playing';
import { csrfHeaders, nameStartingWith, ONLY_IN_SHELL, workspace } from './helpers';
import {
	archiveOwnedAlbum,
	completeGenerationJobWithoutEvent,
	seedRunningGenerationJob,
	seedSongPhoneSong,
	seedTakeStripSong
} from './seed';

const FIRST_VERSION_TAKE_COUNT = 3;
const SECOND_VERSION_TAKE_COUNT = 2;
const SECOND_VERSION_LYRICS = 'Second version lyrics';
const EDITED_LYRICS = 'Third version lyrics';
const SONG_PUT = /\/api\/songs\/[^/]+$/;

interface FoldedSong {
	albumId: string;
	songId: string;
	title: string;
	// Take ids, by the version they sit on.
	v1: string[];
	v2: string[];
}

async function readSong(page: Page, songId: string): Promise<SongItem> {
	const response = await page.request.get(`/api/songs/${songId}`);
	expect(response.ok()).toBe(true);
	return (await response.json()) as SongItem;
}

async function takeIdsOf(page: Page, songId: string): Promise<string[]> {
	return (await readSong(page, songId)).generations.map((take) => take.id).sort();
}

async function createAlbum(page: Page): Promise<string> {
	const album = await page.request.post('/api/albums', {
		headers: await csrfHeaders(page),
		data: { title: `E2E Take folds ${Date.now()}`, artist: '' }
	});
	expect(album.ok()).toBe(true);
	return ((await album.json()) as { id: string }).id;
}

async function seedFoldedSong(page: Page, albumId: string, label: string): Promise<FoldedSong> {
	const title = `Folds ${label} ${Date.now()}`;
	const songId = await seedSongPhoneSong(albumId, title, 1, FIRST_VERSION_TAKE_COUNT);
	const saved = await page.request.put(`/api/songs/${songId}`, {
		headers: await csrfHeaders(page),
		data: { lyrics: SECOND_VERSION_LYRICS }
	});
	expect(saved.ok()).toBe(true);
	const jobId = await seedRunningGenerationJob(songId, {
		progress: 0.5,
		takeIndex: 1,
		takeCount: SECOND_VERSION_TAKE_COUNT,
		phase: 'loading_model'
	});
	await completeGenerationJobWithoutEvent(jobId);
	const { generations } = await readSong(page, songId);
	const idsOf = (version: number) =>
		generations.filter((take) => take.version_number === version).map((take) => take.id);
	expect(idsOf(1)).toHaveLength(FIRST_VERSION_TAKE_COUNT);
	expect(idsOf(2)).toHaveLength(SECOND_VERSION_TAKE_COUNT);
	return { albumId, songId, title, v1: idsOf(1), v2: idsOf(2) };
}

async function openTakes(page: Page, song: FoldedSong): Promise<void> {
	await page.goto(`/album/${song.albumId}`);
	await workspace(page)
		.getByRole('button', { name: songEditorOpenLabel(song.title) })
		.click();
	await showTab(page, EDITOR_TAB_TAKES_LABEL);
	await expect(workspace(page).locator('.take-row')).toHaveCount(SECOND_VERSION_TAKE_COUNT);
}

// The phone has the tabs, the desktop shows both columns at once.
async function showTab(page: Page, label: string): Promise<void> {
	const tab = page.getByRole('tab', { name: nameStartingWith(label) });
	if (await tab.isVisible()) await tab.click();
}

const v1Row = (page: Page) =>
	workspace(page).getByRole('button', {
		name: foldedGroupLabel(1, FIRST_VERSION_TAKE_COUNT, 0),
		exact: false
	});
const v2Row = (page: Page) =>
	workspace(page).getByRole('button', { name: foldedGroupLabel(2, SECOND_VERSION_TAKE_COUNT, 0) });
const takeRow = (page: Page, id: string) => workspace(page).locator(`#take-${id}`);
const toolbar = (page: Page) => workspace(page).locator('.selection-toolbar');

async function tickTakes(page: Page, ...ids: string[]): Promise<void> {
	for (const id of ids)
		await takeRow(page, id)
			.locator('.play-btn')
			.click({ modifiers: ['ControlOrMeta'] });
}

async function expectSelected(page: Page, count: number): Promise<void> {
	await expect(toolbar(page)).toContainText(selectedCountLabel(count));
	await expect(toolbar(page).getByRole('button', { name: bulkDeleteLabel(count) })).toBeVisible();
}

// Holds the real Save's PUT until the test releases it.
async function holdSave(page: Page): Promise<() => Promise<void>> {
	let held: Route | null = null;
	let release: () => void = () => {};
	const arrived = new Promise<void>((resolve) => (release = resolve));
	await page.route(SONG_PUT, async (route) => {
		if (route.request().method() !== 'PUT') return route.continue();
		held = route;
		release();
	});
	return async () => {
		await arrived;
		await (held as Route | null)?.continue();
		await page.unroute(SONG_PUT);
	};
}

async function startSave(page: Page): Promise<void> {
	await showTab(page, EDITOR_TAB_EDIT_LABEL);
	await page.getByRole('textbox', { name: /^Lyrics/ }).fill(EDITED_LYRICS);
	await page.getByRole('button', { name: EDITOR_SAVE_ACCESSIBLE_LABEL }).click();
	await showTab(page, EDITOR_TAB_TAKES_LABEL);
}

let albumId: string;

test.beforeEach(async ({ page }) => {
	albumId = await createAlbum(page);
});

test.afterEach(async ({ page }) => {
	await archiveOwnedAlbum(page.request, albumId);
});

test.describe('folding the takes', { tag: ONLY_IN_SHELL.desktop }, () => {
	test('3/5 the current version is open, an earlier one unfolds in place and folds again by keyboard', async ({
		page
	}) => {
		const song = await seedFoldedSong(page, albumId, 'fold');
		await openTakes(page, song);
		const head = workspace(page).locator('.version-head');
		await expect(head).toContainText(currentVersionHeadLabel(2, SECOND_VERSION_TAKE_COUNT));
		await expect(workspace(page).getByText(EARLIER_VERSIONS_LABEL)).toBeVisible();
		await expect(v1Row(page)).toHaveAttribute('aria-expanded', 'false');

		await v1Row(page).click();
		await expect(v1Row(page)).toHaveAttribute('aria-expanded', 'true');
		await expect(workspace(page).locator('.take-row')).toHaveCount(
			SECOND_VERSION_TAKE_COUNT + FIRST_VERSION_TAKE_COUNT
		);

		await v1Row(page).press('Enter');
		await expect(v1Row(page)).toBeFocused();
		await expect(v1Row(page)).toHaveAttribute('aria-expanded', 'false');
		await expect(workspace(page).locator('.take-row')).toHaveCount(SECOND_VERSION_TAKE_COUNT);
	});

	test('16-18/21 folding clears the ticks inside the version and ends select mode when none is left', async ({
		page
	}) => {
		const song = await seedFoldedSong(page, albumId, 'ticks');
		await openTakes(page, song);
		await tickTakes(page, song.v2[0]);
		await expectSelected(page, 1);

		await v1Row(page).click();
		await tickTakes(page, song.v1[0], song.v1[1]);
		await expectSelected(page, 3);

		await v1Row(page).click();
		await expectSelected(page, 1);
		await v1Row(page).click();
		await expect(workspace(page).locator('.take-row.selected')).toHaveCount(1);

		await toolbar(page).getByRole('button', { name: 'Cancel' }).click();
		await tickTakes(page, song.v1[0]);
		await expectSelected(page, 1);
		await v1Row(page).click();
		await expect(toolbar(page)).toHaveCount(0);
	});

	test('23 Select all unkept covers the rendered takes only', async ({ page }) => {
		const song = await seedFoldedSong(page, albumId, 'all');
		await openTakes(page, song);
		await tickTakes(page, song.v2[0]);

		await toolbar(page).getByRole('button', { name: TAKE_SELECT_ALL_UNKEPT_LABEL }).click();

		await expectSelected(page, SECOND_VERSION_TAKE_COUNT);
		await v1Row(page).click();
		await expect(workspace(page).locator('.take-row.selected')).toHaveCount(
			SECOND_VERSION_TAKE_COUNT
		);
	});

	test('28 Delete sends only the rendered ticked takes and the folded ones survive', async ({
		page
	}) => {
		const song = await seedFoldedSong(page, albumId, 'delete');
		await openTakes(page, song);
		await tickTakes(page, song.v2[0]);
		await v1Row(page).click();
		await tickTakes(page, song.v1[0]);
		await v1Row(page).click();
		await expectSelected(page, 1);

		await toolbar(page)
			.getByRole('button', { name: bulkDeleteLabel(1) })
			.click();
		const dialog = page.getByRole('dialog', { name: bulkDeleteTitle(1) });
		await dialog.getByRole('button', { name: TAKE_DELETE_LABEL, exact: true }).click();

		await expect(takeRow(page, song.v2[0])).toHaveCount(0);
		expect(await takeIdsOf(page, song.songId)).toEqual([...song.v1, song.v2[1]].sort());
	});

	test('30 a Save that folds the version under an open dialog changes what Delete sends', async ({
		page
	}) => {
		const song = await seedFoldedSong(page, albumId, 'held');
		await openTakes(page, song);
		await v1Row(page).click();
		await tickTakes(page, song.v2[0], song.v1[0], song.v1[1]);
		await expectSelected(page, 3);
		const release = await holdSave(page);
		await startSave(page);
		await toolbar(page)
			.getByRole('button', { name: bulkDeleteLabel(3) })
			.click();
		await expect(page.getByRole('dialog', { name: bulkDeleteTitle(3) })).toBeVisible();

		await release();

		const dialog = page.getByRole('dialog', { name: bulkDeleteTitle(2) });
		await expect(dialog).toBeVisible();
		await dialog.getByRole('button', { name: TAKE_DELETE_LABEL, exact: true }).click();
		await expect(takeRow(page, song.v1[0])).toHaveCount(0);
		expect(await takeIdsOf(page, song.songId)).toEqual([...song.v2, song.v1[2]].sort());
	});

	test('31 nothing is sent when the Save folded away the only ticked take', async ({ page }) => {
		const song = await seedFoldedSong(page, albumId, 'only');
		await openTakes(page, song);
		await tickTakes(page, song.v2[0]);
		const release = await holdSave(page);
		await startSave(page);
		await toolbar(page)
			.getByRole('button', { name: bulkDeleteLabel(1) })
			.click();
		await expect(page.getByRole('dialog', { name: bulkDeleteTitle(1) })).toBeVisible();

		await release();

		await expect(page.getByRole('dialog')).toHaveCount(0);
		await expect(toolbar(page)).toHaveCount(0);
		expect(await takeIdsOf(page, song.songId)).toEqual([...song.v1, ...song.v2].sort());
	});

	test('33 a single Delete opened before the Save folded its take sends nothing', async ({
		page
	}) => {
		const song = await seedFoldedSong(page, albumId, 'single');
		await openTakes(page, song);
		const release = await holdSave(page);
		await startSave(page);
		await takeRow(page, song.v2[0]).getByRole('button', { name: TAKE_OVERFLOW_LABEL }).click();
		await page.getByRole('button', { name: TAKE_DELETE_LABEL, exact: true }).click();

		await release();
		await expect(v2Row(page)).toBeVisible();
		await page.getByRole('dialog').getByRole('button', { name: TAKE_DELETE_LABEL }).click();

		await expect(page.getByRole('dialog')).toHaveCount(0);
		expect(await takeIdsOf(page, song.songId)).toEqual([...song.v1, ...song.v2].sort());
	});

	test('36 folds and ticks reset on another song and survive a Back and Forward', async ({
		page
	}) => {
		const song = await seedFoldedSong(page, albumId, 'a');
		const other = await seedFoldedSong(page, albumId, 'b');
		await openTakes(page, song);
		await v1Row(page).click();
		await tickTakes(page, song.v1[0]);

		await page.goBack();
		await page.goForward();
		await expect(v1Row(page)).toHaveAttribute('aria-expanded', 'true');
		await expectSelected(page, 1);

		await page.goBack();
		await workspace(page)
			.getByRole('button', { name: songEditorOpenLabel(other.title) })
			.click();
		await expect(v1Row(page)).toHaveAttribute('aria-expanded', 'false');
		await page.goBack();
		await workspace(page)
			.getByRole('button', { name: songEditorOpenLabel(song.title) })
			.click();
		await expect(v1Row(page)).toHaveAttribute('aria-expanded', 'false');
		await expect(toolbar(page)).toHaveCount(0);
	});
});

test.describe('folding the takes on the phone', { tag: ONLY_IN_SHELL.mobile }, () => {
	test('20/38 folding clears the ticks, and an unfold and a tick survive the Edit tab', async ({
		page
	}) => {
		const song = await seedFoldedSong(page, albumId, 'phone');
		await openTakes(page, song);
		await v1Row(page).click();
		await tickTakes(page, song.v2[0], song.v1[0]);
		await expectSelected(page, 2);

		await showTab(page, EDITOR_TAB_EDIT_LABEL);
		await showTab(page, EDITOR_TAB_TAKES_LABEL);
		await expect(v1Row(page)).toHaveAttribute('aria-expanded', 'true');
		await expectSelected(page, 2);

		await v1Row(page).click();
		await expectSelected(page, 1);
	});
});

test.describe('Imported (Q1 a)', { tag: ONLY_IN_SHELL.desktop }, () => {
	test('24/47 starts open when no version holds a take and stays folded once folded by hand', async ({
		page
	}) => {
		const songTitle = `Folds imported ${Date.now()}`;
		await seedTakeStripSong(albumId, songTitle, 2);
		await page.goto(`/album/${albumId}`);
		await workspace(page)
			.getByRole('button', { name: songEditorOpenLabel(songTitle) })
			.click();
		const imported = workspace(page).getByRole('button', { name: foldedGroupLabel(null, 2, 0) });
		await expect(workspace(page).locator('.take-row')).toHaveCount(2);

		await tickTakes(page, ...(await takeIds(page)));
		await imported.click();
		await expect(toolbar(page)).toHaveCount(0);
		await showTab(page, EDITOR_TAB_EDIT_LABEL);
		await showTab(page, EDITOR_TAB_TAKES_LABEL);
		await expect(imported).toHaveAttribute('aria-expanded', 'false');
	});
});

async function takeIds(page: Page): Promise<string[]> {
	const ids = await workspace(page)
		.locator('.take-row')
		.evaluateAll((rows) => rows.map((row) => row.id.replace('take-', '')));
	return ids;
}

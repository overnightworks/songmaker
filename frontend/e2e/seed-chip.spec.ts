// A take's Use seed puts „Seed · take N ×“ at the Generate button (#1928, S5, S6, N2):
// Generate, Repaint and Cover send the seed and it stays until × or a song switch.
// The job endpoints are answered here, so no worker is needed; a job that is
// answered stays running, so each press that starts one gets its own cell.
// Both projects run it: 390 px (the chip stands in the Edit tab's Generate bar)
// and 1440 px (the header).

import { expect, test, type Locator, type Page } from '@playwright/test';
import {
	EDITOR_GENERATE_LABEL,
	EDITOR_TAB_EDIT_LABEL,
	EDITOR_TAB_TAKES_LABEL,
	openNowPlayingLabel,
	songEditorOpenLabel,
	TAKE_OVERFLOW_LABEL,
	TAKE_REPAINT_LABEL
} from '../src/lib/constants';
import { SEED_CHIP_CLEAR_LABEL, TAKE_USE_SEED_LABEL } from '../src/lib/constants/take-task';
import { csrfHeaders, nameStartingWith, ONLY_IN_SHELL, workspace } from './helpers';
import { showTab } from './foldedSong';
import { archiveOwnedAlbum, seedSongPhoneSong } from './seed';

const TAKE_COUNT = 3;
const FIRST_TAKE_SEED = 4127730;
const OTHER_TAKE_SEED = 52000;
const QUEUED_JOB = { id: 'e2e-seed-job', type: 'generate', status: 'queued', progress: 0 };
const GENERATE_ROUTE = /\/api\/songs\/[^/]+\/generate$/;
const REPAINT_ROUTE = /\/api\/generations\/[^/]+\/repaint$/;

interface Songs {
	albumId: string;
	title: string;
	otherTitle: string;
}

let albumId: string;

test.beforeEach(async ({ page }) => {
	const album = await page.request.post('/api/albums', {
		headers: await csrfHeaders(page),
		data: { title: `E2E Seed chip ${Date.now()}`, artist: '' }
	});
	expect(album.ok()).toBe(true);
	albumId = ((await album.json()) as { id: string }).id;
});

test.afterEach(async ({ page }) => {
	await page.unrouteAll({ behavior: 'ignoreErrors' });
	await archiveOwnedAlbum(page.request, albumId);
});

async function seedSongs(): Promise<Songs> {
	const stamp = Date.now();
	const title = `Seed chip ${stamp}`;
	const otherTitle = `Seed chip other ${stamp}`;
	await seedSongPhoneSong(albumId, title, 1, TAKE_COUNT, FIRST_TAKE_SEED);
	await seedSongPhoneSong(albumId, otherTitle, 1, TAKE_COUNT, OTHER_TAKE_SEED);
	return { albumId, title, otherTitle };
}

async function openSong(page: Page, title: string): Promise<void> {
	await workspace(page)
		.getByRole('button', { name: songEditorOpenLabel(title) })
		.click();
	await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
}

async function openOwnSong(page: Page): Promise<Songs> {
	const songs = await seedSongs();
	await page.goto(`/album/${albumId}`);
	await openSong(page, songs.title);
	return songs;
}

async function useSeedOfFirstTake(page: Page): Promise<void> {
	await showTab(page, EDITOR_TAB_TAKES_LABEL);
	await workspace(page)
		.locator('.take-row')
		.first()
		.getByRole('button', { name: TAKE_OVERFLOW_LABEL })
		.click();
	await page
		.getByRole('dialog', { name: TAKE_OVERFLOW_LABEL })
		.getByRole('button', { name: nameStartingWith(TAKE_USE_SEED_LABEL) })
		.click();
}

function chip(page: Page): Locator {
	return page.locator('.seed-chip');
}

async function showChip(page: Page, takeNumber: number): Promise<void> {
	await showTab(page, EDITOR_TAB_EDIT_LABEL);
	await expect(chip(page)).toHaveText(new RegExp(`^\\s*Seed · take ${takeNumber}`));
}

async function pressGenerate(page: Page): Promise<Record<string, unknown>> {
	await page.route(GENERATE_ROUTE, (route) => route.fulfill({ json: QUEUED_JOB }));
	const request = page.waitForRequest(GENERATE_ROUTE);
	await page.getByRole('button', { name: EDITOR_GENERATE_LABEL, exact: true }).click();
	return (await request).postDataJSON() as Record<string, unknown>;
}

test('Use seed puts the chip at Generate and Generate sends the seed while the chip stays (S5, S6)', async ({
	page
}) => {
	await openOwnSong(page);
	await useSeedOfFirstTake(page);
	await showChip(page, 1);
	expect(await pressGenerate(page)).toMatchObject({ seed: FIRST_TAKE_SEED });
	await expect(chip(page)).toBeVisible();
});

test('× takes the chip away and the next Generate sends no seed (S6)', async ({ page }) => {
	await openOwnSong(page);
	await useSeedOfFirstTake(page);
	await showChip(page, 1);
	await chip(page).getByRole('button', { name: SEED_CHIP_CLEAR_LABEL }).click();
	await expect(chip(page)).toHaveCount(0);
	expect(await pressGenerate(page)).not.toHaveProperty('seed');
});

test('A Repaint from the card sends the seed and the chip stays (S6)', async ({ page }) => {
	await openOwnSong(page);
	await useSeedOfFirstTake(page);
	await showTab(page, EDITOR_TAB_TAKES_LABEL);
	await workspace(page)
		.locator('.take-row')
		.first()
		.getByRole('button', { name: TAKE_OVERFLOW_LABEL })
		.click();
	await page
		.getByRole('dialog', { name: TAKE_OVERFLOW_LABEL })
		.getByRole('button', { name: TAKE_REPAINT_LABEL })
		.click();
	await expect(page.locator('.task')).toContainText('seed: from take');
	await page.route(REPAINT_ROUTE, (route) => route.fulfill({ json: QUEUED_JOB }));
	const request = page.waitForRequest(REPAINT_ROUTE);
	await page.locator('.task-foot button').click();
	expect(((await request).postDataJSON() as Record<string, unknown>).seed).toBe(FIRST_TAKE_SEED);
	await showChip(page, 1);
});

test('A song switch clears the chip and coming back shows none (D5)', async ({ page }) => {
	const songs = await openOwnSong(page);
	await useSeedOfFirstTake(page);
	await showChip(page, 1);
	await page.goBack();
	await openSong(page, songs.otherTitle);
	await showTab(page, EDITOR_TAB_EDIT_LABEL);
	await expect(chip(page)).toHaveCount(0);
	await page.goBack();
	await openSong(page, songs.title);
	await showTab(page, EDITOR_TAB_EDIT_LABEL);
	await expect(chip(page)).toHaveCount(0);
});

test(
	"Now Playing's Use seed opens the take's own song with the chip, not the song that was open (N2, D1)",
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }) => {
		const songs = await seedSongs();
		await page.goto(`/album/${albumId}`);
		await openSong(page, songs.otherTitle);
		await workspace(page).locator('.take-row').first().locator('.play-btn').click();
		await page.goBack();
		await openSong(page, songs.title);
		await page
			.getByRole('contentinfo')
			.getByRole('button', { name: new RegExp(`${openNowPlayingLabel('')}$`) })
			.click();
		await page
			.locator('.np-take')
			.getByRole('button', { name: nameStartingWith(TAKE_USE_SEED_LABEL) })
			.click();
		await expect(page.getByRole('heading', { name: songs.otherTitle, exact: true })).toBeVisible();
		await expect(chip(page)).toHaveText(new RegExp(`^\\s*Seed · take 1`));
	}
);

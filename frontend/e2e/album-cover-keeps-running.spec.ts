// A cover suggestion keeps running when the person leaves (frames
// C6-C9 of docs/design/album-browsing.html §(i)): leaving the cover editor
// stops nothing, a run that finished while away waits as an unused suggestion,
// and only × stops a run. CI's stack mounts no image route, so the run is
// seeded in the database (scripts/seed_e2e_job_states.py). Each test makes a
// fresh album of its own and archives it afterwards.

import { expect, test, type Locator, type Page } from '@playwright/test';
import {
	ALBUM_COVER_EDITING_CLOSE_LABEL,
	ALBUM_COVER_EDITING_LABEL,
	ALBUM_COVER_SUGGESTING_LABEL,
	albumCoverSuggestionAlt
} from '../src/lib/constants';
import { csrfHeaders, HOME_PATH, shellOf, workspace } from './helpers';
import { archiveOwnedAlbum } from './seed';
import { completeCoverJob, seedRunningCoverJob } from './seed-cover';

interface FreshAlbum {
	id: string;
	title: string;
}

interface CoverSuggestionsReading {
	job: { id: string; status: string } | null;
	suggestions: { id: string }[];
}

const RUN_STARTED_SECONDS_AGO = 90;
const ELAPSED_TIME_SLACK_SECONDS = 20;
const SECONDS_PER_MINUTE = 60;

// The running slot names the time since the server started the run (E3), and
// it is a status, not a progress bar: the run has no percentage.
async function expectElapsedTimeSinceStart(editing: Locator): Promise<void> {
	const making = editing.getByRole('status').filter({ hasText: ALBUM_COVER_SUGGESTING_LABEL });
	await expect(making).toBeVisible();
	await expect(editing.getByRole('progressbar')).toHaveCount(0);
	const [, minutes = '', secondsPart = ''] =
		(await making.textContent())?.match(/(\d+):(\d{2})/) ?? [];
	expect(minutes).not.toBe('');
	const seconds = Number(minutes) * SECONDS_PER_MINUTE + Number(secondsPart);
	expect(seconds).toBeGreaterThanOrEqual(RUN_STARTED_SECONDS_AGO);
	expect(seconds).toBeLessThanOrEqual(RUN_STARTED_SECONDS_AGO + ELAPSED_TIME_SLACK_SECONDS);
}

async function createFreshAlbum(page: Page, shell: string): Promise<FreshAlbum> {
	const title = `E2E Cover Keeps Running ${shell} ${Date.now()}`;
	const response = await page.request.post('/api/albums', {
		headers: await csrfHeaders(page),
		data: { title, artist: '' }
	});
	expect(response.ok()).toBe(true);
	const { id } = (await response.json()) as { id: string };
	return { id, title };
}

async function readSuggestions(page: Page, albumId: string): Promise<CoverSuggestionsReading> {
	const response = await page.request.get(`/api/albums/${albumId}/cover-suggestions`);
	expect(response.ok()).toBe(true);
	return (await response.json()) as CoverSuggestionsReading;
}

async function openCoverEditor(page: Page, album: FreshAlbum) {
	await page.goto(`/album/${album.id}`);
	await workspace(page).getByRole('button', { name: 'Add cover' }).click();
	return workspace(page).getByRole('group', { name: ALBUM_COVER_EDITING_LABEL });
}

async function withFreshAlbum(
	page: Page,
	shell: string,
	flow: (album: FreshAlbum) => Promise<void>
): Promise<void> {
	const album = await createFreshAlbum(page, shell);
	try {
		await flow(album);
	} finally {
		await archiveOwnedAlbum(page.request, album.id);
	}
}

test('leaving the cover editor and coming back finds the suggestion still running', async ({
	page
}, testInfo) => {
	await withFreshAlbum(page, shellOf(testInfo), async (album) => {
		const jobId = await seedRunningCoverJob(album.id, {
			startedSecondsAgo: RUN_STARTED_SECONDS_AGO
		});
		const editing = await openCoverEditor(page, album);
		await expectElapsedTimeSinceStart(editing);

		await page.goto(HOME_PATH);
		await expect
			.poll(async () => (await readSuggestions(page, album.id)).job)
			.toMatchObject({
				id: jobId,
				status: 'running'
			});

		const reopened = await openCoverEditor(page, album);
		await expectElapsedTimeSinceStart(reopened);
		expect((await readSuggestions(page, album.id)).job).toMatchObject({ status: 'running' });
	});
});

test('a suggestion that finished while away waits when the editor opens again', async ({
	page
}, testInfo) => {
	await withFreshAlbum(page, shellOf(testInfo), async (album) => {
		const jobId = await seedRunningCoverJob(album.id);
		const editing = await openCoverEditor(page, album);
		await expect(
			editing.getByRole('status').filter({ hasText: ALBUM_COVER_SUGGESTING_LABEL })
		).toBeVisible();
		await page.goto(HOME_PATH);

		await completeCoverJob(jobId);
		const reopened = await openCoverEditor(page, album);

		await expect(
			reopened.getByRole('img', { name: albumCoverSuggestionAlt(album.title) })
		).toBeVisible();
		await expect(reopened.getByRole('progressbar')).toHaveCount(0);
		await expect(reopened.getByText(/^1 \/ 1/)).toBeVisible();
		expect((await readSuggestions(page, album.id)).suggestions).toHaveLength(1);
	});
});

test('× stops the running suggestion', async ({ page }, testInfo) => {
	await withFreshAlbum(page, shellOf(testInfo), async (album) => {
		const jobId = await seedRunningCoverJob(album.id);
		const editing = await openCoverEditor(page, album);
		await expect(
			editing.getByRole('status').filter({ hasText: ALBUM_COVER_SUGGESTING_LABEL })
		).toBeVisible();

		await editing.getByRole('button', { name: ALBUM_COVER_EDITING_CLOSE_LABEL }).click();

		await expect(editing).toHaveCount(0);
		await expect
			.poll(async () => (await readSuggestions(page, album.id)).job)
			.toMatchObject({ id: jobId, status: 'cancelled' });
		expect((await readSuggestions(page, album.id)).suggestions).toHaveLength(0);
	});
});

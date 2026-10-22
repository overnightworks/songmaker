// A cover suggestion keeps running when the person leaves (#1133, #1799; frames
// C6-C9 of docs/design/album-browsing.html §(i)): leaving the cover editor
// stops nothing, a run that finished while away waits as an unused suggestion,
// and only × stops a run. CI's stack mounts no image route, so the run is
// seeded in the database (scripts/seed_e2e_job_states.py). Each test makes a
// fresh album of its own and archives it afterwards.

import { expect, test, type Page } from '@playwright/test';
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
		await expect(
			editing.getByRole('progressbar', { name: ALBUM_COVER_SUGGESTING_LABEL })
		).toBeVisible();

		await page.goto(HOME_PATH);
		await expect
			.poll(async () => (await readSuggestions(page, album.id)).job)
			.toMatchObject({
				id: jobId,
				status: 'running'
			});

		const reopened = await openCoverEditor(page, album);
		await expect(
			reopened.getByRole('progressbar', { name: ALBUM_COVER_SUGGESTING_LABEL })
		).toBeVisible();
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
			editing.getByRole('progressbar', { name: ALBUM_COVER_SUGGESTING_LABEL })
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
			editing.getByRole('progressbar', { name: ALBUM_COVER_SUGGESTING_LABEL })
		).toBeVisible();

		await editing.getByRole('button', { name: ALBUM_COVER_EDITING_CLOSE_LABEL }).click();

		await expect(editing).toHaveCount(0);
		await expect
			.poll(async () => (await readSuggestions(page, album.id)).job)
			.toMatchObject({ id: jobId, status: 'cancelled' });
		expect((await readSuggestions(page, album.id)).suggestions).toHaveLength(0);
	});
});

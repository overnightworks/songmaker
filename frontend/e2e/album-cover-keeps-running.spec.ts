// A cover suggestion keeps running when the person leaves (frames
// C6-C9 of docs/design/album-browsing.html §(i)): leaving the cover editor
// stops nothing, a run that finished while away waits as an unused suggestion,
// and only × stops a run. The closed cover says so (E2, C8): a ring and the
// time while it runs, "● n waiting" until USE, Upload or × discards them, and
// a second device sees the same once it opens, reloads or returns to the page
// (E6). CI's stack mounts no image route, so the run is
// seeded in the database (scripts/seed_e2e_job_states.py). Each test makes a
// fresh album of its own and archives it afterwards.

import {
	expect,
	test,
	type Browser,
	type Locator,
	type Page,
	type TestInfo
} from '@playwright/test';
import {
	ALBUM_COVER_EDITING_CLOSE_LABEL,
	ALBUM_COVER_EDITING_LABEL,
	ALBUM_COVER_SUGGESTING_LABEL,
	albumCoverSuggestionAlt
} from '../src/lib/constants';
import { albumCoverWaitingText } from '../src/lib/constants/album-cover-mark';
import { csrfHeaders, HOME_PATH, shellOf, workspace } from './helpers';
import { archiveOwnedAlbum, BASE_URL, STORAGE_STATE_FILE } from './seed';
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

// The closed cover is one button whose name says what it carries; the mark at
// its foot shows the ring and the time, or the waiting count.
function closedCover(page: Page, state: string): Locator {
	return workspace(page).getByRole('button', { name: new RegExp(`^(Add|Edit) cover · ${state}`) });
}

async function expectRunningMarkWithTime(page: Page): Promise<void> {
	const cover = closedCover(page, 'making a suggestion');
	await expect(cover).toBeVisible();
	const mark = cover.locator('.cover-mark');
	await expect(mark).toHaveText(/\d+:\d{2}/);
	const [, minutes = '', secondsPart = ''] =
		(await mark.textContent())?.match(/(\d+):(\d{2})/) ?? [];
	const seconds = Number(minutes) * SECONDS_PER_MINUTE + Number(secondsPart);
	expect(seconds).toBeGreaterThanOrEqual(RUN_STARTED_SECONDS_AGO);
	expect(seconds).toBeLessThanOrEqual(RUN_STARTED_SECONDS_AGO + ELAPSED_TIME_SLACK_SECONDS);
	expect(await cover.getAttribute('aria-label')).not.toMatch(/\d:\d\d/);
}

async function expectWaitingMark(page: Page, count: number): Promise<void> {
	const cover = closedCover(page, `${count} waiting`);
	await expect(cover).toBeVisible();
	await expect(cover.locator('.cover-mark')).toHaveText(albumCoverWaitingText(count));
}

async function expectNoMark(page: Page): Promise<void> {
	await expect(workspace(page).getByRole('button', { name: /^(Add|Edit) cover$/ })).toBeVisible();
	await expect(workspace(page).locator('.cover-mark')).toHaveCount(0);
}

// A second device: its own context, the same account, the same width.
async function withSecondDevice(
	browser: Browser,
	testInfo: TestInfo,
	flow: (second: Page) => Promise<void>
): Promise<void> {
	const { viewport, isMobile, hasTouch } = testInfo.project.use;
	const context = await browser.newContext({
		baseURL: BASE_URL,
		storageState: STORAGE_STATE_FILE,
		viewport,
		isMobile,
		hasTouch
	});
	try {
		await flow(await context.newPage());
	} finally {
		await context.close();
	}
}

test('a running suggestion shows on the closed cover, after a reload, and on a second device once it returns', async ({
	page,
	browser
}, testInfo) => {
	await withFreshAlbum(page, shellOf(testInfo), async (album) => {
		await withSecondDevice(browser, testInfo, async (second) => {
			await second.goto(`/album/${album.id}`);
			await expectNoMark(second);

			await seedRunningCoverJob(album.id, { startedSecondsAgo: RUN_STARTED_SECONDS_AGO });
			await page.goto(`/album/${album.id}`);
			await expectRunningMarkWithTime(page);
			await page.reload();
			await expectRunningMarkWithTime(page);

			await expectNoMark(second);
			await second.evaluate(() => window.dispatchEvent(new Event('focus')));
			await expectRunningMarkWithTime(second);
		});
	});
});

test('a second device that opens the album page sees the running suggestion', async ({
	page,
	browser
}, testInfo) => {
	await withFreshAlbum(page, shellOf(testInfo), async (album) => {
		await seedRunningCoverJob(album.id, { startedSecondsAgo: RUN_STARTED_SECONDS_AGO });
		await withSecondDevice(browser, testInfo, async (second) => {
			await second.goto(`/album/${album.id}`);
			await expectRunningMarkWithTime(second);
		});
	});
});

test('after it finished the cover says "● 1 waiting", a tap opens the editor on it, and × clears the mark', async ({
	page
}, testInfo) => {
	await withFreshAlbum(page, shellOf(testInfo), async (album) => {
		const jobId = await seedRunningCoverJob(album.id);
		await page.goto(`/album/${album.id}`);
		await expect(closedCover(page, 'making a suggestion')).toBeVisible();

		await completeCoverJob(jobId);
		await expectWaitingMark(page, 1);
		await page.reload();
		await expectWaitingMark(page, 1);

		await closedCover(page, '1 waiting').click();
		const editing = workspace(page).getByRole('group', { name: ALBUM_COVER_EDITING_LABEL });
		await expect(
			editing.getByRole('img', { name: albumCoverSuggestionAlt(album.title) })
		).toBeVisible();
		await editing.getByRole('button', { name: ALBUM_COVER_EDITING_CLOSE_LABEL }).click();

		await expect(editing).toHaveCount(0);
		await expectNoMark(page);
		await page.reload();
		await expectNoMark(page);
	});
});

test('Use clears the waiting mark', async ({ page }, testInfo) => {
	await withFreshAlbum(page, shellOf(testInfo), async (album) => {
		const jobId = await seedRunningCoverJob(album.id);
		await completeCoverJob(jobId);
		await page.goto(`/album/${album.id}`);
		await expectWaitingMark(page, 1);

		await closedCover(page, '1 waiting').click();
		const editing = workspace(page).getByRole('group', { name: ALBUM_COVER_EDITING_LABEL });
		await editing.getByRole('button', { name: 'Use', exact: true }).click();

		await expect(editing).toHaveCount(0);
		await expect(workspace(page).getByRole('button', { name: /^Edit cover$/ })).toBeVisible();
		await expect(workspace(page).locator('.cover-mark')).toHaveCount(0);
	});
});

// The version chip next to Lyrics opens the song's versions, and tapping one
// loads it as the draft (issue #1262, #1245 rules 1-6 and 9): a sheet on the
// phone, a popover on the desktop, a confirm before a dirty draft is
// replaced, Undo in the toast, and Generate saving the loaded text as the next
// version while the loaded one stays as it was.
//
// CI's e2e stack runs no ACE-Step worker, so the song's takes are seeded
// directly against the database (scripts/seed_e2e_job_states.py), and
// `/health` reports one worker online for this page only, the way
// song-phone.spec.ts stands in for a real worker's heartbeat. With no worker
// the generate request itself is refused; the flow only needs the version
// Generate saved before it.

import { expect, test, type Locator, type Page, type TestInfo } from '@playwright/test';
import {
	DIALOG_CANCEL_LABEL,
	EDITOR_GENERATE_MODE_LABELS,
	EDITOR_TAB_EDIT_LABEL,
	TOAST_UNDO_LABEL,
	VERSION_REPLACE_DRAFT_CONFIRM_LABEL,
	VERSION_REPLACE_DRAFT_TITLE,
	VERSIONS_SHEET_LABEL,
	versionChipLabel,
	versionLoadedFromLabel,
	versionLoadedToastLabel,
	versionsChipAccessibleLabel
} from '../src/lib/constants';
import type { VersionItem } from '../src/lib/api/types';
import { csrfHeaders, nameStartingWith, shellOf, workspace } from './helpers';
import {
	completeGenerationJobWithoutEvent,
	readSeededLibrary,
	runMarker,
	seedRunningGenerationJob,
	seedSongPhoneSong
} from './seed';

const SONG_TITLE = 'Song Versions';
// seedSongPhoneSong's own first-version lyrics, which v1 keeps.
const FIRST_VERSION_LYRICS = 'Song Phone Takes seeded lyrics';
const SECOND_VERSION_LYRICS = 'Rain on the window, the city asleep';
const UNSAVED_LINE = 'a line nobody saved';
const TOAST_DISMISS_LABEL = 'Dismiss';

interface SeededVersions {
	songId: string;
	title: string;
	albumId: string;
}

/**
 * A song with two versions: v1 from the seed with its take, v2 saved over it
 * with other lyrics -- with a take of its own unless `secondVersionTaken` is
 * false, which leaves the take-less latest version every plain Save makes.
 */
async function seedTwoVersions(
	page: Page,
	testInfo: TestInfo,
	secondVersionTaken = true
): Promise<SeededVersions> {
	const library = readSeededLibrary();
	// A per-attempt title: a CI retry re-seeding the same title into the same
	// shared album would leave two rows starting with it.
	const title = `${SONG_TITLE} ${shellOf(testInfo)} ${runMarker()}`;
	const songId = await seedSongPhoneSong(library.songPhoneAlbumId, title, 1, 1);
	const saved = await page.request.put(`/api/songs/${songId}`, {
		headers: await csrfHeaders(page),
		data: { lyrics: SECOND_VERSION_LYRICS }
	});
	expect(saved.ok(), `Saving v2 failed: ${await saved.text()}`).toBeTruthy();
	if (!secondVersionTaken) return { songId, title, albumId: library.songPhoneAlbumId };
	const jobId = await seedRunningGenerationJob(songId, {
		progress: 0.5,
		takeIndex: 1,
		takeCount: 1,
		phase: 'loading_model'
	});
	await completeGenerationJobWithoutEvent(jobId);
	return { songId, title, albumId: library.songPhoneAlbumId };
}

async function reportOneWorkerOnline(page: Page): Promise<void> {
	await page.route('**/health', async (route) => {
		const response = await route.fetch();
		const body = (await response.json()) as Record<string, unknown>;
		await route.fulfill({
			response,
			json: { ...body, acestep_workers_online: 1, acestep_workers_total: 1 }
		});
	});
}

// Through the album's track list, the way song-phone.spec.ts opens a song it
// is about to edit.
async function openSongEditor(page: Page, song: SeededVersions): Promise<void> {
	await page.goto(`/album/${song.albumId}`);
	await workspace(page)
		.getByRole('button', { name: nameStartingWith(song.title) })
		.click();
	const editTab = page.getByRole('tab', { name: EDITOR_TAB_EDIT_LABEL, exact: true });
	if (await editTab.isVisible()) await editTab.click();
	await expect(lyricsField(page)).toHaveValue(SECOND_VERSION_LYRICS);
}

async function readVersions(page: Page, songId: string): Promise<VersionItem[]> {
	const response = await page.request.get(`/api/songs/${songId}/versions`);
	expect(response.ok()).toBeTruthy();
	return (await response.json()) as VersionItem[];
}

function lyricsField(page: Page): Locator {
	return page.getByRole('textbox', { name: /^Lyrics/ });
}

function versionChip(page: Page): Locator {
	return workspace(page).getByRole('button', {
		name: nameStartingWith(versionsChipAccessibleLabel(''))
	});
}

function versionsSheet(page: Page): Locator {
	return page.getByRole('dialog', { name: VERSIONS_SHEET_LABEL });
}

function versionRow(page: Page, versionNumber: number): Locator {
	return versionsSheet(page).getByRole('button', { name: nameStartingWith(`v${versionNumber} `) });
}

function loadedToast(page: Page): Locator {
	return page.getByRole('alert').filter({ hasText: versionLoadedToastLabel(1) });
}

function replaceDraftDialog(page: Page): Locator {
	return page.getByRole('dialog', { name: VERSION_REPLACE_DRAFT_TITLE });
}

async function tapVersion(page: Page, versionNumber: number): Promise<void> {
	await versionChip(page).click();
	await expect(versionsSheet(page)).toBeVisible();
	await versionRow(page, versionNumber).click();
}

test.describe('the versions of a song', () => {
	for (const { secondVersionTaken, v2 } of [
		{ secondVersionTaken: true, v2: 'v2 with a take' },
		{ secondVersionTaken: false, v2: 'a take-less v2' }
	]) {
		test(`tapping v1 loads it as the draft, and Generate makes v3 while v1 and ${v2} stay as they were`, async ({
			page
		}, testInfo) => {
			await reportOneWorkerOnline(page);
			const song = await seedTwoVersions(page, testInfo, secondVersionTaken);
			await openSongEditor(page, song);
			await expect(versionChip(page)).toHaveText(versionChipLabel(2, false));

			await tapVersion(page, 1);

			await expect(versionsSheet(page)).toBeHidden();
			await expect(lyricsField(page)).toHaveValue(FIRST_VERSION_LYRICS);
			await expect(workspace(page).getByText(versionLoadedFromLabel(1))).toBeVisible();
			await expect(versionChip(page)).toHaveText(versionChipLabel(2, true));
			await expect(loadedToast(page)).toBeVisible();
			expect((await readVersions(page, song.songId)).map((v) => v.version_number)).toEqual([2, 1]);

			// On the phone the toast stands over the Generate bar.
			await loadedToast(page).getByRole('button', { name: TOAST_DISMISS_LABEL }).click();
			const queued = page.waitForResponse(
				(response) =>
					response.url().endsWith(`/api/songs/${song.songId}/generate`) &&
					response.request().method() === 'POST'
			);
			await workspace(page)
				.getByRole('button', { name: nameStartingWith(EDITOR_GENERATE_MODE_LABELS.generate) })
				.click();
			// The worker-less stack may refuse the job itself; what counts here is
			// the version Generate saved before it asked for one.
			await queued;

			await expect(versionChip(page)).toHaveText(versionChipLabel(3, false));
			await expect(workspace(page).getByText(versionLoadedFromLabel(1))).toBeHidden();
			const [newest, second, first] = await readVersions(page, song.songId);
			expect(newest?.version_number).toBe(3);
			expect(newest?.lyrics).toBe(FIRST_VERSION_LYRICS);
			expect(second?.lyrics).toBe(SECOND_VERSION_LYRICS);
			expect(first?.version_number).toBe(1);
			expect(first?.lyrics).toBe(FIRST_VERSION_LYRICS);
		});
	}

	test('a dirty draft is asked about first; Cancel keeps it, Undo after Replace brings it back, Back closes the sheet', async ({
		page
	}, testInfo) => {
		const song = await seedTwoVersions(page, testInfo);
		await openSongEditor(page, song);
		const editedLyrics = `${SECOND_VERSION_LYRICS}\n${UNSAVED_LINE}`;
		await lyricsField(page).fill(editedLyrics);
		await expect(versionChip(page)).toHaveText(versionChipLabel(2, true));

		await tapVersion(page, 1);
		await expect(replaceDraftDialog(page)).toBeVisible();
		await replaceDraftDialog(page).getByRole('button', { name: DIALOG_CANCEL_LABEL }).click();
		await expect(replaceDraftDialog(page)).toBeHidden();
		await expect(versionsSheet(page)).toBeVisible();
		await expect(lyricsField(page)).toHaveValue(editedLyrics);

		await versionRow(page, 1).click();
		await replaceDraftDialog(page)
			.getByRole('button', { name: VERSION_REPLACE_DRAFT_CONFIRM_LABEL })
			.click();
		await expect(versionsSheet(page)).toBeHidden();
		await expect(lyricsField(page)).toHaveValue(FIRST_VERSION_LYRICS);

		await loadedToast(page).getByRole('button', { name: TOAST_UNDO_LABEL }).click();
		await expect(lyricsField(page)).toHaveValue(editedLyrics);
		await expect(workspace(page).getByText(versionLoadedFromLabel(1))).toBeHidden();

		await versionChip(page).click();
		await expect(versionsSheet(page)).toBeVisible();
		await page.goBack();
		await expect(versionsSheet(page)).toBeHidden();
		await expect(lyricsField(page)).toHaveValue(editedLyrics);
		expect((await readVersions(page, song.songId)).map((v) => v.version_number)).toEqual([2, 1]);
	});
});

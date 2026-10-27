// The version chip next to Lyrics opens the song's versions, and tapping one
// loads it as the draft (issue #1262, #1245 rules 1-6 and 9): a sheet on the
// phone, a popover on the desktop, a confirm before a dirty draft is
// replaced, Undo in the toast, and Generate saving the loaded text as the next
// version while the loaded one stays as it was. "Open vN" on a take group and
// in Now Playing loads a version the same way, and imported takes say they
// have no version (issue #1273, #1245 rules 7-8). A version is deleted from
// its row in the sheet, behind a confirm that names its takes and the album
// pick among them (issue #1284, #1245 rule 10). A draft equal to a saved
// version loads the next one without asking, tapping the version the draft
// already holds changes nothing and keeps its Undo, the delete confirm says an
// unsaved draft goes too, and the sheet stands over the whole page: the
// phone's backdrop dims all of it (issue #1286). Leaving an untouched load
// asks nothing, a peek at the sheet keeps the Undo, the Undo toast keeps its
// time while the sheet is open, and the delete confirm says what an untouched
// load loses (issue #1296). An untouched load is not called unsaved, the
// delete confirm says a pending Undo goes too, an imported take is named as
// one, Open on the current version answers, and Open in Now Playing after
// arriving from the album keeps the take where it stood (issue #1300). The
// page's clock is held still once the editor shows, so a load's Undo lasts
// until a test moves the clock on.
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
	EDITOR_GENERATE_LABEL,
	EDITOR_UNSAVED_TITLE,
	EDITOR_TAB_EDIT_LABEL,
	EDITOR_TAB_TAKES_LABEL,
	NOW_PLAYING_IMPORTED_TAKE_NO_LYRICS,
	TOAST_UNDO_LABEL,
	TRANSPORT_PAUSE_LABEL,
	TRANSPORT_PLAY_LABEL,
	VERSION_DELETE_CONFIRM_LABEL,
	VERSION_DELETE_DRAFT_GOES,
	VERSION_DELETE_LOAD_UNDO_GOES,
	VERSION_REPLACE_DRAFT_CONFIRM_LABEL,
	VERSION_REPLACE_DRAFT_TITLE,
	VERSIONS_SHEET_CLOSE_LABEL,
	VERSIONS_SHEET_LABEL,
	versionAlreadyTheDraftLabel,
	versionChipLabel,
	versionDeleteLabel,
	versionDeleteLoadedDraftGoes,
	versionDeleteLoadedDraftReplacedBy,
	versionDeleteTitle,
	versionLoadedFromLabel,
	versionLoadedToastLabel,
	versionsChipAccessibleLabel,
	openNowPlayingLabel,
	songEditorOpenLabel,
	takesDraftBanner
} from '../src/lib/constants';
import {
	NOW_PLAYING_IMPORTED_TAKE_HEADING,
	NOW_PLAYING_QUEUE_TAB,
	NOW_PLAYING_RIGHT_PANEL_LABEL,
	NOW_PLAYING_TAKE_TAB,
	openVersionLabel,
	currentVersionHeadLabel,
	foldedGroupLabel,
	takeRowLabel,
	takeVersion,
	type TakeVersion
} from '../src/lib/constants/now-playing';
import type { GenerationItem, SongItem, VersionItem } from '../src/lib/api/types';
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
// pauseAt only moves the page's clock forward; this lead keeps the hold ahead
// of the time the page has already reached.
const CLOCK_HOLD_LEAD_MS = 1000;
/** Mid-take in the three-second fixture take. */
const HELD_TAKE_SECONDS = 1.5;

interface SeededVersions {
	songId: string;
	title: string;
	albumId: string;
	v1: TakeVersion;
	v2: TakeVersion;
}

// Every song seeded here joins song-phone.spec.ts's dedicated album, whose
// request budget grows with each sibling song left in it, so a test removes
// the songs it seeded.
const songsSeededByThisTest: string[] = [];

async function deleteSeededSong(page: Page, songId: string): Promise<void> {
	const deleted = await page.request.delete(`/api/songs/${songId}`, {
		headers: await csrfHeaders(page)
	});
	expect(deleted.ok(), `Deleting a seeded song failed: ${await deleted.text()}`).toBeTruthy();
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
	songsSeededByThisTest.push(songId);
	const saved = await page.request.put(`/api/songs/${songId}`, {
		headers: await csrfHeaders(page),
		data: { lyrics: SECOND_VERSION_LYRICS }
	});
	expect(saved.ok(), `Saving v2 failed: ${await saved.text()}`).toBeTruthy();
	const versions = await readVersions(page, songId);
	const seeded = {
		songId,
		title,
		albumId: library.songPhoneAlbumId,
		v1: seededVersion(versions, 1),
		v2: seededVersion(versions, 2)
	};
	if (!secondVersionTaken) return seeded;
	const jobId = await seedRunningGenerationJob(songId, {
		progress: 0.5,
		takeIndex: 1,
		takeCount: 1,
		phase: 'loading_model'
	});
	await completeGenerationJobWithoutEvent(jobId);
	return seeded;
}

function seededVersion(versions: VersionItem[], versionNumber: number): TakeVersion {
	const seeded = versions.find((version) => version.version_number === versionNumber);
	const version = seeded ? takeVersion(seeded.id, seeded.version_number) : null;
	if (!version) throw new Error(`Expected the seeded song to have v${versionNumber}`);
	return version;
}

/** Saves the latest lyrics again as `count` more versions, so a song has more than the popover shows. */
async function saveFurtherVersions(page: Page, songId: string, count: number): Promise<void> {
	for (let saves = 0; saves < count; saves += 1) {
		const saved = await page.request.put(`/api/songs/${songId}`, {
			headers: await csrfHeaders(page),
			data: { lyrics: SECOND_VERSION_LYRICS, new_version: true }
		});
		expect(saved.ok(), `Saving a further version failed: ${await saved.text()}`).toBeTruthy();
	}
}

// Through the album's track list, the way song-phone.spec.ts opens a song it
// is about to edit.
async function openSongEditor(page: Page, song: SeededVersions): Promise<void> {
	await page.goto(`/album/${song.albumId}`);
	await workspace(page)
		.getByRole('button', { name: songEditorOpenLabel(song.title) })
		.click();
	const editTab = page.getByRole('tab', { name: EDITOR_TAB_EDIT_LABEL, exact: true });
	if (await editTab.isVisible()) await editTab.click();
	await expect(lyricsField(page)).toHaveValue(SECOND_VERSION_LYRICS);
	await holdTheClock(page);
}

// A load's Undo lasts a few seconds of the page's clock. Held still, it lasts
// until a test moves the clock on with fastForward, so no step that follows a
// load races the wall clock.
async function holdTheClock(page: Page): Promise<void> {
	await page.clock.pauseAt(Date.now() + CLOCK_HOLD_LEAD_MS);
}

async function readVersions(page: Page, songId: string): Promise<VersionItem[]> {
	const response = await page.request.get(`/api/songs/${songId}/versions`);
	expect(response.ok()).toBeTruthy();
	return (await response.json()) as VersionItem[];
}

async function takeOf(page: Page, songId: string, versionNumber: number): Promise<GenerationItem> {
	const response = await page.request.get(`/api/songs/${songId}`);
	expect(response.ok()).toBeTruthy();
	const song = (await response.json()) as SongItem;
	const take = song.generations.find((generation) => generation.version_number === versionNumber);
	if (!take) throw new Error(`Expected a take of v${versionNumber}`);
	return take;
}

async function pickTheTakeOf(page: Page, songId: string, versionNumber: number): Promise<void> {
	const take = await takeOf(page, songId, versionNumber);
	const picked = await page.request.post(`/api/generations/${take.id}/pick`, {
		headers: await csrfHeaders(page)
	});
	expect(picked.ok(), `Picking the take failed: ${await picked.text()}`).toBeTruthy();
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

function loadedToast(page: Page, versionNumber = 1): Locator {
	return page.getByRole('alert').filter({ hasText: versionLoadedToastLabel(versionNumber) });
}

function replaceDraftDialog(page: Page): Locator {
	return page.getByRole('dialog', { name: VERSION_REPLACE_DRAFT_TITLE });
}

type Box = { x: number; y: number; width: number; height: number };

function boxesOverlap(a: Box | null, b: Box | null): boolean {
	if (!a || !b) throw new Error('Expected both boxes on screen');
	return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

// The phone shows the takes on their own tab, the desktop beside the editor; every folded version unfolds.
async function showTakes(page: Page): Promise<void> {
	const takesTab = page.getByRole('tab', { name: nameStartingWith(EDITOR_TAB_TAKES_LABEL) });
	if (await takesTab.isVisible()) await takesTab.click();
	for (const fold of await page.locator('.version-toggle[aria-expanded=false]').all())
		await fold.click();
}

function takeGroup(page: Page, version: TakeVersion | null, takeCount: number): Locator {
	const versionNumber = version?.versionNumber ?? null;
	const hasText = foldedGroupLabel(versionNumber, takeCount, 0);
	return workspace(page).locator('.version-section').filter({ hasText });
}

// The phone's full Now Playing carries the transport while it covers the
// mini player; elsewhere the transport bar does.
function pauseOfThePlayingTake(page: Page): Locator {
	return page.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true }).first();
}

interface DeckWindow {
	audioDecks: Set<HTMLMediaElement>;
	heldDeck?: HTMLMediaElement;
}

// The player's decks are detached Audio objects no locator reaches, so the
// page collects each one as it is given a source, as playback-restore.spec.ts does.
async function followTheAudioDecks(page: Page): Promise<void> {
	await page.addInitScript(() => {
		const decks = new Set<HTMLMediaElement>();
		(window as unknown as DeckWindow).audioDecks = decks;
		const source = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'src');
		if (!source?.set) throw new Error('HTMLMediaElement has no src setter');
		const setSource = source.set;
		Object.defineProperty(HTMLMediaElement.prototype, 'src', {
			...source,
			set(this: HTMLMediaElement, url: string) {
				decks.add(this);
				setSource.call(this, url);
			}
		});
	});
}

// Pause before seeking so the three-second fixture cannot finish during the
// navigation, and a restart at 0:00 cannot look like an unchanged position.
async function holdThePlayingTakeAt(page: Page, seconds: number): Promise<number> {
	await expect
		.poll(() =>
			page.evaluate((to) => {
				const followed = window as unknown as DeckWindow;
				const playing = [...followed.audioDecks].find((deck) => !deck.paused);
				const { buffered } = playing ?? {};
				if (!playing || !buffered?.length || buffered.end(buffered.length - 1) < to) return false;
				followed.heldDeck = playing;
				return true;
			}, seconds)
		)
		.toBe(true);
	await pauseOfThePlayingTake(page).click();
	await page.evaluate((to) => {
		const held = (window as unknown as DeckWindow).heldDeck;
		if (!held) throw new Error('No take is held');
		held.currentTime = to;
	}, seconds);
	return heldTakePosition(page);
}

async function heldTakePosition(page: Page): Promise<number> {
	return page.evaluate(() => {
		const held = (window as unknown as DeckWindow).heldDeck;
		if (!held) throw new Error('No take is held');
		return held.currentTime;
	});
}

// The phone's transport shows only a progress line, drawn over the length the
// take was recorded with -- the deck's own duration reads Infinity for the
// audio blob it plays.
async function shownTakePosition(page: Page, phoneTakeSeconds: number | null): Promise<number> {
	const transport = page.getByRole('contentinfo');
	if (phoneTakeSeconds === null) {
		return Number(await transport.getByRole('slider', { name: 'Seek playback' }).inputValue());
	}
	const progress = await transport
		.locator('.mobile-progress-fill')
		.evaluate((line) => parseFloat((line as HTMLElement).style.width));
	return (progress / 100) * phoneTakeSeconds;
}

async function recordedSecondsOf(
	page: Page,
	songId: string,
	versionNumber: number
): Promise<number> {
	const seconds = (await takeOf(page, songId, versionNumber)).audio_duration_sec;
	if (seconds === null) throw new Error(`Expected the take of v${versionNumber} to have a length`);
	return seconds;
}

async function tapVersion(page: Page, versionNumber: number): Promise<void> {
	await versionChip(page).click();
	await expect(versionsSheet(page)).toBeVisible();
	await versionRow(page, versionNumber).click();
}

test.describe('the versions of a song', () => {
	test.beforeEach(async ({ page }) => {
		await page.clock.install();
	});

	test.afterEach(async ({ page }) => {
		for (const songId of songsSeededByThisTest.splice(0)) await deleteSeededSong(page, songId);
	});

	for (const { secondVersionTaken, v2 } of [
		{ secondVersionTaken: true, v2: 'v2 with a take' },
		{ secondVersionTaken: false, v2: 'a take-less v2' }
	]) {
		test(`tapping v1 loads it as the draft, and Generate makes v3 while v1 and ${v2} stay as they were`, async ({
			page
		}, testInfo) => {
			const song = await seedTwoVersions(page, testInfo, secondVersionTaken);
			await openSongEditor(page, song);
			await expect(versionChip(page)).toHaveText(versionChipLabel(2, false));

			await tapVersion(page, 1);

			await expect(versionsSheet(page)).toBeHidden();
			await expect(lyricsField(page)).toHaveValue(FIRST_VERSION_LYRICS);
			await expect(workspace(page).getByText(versionLoadedFromLabel(1))).toBeVisible();
			await expect(versionChip(page)).toHaveText(versionChipLabel(2, true));
			await expect(loadedToast(page)).toBeVisible();
			const generate = workspace(page).getByRole('button', {
				name: nameStartingWith(EDITOR_GENERATE_LABEL)
			});
			// On the phone the toast rises above the docked Generate bar, so
			// Generate takes the tap while the toast still shows.
			expect(
				boxesOverlap(await loadedToast(page).boundingBox(), await generate.boundingBox())
			).toBe(false);
			expect((await readVersions(page, song.songId)).map((v) => v.version_number)).toEqual([2, 1]);

			const queued = page.waitForResponse(
				(response) =>
					response.url().endsWith(`/api/songs/${song.songId}/generate`) &&
					response.request().method() === 'POST'
			);
			await generate.click();
			// The worker-less stack may refuse the job itself; what counts here is
			// the version Generate saved before it asked for one.
			await queued;

			await expect(versionChip(page)).toHaveText(versionChipLabel(3, false));
			await expect(workspace(page).getByText(versionLoadedFromLabel(1))).toBeHidden();
			await expect(loadedToast(page)).toBeHidden();
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

	test('the Undo of a load is offered only until the next action: typing ends it, and the opened sheet stands free of it', async ({
		page
	}, testInfo) => {
		const song = await seedTwoVersions(page, testInfo);
		await openSongEditor(page, song);

		await tapVersion(page, 1);
		await expect(loadedToast(page)).toBeVisible();
		const typedLyrics = `${FIRST_VERSION_LYRICS}\n${UNSAVED_LINE}`;
		await lyricsField(page).fill(typedLyrics);
		await expect(loadedToast(page)).toBeHidden();

		await tapVersion(page, 2);
		await replaceDraftDialog(page)
			.getByRole('button', { name: VERSION_REPLACE_DRAFT_CONFIRM_LABEL })
			.click();
		await expect(lyricsField(page)).toHaveValue(SECOND_VERSION_LYRICS);
		await expect(loadedToast(page, 2)).toBeVisible();

		await versionChip(page).click();
		await expect(versionsSheet(page)).toBeVisible();
		await expect(loadedToast(page, 2)).toBeHidden();
		await versionRow(page, 1).click();
		await expect(versionsSheet(page)).toBeHidden();
		await expect(lyricsField(page)).toHaveValue(FIRST_VERSION_LYRICS);
	});

	test('tapping the version the draft already holds changes nothing: the sheet closes and the Undo still brings the typed edit back', async ({
		page
	}, testInfo) => {
		const song = await seedTwoVersions(page, testInfo);
		await openSongEditor(page, song);
		const editedLyrics = `${SECOND_VERSION_LYRICS}\n${UNSAVED_LINE}`;
		await lyricsField(page).fill(editedLyrics);
		await tapVersion(page, 1);
		await replaceDraftDialog(page)
			.getByRole('button', { name: VERSION_REPLACE_DRAFT_CONFIRM_LABEL })
			.click();
		await expect(loadedToast(page)).toBeVisible();

		await tapVersion(page, 1);

		await expect(versionsSheet(page)).toBeHidden();
		await expect(replaceDraftDialog(page)).toHaveCount(0);
		await expect(lyricsField(page)).toHaveValue(FIRST_VERSION_LYRICS);
		await loadedToast(page).getByRole('button', { name: TOAST_UNDO_LABEL }).click();
		await expect(lyricsField(page)).toHaveValue(editedLyrics);
	});

	test('a draft equal to a saved version is clean: after an untouched v1, v2 loads without asking', async ({
		page
	}, testInfo) => {
		const song = await seedTwoVersions(page, testInfo);
		await openSongEditor(page, song);
		await tapVersion(page, 1);
		await expect(lyricsField(page)).toHaveValue(FIRST_VERSION_LYRICS);

		await tapVersion(page, 2);

		await expect(versionsSheet(page)).toBeHidden();
		await expect(lyricsField(page)).toHaveValue(SECOND_VERSION_LYRICS);
		await expect(replaceDraftDialog(page)).toHaveCount(0);
		await expect(versionChip(page)).toHaveText(versionChipLabel(2, false));
	});

	test('an untouched load says how it differs, not that it is unsaved; a typed edit says it is unsaved', async ({
		page
	}, testInfo) => {
		const song = await seedTwoVersions(page, testInfo);
		await openSongEditor(page, song);
		await tapVersion(page, 1);
		await expect(lyricsField(page)).toHaveValue(FIRST_VERSION_LYRICS);

		await expect(page.getByText(EDITOR_UNSAVED_TITLE, { exact: true })).toHaveCount(0);
		await showTakes(page);
		await expect(workspace(page).getByText(takesDraftBanner(2, 3), { exact: true })).toBeVisible();
		if (shellOf(testInfo) === 'mobile') return;

		await lyricsField(page).fill(`${FIRST_VERSION_LYRICS}\n${UNSAVED_LINE}`);
		await expect(workspace(page).getByText(EDITOR_UNSAVED_TITLE, { exact: true })).toBeVisible();
	});

	test('leaving an untouched load asks nothing: Escape goes to the album without the unsaved-changes question', async ({
		page
	}, testInfo) => {
		const song = await seedTwoVersions(page, testInfo);
		await openSongEditor(page, song);
		await tapVersion(page, 1);
		await expect(lyricsField(page)).toHaveValue(FIRST_VERSION_LYRICS);

		await lyricsField(page).focus();
		await lyricsField(page).blur();
		await page.keyboard.press('Escape');

		await expect(lyricsField(page)).toBeHidden();
		await expect(
			workspace(page).getByRole('button', { name: nameStartingWith(song.title) })
		).toBeVisible();
		await expect(page.getByRole('dialog', { name: EDITOR_UNSAVED_TITLE })).toHaveCount(0);
	});

	test('a peek at the sheet keeps the Undo: its toast leaves while the sheet is open and comes back once it closes', async ({
		page
	}, testInfo) => {
		const song = await seedTwoVersions(page, testInfo);
		await openSongEditor(page, song);
		await tapVersion(page, 1);
		await expect(loadedToast(page)).toBeVisible();

		await versionChip(page).click();
		await expect(versionsSheet(page)).toBeVisible();
		await expect(loadedToast(page)).toBeHidden();
		await versionsSheet(page).getByRole('button', { name: VERSIONS_SHEET_CLOSE_LABEL }).click();

		await expect(versionsSheet(page)).toBeHidden();
		await loadedToast(page).getByRole('button', { name: TOAST_UNDO_LABEL }).click();
		await expect(lyricsField(page)).toHaveValue(SECOND_VERSION_LYRICS);
	});

	test('the Undo toast keeps its time while the sheet is open: a tap on the loaded version after 4 s brings it back with time left', async ({
		page
	}, testInfo) => {
		const song = await seedTwoVersions(page, testInfo);
		await openSongEditor(page, song);
		const editedLyrics = `${SECOND_VERSION_LYRICS}\n${UNSAVED_LINE}`;
		await lyricsField(page).fill(editedLyrics);
		await tapVersion(page, 1);
		await replaceDraftDialog(page)
			.getByRole('button', { name: VERSION_REPLACE_DRAFT_CONFIRM_LABEL })
			.click();
		await expect(loadedToast(page)).toBeVisible();
		await versionChip(page).click();
		await expect(versionsSheet(page)).toBeVisible();

		// The toast's five seconds would have run out while the sheet stood open.
		await page.clock.fastForward(4000);
		await versionRow(page, 1).click();
		await expect(versionsSheet(page)).toBeHidden();
		await expect(loadedToast(page)).toBeVisible();
		await page.clock.fastForward(2000);

		await loadedToast(page).getByRole('button', { name: TOAST_UNDO_LABEL }).click();
		await expect(lyricsField(page)).toHaveValue(editedLyrics);
	});

	test('the sheet stands over the whole page: the phone dims all of it, the desktop popover sits under the chip and shows whole rows only', async ({
		page
	}, testInfo) => {
		const song = await seedTwoVersions(page, testInfo);
		if (shellOf(testInfo) === 'desktop') await saveFurtherVersions(page, song.songId, 6);
		await openSongEditor(page, song);
		await versionChip(page).click();
		await expect(versionsSheet(page)).toBeVisible();

		if (shellOf(testInfo) === 'mobile') {
			const topOfThePage = await page.evaluate(() => {
				const hit = document.elementFromPoint(window.innerWidth / 2, 4);
				return {
					label: hit?.getAttribute('aria-label') ?? null,
					background: hit ? getComputedStyle(hit).backgroundColor : null
				};
			});
			expect(topOfThePage.label).toBe(VERSIONS_SHEET_CLOSE_LABEL);
			expect(topOfThePage.background).not.toBe('rgba(0, 0, 0, 0)');
			return;
		}
		const chip = await versionChip(page).boundingBox();
		const popover = await versionsSheet(page).boundingBox();
		if (!chip || !popover) throw new Error('Expected the chip and the popover on screen');
		expect(popover.y).toBeGreaterThan(chip.y + chip.height);
		expect(popover.y).toBeLessThan(chip.y + chip.height + 16);
		expect(popover.y + popover.height).toBeLessThanOrEqual(page.viewportSize()?.height ?? 0);

		const list = versionsSheet(page).getByRole('list');
		const rowsInView = await list.evaluate((element) => {
			const rowHeight = element.querySelector('li')?.getBoundingClientRect().height ?? 0;
			return element.clientHeight / rowHeight;
		});
		expect(rowsInView).toBeGreaterThanOrEqual(2);
		expect(Math.abs(rowsInView - Math.round(rowsInView))).toBeLessThan(0.02);
		await list.evaluate((element) => {
			const rowHeight = element.querySelector('li')?.getBoundingClientRect().height ?? 0;
			element.scrollBy({ top: rowHeight * 1.4 });
		});
		await expect
			.poll(() =>
				list.evaluate((element) => {
					const top = element.getBoundingClientRect().top;
					const rowEdgeAtTop = Array.from(element.querySelectorAll('li')).some(
						(row) => Math.abs(row.getBoundingClientRect().top - top) < 1
					);
					return element.scrollTop > 0 && rowEdgeAtTop;
				})
			)
			.toBe(true);
	});

	test('Open v1 on its take group loads v1 as the draft on Edit', async ({ page }, testInfo) => {
		const song = await seedTwoVersions(page, testInfo);
		await openSongEditor(page, song);
		await showTakes(page);

		await page.getByRole('button', { name: openVersionLabel(1) }).click();

		await expect(lyricsField(page)).toHaveValue(FIRST_VERSION_LYRICS);
		await expect(versionChip(page)).toHaveText(versionChipLabel(2, true));
		await expect(workspace(page).getByText(versionLoadedFromLabel(1))).toBeVisible();
		await expect(loadedToast(page)).toBeVisible();
		expect((await readVersions(page, song.songId)).map((v) => v.version_number)).toEqual([2, 1]);
	});

	test('Open v2 on the clean current version answers: the focus moves to the lyrics and "v2 is already the draft" appears', async ({
		page
	}, testInfo) => {
		const song = await seedTwoVersions(page, testInfo);
		await openSongEditor(page, song);
		await showTakes(page);

		await page.getByRole('button', { name: openVersionLabel(2) }).click();

		await expect(lyricsField(page)).toBeFocused();
		await expect(lyricsField(page)).toHaveValue(SECOND_VERSION_LYRICS);
		await expect(
			page.getByRole('alert').filter({ hasText: versionAlreadyTheDraftLabel(2) })
		).toBeVisible();
		await expect(versionChip(page)).toHaveText(versionChipLabel(2, false));
	});

	test('Open v1 in Now Playing lands on Edit with v1 loaded while the take plays on', async ({
		page
	}, testInfo) => {
		const song = await seedTwoVersions(page, testInfo);
		await openSongEditor(page, song);
		await showTakes(page);
		await takeGroup(page, song.v1, 1)
			.getByRole('button', { name: nameStartingWith(takeRowLabel(1)) })
			.click();
		await expect(page.getByRole('tab', { name: NOW_PLAYING_TAKE_TAB })).toBeVisible();
		await expect(pauseOfThePlayingTake(page)).toBeVisible();

		const openV1 = page.getByRole('button', { name: openVersionLabel(1), exact: true }).last();
		await openV1.click();

		await expect(page.getByRole('tab', { name: NOW_PLAYING_TAKE_TAB })).toBeHidden();
		await expect(lyricsField(page)).toHaveValue(FIRST_VERSION_LYRICS);
		await expect(versionChip(page)).toHaveText(versionChipLabel(2, true));
		await expect(workspace(page).getByText(versionLoadedFromLabel(1))).toBeVisible();
		await expect(pauseOfThePlayingTake(page)).toBeVisible();
	});

	test('Open v1 in Now Playing after arriving from the album lands on Edit with v1 loaded and the take where it stood', async ({
		page
	}, testInfo) => {
		await followTheAudioDecks(page);
		const song = await seedTwoVersions(page, testInfo);
		await openSongEditor(page, song);
		await showTakes(page);
		await takeGroup(page, song.v1, 1)
			.getByRole('button', { name: nameStartingWith(takeRowLabel(1)) })
			.click();
		await expect(page.getByRole('tab', { name: NOW_PLAYING_TAKE_TAB })).toBeVisible();
		await expect(pauseOfThePlayingTake(page)).toBeVisible();

		// Back closes one layer at a time: the phone's This take sheet, which
		// covers the transport, and its Now Playing first, then the song, back
		// to the album it came from.
		const mobile = shellOf(testInfo) === 'mobile';
		const phoneTakeSeconds = mobile ? await recordedSecondsOf(page, song.songId, 1) : null;
		if (mobile) {
			await page.goBack();
			await expect(page.getByRole('dialog', { name: NOW_PLAYING_RIGHT_PANEL_LABEL })).toBeHidden();
			await expect(page.getByRole('dialog', { name: song.title })).toBeVisible();
		}
		const heldAt = await holdThePlayingTakeAt(page, HELD_TAKE_SECONDS);
		expect(heldAt).toBeCloseTo(HELD_TAKE_SECONDS, 1);
		if (mobile) {
			await page.goBack();
			await expect(page.getByRole('dialog', { name: song.title })).toBeHidden();
		}
		await page.goBack();
		await expect(
			workspace(page).getByRole('button', { name: nameStartingWith(song.title) })
		).toBeVisible();
		await expect.poll(() => shownTakePosition(page, phoneTakeSeconds)).toBeCloseTo(heldAt, 1);
		const shownAt = await shownTakePosition(page, phoneTakeSeconds);
		if (mobile) {
			await page
				.getByRole('contentinfo')
				.getByRole('button', { name: openNowPlayingLabel(song.title), exact: true })
				.click();
			await page
				.getByRole('dialog', { name: song.title })
				.getByRole('button', { name: new RegExp(`${NOW_PLAYING_QUEUE_TAB}$`) })
				.click();
		}
		await page.getByRole('tab', { name: NOW_PLAYING_TAKE_TAB }).click();

		const openV1 = page.getByRole('button', { name: openVersionLabel(1), exact: true }).last();
		await openV1.click();

		await expect(lyricsField(page)).toHaveValue(FIRST_VERSION_LYRICS);
		await expect(versionChip(page)).toHaveText(versionChipLabel(2, true));
		await expect(
			page.getByRole('contentinfo').getByRole('button', { name: TRANSPORT_PLAY_LABEL, exact: true })
		).toBeVisible();
		expect(await heldTakePosition(page)).toBe(heldAt);
		await expect.poll(() => shownTakePosition(page, phoneTakeSeconds)).toBe(shownAt);
	});

	test('deleting v1 from its row asks with its take and the album pick, then v1 and its take are gone while v2 stays', async ({
		page
	}, testInfo) => {
		const song = await seedTwoVersions(page, testInfo);
		await pickTheTakeOf(page, song.songId, 1);
		await openSongEditor(page, song);

		await versionChip(page).click();
		await versionsSheet(page)
			.getByRole('button', { name: versionDeleteLabel(1), exact: true })
			.click();
		const confirm = page.getByRole('dialog', { name: versionDeleteTitle(1, 1) });
		await expect(confirm.getByRole('listitem')).toHaveText(['It is the album pick.']);
		await confirm.getByRole('button', { name: VERSION_DELETE_CONFIRM_LABEL }).click();

		await expect(confirm).toBeHidden();
		await expect(versionRow(page, 1)).toHaveCount(0);
		await expect(versionRow(page, 2)).toBeVisible();
		expect((await readVersions(page, song.songId)).map((v) => v.version_number)).toEqual([2]);

		await versionsSheet(page).getByRole('button', { name: VERSIONS_SHEET_CLOSE_LABEL }).click();
		await expect(versionsSheet(page)).toBeHidden();
		await showTakes(page);
		await expect(page.getByText(currentVersionHeadLabel(2, 1))).toBeVisible();
		await expect(takeGroup(page, song.v1, 1)).toHaveCount(0);
	});

	test('the delete confirm over an unsaved draft says the draft goes too, and Cancel keeps it', async ({
		page
	}, testInfo) => {
		const song = await seedTwoVersions(page, testInfo);
		await openSongEditor(page, song);
		const editedLyrics = `${SECOND_VERSION_LYRICS}\n${UNSAVED_LINE}`;
		await lyricsField(page).fill(editedLyrics);

		await versionChip(page).click();
		await versionsSheet(page)
			.getByRole('button', { name: versionDeleteLabel(1), exact: true })
			.click();
		const confirm = page.getByRole('dialog', { name: versionDeleteTitle(1, 1) });
		await expect(confirm).toContainText(VERSION_DELETE_DRAFT_GOES);
		await confirm.getByRole('button', { name: DIALOG_CANCEL_LABEL }).click();

		await expect(confirm).toBeHidden();
		await expect(lyricsField(page)).toHaveValue(editedLyrics);
		expect((await readVersions(page, song.songId)).map((v) => v.version_number)).toEqual([2, 1]);
	});

	test('the delete confirm over an untouched load says what leaves the editor: the load goes with its version, or the next latest replaces it, and its Undo goes too', async ({
		page
	}, testInfo) => {
		const song = await seedTwoVersions(page, testInfo);
		await saveFurtherVersions(page, song.songId, 1);
		await openSongEditor(page, song);
		await tapVersion(page, 1);
		await expect(lyricsField(page)).toHaveValue(FIRST_VERSION_LYRICS);

		for (const { deleted, title, line } of [
			{
				deleted: 1,
				title: versionDeleteTitle(1, 1),
				line: versionDeleteLoadedDraftGoes(1)
			},
			{
				deleted: 2,
				title: versionDeleteTitle(2, 1),
				line: versionDeleteLoadedDraftReplacedBy(1, 3)
			}
		]) {
			await versionChip(page).click();
			await versionsSheet(page)
				.getByRole('button', { name: versionDeleteLabel(deleted), exact: true })
				.click();
			const confirm = page.getByRole('dialog', { name: title });
			await expect(confirm.getByRole('listitem')).toHaveText([line, VERSION_DELETE_LOAD_UNDO_GOES]);
			await confirm.getByRole('button', { name: DIALOG_CANCEL_LABEL }).click();
			await expect(confirm).toBeHidden();
			await versionsSheet(page).getByRole('button', { name: VERSIONS_SHEET_CLOSE_LABEL }).click();
			await expect(versionsSheet(page)).toBeHidden();
		}
		await expect(lyricsField(page)).toHaveValue(FIRST_VERSION_LYRICS);
		expect((await readVersions(page, song.songId)).map((v) => v.version_number)).toEqual([3, 2, 1]);
	});

	test('an imported take groups as Imported with no Open link, and Now Playing names it "Imported take" and says why it has no lyrics', async ({
		page
	}) => {
		const library = readSeededLibrary();
		await page.goto(`/album/${library.albumId}`);
		await workspace(page)
			.getByRole('button', { name: songEditorOpenLabel(library.pickedSongTitle) })
			.click();
		await showTakes(page);

		const imported = takeGroup(page, null, 1);
		await expect(imported).toBeVisible();
		await expect(imported.getByRole('button', { name: /Open v/ })).toHaveCount(0);

		await imported.getByRole('button', { name: nameStartingWith(takeRowLabel(1)) }).click();
		await expect(page.getByRole('tab', { name: NOW_PLAYING_TAKE_TAB })).toBeVisible();
		await expect(page.getByText(NOW_PLAYING_IMPORTED_TAKE_NO_LYRICS)).toBeVisible();
		await expect(
			page.getByRole('heading', { name: NOW_PLAYING_IMPORTED_TAKE_HEADING, exact: true })
		).toBeVisible();
		await expect(page.getByRole('button', { name: /^Open v/ })).toHaveCount(0);
	});
});

// Phone Takes and generation states (#995, #914 L12); Settings also runs on desktop (#1143).
// CI seeds jobs without a worker.

import { GROUPS, phoneSearchResult } from './phone-search';
import { expect, test, type Locator, type Page } from './coverage-test';
import type { VersionItem } from '../src/lib/api/types';
import {
	EDITOR_GENERATE_TAKE_TEMPLATE,
	EDITOR_TAB_EDIT_LABEL,
	EDITOR_VIEW_COWRITER_LABEL,
	EDITOR_UNSAVED_SAVE_LABEL,
	SONG_MENU_LABEL,
	SONG_MENU_SAVE_LABEL,
	EDITOR_UNSAVED_DISCARD_LABEL,
	EDITOR_UNSAVED_TITLE,
	songEditorOpenLabel
} from '../src/lib/constants/song';
import { DIALOG_CANCEL_LABEL } from '../src/lib/constants/dialog';
import { GENERATION_PHASE_LABELS } from '../src/lib/constants/jobs';
import { formatTime } from '../src/lib/utils/format';
import { HITBOX_FREQUENT_PX } from '../src/lib/constants/hitbox';
import { TRANSPORT_PLAY_LABEL } from '../src/lib/constants/transport';
import { words } from '../src/lib/words/en';
import {
	nowPlayingOpenSourceLabel,
	nowPlayingTakeLabel,
	currentVersionHeadLabel,
	takeVersion,
	type TakeVersion,
	NOW_PLAYING_CLOSE,
	openNowPlayingLabel
} from '../src/lib/constants/now-playing';
import {
	boundingBoxes,
	containing,
	FlowGuard,
	ONLY_IN_SHELL,
	MOBILE_VIEWPORT,
	openSettingsSection,
	openPageFromSearch,
	SONG_PHONE_FLOW_API_REQUEST_BUDGET,
	workspace
} from './helpers';
import {
	advanceGenerationJobPhase,
	failGenerationJob,
	readSeededLibrary,
	runMarker,
	seedRunningGenerationJob,
	seedSongPhoneSong
} from './seed';

const SONG_PHONE_SONG_TITLE = 'Song Phone Takes';
const SETTINGS_SECTION = 'Generation';
// Chosen to prove the player names the real seeded version rather than an
// assumed v1 — the whole point of L12's "version number as seeded" clause.
const SONG_PHONE_VERSION_NUMBER = 7;
const SONG_PHONE_TAKE_COUNT = 2;
const SECOND_TAKE_LABEL = nowPlayingTakeLabel(SONG_PHONE_VERSION_NUMBER, SONG_PHONE_TAKE_COUNT);
const PLAYS_FROM_AN_ALBUM = new RegExp(`^${nowPlayingOpenSourceLabel('album', '.+')}$`);
const RUNNING_JOB_TAKE_INDEX = 1;
const RUNNING_JOB_TAKE_COUNT = 2;
// A cold start: the job begins by loading the model, which names no percent
// and no remaining time (#1040), then moves on live to rendering.
const LOADING_JOB_PHASE = 'loading_model';
const LOADING_JOB_PHASE_LABEL = GENERATION_PHASE_LABELS[LOADING_JOB_PHASE];
const LOADING_JOB_PROGRESS = 0;
const RUNNING_JOB_PROGRESS = 0.36;
// The job has been generating this many seconds, so the remaining-time
// estimate lands well inside a plausible single-digit-minute ETA rather than
// at either extreme.
const RUNNING_JOB_PHASE = 'rendering';
const RUNNING_JOB_PHASE_LABEL = GENERATION_PHASE_LABELS[RUNNING_JOB_PHASE];
const RUNNING_JOB_GENERATION_STARTED_OFFSET_SECONDS = 64;
const RUNNING_JOB_TAKE_COUNTER = EDITOR_GENERATE_TAKE_TEMPLATE.replace(
	'{index}',
	String(RUNNING_JOB_TAKE_INDEX)
).replace('{count}', String(RUNNING_JOB_TAKE_COUNT));
const REMAINING_TIME_PATTERN = /~\d+:\d{2}/;
const ELAPSED_TIME_PATTERN = /\d+:\d{2}/;
const CLOCK_HOLD_LEAD_MS = 1000;
const CLOCK_RUN_SECONDS = 12;
const RAW_WORKER_FAILURE = 'ACE-Step worker: CUDA out of memory on device 0';
const FAILED_GENERATION_SENTENCE = 'Generating failed — try again.';
const UNSAVED_DRAFT_LINE = 'a line nobody saved';

// The seeded take's version as the app reads it, so a group label names it
// through the one predicate that decides whether a take has a version.
async function seededTakeVersion(page: Page, songId: string): Promise<TakeVersion> {
	const response = await page.request.get(`/api/songs/${songId}/versions`);
	expect(response.ok()).toBeTruthy();
	const [seeded] = (await response.json()) as VersionItem[];
	const version = seeded ? takeVersion(seeded.id, seeded.version_number) : null;
	if (!version) throw new Error('Expected the seeded song to have a version');
	return version;
}

function songBackButton(page: Page): Locator {
	return page.locator('.mobile-strip').getByRole('button', { name: /^Back to / });
}

const phoneTabs = (page: Page) => page.getByRole('navigation', { name: words['phoneTabs.nav'] });

async function observeTabAttachments(page: Page): Promise<void> {
	await page.addInitScript((label) => {
		const selector = `nav[aria-label="${label}"]`;
		const attachments: { at: number; sinceWindowMs: number; window: string }[] = [];
		Reflect.set(window, 'phoneTabAttachments', attachments);
		Reflect.set(window, 'phoneTabWindow', 'startup');
		Reflect.set(window, 'phoneTabWindowStarted', performance.now());
		new MutationObserver((records) => {
			for (const record of records)
				for (const node of record.addedNodes) {
					if (!(node instanceof Element)) continue;
					const count = Number(node.matches(selector)) + node.querySelectorAll(selector).length;
					for (let i = 0; i < count; i++)
						attachments.push({
							at: performance.now(),
							sinceWindowMs: performance.now() - Reflect.get(window, 'phoneTabWindowStarted'),
							window: Reflect.get(window, 'phoneTabWindow')
						});
				}
		}).observe(document, { childList: true, subtree: true });
	}, words['phoneTabs.nav']);
}

interface SongWithAnUnsavedDraft {
	songHeading: Locator;
	lyrics: Locator;
	savedLyrics: string;
	unsavedDraftDialog: Locator;
}

async function openSongWithAnUnsavedDraft(
	page: Page,
	albumId: string,
	title = `${SONG_PHONE_SONG_TITLE} ${runMarker()} draft`
): Promise<SongWithAnUnsavedDraft> {
	await seedSongPhoneSong(albumId, title, 1, 1);
	const songHeading = page.getByRole('heading', { name: title });
	const lyrics = page.getByRole('textbox', { name: /^Lyrics/ });
	await page.goto(`/album/${albumId}`);
	await workspace(page)
		.getByRole('button', { name: songEditorOpenLabel(title) })
		.click();
	await expect(songHeading).toBeVisible();
	expectSongAddressStands(page, albumId, title);
	const savedLyrics = await lyrics.inputValue();
	await lyrics.fill(`${savedLyrics}\n${UNSAVED_DRAFT_LINE}`);
	return {
		songHeading,
		lyrics,
		savedLyrics,
		unsavedDraftDialog: page.getByRole('dialog', { name: EDITOR_UNSAVED_TITLE })
	};
}

function expectedSongSlug(title: string): string {
	return title.toLowerCase().replace(/\s+/g, '-');
}

// Read once, as soon as the song shows: its address moves with it, not once
// the router has loaded the song's route (issue #1263).
function expectSongAddressStands(page: Page, albumId: string, title: string): void {
	expect(new URL(page.url()).pathname).toBe(`/album/${albumId}/${expectedSongSlug(title)}`);
}

test.describe('song page at phone width', () => {
	test(
		'[defect:#1568] [defect:#1579] lists takes with a play control each, shows a running generation, then its failure',
		{ tag: ONLY_IN_SHELL.mobile },
		async ({ page }) => {
			const guard = new FlowGuard(page);
			const library = readSeededLibrary();
			// A per-attempt title, not the bare constant: CI retries this test once
			// on failure (playwright.config.ts), and a retry re-seeding the same
			// title into the same shared album would leave two rows starting with
			// it, breaking the row lookup below with a strict-mode violation.
			const songTitle = `${SONG_PHONE_SONG_TITLE} ${runMarker()}`;
			const songId = await seedSongPhoneSong(
				library.songPhoneAlbumId,
				songTitle,
				SONG_PHONE_VERSION_NUMBER,
				SONG_PHONE_TAKE_COUNT
			);
			const songAddress = `/album/${library.songPhoneAlbumId}/${expectedSongSlug(songTitle)}`;
			// The one song-phone-panel element (SongPhoneView.svelte): its content
			// swaps with the active tab, so this locator always reads whichever tab
			// is current rather than naming Edit and Takes separately.
			const panel = page.getByRole('tabpanel');

			// A cold open of the song's own address (a reload, a shared link, a
			// bookmark) stands in its album exactly as a track-list open does, so
			// a non-pick take queues the album, not the library pool (#997).
			await page.goto(songAddress);
			await expect(page.getByRole('heading', { name: songTitle })).toBeVisible();

			await page.getByRole('tab', { name: /Takes/ }).click();
			const { versionNumber } = await seededTakeVersion(page, songId);
			await expect(
				panel.getByText(currentVersionHeadLabel(versionNumber, SONG_PHONE_TAKE_COUNT))
			).toBeVisible();

			const playButtons = panel.getByRole('button', {
				name: new RegExp(`^${TRANSPORT_PLAY_LABEL} v`)
			});
			await expect(playButtons).toHaveCount(SONG_PHONE_TAKE_COUNT);
			for (const box of await boundingBoxes(...(await playButtons.all()))) {
				expect(box.width).toBeGreaterThanOrEqual(HITBOX_FREQUENT_PX);
				expect(box.height).toBeGreaterThanOrEqual(HITBOX_FREQUENT_PX);
			}

			await panel
				.getByRole('button', { name: `${TRANSPORT_PLAY_LABEL} ${SECOND_TAKE_LABEL}`, exact: true })
				.click();
			// The phone bar says where the music comes from (#1058, frame C2); the
			// player names the take on Now Playing, opened from the bar's title: on
			// its cover line, exactly, since the take panel's heading, which renders
			// once the song has loaded, starts with the same label.
			await page
				.getByRole('contentinfo')
				.getByRole('button', { name: openNowPlayingLabel(songTitle), exact: true })
				.click();
			const nowPlaying = page.getByRole('dialog', { name: songTitle });
			await expect(nowPlaying.getByRole('button', { name: PLAYS_FROM_AN_ALBUM })).toBeVisible();
			await expect(nowPlaying.getByText(SECOND_TAKE_LABEL, { exact: true })).toBeVisible();
			await nowPlaying.getByRole('button', { name: NOW_PLAYING_CLOSE, exact: true }).click();
			await expect(nowPlaying).toBeHidden();

			// A seeded running job, discovered the same way a reload would: a fresh
			// cold open re-runs loadSongContext's hydrateActiveGeneration.
			const jobId = await seedRunningGenerationJob(songId, {
				progress: LOADING_JOB_PROGRESS,
				takeIndex: RUNNING_JOB_TAKE_INDEX,
				takeCount: RUNNING_JOB_TAKE_COUNT,
				phase: LOADING_JOB_PHASE
			});
			// Held only once the page has booted, never before.
			await page.clock.install();
			await page.goto(songAddress);
			// The song comes back on the Takes tab it was left on (#1047); the
			// Generate status lives on Edit.
			await page.getByRole('tab', { name: EDITOR_TAB_EDIT_LABEL }).click();
			const generateStatus = panel.getByRole('status');
			await expect(generateStatus).toHaveText(
				new RegExp(
					`^\\s*${RUNNING_JOB_TAKE_COUNTER} · ${LOADING_JOB_PHASE_LABEL} ${ELAPSED_TIME_PATTERN.source}\\s*$`
				)
			);
			await page.clock.pauseAt(Date.now() + CLOCK_HOLD_LEAD_MS);

			await page.getByRole('tab', { name: /Takes/ }).click();
			await expect(panel.getByRole('progressbar')).toBeVisible();
			await expect(panel.getByText(LOADING_JOB_PHASE_LABEL)).toBeVisible();
			await expect(panel.getByText(RUNNING_JOB_TAKE_COUNTER, { exact: true })).toBeVisible();
			await expect(panel.getByText(REMAINING_TIME_PATTERN)).toHaveCount(0);
			await expect(panel.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow');
			// The count starts when the page first sees the job, so it is read here.
			const held = (await panel.locator('.status-title').innerText()).match(ELAPSED_TIME_PATTERN);
			if (!held) throw new Error('Expected an elapsed time at the hold');
			const [minutes, seconds] = held[0].split(':').map(Number);
			const elapsedAfterRun = formatTime(minutes * 60 + seconds + CLOCK_RUN_SECONDS);
			await page.clock.runFor(CLOCK_RUN_SECONDS * 1000);
			await expect(panel.locator('.status-title')).toContainText(elapsedAfterRun);
			await page.getByRole('tab', { name: EDITOR_TAB_EDIT_LABEL }).click();
			await expect(generateStatus).toContainText(`Loading model… ${elapsedAfterRun}`);
			await page.getByRole('tab', { name: /Takes/ }).click();
			await page.clock.resume();

			// Leaving the model load live, over the same job's still-open SSE
			// stream — no reload, matching a real worker's own reporting path.
			await advanceGenerationJobPhase(jobId, {
				progress: RUNNING_JOB_PROGRESS,
				phase: RUNNING_JOB_PHASE,
				generationStartedOffsetSeconds: RUNNING_JOB_GENERATION_STARTED_OFFSET_SECONDS
			});
			await expect(panel.getByText(RUNNING_JOB_PHASE_LABEL, { exact: true })).toBeVisible();
			await expect(panel.getByText(RUNNING_JOB_TAKE_COUNTER, { exact: false })).toBeVisible();
			await expect(panel.getByText(REMAINING_TIME_PATTERN)).toBeVisible();

			await page.getByRole('tab', { name: EDITOR_TAB_EDIT_LABEL }).click();
			await expect(generateStatus).toContainText(
				new RegExp(
					`${RUNNING_JOB_TAKE_COUNTER} · ${RUNNING_JOB_PHASE_LABEL} · ${Math.round(RUNNING_JOB_PROGRESS * 100)}% · ${REMAINING_TIME_PATTERN.source}`
				)
			);

			// Failing the same job live, over its still-open SSE stream — no
			// reload, matching a real worker crash's own reporting path.
			// L6/L11: the live stream projects worker details to the musician line.
			await failGenerationJob(jobId, RAW_WORKER_FAILURE);
			await expect(panel.getByText(FAILED_GENERATION_SENTENCE)).toBeVisible();
			await expect(page.getByText(RAW_WORKER_FAILURE)).toHaveCount(0);
			await expect(panel.locator('.failure button')).toHaveCount(0);

			console.log(`Song-phone flow /api requests: ${guard.apiRequestCount}`);
			guard.assertClean();
			guard.assertWithinBudget(SONG_PHONE_FLOW_API_REQUEST_BUDGET);
		}
	);

	// Issue #1047: the tab choice is remembered per song for the session; a
	// song opened for the first time lands on Edit, and a reload restores the
	// tab the open song was left on. The phone song page has no previous/next
	// control (#970), so stepping between songs is proven in navigation.test.ts.
	test(
		'remembers each song tab, opens a fresh song on Edit, and keeps the tab on reload',
		{ tag: ONLY_IN_SHELL.mobile },
		async ({ page }) => {
			const library = readSeededLibrary();
			const albumAddress = `/album/${library.songPhoneAlbumId}`;
			const marker = runMarker();
			const firstTitle = `${SONG_PHONE_SONG_TITLE} ${marker} first`;
			const secondTitle = `${SONG_PHONE_SONG_TITLE} ${marker} second`;
			await seedSongPhoneSong(library.songPhoneAlbumId, firstTitle, 1, 1);
			await seedSongPhoneSong(library.songPhoneAlbumId, secondTitle, 1, 1);
			const editTab = page.getByRole('tab', { name: EDITOR_TAB_EDIT_LABEL });
			const takesTab = page.getByRole('tab', { name: /^Takes/ });
			const openFromAlbum = async (title: string) => {
				await workspace(page)
					.getByRole('button', { name: songEditorOpenLabel(title) })
					.click();
				await expect(page.getByRole('heading', { name: title })).toBeVisible();
				expectSongAddressStands(page, library.songPhoneAlbumId, title);
			};

			await page.goto(albumAddress);
			await openFromAlbum(firstTitle);
			await expect(editTab).toHaveAttribute('aria-selected', 'true');
			await takesTab.click();
			await expect(takesTab).toHaveAttribute('aria-selected', 'true');

			await page.goBack();
			await openFromAlbum(secondTitle);
			await expect(editTab).toHaveAttribute('aria-selected', 'true');

			await page.goBack();
			await openFromAlbum(firstTitle);
			await expect(takesTab).toHaveAttribute('aria-selected', 'true');

			await page.reload();
			await expect(page.getByRole('heading', { name: firstTitle })).toBeVisible();
			await expect(takesTab).toHaveAttribute('aria-selected', 'true');

			await editTab.click();
			await page.reload();
			await expect(page.getByRole('heading', { name: firstTitle })).toBeVisible();
			await expect(editTab).toHaveAttribute('aria-selected', 'true');
		}
	);

	test(
		'1354_37a_A4: a Search album selection with an unsaved draft asks first: Cancel keeps the draft, Discard leaves (#1143)',
		{ tag: ONLY_IN_SHELL.mobile },
		async ({ page }) => {
			const library = readSeededLibrary();
			const { songHeading, lyrics, savedLyrics, unsavedDraftDialog } =
				await openSongWithAnUnsavedDraft(page, library.songPhoneAlbumId);
			const selectTheOtherAlbumFromSearch = async () => {
				await (
					await phoneSearchResult(
						page,
						GROUPS.albums,
						library.secondAlbumTitle,
						containing(library.secondAlbumTitle)
					)
				).click();
				await expect(unsavedDraftDialog).toBeVisible();
			};

			await selectTheOtherAlbumFromSearch();
			await unsavedDraftDialog
				.getByRole('button', { name: DIALOG_CANCEL_LABEL, exact: true })
				.click();
			await expect(unsavedDraftDialog).toBeHidden();
			await expect(songHeading).toBeVisible();
			await expect(lyrics).toHaveValue(new RegExp(`${UNSAVED_DRAFT_LINE}$`));

			await selectTheOtherAlbumFromSearch();
			await unsavedDraftDialog
				.getByRole('button', { name: EDITOR_UNSAVED_DISCARD_LABEL, exact: true })
				.click();
			await expect(
				workspace(page).getByRole('heading', { name: library.secondAlbumTitle })
			).toBeVisible();

			await page.goBack();
			await expect(songHeading).toBeVisible();
			await expect(lyrics).toHaveValue(savedLyrics);
		}
	);

	test(
		'defect:#1583: Discard on a Settings page from Search lands on its address, which a reload keeps (#1143)',
		{ tag: ONLY_IN_SHELL.mobile },
		async ({ page }) => {
			const library = readSeededLibrary();
			const { unsavedDraftDialog } = await openSongWithAnUnsavedDraft(
				page,
				library.songPhoneAlbumId
			);

			await openPageFromSearch(page, SETTINGS_SECTION);
			await expect(unsavedDraftDialog).toBeVisible();
			await unsavedDraftDialog
				.getByRole('button', { name: EDITOR_UNSAVED_DISCARD_LABEL, exact: true })
				.click();

			const settingsHeading = page.getByRole('heading', { name: SETTINGS_SECTION, level: 1 });
			await expect(page).toHaveURL(/\/settings\/generation$/);
			await expect(settingsHeading).toBeVisible();
			await page.reload();
			await expect(page).toHaveURL(/\/settings\/generation$/);
			await expect(settingsHeading).toBeVisible();
		}
	);

	test(
		'1354_61_C13b: Back with an unsaved draft asks first: Cancel keeps the draft on the song, Discard leaves without saving (#1143)',
		{ tag: ONLY_IN_SHELL.mobile },
		async ({ page }, testInfo) => {
			await observeTabAttachments(page);
			const library = readSeededLibrary();
			const { songHeading, lyrics, savedLyrics, unsavedDraftDialog } =
				await openSongWithAnUnsavedDraft(page, library.songPhoneAlbumId);
			const songAddress = page.url();

			await page.evaluate(() => {
				Reflect.set(window, 'phoneTabWindow', 'cancel');
				Reflect.set(window, 'phoneTabWindowStarted', performance.now());
			});
			await page.goBack();
			await expect(unsavedDraftDialog).toBeVisible();
			await expect(phoneTabs(page)).toHaveCount(0);
			await expect(page).toHaveURL(songAddress);
			await unsavedDraftDialog
				.getByRole('button', { name: DIALOG_CANCEL_LABEL, exact: true })
				.click();
			await expect(unsavedDraftDialog).toBeHidden();
			await expect(page).toHaveURL(songAddress);
			await expect(songHeading).toBeVisible();
			await expect(phoneTabs(page)).toHaveCount(0);
			await expect(lyrics).toHaveValue(new RegExp(`${UNSAVED_DRAFT_LINE}$`));

			await page.evaluate(() => {
				Reflect.set(window, 'phoneTabWindow', 'discard');
				Reflect.set(window, 'phoneTabWindowStarted', performance.now());
			});
			await page.goBack();
			await expect(unsavedDraftDialog).toBeVisible();
			await expect(phoneTabs(page)).toHaveCount(0);
			await page.evaluate(() => Reflect.set(window, 'phoneTabWindow', 'discard-confirmed'));
			await unsavedDraftDialog
				.getByRole('button', { name: EDITOR_UNSAVED_DISCARD_LABEL, exact: true })
				.click();
			await expect(page).toHaveURL(new RegExp(`/album/${library.songPhoneAlbumId}$`));
			await expect(songHeading).toBeHidden();
			await expect(phoneTabs(page)).toBeVisible();
			await testInfo.attach('tab-attachments.json', {
				body: JSON.stringify(await page.evaluate(() => Reflect.get(window, 'phoneTabAttachments'))),
				contentType: 'application/json'
			});

			await page.goForward();
			await expect(songHeading).toBeVisible();
			await expect(phoneTabs(page)).toHaveCount(0);
			await expect(lyrics).toHaveValue(savedLyrics);
		}
	);

	test.describe('song bar Back (#1591)', () => {
		for (const origin of ['album', 'Home'] as const) {
			test(
				`1354_61_C12 1354_rule_32: clean song returns to ${origin}, and editor tabs keep its Back`,
				{ tag: ONLY_IN_SHELL.mobile },
				async ({ page }) => {
					const { songPhoneAlbumId } = readSeededLibrary();
					const { lyrics, savedLyrics, songHeading } = await openSongWithAnUnsavedDraft(
						page,
						songPhoneAlbumId,
						`QA ${runMarker().slice(-8)}`
					);
					const title = await songHeading.innerText();
					await lyrics.fill(savedLyrics);
					const bar = page.locator('.mobile-strip');
					const albumResponse = await page.request.get(`/api/albums/${songPhoneAlbumId}`);
					expect(albumResponse.ok()).toBe(true);
					const album: { title: string } = await albumResponse.json();
					let name = `Back to ${album.title}`;
					let destination = `/album/${songPhoneAlbumId}`;
					if (origin === 'Home') {
						await page.goto('/');
						await page
							.getByRole('region', { name: words['homeWrite.label'], exact: true })
							.getByRole('button', { name: songEditorOpenLabel(title), exact: true })
							.click();
						await expect(songHeading).toBeVisible();
						name = 'Back to Home';
						destination = '/';
					}
					const back = bar.getByRole('button', { name, exact: true });
					await expect(back).toBeVisible();
					expect(title).toHaveLength(11);
					expect(await bar.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(
						true
					);
					const titleBox = await bar.getByRole('heading', { name: title }).boundingBox();
					const backBox = await back.boundingBox();
					if (!titleBox || !backBox) throw new Error('Expected title and Back');
					expect(backBox.x + backBox.width).toBeLessThanOrEqual(titleBox.x);
					await expect(phoneTabs(page)).toHaveCount(0);
					await expect(bar.getByRole('button', { name: 'Open menu' })).toHaveCount(0);
					const address = page.url();
					const length = await page.evaluate(() => history.length);
					for (const tab of [EDITOR_VIEW_COWRITER_LABEL, EDITOR_TAB_EDIT_LABEL]) {
						await page.getByRole('tab', { name: tab, exact: true }).click();
						await expect(page).toHaveURL(address);
						await expect(back).toBeVisible();
						expect(await page.evaluate(() => history.length)).toBe(length);
						await expect(workspace(page).getByRole('button', { name: /^Back to / })).toHaveCount(0);
					}
					await back.click();
					await expect(page).toHaveURL(new URL(destination, address).href);
					await expect(songHeading).toBeHidden();
					await expect(phoneTabs(page)).toBeVisible();
					expect(await page.evaluate(() => history.length)).toBe(length);
				}
			);
		}

		for (const choice of [
			DIALOG_CANCEL_LABEL,
			EDITOR_UNSAVED_DISCARD_LABEL,
			EDITOR_UNSAVED_SAVE_LABEL
		]) {
			test(
				`1354_61_C${choice === DIALOG_CANCEL_LABEL ? '13' : choice === EDITOR_UNSAVED_SAVE_LABEL ? '14' : '15'} 1354_rule_32: song ‹ asks first and honors ${choice}`,
				{ tag: ONLY_IN_SHELL.mobile },
				async ({ page }) => {
					const { songPhoneAlbumId } = readSeededLibrary();
					const { lyrics, savedLyrics, songHeading, unsavedDraftDialog } =
						await openSongWithAnUnsavedDraft(page, songPhoneAlbumId);
					const address = page.url();
					const draft = await lyrics.inputValue();
					await songBackButton(page).click();
					await expect(unsavedDraftDialog).toBeVisible();
					await expect(phoneTabs(page)).toHaveCount(0);
					await expect(page).toHaveURL(address);
					await unsavedDraftDialog.getByRole('button', { name: choice, exact: true }).click();
					await expect(unsavedDraftDialog).toBeHidden();
					if (choice === DIALOG_CANCEL_LABEL) {
						await expect(page).toHaveURL(address);
						await expect(songHeading).toBeVisible();
						await expect(lyrics).toHaveValue(draft);
						await expect(phoneTabs(page)).toHaveCount(0);
					} else {
						await expect(page).toHaveURL(new RegExp(`/album/${songPhoneAlbumId}$`));
						await expect(songHeading).toBeHidden();
						await expect(phoneTabs(page)).toBeVisible();
						await page.goForward();
						await expect(songHeading).toBeVisible();
						await expect(lyrics).toHaveValue(
							choice === EDITOR_UNSAVED_SAVE_LABEL ? draft : savedLyrics
						);
					}
				}
			);
		}

		test(
			'1354_61_C16 1354_rule_32: cold song ‹ names its album and asks before replacing the song',
			{ tag: ONLY_IN_SHELL.mobile },
			async ({ page, context, browser }) => {
				const { songPhoneAlbumId } = readSeededLibrary();
				const { lyrics, savedLyrics } = await openSongWithAnUnsavedDraft(page, songPhoneAlbumId);
				await lyrics.fill(savedLyrics);
				const address = page.url();
				const expectedName = await songBackButton(page).getAttribute('aria-label');
				if (!expectedName) throw new Error('Expected the song Back name');
				const coldContext = await browser.newContext({
					storageState: await context.storageState(),
					viewport: MOBILE_VIEWPORT,
					isMobile: true,
					hasTouch: true
				});
				try {
					const cold = await coldContext.newPage();
					await observeTabAttachments(cold);
					await cold.goto(address);
					const coldLyrics = cold.getByRole('textbox', { name: /^Lyrics/ });
					await expect(coldLyrics).toHaveValue(savedLyrics);
					expect(await cold.evaluate(() => Reflect.get(window, 'phoneTabAttachments'))).toEqual([]);
					await expect(cold.locator('.workspace-wrapper')).not.toHaveAttribute('inert');
					await coldLyrics.fill(UNSAVED_DRAFT_LINE);
					await expect(coldLyrics).toHaveValue(UNSAVED_DRAFT_LINE);
					const readHistoryIndex = () =>
						(window as unknown as { navigation: { currentEntry: { index: number } } }).navigation
							.currentEntry.index;
					const index = await cold.evaluate(readHistoryIndex);
					await cold
						.locator('.mobile-strip')
						.getByRole('button', { name: expectedName, exact: true })
						.click();
					const question = cold.getByRole('dialog', { name: EDITOR_UNSAVED_TITLE });
					await expect(question).toBeVisible();
					await expect(cold).toHaveURL(address);
					await question
						.getByRole('button', { name: EDITOR_UNSAVED_DISCARD_LABEL, exact: true })
						.click();
					await expect(cold).toHaveURL(new RegExp(`/album/${songPhoneAlbumId}$`));
					expect(await cold.evaluate(readHistoryIndex)).toBe(index);
					await expect(phoneTabs(cold)).toBeVisible();
				} finally {
					await coldContext.close();
				}
			}
		);

		test(
			'defect:#1598 1354_rule_32: typing during a held save stays unsaved and ‹ asks',
			{ tag: ONLY_IN_SHELL.mobile },
			async ({ page }) => {
				const { lyrics, unsavedDraftDialog } = await openSongWithAnUnsavedDraft(
					page,
					readSeededLibrary().songPhoneAlbumId
				);
				let releaseSave!: () => void;
				const held = new Promise<void>((resolve) => {
					releaseSave = resolve;
				});
				await page.route('**/api/songs/*', async (route) => {
					if (route.request().method() === 'PUT') await held;
					await route.continue();
				});
				const sent = page.waitForRequest(
					(request) => request.method() === 'PUT' && /\/api\/songs\/[^/]+$/.test(request.url())
				);
				try {
					await page.getByRole('button', { name: SONG_MENU_LABEL, exact: true }).click();
					await page
						.getByRole('dialog', { name: SONG_MENU_LABEL })
						.getByRole('button', { name: SONG_MENU_SAVE_LABEL, exact: true })
						.click();
					await sent;
					const draft = `${await lyrics.inputValue()}\nmore typing during save`;
					await lyrics.fill(draft);
					releaseSave();
					await expect(page.getByText(/^Saved version \d+$/)).toBeVisible();
					await expect(lyrics).toHaveValue(draft);
					await songBackButton(page).click();
					await expect(unsavedDraftDialog).toBeVisible();
					await expect(lyrics).toHaveValue(draft);
				} finally {
					releaseSave();
				}
			}
		);

		for (const dirty of [false, true]) {
			test(
				`1354_rule_30: browser Back closes search over a ${dirty ? 'dirty' : 'clean'} song first`,
				{ tag: ONLY_IN_SHELL.mobile },
				async ({ page }) => {
					const { lyrics, savedLyrics, unsavedDraftDialog, songHeading } =
						await openSongWithAnUnsavedDraft(page, readSeededLibrary().songPhoneAlbumId);
					if (!dirty) await lyrics.fill(savedLyrics);
					const draft = await lyrics.inputValue();
					const address = page.url();
					await page
						.locator('.mobile-strip')
						.getByRole('button', { name: words['phoneAppBar.searchOpen'], exact: true })
						.click();
					const search = page.getByRole('dialog', {
						name: words['phoneAppBar.searchSheet'],
						exact: true
					});
					await expect(search).toBeVisible();
					await page.goBack();
					await expect(search).toBeHidden();
					await expect(unsavedDraftDialog).toBeHidden();
					await expect(page).toHaveURL(address);
					await expect(songHeading).toBeVisible();
					await expect(lyrics).toHaveValue(draft);
				}
			);
		}

		test(
			'1354_rule_25: cold Settings ‹ replaces with Settings',
			{ tag: ONLY_IN_SHELL.mobile },
			async ({ page }) => {
				await page.goto('/settings/voices');
				const length = await page.evaluate(() => history.length);
				await page
					.locator('.mobile-strip')
					.getByRole('button', { name: 'Back to Settings', exact: true })
					.click();
				await expect(page).toHaveURL(/\/settings$/);
				expect(await page.evaluate(() => history.length)).toBe(length);
			}
		);
	});

	// The defect #1144 fixed reproduced on the desktop rail as well; the phone
	// rows above cover Search, this one the 1440 px rail's Settings group.
	test(
		'Discard on a desktop rail Settings link with an unsaved draft lands on the page (#1143)',
		{ tag: ONLY_IN_SHELL.desktop },
		async ({ page }) => {
			const library = readSeededLibrary();
			const { unsavedDraftDialog } = await openSongWithAnUnsavedDraft(
				page,
				library.songPhoneAlbumId
			);

			await openSettingsSection(page, 'desktop', SETTINGS_SECTION);
			await expect(unsavedDraftDialog).toBeVisible();
			await unsavedDraftDialog
				.getByRole('button', { name: EDITOR_UNSAVED_DISCARD_LABEL, exact: true })
				.click();

			await expect(page).toHaveURL(/\/settings\/generation$/);
			await expect(page.getByRole('heading', { name: SETTINGS_SECTION, level: 1 })).toBeVisible();
		}
	);
});

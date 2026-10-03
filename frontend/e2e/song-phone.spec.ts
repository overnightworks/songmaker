// The song page at phone width (issue #995, #914's ruled sentence L12):
// a Takes list with a real play control per take, a running generation's
// progress in both the Generate button and the Takes status slot, and a
// failed generation's literal worker sentence. Mobile project only —
// everything this proves (the compact Edit/Takes tabs, the phone status
// slot, the button's own failure state) is compact-shell UI with no desktop
// counterpart to exercise, the same reason kinetic-strip.spec.ts gives for
// staying desktop-only. The one desktop row is the unsaved-draft dialog on
// the rail's Settings group, which shares the phone rows' arrangement (#1143).
//
// CI's e2e stack (docker-compose.ci.yml) runs no ACE-Step worker, so every
// job state below is seeded directly against the database
// (scripts/seed_e2e_job_states.py) rather than produced by a real
// generation — the same reasoning kinetic-strip.spec.ts's own takes and the
// rail's filler albums already use (issue #344). The running job is failed
// on the *same* job id while its SSE stream is still open
// (/api/jobs/{id}/stream polls the row every second), so the frontend picks
// up the transition live, the way a real worker crash would report it — no
// reload, and no dependence on the reaper ever running.
//
// The same absent worker also means `GET /health` reports
// `acestep_workers_online: 0`, and `generateAction`'s derivation (see its own
// comment) treats that as an unconditional disabled reason that outranks a
// failed job's cause — so without help, the failed-job assertion below would
// never see anything but "No ACE-Step worker online". A narrowly scoped
// `page.route` on `**/health` reports one worker online for this page only,
// standing in for the seeded heartbeat a real worker would publish, so the
// failed generation's own persistent UI is what's on screen instead.

import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import {
	DIALOG_CANCEL_LABEL,
	EDITOR_GENERATE_FAILURE_COLLAPSE_LABEL,
	EDITOR_GENERATE_FAILURE_EXPAND_LABEL,
	EDITOR_GENERATE_TAKE_TEMPLATE,
	EDITOR_TAB_EDIT_LABEL,
	EDITOR_UNSAVED_DISCARD_LABEL,
	EDITOR_UNSAVED_TITLE,
	GENERATION_PHASE_LABELS,
	HITBOX_FREQUENT_PX,
	NOW_PLAYING_CLOSE,
	openNowPlayingLabel,
	RAIL_LIBRARY_LABEL,
	TRANSPORT_PLAY_LABEL
} from '../src/lib/constants';
import {
	NOW_PLAYING_RIGHT_PANEL_LABEL,
	NOW_PLAYING_TAKE_TAB,
	nowPlayingOpenSourceLabel,
	nowPlayingTakeLabel,
	takeGroupLabel,
	takeRowLabel
} from '../src/lib/constants/now-playing';
import {
	boundingBoxes,
	containing,
	FlowGuard,
	nameStartingWith,
	openRailNav,
	openSettingsSection,
	openSettingsSectionFromDrawerSearch,
	playlistEntryRows,
	SONG_PHONE_FLOW_API_REQUEST_BUDGET,
	workspace
} from './helpers';
import {
	advanceGenerationJobPhase,
	failGenerationJob,
	readSeededLibrary,
	runMarker,
	seedPlaylist,
	seedRunningGenerationJob,
	seedSongPhoneSong
} from './seed';

const SONG_PHONE_SONG_TITLE = 'Song Phone Takes';
const ACCOUNT_SECTION = 'Account';
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
const FAILED_GENERATION_SENTENCE = 'ACE-Step worker: CUDA out of memory on device 0';
const UNSAVED_DRAFT_LINE = 'a line nobody saved';

interface SongWithAnUnsavedDraft {
	songHeading: Locator;
	lyrics: Locator;
	savedLyrics: string;
	unsavedDraftDialog: Locator;
}

async function openSongWithAnUnsavedDraft(
	page: Page,
	albumId: string
): Promise<SongWithAnUnsavedDraft> {
	const title = `${SONG_PHONE_SONG_TITLE} ${runMarker()} draft`;
	await seedSongPhoneSong(albumId, title, 1, 1);
	const songHeading = page.getByRole('heading', { name: title });
	const lyrics = page.getByRole('textbox', { name: /^Lyrics/ });
	await page.goto(`/album/${albumId}`);
	await workspace(page)
		.getByRole('button', { name: nameStartingWith(title) })
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
	test('lists takes with a play control each, shows a running generation, then its failure', async ({
		page,
		isMobile
	}) => {
		test.skip(!isMobile, 'Mobile-only compact-shell UI; see the file header.');
		// Stands in for the absent worker's own heartbeat (see the file header):
		// every /health this page makes reports one online, so generateAction's
		// disabled-reason check never masks the failed job below.
		await page.route('**/health', async (route) => {
			const response = await route.fetch();
			const body = (await response.json()) as Record<string, unknown>;
			await route.fulfill({
				response,
				json: { ...body, acestep_workers_online: 1, acestep_workers_total: 1 }
			});
		});
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
		await expect(
			panel.getByText(takeGroupLabel(SONG_PHONE_VERSION_NUMBER, SONG_PHONE_TAKE_COUNT))
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
		// player names the take on Now Playing, opened from the bar's title.
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
		await page.goto(songAddress);
		// The song comes back on the Takes tab it was left on (#1047); the
		// Generate status lives on Edit.
		await page.getByRole('tab', { name: EDITOR_TAB_EDIT_LABEL }).click();
		const generateStatus = panel.getByRole('status');
		await expect(generateStatus).toHaveText(
			`${RUNNING_JOB_TAKE_COUNTER} · ${LOADING_JOB_PHASE_LABEL}`
		);

		await page.getByRole('tab', { name: /Takes/ }).click();
		await expect(panel.getByRole('progressbar')).toBeVisible();
		await expect(panel.getByText(LOADING_JOB_PHASE_LABEL, { exact: true })).toBeVisible();
		await expect(panel.getByText(RUNNING_JOB_TAKE_COUNTER, { exact: true })).toBeVisible();
		await expect(panel.getByText(REMAINING_TIME_PATTERN)).toHaveCount(0);

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
		await failGenerationJob(jobId, FAILED_GENERATION_SENTENCE);
		await expect(panel.getByText(FAILED_GENERATION_SENTENCE)).toBeVisible();
		// The same failure also raises a toast (ToastContainer.svelte) that
		// overlaps the expand button until it is dismissed or its own 5s timer
		// runs out — dismiss it explicitly so the click below isn't racing that
		// timer.
		await page.getByRole('alert').getByRole('button', { name: 'Dismiss' }).click();
		await panel.getByRole('button', { name: EDITOR_GENERATE_FAILURE_EXPAND_LABEL }).click();
		await expect(
			panel.getByRole('button', { name: EDITOR_GENERATE_FAILURE_COLLAPSE_LABEL })
		).toBeVisible();

		console.log(`Song-phone flow /api requests: ${guard.apiRequestCount}`);
		guard.assertClean();
		guard.assertWithinBudget(SONG_PHONE_FLOW_API_REQUEST_BUDGET);
	});

	// Issue #1047: the tab choice is remembered per song for the session; a
	// song opened for the first time lands on Edit, and a reload restores the
	// tab the open song was left on. The phone song page has no previous/next
	// control (#970), so stepping between songs is proven in navigation.test.ts.
	test('remembers each song tab, opens a fresh song on Edit, and keeps the tab on reload', async ({
		page,
		isMobile
	}) => {
		test.skip(!isMobile, 'Mobile-only compact-shell UI; see the file header.');
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
				.getByRole('button', { name: nameStartingWith(title) })
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
	});

	test('a drawer album tap with an unsaved draft asks first: Cancel keeps the draft, Discard leaves (#1143)', async ({
		page,
		isMobile
	}) => {
		test.skip(!isMobile, 'Mobile-only compact-shell UI; see the file header.');
		const library = readSeededLibrary();
		const { songHeading, lyrics, savedLyrics, unsavedDraftDialog } =
			await openSongWithAnUnsavedDraft(page, library.songPhoneAlbumId);
		const tapTheOtherAlbumInTheDrawer = async () => {
			const rail = await openRailNav(page, 'mobile');
			await rail.getByRole('button', { name: containing(library.secondAlbumTitle) }).click();
			await expect(unsavedDraftDialog).toBeVisible();
		};

		await tapTheOtherAlbumInTheDrawer();
		await unsavedDraftDialog
			.getByRole('button', { name: DIALOG_CANCEL_LABEL, exact: true })
			.click();
		await expect(unsavedDraftDialog).toBeHidden();
		await expect(songHeading).toBeVisible();
		await expect(lyrics).toHaveValue(new RegExp(`${UNSAVED_DRAFT_LINE}$`));

		await tapTheOtherAlbumInTheDrawer();
		await unsavedDraftDialog
			.getByRole('button', { name: EDITOR_UNSAVED_DISCARD_LABEL, exact: true })
			.click();
		await expect(
			workspace(page).getByRole('heading', { name: library.secondAlbumTitle })
		).toBeVisible();

		await page.goBack();
		await expect(songHeading).toBeVisible();
		await expect(lyrics).toHaveValue(savedLyrics);
	});

	test('Discard on a Settings page from the drawer search lands on its address, which a reload keeps (#1143)', async ({
		page,
		isMobile
	}) => {
		test.skip(!isMobile, 'Mobile-only compact-shell UI; see the file header.');
		const library = readSeededLibrary();
		const { unsavedDraftDialog } = await openSongWithAnUnsavedDraft(page, library.songPhoneAlbumId);

		await openSettingsSectionFromDrawerSearch(page, ACCOUNT_SECTION);
		await expect(unsavedDraftDialog).toBeVisible();
		await unsavedDraftDialog
			.getByRole('button', { name: EDITOR_UNSAVED_DISCARD_LABEL, exact: true })
			.click();

		const accountHeading = page.getByRole('heading', { name: ACCOUNT_SECTION, level: 1 });
		await expect(page).toHaveURL(/\/settings\/account$/);
		await expect(accountHeading).toBeVisible();
		await page.reload();
		await expect(page).toHaveURL(/\/settings\/account$/);
		await expect(accountHeading).toBeVisible();
	});

	test('Back with an unsaved draft asks first: Cancel keeps the draft on the song, Discard leaves without saving (#1143)', async ({
		page,
		isMobile
	}) => {
		test.skip(!isMobile, 'Mobile-only compact-shell UI; see the file header.');
		const library = readSeededLibrary();
		const { songHeading, lyrics, savedLyrics, unsavedDraftDialog } =
			await openSongWithAnUnsavedDraft(page, library.songPhoneAlbumId);
		const songAddress = page.url();

		await page.goBack();
		await expect(unsavedDraftDialog).toBeVisible();
		await expect(page).toHaveURL(songAddress);
		await unsavedDraftDialog
			.getByRole('button', { name: DIALOG_CANCEL_LABEL, exact: true })
			.click();
		await expect(unsavedDraftDialog).toBeHidden();
		await expect(page).toHaveURL(songAddress);
		await expect(songHeading).toBeVisible();
		await expect(lyrics).toHaveValue(new RegExp(`${UNSAVED_DRAFT_LINE}$`));

		await page.goBack();
		await expect(unsavedDraftDialog).toBeVisible();
		await unsavedDraftDialog
			.getByRole('button', { name: EDITOR_UNSAVED_DISCARD_LABEL, exact: true })
			.click();
		await expect(page).toHaveURL(new RegExp(`/album/${library.songPhoneAlbumId}$`));
		await expect(songHeading).toBeHidden();

		await page.goForward();
		await expect(songHeading).toBeVisible();
		await expect(lyrics).toHaveValue(savedLyrics);
	});

	// The defect #1144 fixed reproduced on the desktop rail as well; the phone
	// rows above cover the drawer, this one the 1440 px rail's Settings group.
	test('Discard on a desktop rail Settings link with an unsaved draft lands on the page (#1143)', async ({
		page,
		isMobile
	}) => {
		test.skip(isMobile, 'Desktop rail Settings group; the phone reaches Settings above.');
		const library = readSeededLibrary();
		const { unsavedDraftDialog } = await openSongWithAnUnsavedDraft(page, library.songPhoneAlbumId);

		await openSettingsSection(page, 'desktop', ACCOUNT_SECTION);
		await expect(unsavedDraftDialog).toBeVisible();
		await unsavedDraftDialog
			.getByRole('button', { name: EDITOR_UNSAVED_DISCARD_LABEL, exact: true })
			.click();

		await expect(page).toHaveURL(/\/settings\/account$/);
		await expect(page.getByRole('heading', { name: ACCOUNT_SECTION, level: 1 })).toBeVisible();
	});
});

// Leaving Now Playing on the phone (issue #1002): the full surface is a
// pushed screen, so the phone's Back -- and × right after open -- shows the
// screen it was opened from again, never the entry below that screen, and
// leaves no copy of it behind for the next Back to land on. A take row opens
// Now Playing on This take with its sheet up, whose backdrop never covers ×
// (#1052), so one tap on × closes Now Playing there too; Back closes that sheet
// first and Now Playing with the next one (#1119). A playlist row only
// plays in place (#1010), so that origin opens Now Playing through the
// mini-player's own entry, which brings no sheet up.
// The base library's songs each carry one reimported take, their first.
const SEEDED_TAKE_NUMBER = 1;

interface NowPlayingOrigin {
	playing: string;
	origin: Locator;
	cameFrom: Locator;
	opensOnTakeSheet: boolean;
}

const NOW_PLAYING_ORIGINS: {
	name: string;
	openFromRow: (page: Page, request: APIRequestContext) => Promise<NowPlayingOrigin>;
}[] = [
	{
		name: 'a playlist opened from the wall',
		openFromRow: async (page, request) => {
			const playlist = await seedPlaylist(request, readSeededLibrary());
			const [playing] = playlist.songTitles;
			await page.goto('/');
			await workspace(page)
				.locator('.library-wall .tile-grid')
				.locator('.wall-tile-body')
				.filter({ hasText: playlist.title })
				.click();
			const origin = workspace(page).getByRole('heading', { name: playlist.title });
			await expect(origin).toBeVisible();
			const playedCard = playlistEntryRows(page).first();
			const playedCardBox = await playedCard.boundingBox();
			if (!playedCardBox) throw new Error('Expected a visible playlist row');
			await playedCard.tap({ position: { x: 4, y: playedCardBox.height - 4 } });
			await expect(page.getByRole('contentinfo').getByText(playing)).toBeVisible();
			await expect(origin).toBeVisible();
			await expect(page.getByRole('tab', { name: NOW_PLAYING_TAKE_TAB })).toBeHidden();
			await page
				.getByRole('contentinfo')
				.getByRole('button', { name: openNowPlayingLabel(playing), exact: true })
				.click();
			return {
				playing,
				origin,
				cameFrom: workspace(page).getByRole('heading', { name: RAIL_LIBRARY_LABEL }),
				opensOnTakeSheet: false
			};
		}
	},
	{
		name: 'a song opened from its album',
		openFromRow: async (page) => {
			const library = readSeededLibrary();
			const playing = library.pickedSongTitle;
			await page.goto(`/album/${library.albumId}`);
			await workspace(page)
				.getByRole('button', { name: nameStartingWith(playing) })
				.click();
			const origin = page.getByRole('heading', { name: playing });
			await expect(origin).toBeVisible();
			await page.getByRole('tab', { name: /Takes/ }).click();
			await page
				.getByRole('tabpanel')
				.getByRole('button', { name: nameStartingWith(takeRowLabel(SEEDED_TAKE_NUMBER)) })
				.click();
			await expect(page.getByRole('tab', { name: NOW_PLAYING_TAKE_TAB })).toBeVisible();
			return {
				playing,
				origin,
				cameFrom: workspace(page).getByRole('heading', { name: library.albumTitle }),
				opensOnTakeSheet: true
			};
		}
	}
];

const NOW_PLAYING_LEAVES: {
	name: string;
	leave: (page: Page, opened: NowPlayingOrigin) => Promise<void>;
}[] = [
	{
		name: 'Back',
		leave: async (page, { playing, opensOnTakeSheet }) => {
			if (opensOnTakeSheet) {
				await page.goBack();
				await expect(
					page.getByRole('dialog', { name: NOW_PLAYING_RIGHT_PANEL_LABEL })
				).toBeHidden();
				await expect(page.getByRole('dialog', { name: playing })).toBeVisible();
			}
			await page.goBack();
		}
	},
	{
		// A reload -- or a phone restoring a tab it discarded -- drops the open
		// Now Playing, and the sheet over it, but not their history entries;
		// once its library has loaded the app steps back off each of them onto
		// an entry no layer marks, and Back is meant from then on.
		name: 'a reload',
		leave: async (page) => {
			await page.addInitScript(() => {
				window.addEventListener('popstate', () => {
					if (history.state?.layer === undefined) {
						document.documentElement.setAttribute('data-e2e-stepped-back', '');
					}
				});
			});
			await page.reload();
			await expect(page.locator('html[data-e2e-stepped-back]')).toBeAttached();
		}
	},
	{
		name: '× right after open',
		leave: async (page, { playing, opensOnTakeSheet }) => {
			const takeSheet = page.getByRole('dialog', { name: NOW_PLAYING_RIGHT_PANEL_LABEL });
			if (opensOnTakeSheet) await expect(takeSheet).toBeVisible();
			await page
				.getByRole('dialog', { name: playing })
				.getByRole('button', { name: NOW_PLAYING_CLOSE, exact: true })
				.tap();
		}
	}
];

test.describe('leaving Now Playing at phone width', () => {
	for (const { name: originName, openFromRow } of NOW_PLAYING_ORIGINS) {
		for (const { name: leaveName, leave } of NOW_PLAYING_LEAVES) {
			test(`${leaveName} from Now Playing shows ${originName} again`, async ({
				page,
				request,
				isMobile
			}) => {
				test.skip(!isMobile, 'Mobile-only compact-shell UI; see the file header.');
				const guard = new FlowGuard(page);
				const opened = await openFromRow(page, request);
				const { origin, cameFrom } = opened;
				const nowPlaying = page.getByRole('dialog', { name: opened.playing });
				await expect(nowPlaying).toBeVisible();
				const originAddress = page.url();

				await leave(page, opened);

				await expect(nowPlaying).toBeHidden();
				await expect(origin).toBeVisible();
				expect(page.url()).toBe(originAddress);

				await page.goBack();
				await expect(cameFrom).toBeVisible();
				guard.assertClean();
			});
		}
	}
});

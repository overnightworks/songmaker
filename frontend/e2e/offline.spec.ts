// Network loss: phone Generate placement (#1039) and generation recovery (#1098),
// plus server, take-play (#1161) and album-start (#1288) recovery in both shells.
// loseNetwork also closes open streams; setOffline alone leaves them running.

import { expect, test, type Locator, type Page, type Route } from '@playwright/test';
import {
	collectionActionLabel,
	EDITOR_GENERATE_CANCEL_OFFLINE_LABEL,
	EDITOR_GENERATE_LAST_SEEN_PROGRESS_LABEL,
	EDITOR_GENERATE_LABEL,
	EDITOR_GENERATE_RECONNECTING_LABEL,
	EDITOR_GENERATE_TAKE_TEMPLATE,
	RESOURCE_EVENT_STREAM_PATH,
	RESOURCE_SYNC_ERROR,
	RESOURCE_SYNC_RETURN_PROBE_INTERVAL_MS,
	SSE_RECONNECT_JITTER_RATIO,
	SSE_RECONNECT_MAX_DELAY_MS,
	TRANSPORT_PAUSE_LABEL,
	TRANSPORT_PLAY_LABEL,
	TRANSPORT_RETRY_LABEL,
	songEditorOpenLabel
} from '../src/lib/constants';
import {
	boundingBoxes,
	sameOriginHeaders,
	FlowGuard,
	loseNetwork,
	offlineStrip, // 1354_65_A3: shared status locator for the offline proofs.
	OFFLINE_FLOW_API_REQUEST_BUDGET,
	OFFLINE_RUNNING_TAKE_FLOW_API_REQUEST_BUDGET,
	ONLY_IN_SHELL,
	nameStartingWith,
	regainNetwork,
	workspace,
	HOME_PATH
} from './helpers';
import {
	advanceGenerationJobPhase,
	completeGenerationJobWithoutEvent,
	readSeededLibrary,
	runMarker,
	seedRunningGenerationJob,
	seedQueuedGenerationJob,
	seedSongPhoneSong
} from './seed';

const OFFLINE_SONG_TITLE = 'Offline Strip';
// The ruled "within about a second" of losing the network.
const OFFLINE_NOTICE_MS = 1_500;
// The ruling on #1032: back online, the page has caught up within 10 seconds.
const BACK_ONLINE_MS = 10_000;
// The player's first stall look comes 5 s after Play; a take tapped offline
// already says 'recovering' from the tap (#1312), and still does after it.
const FIRST_STALL_LOOK_MS = 10_000;
const TAKE_AUDIO_PATH_PREFIX = '/audio/';
// The request an album start makes for a song's takes (`fetchSong`).
const SONG_TAKES_PATH = /^\/api\/songs\/[^/]+$/;
// The deck's contract (continuousDeck.ts): three downloads in a row fail,
// then it parks until the player retries.
const DECK_DOWNLOAD_ATTEMPTS = 3;
// The ruling on #1099: a server that comes back while the browser stayed
// online is found by the page's return probe, at most one interval until it
// asks and one more for its answer -- about 2 seconds.
const SERVER_BACK_MS = 2 * RESOURCE_SYNC_RETURN_PROBE_INTERVAL_MS;
const RESOURCE_STREAM = `**${RESOURCE_EVENT_STREAM_PATH}**`;
const SESSION_CHECK = '**/api/auth/me';
const GENERATE_LABEL = EDITOR_GENERATE_LABEL;
// The toast a generate job's end raises (`notifyTerminalJob` in stores/jobs.ts).
const JOB_COMPLETED_TOAST = 'generate completed';
// The ride through three tunnels on #1039's final drive (#1141).
const OUTAGES_IN_ONE_RIDE = 3;
// What each outage past the first adds to the running-take flow's cost: the
// session check's once-a-second probe and the job stream's and song refresh's
// refused retries while the network is gone, and the streams that reopen on
// its return. The probe count follows how long each outage lasts; CI run
// 36716007334 (30.09.2026) measured 48 and 50 for the whole three-outage flow.
const API_REQUESTS_PER_FURTHER_OUTAGE = 10;
const THREE_OUTAGES_FLOW_API_REQUEST_BUDGET =
	OFFLINE_RUNNING_TAKE_FLOW_API_REQUEST_BUDGET +
	(OUTAGES_IN_ONE_RIDE - 1) * API_REQUESTS_PER_FURTHER_OUTAGE;
const JOB_STREAM_PATH = /^\/api\/jobs\/[^/]+\/stream$/;
// The job stream's next reopen comes at most one jittered backoff ceiling
// later, and its first message after the server's first poll.
const NEXT_JOB_STREAM_REOPEN_MS =
	SSE_RECONNECT_MAX_DELAY_MS * (1 + SSE_RECONNECT_JITTER_RATIO) + OFFLINE_NOTICE_MS;
// Playwright's default 30 s, plus the refused reopens and the one that answers.
const REFUSED_JOB_STREAM_TEST_TIMEOUT_MS = 30_000 + 2 * NEXT_JOB_STREAM_REOPEN_MS;

function generateButton(page: Page): Locator {
	return page.getByRole('tabpanel').getByRole('button', { name: nameStartingWith(GENERATE_LABEL) });
}

/** What a colour token resolves to on the page right now, as `getComputedStyle` reports it. */
function resolvedToken(page: Page, token: string): Promise<string> {
	return page.evaluate((name) => {
		const probe = document.createElement('span');
		probe.style.color = `var(${name})`;
		document.body.append(probe);
		const color = getComputedStyle(probe).color;
		probe.remove();
		return color;
	}, token);
}

type ServerAnswer = (route: Route) => Promise<void>;

/**
 * The server fails right after the page has checked its session: the live
 * stream and every later session check -- the probe that tells the page
 * whether the server is there at all -- get `answer` until `serverReturns`.
 * Returns how many of those later checks it has answered so far.
 */
async function serverFailsAfterSessionCheck(
	page: Page,
	answer: ServerAnswer
): Promise<() => number> {
	let sessionChecked = false;
	let answeredChecks = 0;
	await page.route(RESOURCE_STREAM, answer);
	await page.route(SESSION_CHECK, (route) => {
		if (!sessionChecked) {
			sessionChecked = true;
			return route.continue();
		}
		answeredChecks += 1;
		return answer(route);
	});
	return () => answeredChecks;
}

/** Answers a job stream once with where the job stands, then ends it the way a dropped connection does. */
async function answerOnceAndDrop(route: Route): Promise<void> {
	const jobRecord = route
		.request()
		.url()
		.replace(/\/stream$/, '');
	const job: unknown = await (await route.fetch({ url: jobRecord })).json();
	await route.fulfill({
		status: 200,
		contentType: 'text/event-stream',
		body: `data: ${JSON.stringify(job)}\n\n`
	});
}

interface LockScreenMoment {
	title: string | null;
	state: MediaSessionPlaybackState;
}

interface LockScreenWindow {
	lockScreen: { moments: LockScreenMoment[]; press: (action: MediaSessionAction) => void };
}

// A locked phone shows only the page's media session: the page writes down
// every title and state it hands the session, and keeps the actions it
// installs there so the flow can press them as the lock screen would.
async function watchTheLockScreen(page: Page): Promise<void> {
	await page.addInitScript(() => {
		const session = navigator.mediaSession;
		const prototype = Object.getPrototypeOf(session) as MediaSession;
		const metadata = Object.getOwnPropertyDescriptor(prototype, 'metadata');
		const state = Object.getOwnPropertyDescriptor(prototype, 'playbackState');
		if (!metadata?.get || !metadata.set || !state?.get || !state.set)
			throw new Error('The media session has no metadata or playbackState accessors');
		const readMetadata = metadata.get;
		const writeMetadata = metadata.set;
		const readState = state.get;
		const writeState = state.set;
		const moments: LockScreenMoment[] = [];
		const noteTheMoment = () =>
			moments.push({
				title: (readMetadata.call(session) as MediaMetadata | null)?.title ?? null,
				state: readState.call(session) as MediaSessionPlaybackState
			});
		Object.defineProperty(session, 'metadata', {
			configurable: true,
			get: () => readMetadata.call(session),
			set: (value: MediaMetadata | null) => {
				writeMetadata.call(session, value);
				noteTheMoment();
			}
		});
		Object.defineProperty(session, 'playbackState', {
			configurable: true,
			get: () => readState.call(session),
			set: (value: MediaSessionPlaybackState) => {
				writeState.call(session, value);
				noteTheMoment();
			}
		});
		const actions = new Map<MediaSessionAction, MediaSessionActionHandler | null>();
		const setActionHandler = session.setActionHandler.bind(session);
		session.setActionHandler = (action, handler) => {
			actions.set(action, handler);
			setActionHandler(action, handler);
		};
		(window as unknown as LockScreenWindow).lockScreen = {
			moments,
			press: (action) => {
				const handler = actions.get(action);
				if (!handler) throw new Error(`The page installed no lock-screen ${action}`);
				handler({ action });
			}
		};
	});
}

function lockScreenMoments(page: Page): Promise<LockScreenMoment[]> {
	return page.evaluate(() => (window as unknown as LockScreenWindow).lockScreen.moments);
}

async function lockScreenNow(page: Page): Promise<LockScreenMoment | undefined> {
	return (await lockScreenMoments(page)).at(-1);
}

function pressOnTheLockScreen(page: Page, action: MediaSessionAction): Promise<void> {
	return page.evaluate((pressed) => {
		(window as unknown as LockScreenWindow).lockScreen.press(pressed);
	}, action);
}

async function serverReturns(page: Page): Promise<void> {
	await page.unroute(RESOURCE_STREAM);
	await page.unroute(SESSION_CHECK);
}

test.describe('losing the network on the phone', { tag: ONLY_IN_SHELL.mobile }, () => {
	test('shows one calm strip on the mini player, disables Generate above it, and goes by itself once back online', async ({
		page,
		context
	}) => {
		const guard = new FlowGuard(page, { losesNetworkOnPurpose: true });
		const library = readSeededLibrary();
		const songTitle = `${OFFLINE_SONG_TITLE} ${runMarker()}`;
		await seedSongPhoneSong(library.songPhoneAlbumId, songTitle, 1, 1);
		const generate = generateButton(page);
		const miniPlayer = page.getByRole('contentinfo');

		await page.goto(`/album/${library.songPhoneAlbumId}`);
		await workspace(page)
			.getByRole('button', { name: songEditorOpenLabel(songTitle) })
			.click();
		await expect(page.getByRole('heading', { name: songTitle })).toBeVisible();
		await expect(generate).toHaveAccessibleName(GENERATE_LABEL);
		await expect(offlineStrip(page)).toHaveCount(0);

		await loseNetwork(page, context);

		await expect(offlineStrip(page)).toBeVisible({ timeout: OFFLINE_NOTICE_MS });
		await expect(offlineStrip(page).getByRole('button')).toHaveCount(0);
		await expect(generate).toBeDisabled();
		await expect(generate).toHaveAccessibleName(GENERATE_LABEL);
		await expect(generate).not.toContainText('ⓘ');
		await expect(page.getByText(RESOURCE_SYNC_ERROR)).toHaveCount(0);
		const [generateBox, stripBox, miniPlayerBox] = await boundingBoxes(
			generate,
			offlineStrip(page),
			miniPlayer
		);
		expect(generateBox.y + generateBox.height).toBeLessThanOrEqual(stripBox.y);
		expect(stripBox.y + stripBox.height).toBeCloseTo(miniPlayerBox.y, 0);

		await regainNetwork(page, context);

		await expect(offlineStrip(page)).toHaveCount(0, { timeout: BACK_ONLINE_MS });
		await expect(generate).toHaveAccessibleName(GENERATE_LABEL);
		await expect(page.getByText(RESOURCE_SYNC_ERROR)).toHaveCount(0);

		console.log(`Offline flow /api requests: ${guard.apiRequestCount}`);
		guard.assertClean();
		guard.assertWithinBudget(OFFLINE_FLOW_API_REQUEST_BUDGET);
	});
});

test.describe('a server the online browser cannot reach', () => {
	for (const [failure, answer] of [
		['refuses the connection', (route: Route) => route.abort('connectionrefused')],
		['answers 502', (route: Route) => route.fulfill({ status: 502, body: 'bad gateway' })]
	] as const) {
		test(`shows the same calm strip while the server ${failure} as the page loads, and drops it within about 2 s of the server's return`, async ({
			page
		}) => {
			await serverFailsAfterSessionCheck(page, answer);
			await page.goto(HOME_PATH);

			await expect(offlineStrip(page)).toBeVisible();
			await expect(page.getByText(RESOURCE_SYNC_ERROR)).toHaveCount(0);

			await serverReturns(page);

			await expect(offlineStrip(page)).toHaveCount(0, { timeout: SERVER_BACK_MS });
			await expect(page.getByText(RESOURCE_SYNC_ERROR)).toHaveCount(0);
		});
	}

	test('shows no strip while the server answers the live stream and its session check with a rate limit', async ({
		page
	}) => {
		const answeredSessionChecks = await serverFailsAfterSessionCheck(page, (route) =>
			route.fulfill({ status: 429, body: 'too many requests' })
		);
		await page.goto(HOME_PATH);

		// The second rate-limited check follows the stream's first retry, long
		// after the page acted on the first one.
		await expect.poll(answeredSessionChecks, { timeout: BACK_ONLINE_MS }).toBeGreaterThanOrEqual(2);
		await expect(offlineStrip(page)).toHaveCount(0);
	});
});

test.describe(
	'losing the network while a take plays on the phone',
	{ tag: ONLY_IN_SHELL.mobile },
	() => {
		test('rests the strip above the mini player without moving or covering its transport', async ({
			page,
			context
		}) => {
			const library = readSeededLibrary();
			const songTitle = `${OFFLINE_SONG_TITLE} Playing ${runMarker()}`;
			await seedSongPhoneSong(library.songPhoneAlbumId, songTitle, 1, 1);
			const miniPlayer = page.getByRole('contentinfo');
			const pause = miniPlayer.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true });

			await openOfflineTakes(page, library.songPhoneAlbumId, songTitle);
			await page
				.getByRole('tabpanel')
				.getByRole('button', { name: new RegExp(`^${TRANSPORT_PLAY_LABEL} v`) })
				.click();
			await expect(pause).toBeVisible();
			const [miniPlayerOnline, pauseOnline] = await boundingBoxes(miniPlayer, pause);

			// The browser's own offline event is what raises the strip here: stopping
			// the page's loads as `loseNetwork` does would end the take's audio too.
			await page.route(RESOURCE_STREAM, (route) => route.abort('internetdisconnected'));
			await context.setOffline(true);
			await expect(offlineStrip(page)).toBeVisible({ timeout: OFFLINE_NOTICE_MS });

			const [stripBox, miniPlayerOffline, pauseOffline] = await boundingBoxes(
				offlineStrip(page),
				miniPlayer,
				pause
			);
			expect(miniPlayerOffline).toEqual(miniPlayerOnline);
			expect(pauseOffline).toEqual(pauseOnline);
			expect(stripBox.y + stripBox.height).toBeLessThanOrEqual(miniPlayerOffline.y);

			await page.unroute(RESOURCE_STREAM);
			await context.setOffline(false);
			await expect(offlineStrip(page)).toHaveCount(0, { timeout: BACK_ONLINE_MS });
		});
	}
);

// Offline, a take with no bytes yet waits instead of offering Retry (#1282):
// its download parks after its attempts, the player's stall looks wait
// without asking again while the network is announced gone, and the
// transport keeps its spinner until the network's return resumes the take.
// From the tap it shows the album header start's waiting transport, Pause
// with its spinner (#1312), on the phone and the desktop alike.
test.describe('tapping a take row Play while the network is gone', () => {
	test('waits with Pause and its spinner from the tap and no Retry, and plays the take by itself once the network is back (#1161 R2, #1312)', async ({
		page,
		context,
		isMobile
	}) => {
		const guard = new FlowGuard(page, { losesNetworkOnPurpose: true });
		const library = readSeededLibrary();
		const songTitle = `${OFFLINE_SONG_TITLE} Tapped ${runMarker()}`;
		await seedSongPhoneSong(library.songPhoneAlbumId, songTitle, 1, 1);
		const transport = page.getByRole('contentinfo');
		const pause = transport.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true });
		const retry = transport.getByRole('button', { name: TRANSPORT_RETRY_LABEL, exact: true });
		const spinner = transport.locator('.play-btn .spinner');
		const waitingSpinner = pause.locator('.spinner');
		const takeRowPlay = workspace(page)
			.locator('.take-row')
			.getByRole('button', { name: new RegExp(`^${TRANSPORT_PLAY_LABEL} v`) });

		await page.goto(`/album/${library.songPhoneAlbumId}`);
		await workspace(page)
			.getByRole('button', { name: songEditorOpenLabel(songTitle) })
			.click();
		if (isMobile) await page.getByRole('tab', { name: /Takes/ }).click();
		await expect(page).toHaveURL(new RegExp(`/album/${library.songPhoneAlbumId}/[^/]+$`));
		await expect(takeRowPlay).toBeVisible();

		await loseNetwork(page, context);
		await expect(offlineStrip(page)).toBeVisible({ timeout: OFFLINE_NOTICE_MS });
		let offlineAudioRequests = 0;
		page.on('request', (sent) => {
			if (new URL(sent.url()).pathname.startsWith(TAKE_AUDIO_PATH_PREFIX))
				offlineAudioRequests += 1;
		});
		await takeRowPlay.click();
		await expect(waitingSpinner).toBeVisible();
		await expect.poll(() => offlineAudioRequests).toBe(DECK_DOWNLOAD_ATTEMPTS);
		await expect(waitingSpinner).toBeVisible({ timeout: FIRST_STALL_LOOK_MS });
		expect(offlineAudioRequests).toBe(DECK_DOWNLOAD_ATTEMPTS);
		await expect(retry).toHaveCount(0);
		await expect(page.getByRole('alert')).toHaveCount(0);

		await regainNetwork(page, context);

		await expect(spinner).toHaveCount(0, { timeout: BACK_ONLINE_MS });
		await expect(pause).toBeVisible();
		await expect(retry).toHaveCount(0);
		guard.assertClean();
	});
});

// Offline, the album header Play no longer drops silently when the album's
// takes cannot be read (#1288): the bar holds its start notice and the
// waiting transport with no toast, and the album starts by itself once the
// network is back.
test.describe('pressing the album header Play while the network is gone', () => {
	function headerStartControls(page: Page) {
		const transport = page.getByRole('contentinfo');
		return {
			transport,
			barPause: transport.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true }),
			play: workspace(page).getByRole('button', {
				name: collectionActionLabel(TRANSPORT_PLAY_LABEL, 'album'),
				exact: true
			}),
			headerPause: workspace(page).getByRole('button', {
				name: collectionActionLabel(TRANSPORT_PAUSE_LABEL, 'album'),
				exact: true
			}),
			songTakesRefused: () =>
				page.waitForEvent('requestfailed', (request) =>
					SONG_TAKES_PATH.test(new URL(request.url()).pathname)
				)
		};
	}

	test('waits in the bar, the header and the lock screen with no toast, pauses and resumes from the lock screen, and plays the album by itself once the network is back (#1288, #1330)', async ({
		page,
		context
	}) => {
		const guard = new FlowGuard(page, { losesNetworkOnPurpose: true });
		const library = readSeededLibrary();
		const [firstTrack] = library.albumTracks;
		const { transport, barPause, play, headerPause, songTakesRefused } = headerStartControls(page);
		const waitingOnTheLockScreen = { title: firstTrack.songTitle, state: 'playing' };
		await watchTheLockScreen(page);

		await page.goto(`/album/${library.albumId}`);
		await expect(play).toBeVisible();
		await loseNetwork(page, context);
		await expect(offlineStrip(page)).toBeVisible({ timeout: OFFLINE_NOTICE_MS });
		const firstRefusal = songTakesRefused();
		await play.click();
		await firstRefusal;

		await expect(transport.getByText(firstTrack.songTitle, { exact: true })).toBeVisible();
		await expect(barPause.locator('.spinner')).toBeVisible();
		await expect(headerPause).toHaveAttribute('aria-busy', 'true');
		await expect.poll(() => lockScreenNow(page)).toEqual(waitingOnTheLockScreen);
		await expect(page.getByRole('alert')).toHaveCount(0);

		await pressOnTheLockScreen(page, 'pause');
		await expect
			.poll(() => lockScreenNow(page))
			.toEqual({ title: firstTrack.songTitle, state: 'paused' });
		await expect(play).toBeVisible();
		const refusedAgain = songTakesRefused();
		await pressOnTheLockScreen(page, 'play');
		await refusedAgain;
		await expect(headerPause).toHaveAttribute('aria-busy', 'true');
		await expect.poll(() => lockScreenNow(page)).toEqual(waitingOnTheLockScreen);
		const sinceTheResume = (await lockScreenMoments(page)).length;

		await regainNetwork(page, context);

		await expect(offlineStrip(page)).toHaveCount(0, { timeout: BACK_ONLINE_MS });
		await expect(transport.getByText(firstTrack.songTitle, { exact: true })).toBeVisible();
		await expect(barPause).toBeVisible();
		await expect(barPause.locator('.spinner')).toHaveCount(0);
		await expect(headerPause).toBeVisible();
		expect(
			(await lockScreenMoments(page))
				.slice(sinceTheResume)
				.filter(
					(moment) =>
						moment.title !== waitingOnTheLockScreen.title ||
						moment.state !== waitingOnTheLockScreen.state
				)
		).toEqual([]);
		await expect(page.getByRole('alert')).toHaveCount(0);
		guard.assertClean();
	});

	// The most common daily state: a take of another album is loaded and
	// paused, here restored by the reload that opens this album.
	test('with a paused take of another album loaded, waits in its place in the header, the bar and the lock screen, and plays the album once the network is back (#1330)', async ({
		page,
		context,
		isMobile
	}) => {
		const guard = new FlowGuard(page, { losesNetworkOnPurpose: true });
		const library = readSeededLibrary();
		const [firstTrack] = library.albumTracks;
		const loadedTitle = `${OFFLINE_SONG_TITLE} Loaded ${runMarker()}`;
		await seedSongPhoneSong(library.songPhoneAlbumId, loadedTitle, 1, 1);
		const { transport, barPause, play, headerPause, songTakesRefused } = headerStartControls(page);
		const waitingOnTheLockScreen = { title: firstTrack.songTitle, state: 'playing' };
		await watchTheLockScreen(page);

		await page.goto(`/album/${library.songPhoneAlbumId}`);
		await workspace(page)
			.getByRole('button', { name: songEditorOpenLabel(loadedTitle) })
			.click();
		if (isMobile) await page.getByRole('tab', { name: /Takes/ }).click();
		await workspace(page)
			.locator('.take-row')
			.getByRole('button', { name: new RegExp(`^${TRANSPORT_PLAY_LABEL} v`) })
			.click();
		await expect(barPause.locator('.spinner')).toHaveCount(0);
		await barPause.click();
		await expect(
			transport.getByRole('button', { name: TRANSPORT_PLAY_LABEL, exact: true })
		).toBeVisible();
		await page.goto(`/album/${library.albumId}`);
		await expect(transport.getByText(loadedTitle, { exact: true })).toBeVisible();
		await expect(play).toBeVisible();
		await loseNetwork(page, context);
		await expect(offlineStrip(page)).toBeVisible({ timeout: OFFLINE_NOTICE_MS });
		const refusal = songTakesRefused();
		await play.click();
		await refusal;

		await expect(transport.getByText(firstTrack.songTitle, { exact: true })).toBeVisible();
		await expect(transport.getByText(loadedTitle, { exact: true })).toHaveCount(0);
		await expect(barPause.locator('.spinner')).toBeVisible();
		await expect(headerPause).toHaveAttribute('aria-busy', 'true');
		await expect.poll(() => lockScreenNow(page)).toEqual(waitingOnTheLockScreen);

		await regainNetwork(page, context);

		await expect(offlineStrip(page)).toHaveCount(0, { timeout: BACK_ONLINE_MS });
		await expect(transport.getByText(firstTrack.songTitle, { exact: true })).toBeVisible();
		await expect(barPause.locator('.spinner')).toHaveCount(0);
		await expect(headerPause).toBeVisible();
		await expect.poll(() => lockScreenNow(page)).toEqual(waitingOnTheLockScreen);
		await expect(page.getByRole('alert')).toHaveCount(0);
		guard.assertClean();
	});
});

async function seedOfflineRunningSong(suffix: string, progress: number) {
	const library = readSeededLibrary();
	const songTitle = `${OFFLINE_SONG_TITLE} ${suffix} ${runMarker()}`;
	const songId = await seedSongPhoneSong(library.songPhoneAlbumId, songTitle, 1, 1);
	const jobId = await seedRunningGenerationJob(songId, {
		progress,
		takeIndex: 1,
		takeCount: 2,
		phase: 'rendering',
		generationStartedOffsetSeconds: 30
	});
	const takeCounter = `${EDITOR_GENERATE_TAKE_TEMPLATE.replace('{index}', '1').replace('{count}', '2')} · `;
	return { library, songTitle, songId, jobId, takeCounter };
}

async function openOfflineTakes(page: Page, albumId: string, songTitle: string): Promise<void> {
	await page.goto(`/album/${albumId}`);
	await workspace(page)
		.getByRole('button', { name: songEditorOpenLabel(songTitle) })
		.click();
	await page.getByRole('tab', { name: /Takes/ }).click();
	// Wait for the song route before cutting the network during its module load.
	await expect(page).toHaveURL(new RegExp(`/album/${albumId}/[^/]+$`));
}

test.describe(
	'losing the network while a take generates on the phone',
	{ tag: ONLY_IN_SHELL.mobile },
	() => {
		// Cover terminal events both after reconnect and on a stream left open offline.
		for (const { endArrives, keepOpenStreams } of [
			{ endArrives: 'once the network is back', keepOpenStreams: false },
			{ endArrives: 'offline, on the job stream still open', keepOpenStreams: true }
		]) {
			test(`1160-F15-arrival: greys the running card with its last progress, and keeps it until the take that finished offline is in the list, when the end arrives ${endArrives}`, async ({
				page,
				context
			}) => {
				const guard = new FlowGuard(page, { losesNetworkOnPurpose: true });
				const seededTakes = 1;
				const { library, songTitle, songId, jobId, takeCounter } = await seedOfflineRunningSong(
					'Running',
					0.4
				);
				const panel = page.getByRole('tabpanel');
				const takesTab = page.getByRole('tab', { name: /Takes/ });
				const runningRing = takesTab.locator('.ring');
				const playTakePrefix = `${TRANSPORT_PLAY_LABEL} v`;
				const playButtons = panel.getByRole('button', { name: new RegExp(`^${playTakePrefix}`) });
				const lastSeenBar = panel.getByRole('progressbar', {
					name: EDITOR_GENERATE_LAST_SEEN_PROGRESS_LABEL
				});
				await openOfflineTakes(page, library.songPhoneAlbumId, songTitle);
				await expect(panel.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '40');
				await expect(panel.getByText(new RegExp(`^${takeCounter}40%`))).toBeVisible();
				await expect(playButtons).toHaveCount(seededTakes);
				await loseNetwork(page, context, { keepOpenStreams });
				await expect(panel.getByText(EDITOR_GENERATE_RECONNECTING_LABEL)).toBeVisible({
					timeout: OFFLINE_NOTICE_MS
				});
				await expect(
					panel.getByText(`${takeCounter}last seen at 40%`, { exact: true })
				).toBeVisible();
				await expect(panel.getByText(/~\d/)).toHaveCount(0);
				await expect(lastSeenBar).toHaveAttribute('aria-valuenow', '40');
				const cancel = panel.getByRole('button', { name: EDITOR_GENERATE_CANCEL_OFFLINE_LABEL });
				await expect(cancel).toHaveAttribute('aria-disabled', 'true');
				const grey = await resolvedToken(page, '--text-disabled');
				await expect(lastSeenBar.locator('span')).toHaveCSS('background-color', grey);
				await expect(lastSeenBar.locator('span')).toHaveAttribute('style', /width: 40%/);
				await expect(cancel).toHaveCSS('color', grey);
				await expect(runningRing).toHaveCSS('color', grey);
				await page.evaluate(
					({ prefix, takesBefore }) => {
						const takes = document.querySelector('[role="tabpanel"]');
						if (!takes) throw new Error('Expected the Takes panel');
						const gaps = { seen: false };
						Object.assign(window, { takeArrivalGaps: gaps });
						new MutationObserver(() => {
							const cardShows = takes.querySelector('[role="progressbar"]') !== null;
							const takeShows =
								takes.querySelectorAll(`button[aria-label^="${prefix}"]`).length > takesBefore;
							if (!cardShows && !takeShows) gaps.seen = true;
						}).observe(takes, { childList: true, subtree: true });
					},
					{ prefix: playTakePrefix, takesBefore: seededTakes }
				);
				const songRefreshFailed = keepOpenStreams
					? page.waitForEvent(
							'requestfailed',
							(request) => new URL(request.url()).pathname === `/api/songs/${songId}`
						)
					: null;
				await completeGenerationJobWithoutEvent(jobId);
				if (songRefreshFailed) {
					await songRefreshFailed;
					await expect(panel.getByText(EDITOR_GENERATE_RECONNECTING_LABEL)).toBeVisible();
				}
				await expect(lastSeenBar).toBeVisible();
				await expect(page.getByText(JOB_COMPLETED_TOAST)).toHaveCount(0);
				await regainNetwork(page, context);
				await expect(playButtons).toHaveCount(seededTakes + 2, { timeout: BACK_ONLINE_MS });
				await expect(page.getByText(JOB_COMPLETED_TOAST)).toBeVisible();
				await expect(panel.getByRole('progressbar')).toHaveCount(0);
				await expect(runningRing).toHaveCount(0);
				await expect(offlineStrip(page)).toHaveCount(0);
				const sawNeitherCardNorTake = await page.evaluate(
					() => (window as unknown as { takeArrivalGaps: { seen: boolean } }).takeArrivalGaps.seen
				);
				expect(sawNeitherCardNorTake).toBe(false);
				console.log(`Offline running-take flow /api requests: ${guard.apiRequestCount}`);
				guard.assertClean();
				guard.assertWithinBudget(OFFLINE_RUNNING_TAKE_FLOW_API_REQUEST_BUDGET);
			});
		}
		test('restores the real queued position after reconnecting without navigation (1160-F10-queued-browser)', async ({
			page,
			context
		}) => {
			const library = readSeededLibrary();
			const title = `${OFFLINE_SONG_TITLE} Queued ${runMarker()}`;
			const songId = await seedSongPhoneSong(library.songPhoneAlbumId, title, 1, 0);
			const jobId = await seedQueuedGenerationJob(songId);
			const panel = page.getByRole('tabpanel');
			const expectRealQueuedPosition = () =>
				expect(async () => {
					const response = await page.request.get(`/api/jobs/${jobId}`);
					expect(response.ok()).toBeTruthy();
					const { queue_position: position } = await response.json();
					expect(Number.isInteger(position)).toBe(true);
					expect(position).toBeGreaterThan(0);
					await expect(panel.getByText(/Queued #/)).toHaveText(`Queued #${position}`);
				}).toPass({ timeout: BACK_ONLINE_MS });
			const cleanupErrors: unknown[] = [];
			try {
				await openOfflineTakes(page, library.songPhoneAlbumId, title);
				await expectRealQueuedPosition();
				const address = page.url();
				await loseNetwork(page, context);
				await expect(panel.getByText(EDITOR_GENERATE_RECONNECTING_LABEL)).toBeVisible({
					timeout: OFFLINE_NOTICE_MS
				});
				await expect(panel.getByText(/Queued #/)).toHaveCount(0);
				await regainNetwork(page, context);
				await expectRealQueuedPosition();
				await expect(panel.getByText(EDITOR_GENERATE_RECONNECTING_LABEL)).toHaveCount(0);
				await expect(page).toHaveURL(address);
			} finally {
				try {
					await regainNetwork(page, context);
					const cancelled = await page.request.post(`/api/jobs/${jobId}/cancel`, {
						headers: await sameOriginHeaders(page)
					});
					expect(cancelled.ok()).toBeTruthy();
				} catch (error) {
					cleanupErrors.push(error);
					console.error('Queued job cleanup failed:', error);
				}
			}
			if (cleanupErrors.length) throw cleanupErrors[0];
		});

		test('keeps the running card through three outages in one ride, with no red toast, and resumes it live', async ({
			page,
			context
		}) => {
			const guard = new FlowGuard(page, { losesNetworkOnPurpose: true });
			const { library, songTitle, jobId, takeCounter } = await seedOfflineRunningSong(
				'Tunnels',
				0.4
			);
			const panel = page.getByRole('tabpanel');

			await openOfflineTakes(page, library.songPhoneAlbumId, songTitle);
			await expect(panel.getByText(new RegExp(`^${takeCounter}40%`))).toBeVisible();

			for (let outage = 0; outage < OUTAGES_IN_ONE_RIDE; outage++) {
				const retryRefusedOffline = page.waitForEvent(
					'requestfailed',
					(request) =>
						JOB_STREAM_PATH.test(new URL(request.url()).pathname) &&
						(request.failure()?.errorText ?? '').includes('ERR_INTERNET_DISCONNECTED')
				);
				await loseNetwork(page, context);
				await expect(panel.getByText(EDITOR_GENERATE_RECONNECTING_LABEL)).toBeVisible({
					timeout: OFFLINE_NOTICE_MS
				});
				await retryRefusedOffline;
				await expect(
					panel.getByText(`${takeCounter}last seen at 40%`, { exact: true })
				).toBeVisible();

				await regainNetwork(page, context);

				await expect(panel.getByText(new RegExp(`^${takeCounter}40%`))).toBeVisible({
					timeout: BACK_ONLINE_MS
				});
				await expect(panel.getByText(EDITOR_GENERATE_RECONNECTING_LABEL)).toHaveCount(0);
				await expect(page.getByRole('alert')).toHaveCount(0);
			}

			await advanceGenerationJobPhase(jobId, { progress: 0.7, phase: 'rendering' });
			await expect(panel.getByText(new RegExp(`^${takeCounter}70%`))).toBeVisible();
			await expect(page.getByRole('alert')).toHaveCount(0);
			await expect(offlineStrip(page)).toHaveCount(0);

			console.log(`Three-outage running-take flow /api requests: ${guard.apiRequestCount}`);
			guard.assertClean();
			guard.assertWithinBudget(THREE_OUTAGES_FLOW_API_REQUEST_BUDGET);
		});

		test('reads "Reconnecting…" with its last progress while the online page cannot reopen the job stream, and goes live with its first fresh message (#1161 R1)', async ({
			page
		}) => {
			test.setTimeout(REFUSED_JOB_STREAM_TEST_TIMEOUT_MS);
			const { library, songTitle, jobId, takeCounter } = await seedOfflineRunningSong(
				'Refused',
				0.55
			);
			const jobStream = `/api/jobs/${jobId}/stream`;
			const panel = page.getByRole('tabpanel');
			// Every reopen after the first stream is refused until the server has room again.
			let streamOpens = 0;
			let refusing = true;
			await page.route(`**${jobStream}`, async (route) => {
				streamOpens += 1;
				if (streamOpens === 1) return answerOnceAndDrop(route);
				return refusing ? route.fulfill({ status: 429 }) : route.continue();
			});

			await openOfflineTakes(page, library.songPhoneAlbumId, songTitle);

			await expect(panel.getByText(EDITOR_GENERATE_RECONNECTING_LABEL)).toBeVisible({
				timeout: BACK_ONLINE_MS
			});
			await expect(
				panel.getByText(`${takeCounter}last seen at 55%`, { exact: true })
			).toBeVisible();
			await expect(panel.getByText(/~\d/)).toHaveCount(0);
			await expect(offlineStrip(page)).toHaveCount(0);
			await advanceGenerationJobPhase(jobId, { progress: 0.65, phase: 'rendering' });
			await expect
				.poll(() => streamOpens, { timeout: NEXT_JOB_STREAM_REOPEN_MS })
				.toBeGreaterThan(2);
			await expect(
				panel.getByText(`${takeCounter}last seen at 55%`, { exact: true })
			).toBeVisible();

			refusing = false;

			await expect(panel.getByText(new RegExp(`^${takeCounter}65%`))).toBeVisible({
				timeout: NEXT_JOB_STREAM_REOPEN_MS
			});
			await expect(panel.getByText(EDITOR_GENERATE_RECONNECTING_LABEL)).toHaveCount(0);
		});
	}
);

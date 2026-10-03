// Losing the network on the phone (#1039 O1, O3, O5; slices #1080, #1098): within
// about a second one calm strip, "You're offline — retrying", rests on the
// top edge of the mini player, Generate is disabled without a reason of its
// own and stays above the strip, and once the network is back the strip goes
// by itself. A take generating meanwhile stops looking live (#1098): its card
// reads "Reconnecting…" with the last progress it saw, in grey, its cancel and
// the Takes ring grey too, and when the job ended while the network was gone
// the card stays until its take is in the list. The card reads the same while
// the browser is online but the job's stream stays refused, and a take tapped
// offline plays by itself once the network is back (#1161). Mobile project
// only: the phone's Generate bar is compact-shell UI, and the unit suite pins
// the desktop placement (PlayerBar.test.ts). The album header Play pressed
// offline waits and starts the album once the network is back (#1288), on
// the phone and the desktop alike.
//
// The network is cut for real (`loseNetwork`): `setOffline` alone leaves an
// already open event stream running, so the page's open loads are stopped
// the way a dropped network ends them, and every reopen of the library's live
// stream is refused until the network returns.

import { expect, test, type Locator, type Page, type Route } from '@playwright/test';
import {
	collectionPlayLabel,
	EDITOR_GENERATE_CANCEL_OFFLINE_LABEL,
	EDITOR_GENERATE_LAST_SEEN_PROGRESS_LABEL,
	EDITOR_GENERATE_MODE_LABELS,
	EDITOR_GENERATE_RECONNECTING_LABEL,
	EDITOR_GENERATE_TAKE_TEMPLATE,
	EDITOR_GPU_OFFLINE_TITLE,
	LIBRARY_QUEUE_LOADING_TITLE,
	OFFLINE_STRIP_MESSAGE,
	RESOURCE_EVENT_STREAM_PATH,
	RESOURCE_SYNC_ERROR,
	RESOURCE_SYNC_RETURN_PROBE_INTERVAL_MS,
	SSE_RECONNECT_JITTER_RATIO,
	SSE_RECONNECT_MAX_DELAY_MS,
	TRANSPORT_PAUSE_LABEL,
	TRANSPORT_PLAY_LABEL,
	TRANSPORT_RETRY_LABEL
} from '../src/lib/constants';
import {
	boundingBoxes,
	FlowGuard,
	loseNetwork,
	OFFLINE_FLOW_API_REQUEST_BUDGET,
	OFFLINE_RUNNING_TAKE_FLOW_API_REQUEST_BUDGET,
	nameStartingWith,
	regainNetwork,
	workspace
} from './helpers';
import {
	advanceGenerationJobPhase,
	completeGenerationJobWithoutEvent,
	readSeededLibrary,
	runMarker,
	seedRunningGenerationJob,
	seedSongPhoneSong
} from './seed';

const OFFLINE_SONG_TITLE = 'Offline Strip';
// The ruled "within about a second" of losing the network.
const OFFLINE_NOTICE_MS = 1_500;
// The ruling on #1032: back online, the page has caught up within 10 seconds.
const BACK_ONLINE_MS = 10_000;
// The player's first stall look comes 5 s after Play; until it the transport
// says 'loading', from it on 'recovering'.
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
const GENERATE_LABEL = EDITOR_GENERATE_MODE_LABELS.generate;
// The toast a generate job's end raises (`notifyTerminalJob` in stores/jobs.ts).
const JOB_COMPLETED_TOAST = 'generate completed';
// CI's stack runs no ACE-Step worker, so online the Generate bar names that
// reason inside its own box (#1011).
const GENERATE_WITHOUT_GPU = `${GENERATE_LABEL} — ${EDITOR_GPU_OFFLINE_TITLE}`;
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

function offlineStrip(page: Page): Locator {
	return page.getByRole('status').filter({ hasText: OFFLINE_STRIP_MESSAGE });
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

async function serverReturns(page: Page): Promise<void> {
	await page.unroute(RESOURCE_STREAM);
	await page.unroute(SESSION_CHECK);
}

test.describe('losing the network on the phone', () => {
	test('shows one calm strip on the mini player, disables Generate above it, and goes by itself once back online', async ({
		page,
		context,
		isMobile
	}) => {
		test.skip(!isMobile, 'Mobile-only compact-shell UI; see the file header.');
		const guard = new FlowGuard(page, { losesNetworkOnPurpose: true });
		const library = readSeededLibrary();
		const songTitle = `${OFFLINE_SONG_TITLE} ${runMarker()}`;
		await seedSongPhoneSong(library.songPhoneAlbumId, songTitle, 1, 1);
		const generate = generateButton(page);
		const miniPlayer = page.getByRole('contentinfo');

		await page.goto(`/album/${library.songPhoneAlbumId}`);
		await workspace(page)
			.getByRole('button', { name: nameStartingWith(songTitle) })
			.click();
		await expect(page.getByRole('heading', { name: songTitle })).toBeVisible();
		await expect(generate).toHaveAccessibleName(GENERATE_WITHOUT_GPU);
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
		await expect(generate).toHaveAccessibleName(GENERATE_WITHOUT_GPU);
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
			await page.goto('/');

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
		await page.goto('/');

		// The second rate-limited check follows the stream's first retry, long
		// after the page acted on the first one.
		await expect.poll(answeredSessionChecks, { timeout: BACK_ONLINE_MS }).toBeGreaterThanOrEqual(2);
		await expect(offlineStrip(page)).toHaveCount(0);
	});
});

test.describe('losing the network while a take plays on the phone', () => {
	test('rests the strip above the mini player without moving or covering its transport', async ({
		page,
		context,
		isMobile
	}) => {
		test.skip(!isMobile, 'Mobile-only mini player; see the file header.');
		const library = readSeededLibrary();
		const songTitle = `${OFFLINE_SONG_TITLE} Playing ${runMarker()}`;
		await seedSongPhoneSong(library.songPhoneAlbumId, songTitle, 1, 1);
		const miniPlayer = page.getByRole('contentinfo');
		const pause = miniPlayer.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true });

		await page.goto(`/album/${library.songPhoneAlbumId}`);
		await workspace(page)
			.getByRole('button', { name: nameStartingWith(songTitle) })
			.click();
		await page.getByRole('tab', { name: /Takes/ }).click();
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
});

// Offline, a take with no bytes yet waits instead of offering Retry (#1282):
// its download parks after its attempts, the player's stall looks wait
// without asking again while the network is announced gone, and the
// transport keeps its spinner until the network's return resumes the take.
test.describe('tapping Play while the network is gone on the phone', () => {
	// The take must come over the network, not from the service worker's cache.
	test.use({ serviceWorkers: 'block' });

	test('waits with the spinner and no Retry, and plays the take by itself once the network is back (#1161 R2)', async ({
		page,
		context,
		isMobile
	}) => {
		test.skip(!isMobile, 'Mobile-only mini player; see the file header.');
		const guard = new FlowGuard(page, { losesNetworkOnPurpose: true });
		const library = readSeededLibrary();
		const songTitle = `${OFFLINE_SONG_TITLE} Tapped ${runMarker()}`;
		await seedSongPhoneSong(library.songPhoneAlbumId, songTitle, 1, 1);
		const miniPlayer = page.getByRole('contentinfo');
		const pause = miniPlayer.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true });
		const retry = miniPlayer.getByRole('button', { name: TRANSPORT_RETRY_LABEL, exact: true });
		const spinner = miniPlayer.locator('.play-btn .spinner');
		const loadingSpinner = miniPlayer
			.getByRole('button', { name: TRANSPORT_PLAY_LABEL, exact: true })
			.locator('.spinner');
		const recoveringSpinner = pause.locator('.spinner');

		await page.goto(`/album/${library.songPhoneAlbumId}`);
		await workspace(page)
			.getByRole('button', { name: nameStartingWith(songTitle) })
			.click();
		await page.getByRole('tab', { name: /Takes/ }).click();
		await expect(page).toHaveURL(new RegExp(`/album/${library.songPhoneAlbumId}/[^/]+$`));

		await loseNetwork(page, context);
		await expect(offlineStrip(page)).toBeVisible({ timeout: OFFLINE_NOTICE_MS });
		let offlineAudioRequests = 0;
		page.on('request', (sent) => {
			if (new URL(sent.url()).pathname.startsWith(TAKE_AUDIO_PATH_PREFIX))
				offlineAudioRequests += 1;
		});
		await page
			.getByRole('tabpanel')
			.getByRole('button', { name: new RegExp(`^${TRANSPORT_PLAY_LABEL} v`) })
			.click();
		await expect(loadingSpinner).toBeVisible();
		await expect.poll(() => offlineAudioRequests).toBe(DECK_DOWNLOAD_ATTEMPTS);
		await expect(recoveringSpinner).toBeVisible({ timeout: FIRST_STALL_LOOK_MS });
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
// takes cannot be read (#1288): the bar holds its start notice with no toast,
// and the album starts by itself once the network is back.
test.describe('pressing the album header Play while the network is gone', () => {
	// The takes must come over the network, not from the service worker's cache.
	test.use({ serviceWorkers: 'block' });

	test('waits in the bar with no toast and plays the album by itself once the network is back (#1288)', async ({
		page,
		context
	}) => {
		const guard = new FlowGuard(page, { losesNetworkOnPurpose: true });
		const library = readSeededLibrary();
		const [firstTrack] = library.albumTracks;
		const transport = page.getByRole('contentinfo');
		const waiting = transport.getByText(LIBRARY_QUEUE_LOADING_TITLE, { exact: true });
		const play = workspace(page).getByRole('button', {
			name: collectionPlayLabel('album'),
			exact: true
		});

		await page.goto(`/album/${library.albumId}`);
		await expect(play).toBeVisible();
		await loseNetwork(page, context);
		await expect(offlineStrip(page)).toBeVisible({ timeout: OFFLINE_NOTICE_MS });
		const songTakesRefused = page.waitForEvent('requestfailed', (request) =>
			SONG_TAKES_PATH.test(new URL(request.url()).pathname)
		);
		await play.click();
		await songTakesRefused;

		await expect(waiting).toBeVisible();
		await expect(page.getByRole('alert')).toHaveCount(0);

		await regainNetwork(page, context);

		await expect(offlineStrip(page)).toHaveCount(0, { timeout: BACK_ONLINE_MS });
		await expect(transport.getByText(firstTrack.songTitle, { exact: true })).toBeVisible();
		await expect(
			transport.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true })
		).toBeVisible();
		await expect(waiting).toHaveCount(0);
		await expect(page.getByRole('alert')).toHaveCount(0);
		guard.assertClean();
	});
});

test.describe('losing the network while a take generates on the phone', () => {
	// The same shape as take-arrives.spec.ts's offline flow: the service
	// worker stays out of the loads the returning network makes.
	test.use({ serviceWorkers: 'block' });

	// The job's end reaches the page either on its stream reopened once the
	// network is back, or on the stream still open when the network went --
	// the end then arrives offline, while the song refresh it asks for cannot.
	for (const { endArrives, keepOpenStreams } of [
		{ endArrives: 'once the network is back', keepOpenStreams: false },
		{ endArrives: 'offline, on the job stream still open', keepOpenStreams: true }
	]) {
		test(`greys the running card with its last progress, and keeps it until the take that finished offline is in the list, when the end arrives ${endArrives}`, async ({
			page,
			context,
			isMobile
		}) => {
			test.skip(!isMobile, 'Mobile-only compact-shell UI; see the file header.');
			const guard = new FlowGuard(page, { losesNetworkOnPurpose: true });
			const library = readSeededLibrary();
			const songTitle = `${OFFLINE_SONG_TITLE} Running ${runMarker()}`;
			const seededTakes = 1;
			const songId = await seedSongPhoneSong(library.songPhoneAlbumId, songTitle, 1, seededTakes);
			const jobId = await seedRunningGenerationJob(songId, {
				progress: 0.4,
				takeIndex: 1,
				takeCount: 2,
				phase: 'rendering',
				generationStartedOffsetSeconds: 30
			});
			const takeCounter = `${EDITOR_GENERATE_TAKE_TEMPLATE.replace('{index}', '1').replace('{count}', '2')} · `;
			const panel = page.getByRole('tabpanel');
			const takesTab = page.getByRole('tab', { name: /Takes/ });
			const runningRing = takesTab.locator('.ring');
			const playTakePrefix = `${TRANSPORT_PLAY_LABEL} v`;
			const playButtons = panel.getByRole('button', { name: new RegExp(`^${playTakePrefix}`) });
			const lastSeenBar = panel.getByRole('progressbar', {
				name: EDITOR_GENERATE_LAST_SEEN_PROGRESS_LABEL
			});

			await page.goto(`/album/${library.songPhoneAlbumId}`);
			await workspace(page)
				.getByRole('button', { name: nameStartingWith(songTitle) })
				.click();
			await takesTab.click();
			await expect(panel.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '40');
			await expect(panel.getByText(new RegExp(`^${takeCounter}40%`))).toBeVisible();
			await expect(playButtons).toHaveCount(seededTakes);
			// The card shows before the song's route module has loaded; the address
			// moves to the song only once it has, and cutting the network earlier
			// fails that load into SvelteKit's error page.
			await expect(page).toHaveURL(new RegExp(`/album/${library.songPhoneAlbumId}/[^/]+$`));

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

			await expect(playButtons).toHaveCount(seededTakes + 1, { timeout: BACK_ONLINE_MS });
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

	test('keeps the running card through three outages in one ride, with no red toast, and resumes it live', async ({
		page,
		context,
		isMobile
	}) => {
		test.skip(!isMobile, 'Mobile-only compact-shell UI; see the file header.');
		const guard = new FlowGuard(page, { losesNetworkOnPurpose: true });
		const library = readSeededLibrary();
		const songTitle = `${OFFLINE_SONG_TITLE} Tunnels ${runMarker()}`;
		const songId = await seedSongPhoneSong(library.songPhoneAlbumId, songTitle, 1, 1);
		const jobId = await seedRunningGenerationJob(songId, {
			progress: 0.4,
			takeIndex: 1,
			takeCount: 2,
			phase: 'rendering',
			generationStartedOffsetSeconds: 30
		});
		const takeCounter = `${EDITOR_GENERATE_TAKE_TEMPLATE.replace('{index}', '1').replace('{count}', '2')} · `;
		const panel = page.getByRole('tabpanel');

		await page.goto(`/album/${library.songPhoneAlbumId}`);
		await workspace(page)
			.getByRole('button', { name: nameStartingWith(songTitle) })
			.click();
		await page.getByRole('tab', { name: /Takes/ }).click();
		await expect(panel.getByText(new RegExp(`^${takeCounter}40%`))).toBeVisible();
		await expect(page).toHaveURL(new RegExp(`/album/${library.songPhoneAlbumId}/[^/]+$`));

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
		page,
		isMobile
	}) => {
		test.skip(!isMobile, 'Mobile-only compact-shell UI; see the file header.');
		test.setTimeout(REFUSED_JOB_STREAM_TEST_TIMEOUT_MS);
		const library = readSeededLibrary();
		const songTitle = `${OFFLINE_SONG_TITLE} Refused ${runMarker()}`;
		const songId = await seedSongPhoneSong(library.songPhoneAlbumId, songTitle, 1, 1);
		const jobId = await seedRunningGenerationJob(songId, {
			progress: 0.55,
			takeIndex: 1,
			takeCount: 2,
			phase: 'rendering',
			generationStartedOffsetSeconds: 30
		});
		const jobStream = `/api/jobs/${jobId}/stream`;
		const takeCounter = `${EDITOR_GENERATE_TAKE_TEMPLATE.replace('{index}', '1').replace('{count}', '2')} · `;
		const panel = page.getByRole('tabpanel');
		// Every reopen after the first stream is refused until the server has room again.
		let streamOpens = 0;
		let refusing = true;
		await page.route(`**${jobStream}`, async (route) => {
			streamOpens += 1;
			if (streamOpens === 1) return answerOnceAndDrop(route);
			return refusing ? route.fulfill({ status: 429 }) : route.continue();
		});

		await page.goto(`/album/${library.songPhoneAlbumId}`);
		await workspace(page)
			.getByRole('button', { name: nameStartingWith(songTitle) })
			.click();
		await page.getByRole('tab', { name: /Takes/ }).click();

		await expect(panel.getByText(EDITOR_GENERATE_RECONNECTING_LABEL)).toBeVisible({
			timeout: BACK_ONLINE_MS
		});
		await expect(panel.getByText(`${takeCounter}last seen at 55%`, { exact: true })).toBeVisible();
		await expect(panel.getByText(/~\d/)).toHaveCount(0);
		await expect(offlineStrip(page)).toHaveCount(0);
		await advanceGenerationJobPhase(jobId, { progress: 0.65, phase: 'rendering' });
		await expect.poll(() => streamOpens, { timeout: NEXT_JOB_STREAM_REOPEN_MS }).toBeGreaterThan(2);
		await expect(panel.getByText(`${takeCounter}last seen at 55%`, { exact: true })).toBeVisible();

		refusing = false;

		await expect(panel.getByText(new RegExp(`^${takeCounter}65%`))).toBeVisible({
			timeout: NEXT_JOB_STREAM_REOPEN_MS
		});
		await expect(panel.getByText(EDITOR_GENERATE_RECONNECTING_LABEL)).toHaveCount(0);
	});
});

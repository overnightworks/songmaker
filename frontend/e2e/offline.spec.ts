// Losing the network on the phone (#1039 O1, O3, O5; slices #1080, #1098): within
// about a second one calm strip, "You're offline — retrying", rests on the
// top edge of the mini player, Generate is disabled without a reason of its
// own and stays above the strip, and once the network is back the strip goes
// by itself. A take generating meanwhile stops looking live (#1098): its card
// reads "Reconnecting…" with the last progress it saw, in grey, its cancel and
// the Takes ring grey too, and when the job ended while the network was gone
// the card stays until its take is in the list. Mobile project only: the phone's Generate bar is compact-shell
// UI, and the unit suite pins the desktop placement (PlayerBar.test.ts).
//
// The network is cut for real (`loseNetwork`): `setOffline` alone leaves an
// already open event stream running, so the page's open loads are stopped
// the way a dropped network ends them, and every reopen of the library's live
// stream is refused until the network returns.

import { expect, test, type Locator, type Page, type Route } from '@playwright/test';
import {
	EDITOR_GENERATE_CANCEL_OFFLINE_LABEL,
	EDITOR_GENERATE_LAST_SEEN_PROGRESS_LABEL,
	EDITOR_GENERATE_MODE_LABELS,
	EDITOR_GENERATE_RECONNECTING_LABEL,
	EDITOR_GENERATE_TAKE_TEMPLATE,
	EDITOR_GPU_OFFLINE_TITLE,
	OFFLINE_STRIP_MESSAGE,
	RESOURCE_EVENT_STREAM_PATH,
	RESOURCE_SYNC_ERROR,
	RESOURCE_SYNC_RETURN_PROBE_INTERVAL_MS,
	TRANSPORT_PAUSE_LABEL,
	TRANSPORT_PLAY_LABEL
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
// The ruling on #1099: a server that comes back while the browser stayed
// online is found by the page's return probe, at most one interval until it
// asks and one more for its answer -- about 2 seconds.
const SERVER_BACK_MS = 2 * RESOURCE_SYNC_RETURN_PROBE_INTERVAL_MS;
const RESOURCE_STREAM = `**${RESOURCE_EVENT_STREAM_PATH}**`;
const SESSION_CHECK = '**/api/auth/me';
const GENERATE_LABEL = EDITOR_GENERATE_MODE_LABELS.generate;
// CI's stack runs no ACE-Step worker, so online the Generate bar names that
// reason inside its own box (#1011).
const GENERATE_WITHOUT_GPU = `${GENERATE_LABEL} — ${EDITOR_GPU_OFFLINE_TITLE}`;

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

test.describe('losing the network while a take generates on the phone', () => {
	// The same shape as take-arrives.spec.ts's offline flow: the service
	// worker stays out of the loads the returning network makes.
	test.use({ serviceWorkers: 'block' });

	test('greys the running card with its last progress, and keeps it until the take that finished offline is in the list', async ({
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

		await loseNetwork(page, context);

		await expect(panel.getByText(EDITOR_GENERATE_RECONNECTING_LABEL)).toBeVisible({
			timeout: OFFLINE_NOTICE_MS
		});
		await expect(panel.getByText(`${takeCounter}last seen at 40%`, { exact: true })).toBeVisible();
		await expect(panel.getByText(/~\d/)).toHaveCount(0);
		await expect(lastSeenBar).toHaveAttribute('aria-valuenow', '40');
		const cancel = panel.getByRole('button', { name: EDITOR_GENERATE_CANCEL_OFFLINE_LABEL });
		await expect(cancel).toHaveAttribute('aria-disabled', 'true');
		const grey = await resolvedToken(page, '--text-disabled');
		await expect(lastSeenBar.locator('span')).toHaveCSS('background-color', grey);
		await expect(lastSeenBar.locator('span')).toHaveAttribute('style', /width: 40%/);
		await expect(cancel).toHaveCSS('color', grey);
		await expect(runningRing).toHaveCSS('color', grey);

		await completeGenerationJobWithoutEvent(jobId);
		await expect(lastSeenBar).toBeVisible();
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

		await regainNetwork(page, context);

		await expect(playButtons).toHaveCount(seededTakes + 1, { timeout: BACK_ONLINE_MS });
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
});

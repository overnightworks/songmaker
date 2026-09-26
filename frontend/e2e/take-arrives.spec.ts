// A finished generation's take reaches the phone's Takes list without
// navigation (issue #1020): the operator generated on the phone, stayed on
// Takes, saw the completion toast and the new take was missing until they
// left the song or switched the screen off and on. Mobile project only, for
// the same reason song-phone.spec.ts gives: the Takes tab is compact-shell UI.
//
// CI's e2e stack runs no ACE-Step worker, so the running job and its end are
// seeded directly against the database (scripts/seed_e2e_job_states.py). The
// job is completed with its take but without the `generation.created`
// resource event a real worker also writes: that stands in for the event a
// phone's dropped resource stream never received, so the take can only arrive
// through the job's own terminal refresh — the path this flow pins.

import { expect, test } from '@playwright/test';
import { JOB_TYPE_GENERATE, TRANSPORT_PLAY_LABEL } from '../src/lib/constants';
import { takeGroupLabel } from '../src/lib/constants/now-playing';
import {
	FlowGuard,
	nameStartingWith,
	TAKE_AFTER_RETURN_FLOW_API_REQUEST_BUDGET,
	TAKE_ARRIVES_FLOW_API_REQUEST_BUDGET,
	workspace
} from './helpers';
import {
	completeGenerationJobWithoutEvent,
	readSeededLibrary,
	runMarker,
	seedRunningGenerationJob,
	seedSongPhoneSong
} from './seed';

const TAKE_ARRIVES_SONG_TITLE = 'Take Arrives';
const TAKE_ARRIVES_VERSION_NUMBER = 1;
const SEEDED_TAKE_COUNT = 1;
const GENERATION_COMPLETED_TOAST = `${JOB_TYPE_GENERATE} completed`;
const JOB_STREAM_ROUTE = '**/api/jobs/*/stream';
// Long enough for the cut-off job stream's backoff to pass the 14s mark, where
// the former 30s ceiling would have left it waiting up to 16s more.
const CUT_OFF_MS = 16_000;
// The ruling on #1032: back online, the take is there within 10 seconds.
const TAKE_AFTER_RETURN_MS = 10_000;

test.describe('a finished generation on the phone', () => {
	test('brings its take into the Takes list without navigation, even when its resource event never arrives', async ({
		page,
		isMobile
	}) => {
		test.skip(!isMobile, 'Mobile-only compact-shell UI; see the file header.');
		const guard = new FlowGuard(page);
		const library = readSeededLibrary();
		const songTitle = `${TAKE_ARRIVES_SONG_TITLE} ${runMarker()}`;
		const songId = await seedSongPhoneSong(
			library.songPhoneAlbumId,
			songTitle,
			TAKE_ARRIVES_VERSION_NUMBER,
			SEEDED_TAKE_COUNT
		);
		const jobId = await seedRunningGenerationJob(songId, {
			progress: 0.5,
			takeIndex: 1,
			takeCount: 1,
			runningSinceOffsetSeconds: 30
		});
		const panel = page.getByRole('tabpanel');
		const playButtons = panel.getByRole('button', {
			name: new RegExp(`^${TRANSPORT_PLAY_LABEL} v`)
		});

		await page.goto(`/album/${library.songPhoneAlbumId}`);
		await workspace(page)
			.getByRole('button', { name: nameStartingWith(songTitle) })
			.click();
		await page.getByRole('tab', { name: /Takes/ }).click();
		await expect(panel.getByRole('progressbar')).toBeVisible();
		await expect(
			panel.getByText(takeGroupLabel(TAKE_ARRIVES_VERSION_NUMBER, SEEDED_TAKE_COUNT))
		).toBeVisible();
		await expect(playButtons).toHaveCount(SEEDED_TAKE_COUNT);

		await completeGenerationJobWithoutEvent(jobId);

		await expect(
			page.getByRole('alert').filter({ hasText: GENERATION_COMPLETED_TOAST })
		).toBeVisible();
		await expect(
			panel.getByText(takeGroupLabel(TAKE_ARRIVES_VERSION_NUMBER, SEEDED_TAKE_COUNT + 1))
		).toBeVisible();
		await expect(playButtons).toHaveCount(SEEDED_TAKE_COUNT + 1);
		await expect(page.getByRole('tab', { name: /Takes/ })).toHaveAttribute('aria-selected', 'true');

		console.log(`Take-arrives flow /api requests: ${guard.apiRequestCount}`);
		guard.assertClean();
		guard.assertWithinBudget(TAKE_ARRIVES_FLOW_API_REQUEST_BUDGET);
	});
});

test.describe('a take that finished while the phone was offline', () => {
	// The job stream is cut off with a route; a service worker would take the
	// request out of the page's own routing.
	test.use({ serviceWorkers: 'block' });

	test('is in the Takes list within 10 seconds of the network coming back, and the card stops generating', async ({
		page,
		context,
		isMobile
	}) => {
		test.skip(!isMobile, 'Mobile-only compact-shell UI; see the file header.');
		const guard = new FlowGuard(page);
		const library = readSeededLibrary();
		const songTitle = `${TAKE_ARRIVES_SONG_TITLE} Offline ${runMarker()}`;
		const songId = await seedSongPhoneSong(
			library.songPhoneAlbumId,
			songTitle,
			TAKE_ARRIVES_VERSION_NUMBER,
			SEEDED_TAKE_COUNT
		);
		const jobId = await seedRunningGenerationJob(songId, {
			progress: 0.4,
			takeIndex: 1,
			takeCount: 1,
			runningSinceOffsetSeconds: 30
		});
		const panel = page.getByRole('tabpanel');
		// Each attempt gets a stream that ends at once, the way a dead network
		// drops it, so the job's end can only arrive after the network returns.
		await page.route(JOB_STREAM_ROUTE, (route) =>
			route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
		);

		await page.goto(`/album/${library.songPhoneAlbumId}`);
		await workspace(page)
			.getByRole('button', { name: nameStartingWith(songTitle) })
			.click();
		await page.getByRole('tab', { name: /Takes/ }).click();
		await expect(panel.getByRole('progressbar')).toBeVisible();

		await completeGenerationJobWithoutEvent(jobId);
		await page.waitForTimeout(CUT_OFF_MS);
		await expect(
			panel.getByText(takeGroupLabel(TAKE_ARRIVES_VERSION_NUMBER, SEEDED_TAKE_COUNT + 1))
		).toHaveCount(0);

		await page.unroute(JOB_STREAM_ROUTE);
		await context.setOffline(true);
		await context.setOffline(false);

		await expect(
			panel.getByText(takeGroupLabel(TAKE_ARRIVES_VERSION_NUMBER, SEEDED_TAKE_COUNT + 1))
		).toBeVisible({ timeout: TAKE_AFTER_RETURN_MS });
		await expect(panel.getByRole('progressbar')).toHaveCount(0);
		await expect(page.getByText('Failed to fetch')).toHaveCount(0);

		console.log(`Take-after-return flow /api requests: ${guard.apiRequestCount}`);
		guard.assertClean();
		guard.assertWithinBudget(TAKE_AFTER_RETURN_FLOW_API_REQUEST_BUDGET);
	});
});

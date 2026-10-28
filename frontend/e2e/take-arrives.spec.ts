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

import { expect, test, type Page } from '@playwright/test';
import {
	JOB_TYPE_GENERATE,
	OFFLINE_STRIP_MESSAGE,
	RESOURCE_SYNC_ERROR,
	songEditorOpenLabel,
	TRANSPORT_PLAY_LABEL
} from '../src/lib/constants';
import type { VersionItem } from '../src/lib/api/types';
import {
	currentVersionHeadLabel,
	takeVersion,
	type TakeVersion
} from '../src/lib/constants/now-playing';
import {
	FlowGuard,
	loseNetwork,
	ONLY_IN_SHELL,
	regainNetwork,
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
// The cut-off job stream opens, then reopens after 2, 4 and 8 seconds of
// backoff: its fourth open is the 14s mark, past which the former 30s ceiling
// would have left it waiting up to 16s more. Jitter can carry that mark to
// 16.8s, and the cut-off ends as soon as the stream reaches it.
const CUT_OFF_STREAM_OPENS = 4;
const CUT_OFF_TIMEOUT_MS = 20_000;
// The ruling on #1032: back online, the take is there within 10 seconds.
const TAKE_AFTER_RETURN_MS = 10_000;

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

test.describe('a finished generation on the phone', { tag: ONLY_IN_SHELL.mobile }, () => {
	test('1160-F15-arrival: brings its take into the Takes list without navigation and drops its card, even when its resource event never arrives', async ({
		page
	}) => {
		const guard = new FlowGuard(page);
		const library = readSeededLibrary();
		const songTitle = `${TAKE_ARRIVES_SONG_TITLE} ${runMarker()}`;
		const songId = await seedSongPhoneSong(
			library.songPhoneAlbumId,
			songTitle,
			TAKE_ARRIVES_VERSION_NUMBER,
			SEEDED_TAKE_COUNT
		);
		const seeded = await seededTakeVersion(page, songId);
		const jobId = await seedRunningGenerationJob(songId, {
			progress: 0.5,
			takeIndex: 1,
			takeCount: 2,
			phase: 'rendering',
			generationStartedOffsetSeconds: 30
		});
		const panel = page.getByRole('tabpanel');
		const playButtons = panel.getByRole('button', {
			name: new RegExp(`^${TRANSPORT_PLAY_LABEL} v`)
		});

		await page.goto(`/album/${library.songPhoneAlbumId}`);
		await workspace(page)
			.getByRole('button', { name: songEditorOpenLabel(songTitle) })
			.click();
		await page.getByRole('tab', { name: /Takes/ }).click();
		await expect(panel.getByRole('progressbar')).toBeVisible();
		await expect(
			panel.getByText(currentVersionHeadLabel(seeded.versionNumber, SEEDED_TAKE_COUNT))
		).toBeVisible();
		await expect(playButtons).toHaveCount(SEEDED_TAKE_COUNT);

		await completeGenerationJobWithoutEvent(jobId);

		await expect(
			page.getByRole('alert').filter({ hasText: GENERATION_COMPLETED_TOAST })
		).toBeVisible();
		await expect(
			panel.getByText(currentVersionHeadLabel(seeded.versionNumber, SEEDED_TAKE_COUNT + 2))
		).toBeVisible();
		await expect(playButtons).toHaveCount(SEEDED_TAKE_COUNT + 2);
		await expect(panel.getByRole('progressbar')).toHaveCount(0);
		await expect(page.getByRole('tab', { name: /Takes/ })).toHaveAttribute('aria-selected', 'true');

		console.log(`Take-arrives flow /api requests: ${guard.apiRequestCount}`);
		guard.assertClean();
		guard.assertWithinBudget(TAKE_ARRIVES_FLOW_API_REQUEST_BUDGET);
	});
});

test.describe(
	'a take that finished while the phone was offline',
	{ tag: ONLY_IN_SHELL.mobile },
	() => {
		test('is in the Takes list within 10 seconds of the network coming back, and the card stops generating', async ({
			page,
			context
		}) => {
			const guard = new FlowGuard(page, { losesNetworkOnPurpose: true });
			const library = readSeededLibrary();
			const songTitle = `${TAKE_ARRIVES_SONG_TITLE} Offline ${runMarker()}`;
			const songId = await seedSongPhoneSong(
				library.songPhoneAlbumId,
				songTitle,
				TAKE_ARRIVES_VERSION_NUMBER,
				SEEDED_TAKE_COUNT
			);
			const seeded = await seededTakeVersion(page, songId);
			const jobId = await seedRunningGenerationJob(songId, {
				progress: 0.4,
				takeIndex: 1,
				takeCount: 1,
				phase: 'rendering',
				generationStartedOffsetSeconds: 30
			});
			const panel = page.getByRole('tabpanel');
			// Each attempt gets a stream that ends at once, the way a dead network
			// drops it, so the job's end can only arrive after the network returns.
			let streamOpens = 0;
			await page.route(JOB_STREAM_ROUTE, (route) => {
				streamOpens += 1;
				return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' });
			});

			await page.goto(`/album/${library.songPhoneAlbumId}`);
			await workspace(page)
				.getByRole('button', { name: songEditorOpenLabel(songTitle) })
				.click();
			await page.getByRole('tab', { name: /Takes/ }).click();
			await expect(panel.getByRole('progressbar')).toBeVisible();

			await completeGenerationJobWithoutEvent(jobId);
			await expect
				.poll(() => streamOpens, { timeout: CUT_OFF_TIMEOUT_MS })
				.toBeGreaterThanOrEqual(CUT_OFF_STREAM_OPENS);
			await expect(
				panel.getByText(currentVersionHeadLabel(seeded.versionNumber, SEEDED_TAKE_COUNT + 1))
			).toHaveCount(0);

			await page.unroute(JOB_STREAM_ROUTE);
			await loseNetwork(page, context);
			await expect(page.getByText(OFFLINE_STRIP_MESSAGE)).toBeVisible();
			await regainNetwork(page, context);

			await expect(
				panel.getByText(currentVersionHeadLabel(seeded.versionNumber, SEEDED_TAKE_COUNT + 1))
			).toBeVisible({
				timeout: TAKE_AFTER_RETURN_MS
			});
			await expect(panel.getByRole('progressbar')).toHaveCount(0);
			await expect(page.getByText(OFFLINE_STRIP_MESSAGE)).toHaveCount(0);
			await expect(page.getByText(RESOURCE_SYNC_ERROR)).toHaveCount(0);

			console.log(`Take-after-return flow /api requests: ${guard.apiRequestCount}`);
			guard.assertClean();
			guard.assertWithinBudget(TAKE_AFTER_RETURN_FLOW_API_REQUEST_BUDGET);
		});
	}
);

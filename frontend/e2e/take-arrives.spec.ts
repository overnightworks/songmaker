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
			phase: 'rendering',
			generationStartedOffsetSeconds: 30
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

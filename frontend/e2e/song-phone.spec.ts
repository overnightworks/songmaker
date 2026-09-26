// The song page at phone width (issue #995, #914's ruled sentence L12):
// a Takes list with a real play control per take, a running generation's
// progress in both the Generate button and the Takes status slot, and a
// failed generation's literal worker sentence. Mobile project only —
// everything this proves (the compact Write/Takes tabs, the phone status
// slot, the button's own failure state) is compact-shell UI with no desktop
// counterpart to exercise, the same reason kinetic-strip.spec.ts gives for
// staying desktop-only.
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

import { expect, test } from '@playwright/test';
import {
	EDITOR_GENERATE_FAILURE_COLLAPSE_LABEL,
	EDITOR_GENERATE_FAILURE_EXPAND_LABEL,
	EDITOR_GENERATE_TAKE_TEMPLATE,
	HITBOX_FREQUENT_PX,
	TRANSPORT_PLAY_LABEL
} from '../src/lib/constants';
import { nowPlayingTakeLabel, takeGroupLabel } from '../src/lib/constants/now-playing';
import {
	boundingBoxes,
	FlowGuard,
	nameStartingWith,
	SONG_PHONE_FLOW_API_REQUEST_BUDGET,
	workspace
} from './helpers';
import {
	failGenerationJob,
	readSeededLibrary,
	seedRunningGenerationJob,
	seedSongPhoneSong
} from './seed';

const SONG_PHONE_SONG_TITLE = 'Song Phone Takes';
// Chosen to prove the player names the real seeded version rather than an
// assumed v1 — the whole point of L12's "version number as seeded" clause.
const SONG_PHONE_VERSION_NUMBER = 7;
const SONG_PHONE_TAKE_COUNT = 2;
const SECOND_TAKE_LABEL = nowPlayingTakeLabel(SONG_PHONE_VERSION_NUMBER, SONG_PHONE_TAKE_COUNT);
const RUNNING_JOB_TAKE_INDEX = 1;
const RUNNING_JOB_TAKE_COUNT = 2;
const RUNNING_JOB_PROGRESS = 0.36;
// Backdating running_since by this many seconds gives the remaining-time
// estimate real elapsed time to divide the remaining progress by (see
// seed_e2e_job_states.py's own note) — chosen so the result lands well
// inside a plausible single-digit-minute ETA rather than at either extreme.
const RUNNING_JOB_RUNNING_SINCE_OFFSET_SECONDS = 64;
const RUNNING_JOB_TAKE_COUNTER = EDITOR_GENERATE_TAKE_TEMPLATE.replace(
	'{index}',
	String(RUNNING_JOB_TAKE_INDEX)
).replace('{count}', String(RUNNING_JOB_TAKE_COUNT));
const REMAINING_TIME_PATTERN = /~\d+:\d{2}/;
const FAILED_GENERATION_SENTENCE = 'ACE-Step worker: CUDA out of memory on device 0';

function expectedSongSlug(title: string): string {
	return title.toLowerCase().replace(/\s+/g, '-');
}

test.describe('song page at phone width', () => {
	test('lists takes with a play control each, shows a running generation, then its failure', async ({
		page,
		isMobile
	}) => {
		test.skip(!isMobile, 'Mobile-only compact-shell UI; see the file header.');
		const guard = new FlowGuard(page);
		const library = readSeededLibrary();
		const songId = await seedSongPhoneSong(
			library.songPhoneAlbumId,
			SONG_PHONE_SONG_TITLE,
			SONG_PHONE_VERSION_NUMBER,
			SONG_PHONE_TAKE_COUNT
		);
		const songAddress = `/album/${library.songPhoneAlbumId}/${expectedSongSlug(SONG_PHONE_SONG_TITLE)}`;
		// The one song-phone-panel element (SongPhoneView.svelte): its content
		// swaps with the active tab, so this locator always reads whichever tab
		// is current rather than naming Write and Takes separately.
		const panel = page.getByRole('tabpanel');

		// Opens through the album's own song row (selectSong), not a direct deep
		// link to the song address: only that in-app selection sets
		// selectedAlbumId (navigation.ts's applySelectedSong), which is what
		// playing a take needs to queue from this album rather than falling
		// back to the library-wide pool — the same real path a musician walks
		// from the rail into an album into a song.
		await page.goto(`/album/${library.songPhoneAlbumId}`);
		await workspace(page)
			.getByRole('button', { name: nameStartingWith(SONG_PHONE_SONG_TITLE) })
			.click();
		await expect(page.getByRole('heading', { name: SONG_PHONE_SONG_TITLE })).toBeVisible();

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
		await expect(page.getByRole('contentinfo').getByText(SECOND_TAKE_LABEL)).toBeVisible();

		// A seeded running job, discovered the same way a reload would: a fresh
		// cold open re-runs loadSongContext's hydrateActiveGeneration.
		const jobId = await seedRunningGenerationJob(songId, {
			progress: RUNNING_JOB_PROGRESS,
			takeIndex: RUNNING_JOB_TAKE_INDEX,
			takeCount: RUNNING_JOB_TAKE_COUNT,
			runningSinceOffsetSeconds: RUNNING_JOB_RUNNING_SINCE_OFFSET_SECONDS
		});
		await page.goto(songAddress);
		const generateStatus = panel.getByRole('status');
		await expect(generateStatus.getByText(RUNNING_JOB_TAKE_COUNTER)).toBeVisible();
		await expect(
			generateStatus.getByText(`${Math.round(RUNNING_JOB_PROGRESS * 100)}%`)
		).toBeVisible();
		await expect(generateStatus.getByText(REMAINING_TIME_PATTERN)).toBeVisible();

		await page.getByRole('tab', { name: /Takes/ }).click();
		await expect(panel.getByRole('progressbar')).toBeVisible();
		await expect(panel.getByText(RUNNING_JOB_TAKE_COUNTER, { exact: false })).toBeVisible();
		await expect(panel.getByText(REMAINING_TIME_PATTERN)).toBeVisible();

		// Failing the same job live, over its still-open SSE stream — no
		// reload, matching a real worker crash's own reporting path.
		await failGenerationJob(jobId, FAILED_GENERATION_SENTENCE);
		await page.getByRole('tab', { name: /Write/ }).click();
		await expect(panel.getByText(FAILED_GENERATION_SENTENCE)).toBeVisible();
		await panel.getByRole('button', { name: EDITOR_GENERATE_FAILURE_EXPAND_LABEL }).click();
		await expect(
			panel.getByRole('button', { name: EDITOR_GENERATE_FAILURE_COLLAPSE_LABEL })
		).toBeVisible();

		console.log(`Song-phone flow /api requests: ${guard.apiRequestCount}`);
		guard.assertClean();
		guard.assertWithinBudget(SONG_PHONE_FLOW_API_REQUEST_BUDGET);
	});
});

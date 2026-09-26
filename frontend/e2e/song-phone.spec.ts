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
	EDITOR_GENERATE_FAILURE_COLLAPSE_LABEL,
	EDITOR_GENERATE_FAILURE_EXPAND_LABEL,
	EDITOR_GENERATE_TAKE_TEMPLATE,
	HITBOX_FREQUENT_PX,
	NOW_PLAYING_CLOSE,
	RAIL_LIBRARY_LABEL,
	TRANSPORT_PLAY_LABEL
} from '../src/lib/constants';
import {
	NOW_PLAYING_RIGHT_PANEL_LABEL,
	NOW_PLAYING_TAKE_TAB,
	nowPlayingTakeLabel,
	takeGroupLabel,
	takeRowLabel
} from '../src/lib/constants/now-playing';
import {
	boundingBoxes,
	FlowGuard,
	nameStartingWith,
	playlistEntryRows,
	SONG_PHONE_FLOW_API_REQUEST_BUDGET,
	workspace
} from './helpers';
import {
	failGenerationJob,
	readSeededLibrary,
	runMarker,
	seedPlaylist,
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
			.getByRole('button', { name: nameStartingWith(songTitle) })
			.click();
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
});

// Leaving Now Playing on the phone (issue #1002): the full surface is a
// pushed screen, so the phone's Back -- and × right after open -- shows the
// screen it was opened from again, never the entry below that screen, and
// leaves no copy of it behind for the next Back to land on. A take row opens
// Now Playing on This take, whose sheet backdrop still takes the first tap
// meant for × (#1003), so the × case closes that sheet with Escape first.
// The base library's songs each carry one reimported take, their first.
const SEEDED_TAKE_NUMBER = 1;

interface NowPlayingOrigin {
	playing: string;
	origin: Locator;
	cameFrom: Locator;
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
			await playlistEntryRows(page)
				.first()
				.getByRole('button', { name: nameStartingWith(playing) })
				.click();
			return {
				playing,
				origin,
				cameFrom: workspace(page).getByRole('heading', { name: RAIL_LIBRARY_LABEL })
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
			return {
				playing,
				origin,
				cameFrom: workspace(page).getByRole('heading', { name: library.albumTitle })
			};
		}
	}
];

const NOW_PLAYING_LEAVES: {
	name: string;
	leave: (page: Page, playing: string) => Promise<void>;
}[] = [
	{
		name: 'Back',
		leave: async (page) => {
			await page.goBack();
		}
	},
	{
		// A reload -- or a phone restoring a tab it discarded -- drops the open
		// Now Playing but not its history entry; once its library has loaded
		// the app steps back off that entry, and Back is meant from then on.
		name: 'a reload',
		leave: async (page) => {
			await page.addInitScript(() => {
				window.addEventListener(
					'popstate',
					() => document.documentElement.setAttribute('data-e2e-stepped-back', ''),
					{ once: true }
				);
			});
			await page.reload();
			await expect(page.locator('html[data-e2e-stepped-back]')).toBeAttached();
		}
	},
	{
		name: '× right after open',
		leave: async (page, playing) => {
			await page.keyboard.press('Escape');
			await expect(page.getByRole('dialog', { name: NOW_PLAYING_RIGHT_PANEL_LABEL })).toBeHidden();
			await page
				.getByRole('dialog', { name: playing })
				.getByRole('button', { name: NOW_PLAYING_CLOSE, exact: true })
				.click();
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
				const { playing, origin, cameFrom } = await openFromRow(page, request);
				const nowPlayingTab = page.getByRole('tab', { name: NOW_PLAYING_TAKE_TAB });
				await expect(nowPlayingTab).toBeVisible();
				const originAddress = page.url();

				await leave(page, playing);

				await expect(nowPlayingTab).toBeHidden();
				await expect(origin).toBeVisible();
				expect(page.url()).toBe(originAddress);

				await page.goBack();
				await expect(cameFrom).toBeVisible();
				guard.assertClean();
			});
		}
	}
});

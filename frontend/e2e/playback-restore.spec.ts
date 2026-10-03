import { expect, test, type Page } from '@playwright/test';
import { TRANSPORT_PAUSE_LABEL, TRANSPORT_PLAY_LABEL } from '../src/lib/constants';
import {
	csrfHeaders,
	FlowGuard,
	nameStartingWith,
	shellOf,
	workspace,
	type Shell
} from './helpers';
import { readSeededLibrary, runMarker, seedSongPhoneSong } from './seed';

/**
 * Measured in CI (01.10.2026, #1236): 43 requests on desktop and 46 on mobile
 * for opening the album and the song, playing the take, the reload whose
 * restore asks for the saved song alone, and the tap that plays it on and
 * gathers its album; 46 and 43 when the restored take plays on into the next
 * song. The songs and their takes are seeded against the database and cost
 * nothing here.
 */
const PLAYBACK_RESTORE_FLOW_API_REQUEST_BUDGET = 50;

/** The fixture take's length (`e2e/fixtures/take.mp3`). */
const TAKE_SECONDS = 3;

/** Mid-take in the fixture take. */
const MID_TAKE_SECONDS = 1.5;

/** Far enough into a playing take that its position is no start, with time left to pause. */
const WELL_INTO_TAKE_SECONDS = 1;

/** The transport's position as often as the take moves on, so a pause lands before its end. */
const POSITION_POLL_INTERVALS_MS = [100];

/** The rest of the fixture take plus the next take's start, with room for a slow runner. */
const TRACK_CHANGE_TIMEOUT_MS = 15_000;

interface DeckWindow {
	audioDecks: Set<HTMLMediaElement>;
}

// The player's decks are detached Audio objects no locator reaches, so the
// page collects each one as it is given a source: a take's own URL on the two
// decks, a media source on the continuous deck, which never calls load().
// Headless Chromium does not advance them far enough to emit `playing`; the
// real play() call raises it, as the other playback flows do.
async function followTheAudioDecks(page: Page): Promise<void> {
	await page.addInitScript(() => {
		const decks = new Set<HTMLMediaElement>();
		(window as unknown as DeckWindow).audioDecks = decks;
		const source = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'src');
		if (!source?.set) throw new Error('HTMLMediaElement has no src setter');
		const setSource = source.set;
		Object.defineProperty(HTMLMediaElement.prototype, 'src', {
			...source,
			set(this: HTMLMediaElement, url: string) {
				decks.add(this);
				setSource.call(this, url);
			}
		});
		const nativePlay = HTMLMediaElement.prototype.play;
		HTMLMediaElement.prototype.play = function () {
			const result = nativePlay.call(this);
			queueMicrotask(() => this.dispatchEvent(new Event('playing')));
			return result;
		};
	});
}

async function seekThePlayingDeck(page: Page, seconds: number): Promise<void> {
	await page.evaluate((to) => {
		const decks = [...(window as unknown as DeckWindow).audioDecks];
		const playing = decks.find((deck) => !deck.paused);
		if (!playing) throw new Error('No deck is playing');
		playing.currentTime = to;
	}, seconds);
}

// After a reload only the restored take has a source: nothing preloads after
// it until its queue continues.
async function loadedDeckPositions(page: Page): Promise<number[]> {
	return page.evaluate(() =>
		[...(window as unknown as DeckWindow).audioDecks]
			.filter((deck) => deck.currentSrc !== '')
			.map((deck) => deck.currentTime)
	);
}

// The record is the one per-user key the app keeps for what was playing.
async function savedQueueSource(page: Page): Promise<unknown> {
	return page.evaluate(() => {
		const key = Object.keys(localStorage).find((name) => name.startsWith('playbackResume:'));
		return key === undefined ? null : JSON.parse(localStorage.getItem(key) ?? 'null').source;
	});
}

function transportOf(page: Page) {
	const transport = page.getByRole('contentinfo');
	return {
		transport,
		play: transport.getByRole('button', { name: TRANSPORT_PLAY_LABEL, exact: true }),
		pause: transport.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true })
	};
}

// Plays the song's one take from its album.
async function playTheSongsTake(
	page: Page,
	shell: Shell,
	albumId: string,
	songTitle: string
): Promise<void> {
	await page.goto(`/album/${albumId}`);
	await workspace(page)
		.getByRole('button', { name: nameStartingWith(songTitle) })
		.click();
	if (shell === 'mobile') await page.getByRole('tab', { name: /Takes/ }).click();
	const take = workspace(page).locator('.take-row');
	await expect(take).toHaveCount(1);
	await take.getByRole('button', { name: nameStartingWith(TRANSPORT_PLAY_LABEL) }).click();
	await expect(transportOf(page).pause).toBeVisible();
}

// Plays the song's one take from its album, pauses it mid-take and reloads,
// as a page Android killed and the listener reopened.
async function pauseMidTakeAndReload(
	page: Page,
	shell: Shell,
	albumId: string,
	songTitle: string
): Promise<void> {
	const { play, pause } = transportOf(page);
	await playTheSongsTake(page, shell, albumId, songTitle);
	await seekThePlayingDeck(page, MID_TAKE_SECONDS);
	await pause.click();
	await expect(play).toBeVisible();

	await page.reload();
}

// The desktop transport shows the take's position on its seek slider; the
// phone's shows it only as the progress line across its top.
async function shownPosition(page: Page, shell: Shell): Promise<number> {
	const { transport } = transportOf(page);
	if (shell === 'desktop') {
		return Number(await transport.getByRole('slider', { name: 'Seek playback' }).inputValue());
	}
	const fill = transport.locator('.mobile-progress-fill');
	const percent = parseFloat(await fill.evaluate((line) => (line as HTMLElement).style.width));
	return (percent / 100) * TAKE_SECONDS;
}

test('reload mid-take shows the same take at the same position, paused', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const shell = shellOf(testInfo);
	const library = readSeededLibrary();
	const songTitle = `Playback Restore ${shell} ${runMarker()}`;
	await seedSongPhoneSong(library.songPhoneAlbumId, songTitle, 1, 1);
	await followTheAudioDecks(page);
	const { transport, play: transportPlay, pause: transportPause } = transportOf(page);

	await pauseMidTakeAndReload(page, shell, library.songPhoneAlbumId, songTitle);

	await expect(transport).toContainText(songTitle);
	await expect(transportPlay).toBeVisible();
	await expect.poll(() => loadedDeckPositions(page)).toEqual([expect.closeTo(MID_TAKE_SECONDS, 0)]);
	await expect.poll(() => shownPosition(page, shell)).toBeCloseTo(MID_TAKE_SECONDS, 0);

	await transportPlay.click();
	await expect(transportPause).toBeVisible();
	await transportPause.click();
	await expect(transportPlay).toBeVisible();
	expect(await savedQueueSource(page)).toEqual({
		type: 'album',
		albumId: library.songPhoneAlbumId
	});

	console.log(`Playback restore flow /api requests (${shell}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(PLAYBACK_RESTORE_FLOW_API_REQUEST_BUDGET);
});

// An album of its own holds just the two songs, so the second one follows the
// first.
async function withAlbumOfTwoSongs(
	page: Page,
	marker: string,
	flow: (album: { id: string; firstTitle: string; secondTitle: string }) => Promise<void>
): Promise<void> {
	const created = await page.request.post('/api/albums', {
		headers: await csrfHeaders(page),
		data: { title: `E2E Restore Queue ${marker}`, artist: '' }
	});
	expect(created.ok()).toBe(true);
	const { id } = (await created.json()) as { id: string };
	const firstTitle = `Restore Queue ${marker} first`;
	const secondTitle = `Restore Queue ${marker} second`;
	try {
		await seedSongPhoneSong(id, firstTitle, 1, 1);
		await seedSongPhoneSong(id, secondTitle, 1, 1);
		await flow({ id, firstTitle, secondTitle });
	} finally {
		const removed = await page.request.delete(`/api/albums/${id}`, {
			headers: await csrfHeaders(page)
		});
		expect(removed.ok()).toBe(true);
	}
}

test('reload mid-album, one tap plays on, and the next song follows when the take ends', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const shell = shellOf(testInfo);
	await followTheAudioDecks(page);
	const { transport, play, pause } = transportOf(page);

	await withAlbumOfTwoSongs(page, `${shell} ${runMarker()}`, async (album) => {
		await pauseMidTakeAndReload(page, shell, album.id, album.firstTitle);

		await expect(transport).toContainText(album.firstTitle);
		await play.click();
		await expect(pause).toBeVisible();
		await expect(transport).toContainText(album.secondTitle, {
			timeout: TRACK_CHANGE_TIMEOUT_MS
		});
	});

	console.log(`Playback restore queue flow /api requests (${shell}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(PLAYBACK_RESTORE_FLOW_API_REQUEST_BUDGET);
});

test("reload after a pause in the album's second take shows it at its saved position", async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const shell = shellOf(testInfo);
	await followTheAudioDecks(page);
	const { transport, play, pause } = transportOf(page);

	await withAlbumOfTwoSongs(page, `${shell} ${runMarker()}`, async (album) => {
		await playTheSongsTake(page, shell, album.id, album.firstTitle);
		await expect(transport).toContainText(album.secondTitle, {
			timeout: TRACK_CHANGE_TIMEOUT_MS
		});
		await expect
			.poll(() => shownPosition(page, shell), { intervals: POSITION_POLL_INTERVALS_MS })
			.toBeGreaterThanOrEqual(WELL_INTO_TAKE_SECONDS);
		await pause.click();
		await expect(play).toBeVisible();
		const pausedAt = await shownPosition(page, shell);
		await page.reload();

		await expect(transport).toContainText(album.secondTitle);
		await expect(play).toBeVisible();
		await expect.poll(() => shownPosition(page, shell)).toBeCloseTo(pausedAt, 0);
	});

	console.log(`Playback restore later take /api requests (${shell}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(PLAYBACK_RESTORE_FLOW_API_REQUEST_BUDGET);
});

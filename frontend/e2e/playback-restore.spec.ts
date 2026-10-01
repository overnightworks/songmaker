import { expect, test, type Page } from '@playwright/test';
import { TRANSPORT_PAUSE_LABEL, TRANSPORT_PLAY_LABEL } from '../src/lib/constants';
import { FlowGuard, nameStartingWith, shellOf, workspace, type Shell } from './helpers';
import { readSeededLibrary, runMarker, seedSongPhoneSong } from './seed';

/**
 * Measured on two local runs against one stack (01.10.2026, #1236): 44 requests
 * on desktop and 46 on mobile for opening the album and the song, playing the
 * take, and the reload whose restore rebuilds the album queue (one song fetch
 * plus the album's songs); 48 and 51 when the restored take plays on into the
 * next song. Doubling the album's songs added at most one. The songs and their
 * takes are seeded against the database and cost nothing here.
 */
const PLAYBACK_RESTORE_FLOW_API_REQUEST_BUDGET = 60;

/** Mid-take in the 3 s fixture take (`e2e/fixtures/take.mp3`). */
const MID_TAKE_SECONDS = 1.5;

/** The rest of the fixture take plus the next take's start, with room for a slow runner. */
const TRACK_CHANGE_TIMEOUT_MS = 15_000;

interface DeckWindow {
	audioDecks: Set<HTMLMediaElement>;
}

// The player's two decks are detached Audio objects no locator reaches, so the
// page collects them as they load. Headless Chromium does not advance them far
// enough to emit `playing`; the real play() call raises it, as the other
// playback flows do.
async function followTheAudioDecks(page: Page): Promise<void> {
	await page.addInitScript(() => {
		const decks = new Set<HTMLMediaElement>();
		(window as unknown as DeckWindow).audioDecks = decks;
		const nativeLoad = HTMLMediaElement.prototype.load;
		HTMLMediaElement.prototype.load = function () {
			decks.add(this);
			nativeLoad.call(this);
		};
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

// After a reload the restored take's deck stands at the saved place; the
// standby deck may already hold the next take of its queue, at its start.
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

// Plays the song's one take from its album, pauses it mid-take and reloads,
// as a page Android killed and the listener reopened.
async function pauseMidTakeAndReload(
	page: Page,
	shell: Shell,
	albumId: string,
	songTitle: string
): Promise<void> {
	const { play, pause } = transportOf(page);
	await page.goto(`/album/${albumId}`);
	await workspace(page)
		.getByRole('button', { name: nameStartingWith(songTitle) })
		.click();
	if (shell === 'mobile') await page.getByRole('tab', { name: /Takes/ }).click();
	const take = workspace(page).locator('.take-row');
	await expect(take).toHaveCount(1);
	await take.getByRole('button', { name: nameStartingWith(TRANSPORT_PLAY_LABEL) }).click();
	await expect(pause).toBeVisible();
	await seekThePlayingDeck(page, MID_TAKE_SECONDS);
	await pause.click();
	await expect(play).toBeVisible();

	await page.reload();
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
	await expect
		.poll(() => loadedDeckPositions(page))
		.toContainEqual(expect.closeTo(MID_TAKE_SECONDS, 0));
	if (shell === 'desktop') {
		await expect
			.poll(async () =>
				Number(await transport.getByRole('slider', { name: 'Seek playback' }).inputValue())
			)
			.toBeCloseTo(MID_TAKE_SECONDS, 0);
	}

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

test('reload mid-album, one tap plays on, and the next song follows when the take ends', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const shell = shellOf(testInfo);
	const library = readSeededLibrary();
	const marker = `${shell} ${runMarker()}`;
	const restoredTitle = `Restore Queue ${marker} first`;
	const nextTitle = `Restore Queue ${marker} second`;
	await seedSongPhoneSong(library.songPhoneAlbumId, restoredTitle, 1, 1);
	await seedSongPhoneSong(library.songPhoneAlbumId, nextTitle, 1, 1);
	await followTheAudioDecks(page);
	const { transport, play, pause } = transportOf(page);

	await pauseMidTakeAndReload(page, shell, library.songPhoneAlbumId, restoredTitle);

	await expect(transport).toContainText(restoredTitle);
	await play.click();
	await expect(pause).toBeVisible();
	await expect(transport).toContainText(nextTitle, { timeout: TRACK_CHANGE_TIMEOUT_MS });

	console.log(`Playback restore queue flow /api requests (${shell}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(PLAYBACK_RESTORE_FLOW_API_REQUEST_BUDGET);
});

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
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

const TAKE_FIXTURE = path.join(
	path.dirname(fileURLToPath(import.meta.url)),
	'fixtures',
	'take.mp3'
);

/** The fixture take's length (`e2e/fixtures/take.mp3`). */
const TAKE_SECONDS = 3;

/**
 * How often a long take repeats the fixture's audio: two minutes, far more
 * than the continuous deck's first piece holds, where the fixture take arrives
 * whole in it.
 */
const LONG_TAKE_REPEATS = 40;

const LONG_TAKE_SECONDS = LONG_TAKE_REPEATS * TAKE_SECONDS;

/** Where the listener pauses the long take: past the deck's first piece, inside what it holds. */
const LONG_TAKE_PAUSE_SECONDS = 40;

/** MPEG-2 Layer III bitrates in kbit/s by header index, and sample rates in Hz. */
const MPEG2_LAYER3_KBPS = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160];
const MPEG2_SAMPLE_RATES = [22050, 24000, 16000];

/** Mid-take in the fixture take. */
const MID_TAKE_SECONDS = 1.5;

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

// Moves the playing deck's playhead on within what it holds, as a listener
// skipping ahead does.
async function skipThePlayingDeckAhead(page: Page, seconds: number): Promise<void> {
	await page.evaluate((by) => {
		const decks = [...(window as unknown as DeckWindow).audioDecks];
		const playing = decks.find((deck) => !deck.paused);
		if (!playing) throw new Error('No deck is playing');
		playing.currentTime += by;
	}, seconds);
}

// The fixture's audio frames over and over, without its ID3 tag and the LAME
// Info frame that states the fixture's own length, so the server measures the
// long take as long as it plays.
function longTakeAudio(): Buffer {
	const fixture = readFileSync(TAKE_FIXTURE);
	const tagBytes = 10 + syncsafeInteger(fixture.subarray(6, 10));
	const audioFrames = fixture.subarray(tagBytes + mpeg2Layer3FrameBytes(fixture, tagBytes));
	return Buffer.concat(Array<Buffer>(LONG_TAKE_REPEATS).fill(audioFrames));
}

function syncsafeInteger(bytes: Buffer): number {
	return bytes.reduce((value, byte) => (value << 7) | (byte & 0x7f), 0);
}

function mpeg2Layer3FrameBytes(file: Buffer, at: number): number {
	if (file[at] !== 0xff || (file[at + 1] & 0xfe) !== 0xf2)
		throw new Error(`The fixture has no MPEG-2 Layer III frame at byte ${at}`);
	const flags = file[at + 2];
	const kbps = MPEG2_LAYER3_KBPS[flags >> 4];
	const sampleRate = MPEG2_SAMPLE_RATES[(flags >> 2) & 0b11];
	return Math.floor((72_000 * kbps) / sampleRate) + ((flags >> 1) & 1);
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
async function shownPosition(page: Page, shell: Shell, takeSeconds: number): Promise<number> {
	const { transport } = transportOf(page);
	if (shell === 'desktop') {
		return Number(await transport.getByRole('slider', { name: 'Seek playback' }).inputValue());
	}
	const fill = transport.locator('.mobile-progress-fill');
	const percent = parseFloat(await fill.evaluate((line) => (line as HTMLElement).style.width));
	return (percent / 100) * takeSeconds;
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
	await expect
		.poll(() => shownPosition(page, shell, TAKE_SECONDS))
		.toBeCloseTo(MID_TAKE_SECONDS, 0);

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

async function importSongWithTake(
	page: Page,
	albumId: string,
	title: string,
	audio: Buffer
): Promise<void> {
	const created = await page.request.post('/api/songs', {
		headers: await csrfHeaders(page),
		data: { title, album_id: albumId, lyrics: `${title} lyrics`, prompt: 'calm test tone' }
	});
	expect(created.ok(), `Song creation failed: ${await created.text()}`).toBe(true);
	const { id } = (await created.json()) as { id: string };
	const imported = await page.request.post(`/api/songs/${id}/reimport`, {
		headers: await csrfHeaders(page),
		multipart: { mp3: { name: 'take.mp3', mimeType: 'audio/mpeg', buffer: audio } }
	});
	expect(imported.ok(), `Take import failed: ${await imported.text()}`).toBe(true);
}

// An album of its own holds just the two songs, so the second one follows the
// first. The second song's take is the fixture's unless its audio is given.
async function withAlbumOfTwoSongs(
	page: Page,
	marker: string,
	flow: (album: { id: string; firstTitle: string; secondTitle: string }) => Promise<void>,
	secondTakeAudio?: Buffer
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
		if (secondTakeAudio) await importSongWithTake(page, id, secondTitle, secondTakeAudio);
		else await seedSongPhoneSong(id, secondTitle, 1, 1);
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

test("reload after a pause in the album's second take shows it at its saved position, twice", async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const shell = shellOf(testInfo);
	await followTheAudioDecks(page);
	const { transport, play, pause } = transportOf(page);
	const shownInLongTake = () => shownPosition(page, shell, LONG_TAKE_SECONDS);

	await withAlbumOfTwoSongs(
		page,
		`${shell} ${runMarker()}`,
		async (album) => {
			await playTheSongsTake(page, shell, album.id, album.firstTitle);
			await expect(transport).toContainText(album.secondTitle, {
				timeout: TRACK_CHANGE_TIMEOUT_MS
			});
			await skipThePlayingDeckAhead(page, LONG_TAKE_PAUSE_SECONDS);
			await expect.poll(shownInLongTake).toBeGreaterThanOrEqual(LONG_TAKE_PAUSE_SECONDS);
			await pause.click();
			await expect(play).toBeVisible();
			const pausedAt = await shownInLongTake();

			for (const reload of ['first reload', 'second reload']) {
				await page.reload();
				await expect(transport, reload).toContainText(album.secondTitle);
				await expect(play, reload).toBeVisible();
				await expect.poll(shownInLongTake, { message: reload }).toBeCloseTo(pausedAt, 0);
			}

			await play.click();
			await expect(pause).toBeVisible();
			await expect.poll(shownInLongTake).toBeGreaterThan(pausedAt);
		},
		longTakeAudio()
	);

	console.log(`Playback restore later take /api requests (${shell}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(PLAYBACK_RESTORE_FLOW_API_REQUEST_BUDGET);
});

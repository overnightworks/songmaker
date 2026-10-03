// A queue plays on by itself (#1187 P1, P6): when a take ends, the next one
// starts without a tap, and it was already loading while the first one played
// (P5: no server-side concat before the first byte, so the next take's own
// request is the preload). Where the browser appends MP3 into one source, as
// Chromium does, the album plays on one element that neither pauses nor ends
// between takes (#1254): the track change is the playhead crossing.
//
// Both shells walk every flow. The seeded takes are three seconds long, so a
// real track change happens inside the flow's own time.

import { expect, request, test, type APIRequestContext, type Page } from '@playwright/test';
import {
	collectionPlayLabel,
	openNowPlayingLabel,
	TRANSPORT_PAUSE_LABEL,
	TRANSPORT_PLAY_LABEL,
	TRANSPORT_RETRY_LABEL
} from '../src/lib/constants';
import {
	NOW_PLAYING_SHUFFLE_DISABLE_PREFIX,
	NOW_PLAYING_SHUFFLE_LABEL_PREFIX
} from '../src/lib/constants/now-playing';
import { FlowGuard, nameStartingWith, shellOf, workspace, type Shell } from './helpers';
import {
	BASE_URL,
	createAccount,
	deleteAccount,
	readSeededLibrary,
	runMarker,
	seedPlaylist,
	seedUnpickedLibrary,
	STORAGE_STATE_FILE,
	type SeededLibrary,
	type SeededTake,
	type SeededTrack,
	type SeededUnpickedLibrary
} from './seed';

// A three-second take plus the next take's start, with room for a slow runner.
const TRACK_CHANGE_TIMEOUT_MS = 15_000;
const MEDIA_EVENT_BINDING = 'reportMediaEvent';
const PLAYED_ELEMENTS_KEY = 'e2ePlayedMediaElements';
const STOPPING_EVENTS = ['pause', 'ended'];
const SEEKING_EVENT = 'seeking';
// A new source on an element that already held one empties it first.
const SOURCE_SWAP_EVENT = 'emptied';
const WATCHED_EVENTS = [...STOPPING_EVENTS, SEEKING_EVENT, SOURCE_SWAP_EVENT];
// The fixture take is three seconds long, so a take's second place on the
// deck starts about three seconds in.
const SECOND_PLACE_STARTS_AFTER_SECONDS = 2.5;
// Long enough into a take that the player has shown its position.
const PLAYING_FOR_SECONDS = 0.5;
// Far enough past the shuffle toggle that a seek back would already have landed.
const PLAYS_ON_PAST_THE_TOGGLE_SECONDS = 0.5;
const ACCOUNT_PASSWORD = 'E2eQueue!2026';
const RECOVERY_QUERY = 'recover';
// The deck's contract (continuousDeck.ts): three downloads in a row fail,
// then it parks until the player retries.
const DECK_DOWNLOAD_ATTEMPTS = 3;

/**
 * When each take's audio was first requested and how often, which elements
 * played from which kind of source, where they seeked to, and which stopped
 * or swapped their source. The player's decks are detached `Audio` elements,
 * out of reach of any DOM query, so every element that plays reports its own
 * events through a binding and is kept on the window for its clock.
 */
class PlaybackTimeline {
	private readonly requested = new Map<string, number>();
	private readonly requestCounts = new Map<string, number>();
	private readonly playingElements = new Set<number>();
	readonly stops: string[] = [];
	readonly seeks: number[] = [];
	readonly sourcesPlayed: string[] = [];
	readonly recoveryRequests: string[] = [];
	sourceSwaps = 0;

	static async watch(page: Page): Promise<PlaybackTimeline> {
		const timeline = new PlaybackTimeline();
		page.on('request', (sent) => timeline.recordRequest(sent.url()));
		await page.exposeFunction(
			MEDIA_EVENT_BINDING,
			(element: number, event: string, source: string, position: number) =>
				timeline.recordMediaEvent(element, event, source, position)
		);
		await page.addInitScript(
			({ binding, elementsKey, watchedEvents }) => {
				const elementIds = new WeakMap<HTMLMediaElement, number>();
				const played: HTMLMediaElement[] = [];
				Reflect.set(window, elementsKey, played);
				const nativePlay = HTMLMediaElement.prototype.play;
				HTMLMediaElement.prototype.play = function () {
					if (!elementIds.has(this)) {
						const id = played.push(this) - 1;
						elementIds.set(this, id);
						const report = (event: string) =>
							Reflect.get(window, binding).call(window, id, event, this.src, this.currentTime);
						report('play');
						for (const event of watchedEvents) this.addEventListener(event, () => report(event));
					}
					return nativePlay.call(this);
				};
			},
			{
				binding: MEDIA_EVENT_BINDING,
				elementsKey: PLAYED_ELEMENTS_KEY,
				watchedEvents: WATCHED_EVENTS
			}
		);
		return timeline;
	}

	requestedAt(track: SeededTrack): number | undefined {
		return this.requested.get(track.audioPath);
	}

	requestsOf(track: SeededTrack): number {
		return this.requestCounts.get(track.audioPath) ?? 0;
	}

	// The clock of the one element the deck plays on, 0 until it first plays.
	static clockOf(page: Page): Promise<number> {
		return page.evaluate(
			(elementsKey) =>
				(Reflect.get(window, elementsKey) as HTMLMediaElement[])[0]?.currentTime ?? 0,
			PLAYED_ELEMENTS_KEY
		);
	}

	get elementsPlayed(): number {
		return this.playingElements.size;
	}

	private recordRequest(url: string): void {
		const parsed = new URL(url);
		const path = decodeURIComponent(parsed.pathname);
		if (!this.requested.has(path)) this.requested.set(path, performance.now());
		this.requestCounts.set(path, (this.requestCounts.get(path) ?? 0) + 1);
		if (parsed.searchParams.has(RECOVERY_QUERY)) this.recoveryRequests.push(url);
	}

	private recordMediaEvent(element: number, event: string, source: string, position: number): void {
		if (!this.playingElements.has(element)) this.sourcesPlayed.push(new URL(source).protocol);
		this.playingElements.add(element);
		if (STOPPING_EVENTS.includes(event)) this.stops.push(`${event} on element ${element}`);
		if (event === SEEKING_EVENT) this.seeks.push(position);
		if (event === SOURCE_SWAP_EVENT) this.sourceSwaps += 1;
	}
}

async function expectTransportMovesOn(page: Page, from: SeededTrack, to: SeededTrack) {
	const transport = page.getByRole('contentinfo');
	await expect(transport.getByText(from.songTitle, { exact: true })).toBeVisible();
	await expect(transport.getByText(to.songTitle, { exact: true })).toBeVisible({
		timeout: TRACK_CHANGE_TIMEOUT_MS
	});
	await expect(transport.getByText(from.songTitle, { exact: true })).toHaveCount(0);
}

async function playAlbum(page: Page, albumId: string) {
	await page.goto(`/album/${albumId}`);
	await workspace(page)
		.getByRole('button', { name: collectionPlayLabel('album'), exact: true })
		.click();
}

function trackOf(library: SeededLibrary, take: SeededTake): SeededTrack {
	const track = library.albumTracks.find(({ songTitle }) => songTitle === take.songTitle);
	if (!track) throw new Error(`${take.songTitle} is not one of the album's tracks`);
	return track;
}

async function seedPlaylistOf(library: SeededLibrary, takes: SeededTake[]): Promise<string> {
	const api = await request.newContext({ baseURL: BASE_URL, storageState: STORAGE_STATE_FILE });
	try {
		return (await seedPlaylist(api, { ...library, playlistTakes: takes })).slug;
	} finally {
		await api.dispose();
	}
}

// On the phone shuffle lives in Now Playing, opened from the mini player.
async function toggleShuffle(page: Page, shell: Shell, playingSongTitle: string) {
	const transport = page.getByRole('contentinfo');
	if (shell === 'mobile')
		await transport
			.getByRole('button', { name: openNowPlayingLabel(playingSongTitle), exact: true })
			.click();
	const controls =
		shell === 'desktop' ? transport : page.getByRole('dialog', { name: playingSongTitle });
	const shuffle = controls.getByRole('button', {
		name: nameStartingWith(NOW_PLAYING_SHUFFLE_LABEL_PREFIX, NOW_PLAYING_SHUFFLE_DISABLE_PREFIX)
	});
	await shuffle.click();
	await expect(shuffle).toHaveAttribute('aria-pressed', 'true');
	if (shell === 'mobile') {
		await page.keyboard.press('Escape');
		await expect(page.getByRole('dialog', { name: playingSongTitle })).toBeHidden();
	}
}

test('an album plays from one take into the next on one element that never stops', async ({
	page
}) => {
	const guard = new FlowGuard(page);
	const library = readSeededLibrary();
	const [first, second] = library.albumTracks;
	const timeline = await PlaybackTimeline.watch(page);

	await playAlbum(page, library.albumId);

	await expectTransportMovesOn(page, first, second);
	const movedOnAt = performance.now();
	expect(timeline.requestedAt(second)).toBeLessThan(movedOnAt);
	expect(timeline.elementsPlayed).toBe(1);
	expect(timeline.stops).toEqual([]);
	guard.assertClean();
});

// Prev starts the previous take on a fresh buffer of the same element
// (#1276), and the queue then crosses into the take after it; a new source
// drops the pause the jump back asked for, so the element never stops.
test('Prev on an album starts the previous take and the queue continues into the take after it', async ({
	page
}) => {
	const guard = new FlowGuard(page);
	const library = readSeededLibrary();
	const [first, second] = library.albumTracks;
	const timeline = await PlaybackTimeline.watch(page);
	const transport = page.getByRole('contentinfo');

	await playAlbum(page, library.albumId);
	await expectTransportMovesOn(page, first, second);
	await transport.getByRole('button', { name: 'Previous', exact: true }).click();

	await expectTransportMovesOn(page, first, second);
	expect(timeline.elementsPlayed).toBe(1);
	expect(timeline.stops).toEqual([]);
	guard.assertClean();
});

// Next from the first of two places of one take seeks to the second place
// on the same element (#1299): the place, not the audio, decides where the
// playhead goes.
test('Next between two places of one take in a playlist moves the audio to the second place', async ({
	page
}) => {
	const guard = new FlowGuard(page);
	const library = readSeededLibrary();
	const [twice, once] = library.playlistTakes;
	const slug = await seedPlaylistOf(library, [twice, twice, once]);
	const timeline = await PlaybackTimeline.watch(page);
	const transport = page.getByRole('contentinfo');

	await page.goto(`/playlist/${slug}`);
	await workspace(page)
		.getByRole('button', { name: collectionPlayLabel('playlist'), exact: true })
		.click();
	await expect.poll(() => timeline.requestsOf(trackOf(library, twice))).toBeGreaterThanOrEqual(2);
	await transport.getByRole('button', { name: 'Next', exact: true }).click();

	await expect.poll(() => timeline.seeks).toHaveLength(1);
	expect(timeline.seeks[0]).toBeGreaterThan(SECOND_PLACE_STARTS_AFTER_SECONDS);
	await expectTransportMovesOn(page, trackOf(library, twice), trackOf(library, once));
	expect(timeline.elementsPlayed).toBe(1);
	expect(timeline.sourceSwaps).toBe(0);
	guard.assertClean();
});

// A shuffle toggle rebuilds the queue around the playing take (#1299): the
// element plays on from exactly where it stood, on the same source, and the
// takes ahead follow the new order. It is toggled while paused, so the take
// cannot end in the middle of the toggle.
test('shuffle on an album keeps the playing take where it is and plays on into the new order', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const library = readSeededLibrary();
	const [first] = library.albumTracks;
	const timeline = await PlaybackTimeline.watch(page);
	const transport = page.getByRole('contentinfo');

	await playAlbum(page, library.albumId);
	await expect(transport.getByText(first.songTitle, { exact: true })).toBeVisible();
	await expect.poll(() => PlaybackTimeline.clockOf(page)).toBeGreaterThan(PLAYING_FOR_SECONDS);
	await transport.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true }).click();
	const pausedAt = await PlaybackTimeline.clockOf(page);
	await toggleShuffle(page, shellOf(testInfo), first.songTitle);

	await expect
		.poll(() => PlaybackTimeline.clockOf(page))
		.toBeGreaterThan(pausedAt + PLAYS_ON_PAST_THE_TOGGLE_SECONDS);
	expect(timeline.seeks).toEqual([]);
	await expect(transport.getByText(first.songTitle, { exact: true })).toHaveCount(0, {
		timeout: TRACK_CHANGE_TIMEOUT_MS
	});
	expect(timeline.seeks).toEqual([]);
	expect(timeline.sourceSwaps).toBe(0);
	expect(timeline.elementsPlayed).toBe(1);
	guard.assertClean();
});

// A take ahead whose requests fail on the network waits instead of being
// skipped (#1282): its download parks, the player's stall look resumes it,
// and once the requests succeed the playhead crosses into it on the same
// element. A dropout in the middle of a body is not drivable with
// three-second takes; continuousDeck.test.ts proves that one.
test('an album whose next take fails on the network for a while plays that take once its requests succeed', async ({
	page
}) => {
	const guard = new FlowGuard(page, { losesNetworkOnPurpose: true });
	const library = readSeededLibrary();
	const [first, second] = library.albumTracks;
	const timeline = await PlaybackTimeline.watch(page);
	const transport = page.getByRole('contentinfo');
	const isSecondTake = (url: URL) => decodeURIComponent(url.pathname) === second.audioPath;
	let failedRequests = 0;
	await page.route(isSecondTake, (route) => {
		failedRequests += 1;
		return route.abort('internetdisconnected');
	});

	await playAlbum(page, library.albumId);
	await expect
		.poll(() => failedRequests, { timeout: TRACK_CHANGE_TIMEOUT_MS })
		.toBeGreaterThan(DECK_DOWNLOAD_ATTEMPTS);
	await page.unroute(isSecondTake);

	await expectTransportMovesOn(page, first, second);
	expect(timeline.elementsPlayed).toBe(1);
	expect(timeline.sourcesPlayed).toEqual(['blob:']);
	expect(timeline.stops).toEqual([]);
	expect(timeline.recoveryRequests).toEqual([]);
	await expect(page.getByText(`${second.songTitle} couldn't be loaded, skipped.`)).toHaveCount(0);
	await expect(transport.getByRole('button', { name: TRANSPORT_RETRY_LABEL })).toHaveCount(0);
	guard.assertClean();
});

test.describe('on a fresh account', () => {
	let adminApi: APIRequestContext;
	let accountApi: APIRequestContext;
	let accountId: string;
	let unpicked: SeededUnpickedLibrary;

	test.beforeAll(async () => {
		adminApi = await request.newContext({ baseURL: BASE_URL, storageState: STORAGE_STATE_FILE });
		const username = `e2e-queue-${test.info().project.name}-${runMarker()}`;
		accountId = await createAccount(adminApi, username, ACCOUNT_PASSWORD);
		accountApi = await request.newContext({ baseURL: BASE_URL });
		unpicked = await seedUnpickedLibrary(accountApi, { username, password: ACCOUNT_PASSWORD });
	});

	test.afterAll(async () => {
		await accountApi.dispose();
		await deleteAccount(adminApi, accountId);
		await adminApi.dispose();
	});

	test('a take row in a library with nothing picked continues through its album', async ({
		page,
		context
	}, testInfo) => {
		const guard = new FlowGuard(page);
		const [first, second] = unpicked.tracks;
		await context.clearCookies();
		await context.addCookies((await accountApi.storageState()).cookies);
		const surface = workspace(page);

		await page.goto(`/album/${unpicked.albumId}`);
		await surface
			.locator('.item-row')
			.filter({ hasText: first.songTitle })
			.getByRole('button')
			.click();
		if (shellOf(testInfo) === 'mobile') await surface.getByRole('tab', { name: /Takes/ }).click();
		const take = surface.locator('.take-row');
		await expect(take).toHaveCount(1);
		await take.getByRole('button', { name: nameStartingWith(TRANSPORT_PLAY_LABEL) }).click();

		await expectTransportMovesOn(page, first, second);
		guard.assertClean();
	});
});

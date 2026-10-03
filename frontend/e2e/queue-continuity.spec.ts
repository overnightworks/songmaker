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
import { collectionPlayLabel, TRANSPORT_PLAY_LABEL } from '../src/lib/constants';
import { FlowGuard, nameStartingWith, shellOf, workspace } from './helpers';
import {
	BASE_URL,
	createAccount,
	deleteAccount,
	readSeededLibrary,
	runMarker,
	seedUnpickedLibrary,
	STORAGE_STATE_FILE,
	type SeededTrack,
	type SeededUnpickedLibrary
} from './seed';

// A three-second take plus the next take's start, with room for a slow runner.
const TRACK_CHANGE_TIMEOUT_MS = 15_000;
const MEDIA_EVENT_BINDING = 'reportMediaEvent';
const STOPPING_EVENTS = ['pause', 'ended'];
const ACCOUNT_PASSWORD = 'E2eQueue!2026';

/**
 * When each take's audio was first requested, and which elements played and
 * stopped. The player's decks are detached `Audio` elements, out of reach of
 * any DOM query, so every element that plays reports its own stops through a
 * binding.
 */
class PlaybackTimeline {
	private readonly requested = new Map<string, number>();
	private readonly playingElements = new Set<number>();
	readonly stops: string[] = [];

	static async watch(page: Page): Promise<PlaybackTimeline> {
		const timeline = new PlaybackTimeline();
		page.on('request', (sent) => timeline.recordRequest(sent.url()));
		await page.exposeFunction(MEDIA_EVENT_BINDING, (element: number, event: string) =>
			timeline.recordMediaEvent(element, event)
		);
		await page.addInitScript(
			({ binding, stoppingEvents }) => {
				const elementIds = new WeakMap<HTMLMediaElement, number>();
				let nextId = 0;
				const nativePlay = HTMLMediaElement.prototype.play;
				HTMLMediaElement.prototype.play = function () {
					if (!elementIds.has(this)) {
						const id = nextId++;
						elementIds.set(this, id);
						const report = (event: string) => Reflect.get(window, binding).call(window, id, event);
						report('play');
						for (const event of stoppingEvents) this.addEventListener(event, () => report(event));
					}
					return nativePlay.call(this);
				};
			},
			{ binding: MEDIA_EVENT_BINDING, stoppingEvents: STOPPING_EVENTS }
		);
		return timeline;
	}

	requestedAt(track: SeededTrack): number | undefined {
		return this.requested.get(track.audioPath);
	}

	get elementsPlayed(): number {
		return this.playingElements.size;
	}

	private recordRequest(url: string): void {
		const path = decodeURIComponent(new URL(url).pathname);
		if (!this.requested.has(path)) this.requested.set(path, performance.now());
	}

	private recordMediaEvent(element: number, event: string): void {
		this.playingElements.add(element);
		if (STOPPING_EVENTS.includes(event)) this.stops.push(`${event} on element ${element}`);
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

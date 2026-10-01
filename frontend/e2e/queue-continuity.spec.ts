// A queue plays on by itself (#1187 P1, P6): when a take ends, the next one
// starts without a tap, and it was already loading while the first one played
// (P5: no server-side concat before the first byte, so the next take's own
// request is the preload).
//
// Both shells walk both flows. The seeded takes are three seconds long, so a
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
const TAKE_ENDED_BINDING = 'reportTakeEnded';
const ACCOUNT_PASSWORD = 'E2eQueue!2026';

/**
 * When each take's audio was first requested and first ended, on one clock.
 * The player's decks are detached `Audio` elements, out of reach of any DOM
 * query, so every element that plays reports its own end through a binding.
 */
class PlaybackTimeline {
	private readonly requested = new Map<string, number>();
	private readonly ended = new Map<string, number>();

	static async watch(page: Page): Promise<PlaybackTimeline> {
		const timeline = new PlaybackTimeline();
		page.on('request', (sent) => timeline.record(timeline.requested, sent.url()));
		await page.exposeFunction(TAKE_ENDED_BINDING, (src: string) =>
			timeline.record(timeline.ended, src)
		);
		await page.addInitScript((binding) => {
			const watched = new WeakSet<HTMLMediaElement>();
			const nativePlay = HTMLMediaElement.prototype.play;
			HTMLMediaElement.prototype.play = function () {
				if (!watched.has(this)) {
					watched.add(this);
					this.addEventListener('ended', () =>
						Reflect.get(window, binding).call(window, this.currentSrc)
					);
				}
				return nativePlay.call(this);
			};
		}, TAKE_ENDED_BINDING);
		return timeline;
	}

	requestedAt(track: SeededTrack): number | undefined {
		return this.requested.get(track.audioPath);
	}

	endedAt(track: SeededTrack): number | undefined {
		return this.ended.get(track.audioPath);
	}

	private record(moments: Map<string, number>, url: string): void {
		const path = decodeURIComponent(new URL(url).pathname);
		if (!moments.has(path)) moments.set(path, performance.now());
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

test('an album plays from one take into the next without a tap', async ({ page }) => {
	const guard = new FlowGuard(page);
	const library = readSeededLibrary();
	const [first, second] = library.albumTracks;
	const timeline = await PlaybackTimeline.watch(page);

	await page.goto(`/album/${library.albumId}`);
	await workspace(page)
		.getByRole('button', { name: collectionPlayLabel('album'), exact: true })
		.click();

	await expectTransportMovesOn(page, first, second);
	await expect.poll(() => timeline.endedAt(first)).toBeDefined();
	expect(timeline.requestedAt(second)).toBeLessThan(timeline.endedAt(first) ?? 0);
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

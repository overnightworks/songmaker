import { replaceHistoryEntry } from '#lib/test-utils/library-history.ts';
import { routerHistoryEntry } from '#lib/test-utils/router-history-layout.ts';
import { makeAlbum as album, makeSong as song } from '#lib/test-utils/factories.ts';
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest';
import { get } from 'svelte/store';
import { startFakeRouter } from '#lib/test-utils/app-navigation.ts';
import {
	installHistoryController,
	resetHistoryControllerForTests
} from '#lib/history/historyController.ts';
import { resetLibrarySearchForTests } from '#lib/stores/librarySearch.ts';
import { libraryRootState, resetLibraryContextForTests } from '#lib/stores/libraryContext.ts';
import { resetCollectionForTests } from '#lib/stores/collection.ts';
import { albumList, songList } from '#lib/stores/libraryData.ts';
import { selectedGenerationId, selectedSongId } from '#lib/stores/player.ts';
import { resetPlaylistsForTests } from '#lib/stores/playlists.ts';
import { LIBRARY_ROUTE_PATH } from '#lib/routes/addresses.ts';
import { RESOURCE_EVENT_STREAM_PATH, SONG_LINK_NOT_FOUND_TOAST } from '#lib/constants.ts';
import { toasts } from '#lib/stores/toast.ts';
import {
	resetResourceSyncForTests,
	resourceSync,
	retryResourceSync,
	startLibraryResourceSync,
	stopLibraryResourceSync
} from '#lib/stores/resourceSync.ts';

vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);
vi.mock('$app/state', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppState()
);
vi.mock('$app/paths', () => ({
	resolve: vi.fn((path: string) => path)
}));

import { followLibrarySync, followShellLayers, resetNavigationForTests } from './navigation';

const STANDING_SONG_ID = 's1';
const CONTEXT_LOAD_PATH = `/api/songs/${STANDING_SONG_ID}/active-generation`;
const OTHER_SONG_ID = 's2';
const noItems = { items: [], total: 0, offset: 0, limit: 0, has_more: false };

class FakeEventSource {
	static instances: FakeEventSource[] = [];
	readyState = 0;
	onerror: ((event: Event) => void) | null = null;
	private readonly listeners = new Map<string, Set<(event: Event) => void>>();
	constructor(readonly url: string) {
		FakeEventSource.instances.push(this);
	}
	addEventListener(type: string, listener: (event: Event) => void): void {
		this.listeners.set(type, (this.listeners.get(type) ?? new Set()).add(listener));
	}
	removeEventListener(type: string, listener: (event: Event) => void): void {
		this.listeners.get(type)?.delete(listener);
	}
	close(): void {}
	hello(): void {
		const event = new MessageEvent('hello', { data: JSON.stringify({ high_water_mark: '0' }) });
		for (const listener of this.listeners.get('hello') ?? []) listener(event);
	}
}

let requests: string[] = [];
let failLibraryLists = false;
let goneSongId: string | null = null;
let stopFollowingShellLayers: () => void = () => undefined;

function stubNetwork(): void {
	vi.stubGlobal('EventSource', FakeEventSource);
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: string) => {
			const path = String(input);
			requests.push(path);
			if (path.startsWith('/api/songs?') && failLibraryLists)
				throw new TypeError('Failed to fetch');
			if (path.startsWith('/api/albums?') || path.startsWith('/api/songs?')) {
				return { ok: true, json: async () => noItems };
			}
			const songId = /^\/api\/songs\/([^/?]+)$/.exec(path)?.[1];
			if (songId && songId === goneSongId) {
				return { ok: false, status: 404, json: async () => ({ detail: 'Song not found' }) };
			}
			if (songId) return { ok: true, json: async () => song({ slug: songId, id: songId }) };
			return { ok: true, json: async () => ({}) };
		})
	);
}

function standOnSong(): void {
	selectedSongId.set(STANDING_SONG_ID);
	replaceHistoryEntry(
		LIBRARY_ROUTE_PATH,
		routerHistoryEntry({ library: { ...libraryRootState(), songId: STANDING_SONG_ID } })
	);
}

function pressBackOntoOtherSong(): void {
	const entry = routerHistoryEntry({
		library: { ...libraryRootState(), songId: OTHER_SONG_ID }
	});
	replaceHistoryEntry(LIBRARY_ROUTE_PATH, entry);
	window.dispatchEvent(new PopStateEvent('popstate', { state: entry }));
}

const setReady = (ready: boolean) =>
	resourceSync.update((state) => ({ ...state, ready, status: ready ? 'live' : 'connecting' }));
const standingSongFetches = () =>
	requests.filter((path) => path === `/api/songs/${STANDING_SONG_ID}`).length;
const contextLoads = () => requests.filter((path) => path === CONTEXT_LOAD_PATH).length;
const flushMicrotasks = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

function follow(): () => void {
	const stop = followLibrarySync();
	onTestFinished(stop);
	return stop;
}

beforeEach(() => {
	requests = [];
	failLibraryLists = false;
	goneSongId = null;
	toasts.set([]);
	FakeEventSource.instances = [];
	stubNetwork();
	resetResourceSyncForTests();
	resetNavigationForTests();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylistsForTests();
	resetCollectionForTests();
	stopFollowingShellLayers = followShellLayers();
	albumList.set([album({ share_slug: null })]);
	songList.set([]);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	replaceHistoryEntry(LIBRARY_ROUTE_PATH);
	startFakeRouter();
	installHistoryController();
});

afterEach(() => {
	stopFollowingShellLayers();
	stopLibraryResourceSync();
	resetHistoryControllerForTests();
	resetResourceSyncForTests();
	vi.unstubAllGlobals();
});

describe('navigation following the library sync', () => {
	it.each([
		['not ready', () => setReady(false)],
		[
			'in error',
			() => resourceSync.update((state) => ({ ...state, ready: false, status: 'error' }))
		]
	])(
		'applies a Back onto another library entry after the sync was %s and ready again',
		async (_, lose) => {
			follow();
			setReady(true);
			await flushMicrotasks();
			lose();
			setReady(true);
			await flushMicrotasks();

			pressBackOntoOtherSong();

			await vi.waitFor(() => expect(get(selectedSongId)).toBe(OTHER_SONG_ID));
		}
	);

	it('restores the standing songs context at each ready, with one landing handler', async () => {
		standOnSong();
		follow();

		setReady(true);
		await vi.waitFor(() => expect(contextLoads()).toBe(1));
		setReady(false);
		setReady(true);
		await vi.waitFor(() => expect(contextLoads()).toBe(2));
		await flushMicrotasks();
		pressBackOntoOtherSong();

		await vi.waitFor(() => expect(get(selectedSongId)).toBe(OTHER_SONG_ID));
		expect(contextLoads()).toBe(2);
	});

	it('loads nothing and attaches nothing once following has stopped', async () => {
		standOnSong();
		const stop = follow();
		stop();

		setReady(true);
		await flushMicrotasks();
		pressBackOntoOtherSong();
		await flushMicrotasks();

		expect(contextLoads()).toBe(0);
		expect(get(selectedSongId)).toBe(STANDING_SONG_ID);
	});

	it('does nothing for a ready flag already true when following starts, until it is lost and regained', async () => {
		standOnSong();
		setReady(true);
		follow();
		await flushMicrotasks();
		expect(contextLoads()).toBe(0);

		setReady(false);
		setReady(true);

		await vi.waitFor(() => expect(contextLoads()).toBe(1));
		pressBackOntoOtherSong();
		await vi.waitFor(() => expect(get(selectedSongId)).toBe(OTHER_SONG_ID));
	});

	async function failBootstrapThenRetry(): Promise<void> {
		failLibraryLists = true;
		startLibraryResourceSync(vi.fn());
		const stream = FakeEventSource.instances[0];
		expect(stream.url).toBe(RESOURCE_EVENT_STREAM_PATH);
		stream.hello();
		await vi.waitFor(() => expect(get(resourceSync).status).toBe('error'));

		failLibraryLists = false;
		const retried = retryResourceSync();
		FakeEventSource.instances.at(-1)?.hello();
		expect(await retried).toBe(true);
	}

	it.each([
		[
			'the first ready',
			async () => {
				startLibraryResourceSync(vi.fn());
				FakeEventSource.instances[0].hello();
			},
			2
		],
		['a ready after a failed bootstrap and a Retry', failBootstrapThenRetry, 3]
	])(
		'tells the person once that the standing song is gone at %s',
		async (_, reachReady, fetches) => {
			goneSongId = STANDING_SONG_ID;
			replaceHistoryEntry(
				LIBRARY_ROUTE_PATH,
				routerHistoryEntry({ library: { ...libraryRootState(), songId: STANDING_SONG_ID } })
			);
			follow();

			await reachReady();
			await vi.waitFor(() => expect(get(selectedSongId)).toBeNull());
			await flushMicrotasks();

			const messages = get(toasts).map((toast) => toast.message);
			expect(messages.filter((message) => message === SONG_LINK_NOT_FOUND_TOAST)).toHaveLength(1);
			expect(standingSongFetches()).toBe(fetches);
		}
	);

	it('applies a Back after a failed bootstrap and a Retry', async () => {
		follow();
		await failBootstrapThenRetry();
		await flushMicrotasks();
		pressBackOntoOtherSong();

		await vi.waitFor(() => expect(get(selectedSongId)).toBe(OTHER_SONG_ID));
	});
});

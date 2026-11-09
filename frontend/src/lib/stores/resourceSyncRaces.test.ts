import { makeGeneration, makeSong } from '#lib/test-utils/factories.ts';
import { deferred } from '#lib/test-utils/deferred.ts';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';

vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);

import { ApiError, NetworkError } from '#lib/api/fetch.ts';
import type { GenerationCreatedResourceEvent, SongItem } from '#lib/api/types.ts';
import { EVENT_SOURCE_CLOSED } from '#lib/constants/resource-sync.ts';
import { SSE_RECONNECT_MAX_DELAY_MS } from '#lib/constants/sse-reconnect.ts';
import { ResourceSyncController } from './resourceSync';

type Deps = ConstructorParameters<typeof ResourceSyncController>[0];
type Source = ReturnType<Deps['openEventStream']>;
type State = ResourceSyncController['state'];
type Probe = Awaited<ReturnType<Deps['probeAuth']>>;
type Deferred<T> = ReturnType<typeof deferred<T>>;

const DISCONNECTED: State = {
	status: 'disconnected',
	error: null,
	highWaterMark: null,
	appliedSequence: null,
	ready: false
};

/** A browser dispatches nothing to a source it closed, so neither does this one. */
class ClosableSource implements Source {
	closed = false;
	readyState = 0;
	onerror: ((event: Event) => void) | null = null;
	private readonly listeners = new Map<string, Set<(event: Event) => void>>();

	addEventListener(type: string, listener: (event: Event) => void): void {
		this.listeners.set(type, (this.listeners.get(type) ?? new Set()).add(listener));
	}

	removeEventListener(type: string, listener: (event: Event) => void): void {
		this.listeners.get(type)?.delete(listener);
	}

	close(): void {
		this.closed = true;
	}

	hello(highWaterMark = '0'): void {
		this.dispatch('hello', { high_water_mark: highWaterMark });
	}

	generationCreated(sequence: string, generationId: string, songId = 's1'): void {
		const event: GenerationCreatedResourceEvent = {
			kind: 'generation.created',
			sequence,
			resource_type: 'song',
			resource_id: songId,
			generation_id: generationId,
			created_at: '2026-01-01T00:00:00+00:00'
		};
		this.dispatch('generation.created', event);
	}

	failForGood(): void {
		this.readyState = EVENT_SOURCE_CLOSED;
		this.fail();
	}

	fail(): void {
		if (!this.closed) this.onerror?.(new Event('error'));
	}

	private dispatch(type: string, data: unknown): void {
		if (this.closed) return;
		const event = new MessageEvent(type, { data: JSON.stringify(data) });
		for (const listener of this.listeners.get(type) ?? []) listener(event);
	}
}

function songWithGeneration(songId: string, generationId: string): SongItem {
	return makeSong({
		id: songId,
		generation_count: 1,
		generations: [makeGeneration({ id: generationId, mp3_path: `${generationId}.mp3` })]
	});
}

function serverError(detail: string): ApiError {
	return new ApiError(500, detail, '/api/songs/s1');
}

function arrange(options: Partial<Deps> = {}) {
	const sources: ClosableSource[] = [];
	const fetchCalls: string[] = [];
	const store = writable<State>({ ...DISCONNECTED });
	const loadedWatch: { notify: (() => void) | null } = { notify: null };
	const innerFetch =
		options.fetchSong ?? (async (songId: string) => songWithGeneration(songId, `g-${songId}`));
	const controller = new ResourceSyncController(
		{
			openEventStream: () => {
				const source = new ClosableSource();
				sources.push(source);
				return source;
			},
			applySong: () => undefined,
			listLoadedSongIds: () => ['s1'],
			listPrioritySongIds: () => [],
			forgetSong: () => undefined,
			leaveGoneSong: () => undefined,
			watchLoadedSongs: (onChange) => {
				loadedWatch.notify = onChange;
				return () => {
					loadedWatch.notify = null;
				};
			},
			loadSnapshot: async () => true,
			cancelSnapshot: () => undefined,
			probeAuth: async () => 'ok',
			onUnauthorized: async () => undefined,
			reportStreamReachable: () => undefined,
			...options,
			fetchSong: async (songId: string) => {
				fetchCalls.push(songId);
				return innerFetch(songId);
			}
		},
		store
	);
	return {
		controller,
		sources,
		fetchCalls,
		store,
		loadedWatch,
		latest: () => sources[sources.length - 1]
	};
}

async function runMicrotasks(): Promise<void> {
	for (let turn = 0; turn < 20; turn++) await Promise.resolve();
}

async function goLive(world: ReturnType<typeof arrange>): Promise<void> {
	world.controller.start();
	world.latest().hello();
	await runMicrotasks();
	await world.controller.waitForReady();
}

afterEach(() => {
	vi.useRealTimers();
});

describe('resource sync after a reconnect or a stop', () => {
	it('opens the stream again when Retry follows an unauthorized probe', async () => {
		let probe: Probe = 'unauthorized';
		const world = arrange({ probeAuth: async () => probe });
		world.controller.start();
		world.latest().fail();
		await runMicrotasks();
		expect(world.latest().closed).toBe(true);
		probe = 'ok';

		const retried = world.controller.retry();
		world.latest().hello();
		await runMicrotasks();

		await expect(retried).resolves.toBe(true);
		expect(world.sources).toHaveLength(2);
		world.controller.stop();
	});

	it('shows the failure of the refetch when Retry fails again', async () => {
		vi.useFakeTimers();
		const failures = [serverError('first failure'), serverError('second failure')];
		const world = arrange({
			fetchSong: async () => {
				throw failures.shift();
			}
		});
		await goLive(world);
		await world.controller.requestSongRefresh('s1');
		expect(world.controller.state.error).toBe('first failure');

		await expect(world.controller.retry()).resolves.toBe(false);

		expect(world.controller.state.error).toBe('second failure');
		world.controller.stop();
	});

	it.each([
		{
			case: 'a live event for a generation the song fetch applied',
			fetched: 's1',
			play: async () => {
				const world = arrange();
				await goLive(world);
				await world.controller.requestSongRefresh('s1');
				world.latest().generationCreated('1', 'g-s1');
				await runMicrotasks();
				return world;
			}
		},
		{
			case: 'an event buffered while that generation was being fetched',
			fetched: 's1',
			play: async () => {
				const fetching = deferred<SongItem>();
				const world = arrange({ fetchSong: () => fetching.promise });
				const refreshed = world.controller.requestSongRefresh('s1');
				world.controller.start();
				world.latest().hello();
				await runMicrotasks();
				world.latest().generationCreated('1', 'g-s1');
				fetching.resolve(songWithGeneration('s1', 'g-s1'));
				await refreshed;
				await runMicrotasks();
				return world;
			}
		},
		{
			case: 'an event deferred until its song was loaded',
			fetched: 's2',
			play: async () => {
				let loaded = ['s1'];
				const world = arrange({ listLoadedSongIds: () => loaded });
				await goLive(world);
				world.latest().generationCreated('1', 'g-s2', 's2');
				await world.controller.requestSongRefresh('s2');
				loaded = ['s1', 's2'];
				world.loadedWatch.notify?.();
				await runMicrotasks();
				return world;
			}
		}
	])('fetches a song once when the server replays $case', async ({ play, fetched }) => {
		const world = await play();

		expect(world.fetchCalls).toEqual([fetched]);
		world.controller.stop();
	});

	it('keeps one copy of an event replayed for a song that is not loaded', async () => {
		const world = arrange();
		await goLive(world);

		world.latest().generationCreated('1', 'g-s2', 's2');
		world.latest().generationCreated('1', 'g-s2', 's2');

		expect(world.controller.trackedSizes.deferred).toBe(1);
		world.controller.stop();
	});
});

describe('resource sync bootstrap against a stop or a restart', () => {
	it('stays stopped when the stop comes while the bootstrap drains its songs', async () => {
		const fetching = deferred<SongItem>();
		const world = arrange({ fetchSong: () => fetching.promise });
		const refreshed = world.controller.requestSongRefresh('s1');
		world.controller.start();
		world.latest().hello();
		await runMicrotasks();

		world.controller.stop();
		fetching.resolve(songWithGeneration('s1', 'g-s1'));
		await refreshed;
		await runMicrotasks();

		expect(world.controller.state).toEqual(DISCONNECTED);
	});

	it.each([
		{ case: 'goes live', stopsFirst: false, status: 'live' },
		{ case: 'stays stopped when stopped', stopsFirst: true, status: 'disconnected' }
	])(
		'a bootstrap whose promoted songs are still being fetched $case',
		async ({ stopsFirst, status }) => {
			let loaded = ['s1'];
			const fetching = deferred<SongItem>();
			const world = arrange({
				fetchSong: () => fetching.promise,
				listLoadedSongIds: () => {
					const answer = loaded;
					loaded = ['s1', 's2'];
					return answer;
				},
				loadSnapshot: async () => true
			});
			world.controller.start();
			world.latest().hello();
			world.latest().generationCreated('1', 'g-s2', 's2');
			await runMicrotasks();

			if (stopsFirst) world.controller.stop();
			fetching.resolve(songWithGeneration('s2', 'g-s2'));
			await runMicrotasks();

			expect(world.controller.state.status).toBe(status);
			world.controller.stop();
		}
	);

	it.each([
		{
			case: 'fails',
			settleOlder: (fetch: Deferred<SongItem>) => fetch.reject(serverError('stale'))
		},
		{
			case: 'succeeds',
			settleOlder: (fetch: Deferred<SongItem>) => fetch.resolve(songWithGeneration('s1', 'g-old'))
		}
	])(
		'an older fetch of a song that $case changes nothing once a newer refresh was asked for',
		async ({ settleOlder }) => {
			const fetches = [deferred<SongItem>(), deferred<SongItem>()];
			const applied: string[] = [];
			let fetchCount = 0;
			const world = arrange({
				fetchSong: () => fetches[fetchCount++].promise,
				applySong: (song) => applied.push(...song.generations.map((item) => item.id))
			});
			const [older, newer] = [fetches[0], fetches[1]];
			await goLive(world);
			void world.controller.requestSongRefresh('s1');
			const refreshed = world.controller.requestSongRefresh('s1');

			settleOlder(older);
			await runMicrotasks();

			expect(world.controller.state.error).toBeNull();
			expect(applied).toEqual([]);
			newer.resolve(songWithGeneration('s1', 'g-new'));
			await refreshed;
			expect(applied).toEqual(['g-new']);
			expect(world.fetchCalls).toEqual(['s1', 's1']);
			world.controller.stop();
		}
	);

	it('answers a visibility check at once while the bootstrap still fetches its promoted songs', async () => {
		let loaded = ['s1'];
		const promoted = deferred<SongItem>();
		const world = arrange({
			fetchSong: (songId) =>
				songId === 's2' ? promoted.promise : Promise.resolve(songWithGeneration(songId, 'g-s1')),
			listLoadedSongIds: () => {
				const answer = loaded;
				loaded = ['s1', 's2'];
				return answer;
			},
			listPrioritySongIds: () => ['s1']
		});
		world.controller.start();
		world.latest().hello();
		world.latest().generationCreated('1', 'g-s2', 's2');
		await runMicrotasks();

		let answered = false;
		void world.controller.handleVisibility().then(() => {
			answered = true;
		});
		await runMicrotasks();

		expect(answered).toBe(true);
		promoted.resolve(songWithGeneration('s2', 'g-s2'));
		await runMicrotasks();
		expect(world.controller.state.status).toBe('live');
		world.controller.stop();
	});

	it('does not refetch a failed song when its retry timer fires during the bootstrap', async () => {
		vi.useFakeTimers();
		const slow = deferred<SongItem>();
		const world = arrange({
			fetchSong: (songId) =>
				songId === 's2'
					? slow.promise
					: Promise.reject(new NetworkError('/api/songs/s1', new TypeError('offline')))
		});
		void world.controller.requestSongRefresh('s1');
		void world.controller.requestSongRefresh('s2');
		world.controller.start();
		world.latest().hello();
		await runMicrotasks();

		await vi.advanceTimersByTimeAsync(SSE_RECONNECT_MAX_DELAY_MS * 2);

		expect(world.fetchCalls).toEqual(['s1', 's2']);
		slow.resolve(songWithGeneration('s2', 'g-s2'));
		await runMicrotasks();
		world.controller.stop();
	});

	it('spaces two reopens of a failed first sync that wait for their reconnect', async () => {
		vi.useFakeTimers();
		const world = arrange();
		world.controller.start();
		world.latest().failForGood();
		await runMicrotasks();

		window.dispatchEvent(new Event('focus'));
		expect(world.sources).toHaveLength(2);
		world.latest().failForGood();
		await runMicrotasks();
		window.dispatchEvent(new Event('focus'));

		expect(world.sources).toHaveLength(2);
		world.controller.stop();
	});
});

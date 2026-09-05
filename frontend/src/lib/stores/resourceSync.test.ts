import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get, writable } from 'svelte/store';

const mockClassifyAuthFailure = vi.hoisted(() => vi.fn());

vi.mock('$lib/stores/auth', () => {
	let user: { id: string } | null = null;
	const subscribers = new Set<(value: typeof user) => void>();
	const currentUser = {
		subscribe(fn: (value: typeof user) => void) {
			fn(user);
			subscribers.add(fn);
			return () => subscribers.delete(fn);
		},
		set(value: typeof user) {
			user = value;
			subscribers.forEach((fn) => fn(user));
		}
	};
	return {
		clearAuth: vi.fn(() => currentUser.set(null)),
		classifyAuthFailure: mockClassifyAuthFailure,
		currentUser
	};
});
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import { ApiError } from '$lib/api/fetch';
import { classifyAuthFailure, clearAuth, currentUser } from '$lib/stores/auth';
import { goto } from '$app/navigation';
import type {
	AuthUser,
	GenerationCreatedResourceEvent,
	GenerationItem,
	SongItem
} from '$lib/api/types';
import {
	RESOURCE_EVENT_STREAM_PATH,
	RESOURCE_SYNC_BOOTSTRAP_ERROR_LIMIT,
	RESOURCE_SYNC_ERROR,
	RESOURCE_SYNC_FETCH_CONCURRENCY,
	RESOURCE_SYNC_TRACKED_EVENT_LIMIT,
	RESOURCE_SYNC_VISIBILITY_DEBOUNCE_MS,
	SSE_RECONNECT_BASE_DELAY_MS,
	SSE_RECONNECT_JITTER_RATIO,
	SSE_RECONNECT_MAX_DELAY_MS
} from '$lib/constants';
import { AUTH_ACCOUNT_DISABLED_MESSAGE } from '$lib/constants/auth';
import {
	EMPTY_RESOURCE_SYNC,
	ResourceSyncController,
	probeResourceAuth,
	resetResourceSyncForTests,
	startLibraryResourceSync,
	stopLibraryResourceSync,
	type ResourceAuthProbe,
	type ResourceEventSource,
	type ResourceSyncDeps,
	type ResourceSyncState
} from './resourceSync';

// Jitter only adds to the exponential delay (never subtracts, see
// `sseReconnect.ts`), so a delay at the backoff ceiling can run up to
// `SSE_RECONNECT_MAX_DELAY_MS * (1 + SSE_RECONNECT_JITTER_RATIO)` -- the
// safe amount to advance fake timers by when a test just needs "long enough
// for any pending reconnect, at any attempt count, to have fired".
const SAFE_RECONNECT_ADVANCE_MS = SSE_RECONNECT_MAX_DELAY_MS * (1 + SSE_RECONNECT_JITTER_RATIO);

class MockEventSource implements ResourceEventSource {
	static instances: MockEventSource[] = [];
	url: string;
	withCredentials: boolean;
	closed = false;
	onerror: ((event: Event) => void) | null = null;
	private readonly listeners = new Map<string, Set<(event: Event) => void>>();

	constructor(url: string, init?: { withCredentials?: boolean }) {
		this.url = url;
		this.withCredentials = init?.withCredentials ?? false;
		MockEventSource.instances.push(this);
	}

	addEventListener(type: string, listener: (event: Event) => void): void {
		const listeners = this.listeners.get(type) ?? new Set();
		listeners.add(listener);
		this.listeners.set(type, listeners);
	}

	removeEventListener(type: string, listener: (event: Event) => void): void {
		this.listeners.get(type)?.delete(listener);
	}

	close(): void {
		this.closed = true;
	}

	emit(type: string, data: unknown): void {
		const event = new MessageEvent(type, { data: JSON.stringify(data) });
		for (const listener of this.listeners.get(type) ?? []) listener(event);
	}

	error(): void {
		this.onerror?.(new Event('error'));
	}
}

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		slug: 'track',
		title: 'Track',
		album_id: 'a1',
		album_title: 'Album',
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: '',
		prompt: '',
		bpm: 120,
		audio_duration: 180,
		key_scale: 'Am',
		generation_params: null,
		version_count: 1,
		generation_count: 0,
		best_scores: null,
		best_rating: null,
		generations: [],
		created_at: '2026-01-01T00:00:00+00:00',
		is_shared: false,
		share_slug: null,
		...overrides
	};
}

function gen(id: string, overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id,
		song_id: 's1',
		version_id: 'v1',
		version_number: 1,
		generation_number: 1,
		seed: 1,
		mp3_path: `${id}.mp3`,
		wav_path: null,
		status: 'completed',
		is_picked: false,
		is_kept: false,
		is_archived: false,
		is_shared: false,
		share_slug: null,
		model_mode: 'sft',
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: null,
		scores: null,
		generation_params: null,
		audio_duration_sec: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function created(
	sequence: string,
	generationId: string,
	resourceId = 's1'
): GenerationCreatedResourceEvent {
	return {
		kind: 'generation.created',
		sequence,
		resource_type: 'song',
		resource_id: resourceId,
		generation_id: generationId,
		created_at: '2026-01-01T00:00:00+00:00'
	};
}

function deferred<T>() {
	let resolve!: (value: T) => void;
	let reject!: (reason?: unknown) => void;
	const promise = new Promise<T>((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, resolve, reject };
}

async function flush(): Promise<void> {
	for (let i = 0; i < 20; i++) {
		await Promise.resolve();
	}
}

function setup(options?: {
	loadSnapshot?: ResourceSyncDeps['loadSnapshot'];
	fetchSong?: ResourceSyncDeps['fetchSong'];
	listLoadedSongIds?: ResourceSyncDeps['listLoadedSongIds'];
	listPrioritySongIds?: ResourceSyncDeps['listPrioritySongIds'];
	forgetSong?: ResourceSyncDeps['forgetSong'];
	probeAuth?: ResourceSyncDeps['probeAuth'];
	onUnauthorized?: ResourceSyncDeps['onUnauthorized'];
	applySong?: ResourceSyncDeps['applySong'];
	watchLoadedSongs?: ResourceSyncDeps['watchLoadedSongs'];
}) {
	const sources: MockEventSource[] = [];
	const store = writable<ResourceSyncState>({ ...EMPTY_RESOURCE_SYNC });
	const upserted: SongItem[] = [];
	const fetchCalls: string[] = [];
	const snapshotStarts: number[] = [];
	const cancelled: number[] = [];
	const forgotten: string[] = [];
	const loadedWatch: { notify: (() => void) | null } = { notify: null };
	const innerFetch =
		options?.fetchSong ??
		(async (songId: string) =>
			song({
				id: songId,
				generation_count: 1,
				generations: [gen('g-from-server')]
			}));
	const controller = new ResourceSyncController(
		{
			createEventSource: (url) => {
				const source = new MockEventSource(url);
				sources.push(source);
				return source;
			},
			fetchSong: async (songId: string) => {
				fetchCalls.push(songId);
				return innerFetch(songId);
			},
			applySong: (item) => {
				upserted.push(item);
				options?.applySong?.(item);
			},
			listLoadedSongIds: options?.listLoadedSongIds ?? (() => ['s1']),
			listPrioritySongIds: options?.listPrioritySongIds ?? (() => ['s1']),
			forgetSong: (songId) => {
				forgotten.push(songId);
				options?.forgetSong?.(songId);
			},
			watchLoadedSongs:
				options?.watchLoadedSongs ??
				((onChange) => {
					loadedWatch.notify = onChange;
					return () => {
						loadedWatch.notify = null;
					};
				}),
			loadSnapshot:
				options?.loadSnapshot ??
				(async () => {
					snapshotStarts.push(Date.now());
					return true;
				}),
			cancelSnapshot: () => {
				cancelled.push(1);
			},
			probeAuth: options?.probeAuth ?? (async () => 'ok'),
			onUnauthorized: options?.onUnauthorized ?? (async () => undefined)
		},
		store
	);
	return {
		controller,
		sources,
		store,
		upserted,
		fetchCalls,
		snapshotStarts,
		cancelled,
		forgotten,
		loadedWatch
	};
}

function latestSource(sources: MockEventSource[]): MockEventSource {
	return sources[sources.length - 1];
}

beforeEach(() => {
	MockEventSource.instances = [];
	mockClassifyAuthFailure.mockReset();
	mockClassifyAuthFailure.mockImplementation((error: { status?: unknown }) => {
		if (error.status === 401) return 'unauthorized';
		if (error.status === 403) return 'disabled';
		return 'retryable';
	});
});

afterEach(() => {
	resetResourceSyncForTests();
	vi.unstubAllGlobals();
	vi.useRealTimers();
});

describe('resource sync interleavings', () => {
	it('commit before hello is in the snapshot once', async () => {
		const snapshotSongs: SongItem[] = [];
		const { controller, sources, store, upserted, fetchCalls } = setup({
			loadSnapshot: async () => {
				snapshotSongs.push(song({ generation_count: 1, generations: [gen('g-before')] }));
				return true;
			}
		});
		controller.start();
		latestSource(sources).emit('hello', { high_water_mark: '1' });
		latestSource(sources).emit('generation.created', created('1', 'g-before'));
		await flush();
		await controller.waitForReady();
		expect(get(store).status).toBe('live');
		expect(fetchCalls).toEqual([]);
		expect(upserted).toEqual([]);
		expect(snapshotSongs[0].generations.map((item) => item.id)).toEqual(['g-before']);
		expect(snapshotSongs).toHaveLength(1);
	});

	it('commit between hello and snapshot is applied once after merge', async () => {
		const gate = deferred<boolean>();
		const { controller, sources, upserted, fetchCalls, store } = setup({
			loadSnapshot: () => gate.promise,
			fetchSong: async () => song({ generation_count: 1, generations: [gen('g-mid')] })
		});
		controller.start();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		latestSource(sources).emit('generation.created', created('1', 'g-mid'));
		gate.resolve(true);
		await flush();
		await controller.waitForReady();
		expect(get(store).status).toBe('live');
		expect(upserted.at(-1)?.generations.map((item) => item.id)).toEqual(['g-mid']);
		expect(fetchCalls.filter((id) => id === 's1')).toHaveLength(1);
	});

	it('commit during snapshot is buffered and visible once', async () => {
		const gate = deferred<boolean>();
		const { controller, sources, upserted, fetchCalls, store } = setup({
			loadSnapshot: () => gate.promise,
			fetchSong: async () => song({ generation_count: 1, generations: [gen('g-during')] })
		});
		controller.start();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		expect(fetchCalls).toEqual([]);
		latestSource(sources).emit('generation.created', created('1', 'g-during'));
		await flush();
		expect(fetchCalls).toEqual([]);
		gate.resolve(true);
		await flush();
		await controller.waitForReady();
		expect(get(store).status).toBe('live');
		expect(fetchCalls.filter((id) => id === 's1')).toHaveLength(1);
		const ids = upserted.flatMap((item) => item.generations.map((generation) => generation.id));
		expect(ids.filter((id) => id === 'g-during')).toEqual(['g-during']);
	});

	it('commit after snapshot is a live fetch without a toast owner', async () => {
		let snapshotDone = false;
		const { controller, sources, upserted } = setup({
			fetchSong: async () =>
				snapshotDone
					? song({ generation_count: 1, generations: [gen('g-live')] })
					: song({ generations: [] })
		});
		controller.start();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		await controller.waitForReady();
		snapshotDone = true;
		upserted.length = 0;
		latestSource(sources).emit('generation.created', created('1', 'g-live'));
		await flush();
		expect(upserted).toHaveLength(1);
		expect(upserted[0].generations[0].id).toBe('g-live');
	});
});

describe('resource sync owner', () => {
	it('bounds deferred events and remembered generation ids', async () => {
		let loaded: string[] = [];
		const newestSongId = `s-${RESOURCE_SYNC_TRACKED_EVENT_LIMIT + 1}`;
		const oldestSongId = 's-1';
		const seenSongId = 's-seen';
		const { controller, sources, fetchCalls, loadedWatch } = setup({
			listLoadedSongIds: () => loaded,
			fetchSong: async (songId) =>
				song({
					id: songId,
					generations:
						songId === seenSongId
							? Array.from({ length: RESOURCE_SYNC_TRACKED_EVENT_LIMIT + 1 }, (_, index) =>
									gen(`g-seen-${index + 1}`)
								)
							: [gen(`g-${songId}`)]
				})
		});
		controller.start();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		await controller.waitForReady();

		for (let sequence = 1; sequence <= RESOURCE_SYNC_TRACKED_EVENT_LIMIT + 1; sequence++) {
			latestSource(sources).emit(
				'generation.created',
				created(String(sequence), `g-deferred-${sequence}`, `s-${sequence}`)
			);
		}
		await flush();
		expect(controller.trackedSizes.deferred).toBe(RESOURCE_SYNC_TRACKED_EVENT_LIMIT);

		loaded = [newestSongId];
		loadedWatch.notify?.();
		await flush();
		expect(fetchCalls).toEqual([newestSongId]);

		loaded = [newestSongId, oldestSongId];
		loadedWatch.notify?.();
		await flush();
		expect(fetchCalls).toEqual([newestSongId]);

		loaded = [seenSongId];
		latestSource(sources).emit('generation.created', created('258', 'g-seen-trigger', seenSongId));
		await flush();
		expect(fetchCalls).toEqual([newestSongId, seenSongId]);
		expect(controller.trackedSizes.seenGenerationIds).toBe(RESOURCE_SYNC_TRACKED_EVENT_LIMIT);
	});

	it('duplicate sequence and generation id stay idempotent', async () => {
		let snapshotDone = false;
		const { controller, sources, fetchCalls, upserted } = setup({
			fetchSong: async () =>
				snapshotDone
					? song({ generation_count: 1, generations: [gen('g-dup')] })
					: song({ generations: [] })
		});
		controller.start();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		await controller.waitForReady();
		snapshotDone = true;
		const fetchesAfterReady = fetchCalls.length;
		latestSource(sources).emit('generation.created', created('1', 'g-dup'));
		latestSource(sources).emit('generation.created', created('1', 'g-dup'));
		await flush();
		expect(fetchCalls.length - fetchesAfterReady).toBe(1);
		expect(upserted.filter((item) => item.generations[0]?.id === 'g-dup')).toHaveLength(1);
	});

	it('stale fetch completions are discarded by revision', async () => {
		const first = deferred<SongItem>();
		let calls = 0;
		const { controller, sources, upserted } = setup({
			fetchSong: async () => {
				calls += 1;
				if (calls === 1) return first.promise;
				return song({ generation_count: 1, generations: [gen('g-new')] });
			}
		});
		controller.start();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		await controller.waitForReady();
		upserted.length = 0;
		latestSource(sources).emit('generation.created', created('1', 'g-old'));
		await flush();
		latestSource(sources).emit('generation.created', created('2', 'g-new'));
		await flush();
		first.resolve(song({ generation_count: 1, generations: [gen('g-old')] }));
		await flush();
		expect(upserted.map((item) => item.generations[0]?.id)).toEqual(['g-new']);
	});

	it('disconnect during snapshot does not mark the store live', async () => {
		const gate = deferred<boolean>();
		const { controller, sources, store } = setup({
			loadSnapshot: () => gate.promise
		});
		controller.start();
		const ready = controller.waitForReady();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		latestSource(sources).error();
		await flush();
		expect(get(store).status).toBe('reconnecting');
		expect(get(store).ready).toBe(false);
		gate.resolve(true);
		await flush();
		expect(get(store).status).toBe('reconnecting');
		expect(get(store).ready).toBe(false);
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		expect(await ready).toBe(true);
		expect(get(store).status).toBe('live');
	});

	it('resync during bootstrap reloads the snapshot before live', async () => {
		const loads: number[] = [];
		const first = deferred<boolean>();
		const { controller, sources, store } = setup({
			loadSnapshot: async () => {
				loads.push(1);
				if (loads.length === 1) return first.promise;
				return true;
			}
		});
		controller.start();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		latestSource(sources).emit('resync', { high_water_mark: '4' });
		first.resolve(true);
		await flush();
		await controller.waitForReady();
		expect(loads.length).toBeGreaterThanOrEqual(2);
		expect(get(store).status).toBe('live');
		expect(get(store).highWaterMark).toBe('4');
	});

	it('focus revalidation fetches the selected song, not the whole browse page', async () => {
		const { controller, sources, fetchCalls } = setup({
			listLoadedSongIds: () => ['s1', 's2', 's3'],
			listPrioritySongIds: () => ['s1']
		});
		controller.start();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		await controller.waitForReady();
		const before = fetchCalls.length;
		await controller.handleVisibility();
		expect(fetchCalls.slice(before)).toEqual(['s1']);
	});

	it('limits simultaneous refresh requests while applying every invalidated song', async () => {
		const ids = Array.from(
			{ length: RESOURCE_SYNC_FETCH_CONCURRENCY + 1 },
			(_, index) => `s${index + 1}`
		);
		const inFlight = new Set<string>();
		const maxInFlight: number[] = [];
		const responses = new Map<string, ReturnType<typeof deferred<SongItem>>>();
		const { controller, sources, upserted } = setup({
			listPrioritySongIds: () => ids,
			fetchSong: (songId) => {
				inFlight.add(songId);
				maxInFlight.push(inFlight.size);
				const response = deferred<SongItem>();
				responses.set(songId, response);
				return response.promise.finally(() => inFlight.delete(songId));
			}
		});
		controller.start();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		await controller.waitForReady();

		const refresh = controller.handleVisibility();
		await vi.waitFor(() => expect(responses.size).toBe(RESOURCE_SYNC_FETCH_CONCURRENCY));
		expect(inFlight.size).toBe(RESOURCE_SYNC_FETCH_CONCURRENCY);
		for (const songId of inFlight) {
			const response = responses.get(songId);
			if (!response) throw new Error(`Missing response for ${songId}`);
			response.resolve(
				song({ id: songId, generations: [gen(`g-${songId}`, { song_id: songId })] })
			);
		}
		await vi.waitFor(() => expect(responses.size).toBe(ids.length));
		for (const songId of inFlight) {
			const response = responses.get(songId);
			if (!response) throw new Error(`Missing response for ${songId}`);
			response.resolve(
				song({ id: songId, generations: [gen(`g-${songId}`, { song_id: songId })] })
			);
		}
		await refresh;

		expect(Math.max(...maxInFlight)).toBe(RESOURCE_SYNC_FETCH_CONCURRENCY);
		expect(upserted).toHaveLength(ids.length);
		expect(upserted.map((item) => item.id)).toEqual(expect.arrayContaining(ids));
	});

	it('refresh errors are visible and retryable', async () => {
		let fail = true;
		const { controller, sources, store } = setup({
			loadSnapshot: async () => {
				if (fail) return false;
				return true;
			}
		});
		controller.start();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		await controller.waitForReady();
		expect(get(store).status).toBe('error');
		expect(get(store).error).toBe(RESOURCE_SYNC_ERROR);
		expect(get(store).ready).toBe(false);
		fail = false;
		const ready = controller.retry();
		await flush();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		expect(await ready).toBe(true);
		expect(get(store).status).toBe('live');
		expect(get(store).error).toBeNull();
	});

	it('live fetch errors stay pending for retry', async () => {
		let fail = true;
		const { controller, sources, store, upserted } = setup({
			fetchSong: async () => {
				if (fail) throw new Error('boom');
				return song({ generations: [gen('g1')] });
			}
		});
		controller.start();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		await controller.waitForReady();
		latestSource(sources).emit('generation.created', created('1', 'g1'));
		await flush();
		expect(get(store).status).toBe('error');
		expect(get(store).error).toBe('boom');
		fail = false;
		expect(await controller.retry()).toBe(true);
		expect(get(store).status).toBe('live');
		expect(upserted.at(-1)?.generations[0]?.id).toBe('g1');
	});

	it('unauthorized stream errors stop the owner and clear auth', async () => {
		const onUnauthorized = vi.fn(async () => undefined);
		const { controller, sources, store } = setup({
			probeAuth: async () => 'unauthorized',
			onUnauthorized
		});
		controller.start();
		const source = latestSource(sources);
		source.error();
		await flush();
		expect(source.closed).toBe(true);
		expect(get(store).status).toBe('error');
		expect(onUnauthorized).toHaveBeenCalledOnce();
	});

	it('a disabled-account probe stops the owner without running the session-lost reaction', async () => {
		const onUnauthorized = vi.fn(async () => undefined);
		const { controller, sources, store } = setup({
			probeAuth: async () => 'disabled',
			onUnauthorized
		});
		controller.start();
		const source = latestSource(sources);
		source.error();
		await flush();
		expect(source.closed).toBe(true);
		expect(get(store).status).toBe('error');
		expect(get(store).error).toBe(AUTH_ACCOUNT_DISABLED_MESSAGE);
		expect(onUnauthorized).not.toHaveBeenCalled();
	});

	it('does not schedule a timer reconnect after a disabled-account probe', async () => {
		vi.useFakeTimers();
		const { controller, sources } = setup({ probeAuth: async () => 'disabled' });
		controller.start();
		latestSource(sources).error();
		await flush();
		expect(sources).toHaveLength(1);
		await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);
		await flush();
		expect(sources).toHaveLength(1);
	});

	it('a manual retry after a disabled-account probe opens exactly one new EventSource', async () => {
		const { controller, sources } = setup({ probeAuth: async () => 'disabled' });
		controller.start();
		latestSource(sources).error();
		await flush();
		expect(sources).toHaveLength(1);
		expect(sources[0].closed).toBe(true);

		void controller.retry();
		await flush();

		expect(sources).toHaveLength(2);
		expect(sources[1].closed).toBe(false);
	});

	it('opens a native EventSource with credentials and cleans it up', async () => {
		const { controller, sources, store } = setup();
		controller.start();
		expect(sources).toHaveLength(1);
		expect(sources[0].url).toBe(RESOURCE_EVENT_STREAM_PATH);
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		await controller.waitForReady();
		controller.stop();
		expect(sources[0].closed).toBe(true);
		expect(get(store)).toEqual(EMPTY_RESOURCE_SYNC);
	});

	it('cleanup unbinds visibility revalidation', async () => {
		const { controller, sources, fetchCalls } = setup();
		controller.start();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		await controller.waitForReady();
		controller.stop();
		const before = fetchCalls.length;
		window.dispatchEvent(new Event('focus'));
		document.dispatchEvent(new Event('visibilitychange'));
		await flush();
		expect(fetchCalls).toHaveLength(before);
	});

	it('counts bootstrap failures across hello frames until retry is shown', async () => {
		const gate = deferred<boolean>();
		const { controller, sources, store } = setup({
			loadSnapshot: () => gate.promise
		});
		controller.start();
		const ready = controller.waitForReady();
		for (let i = 0; i < RESOURCE_SYNC_BOOTSTRAP_ERROR_LIMIT; i++) {
			latestSource(sources).emit('hello', { high_water_mark: '0' });
			await flush();
			latestSource(sources).error();
			await flush();
		}
		gate.resolve(true);
		await flush();
		expect(await ready).toBe(false);
		expect(get(store).status).toBe('error');
		expect(get(store).ready).toBe(false);
	});

	it('persistent stream errors during bootstrap become a retryable error', async () => {
		const { controller, sources, store } = setup();
		controller.start();
		const ready = controller.waitForReady();
		for (let i = 0; i < RESOURCE_SYNC_BOOTSTRAP_ERROR_LIMIT; i++) {
			latestSource(sources).error();
			await flush();
		}
		expect(await ready).toBe(false);
		expect(get(store).status).toBe('error');
		expect(get(store).error).toBe(RESOURCE_SYNC_ERROR);
		expect(get(store).ready).toBe(false);
		expect(sources[0].closed).toBe(true);
	});

	it('ignores a stale auth probe after a new hello starts a snapshot', async () => {
		const probe = deferred<ResourceAuthProbe>();
		const firstSnapshot = deferred<boolean>();
		const loads: number[] = [];
		const { controller, sources, store } = setup({
			loadSnapshot: async () => {
				loads.push(1);
				if (loads.length === 1) return firstSnapshot.promise;
				return true;
			},
			probeAuth: async () => probe.promise
		});
		controller.start();
		const ready = controller.waitForReady();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		latestSource(sources).error();
		await flush();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		probe.resolve('ok');
		firstSnapshot.resolve(true);
		await flush();
		expect(await ready).toBe(true);
		expect(get(store).status).toBe('live');
		expect(loads.length).toBeGreaterThanOrEqual(2);
	});

	it('retries failed live refreshes on the next hello instead of hiding them', async () => {
		vi.useFakeTimers();
		let fail = true;
		const { controller, sources, store, upserted } = setup({
			fetchSong: async () => {
				if (fail) throw new Error('boom');
				return song({ generations: [gen('g1')] });
			}
		});
		controller.start();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		await controller.waitForReady();
		latestSource(sources).emit('generation.created', created('1', 'g1'));
		await flush();
		expect(get(store).status).toBe('error');
		latestSource(sources).error();
		await flush();
		expect(get(store).status).toBe('error');
		// The dropped connection reconnects itself after a backoff delay
		// (issue #257) instead of relying on the browser's native retry.
		await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);
		await flush();
		fail = false;
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		expect(get(store).status).toBe('live');
		expect(get(store).error).toBeNull();
		expect(upserted.at(-1)?.generations[0]?.id).toBe('g1');
	});

	it('retains invalidations until an in-flight song enters the loaded set', async () => {
		let loaded: string[] = [];
		const { controller, sources, fetchCalls, upserted, loadedWatch } = setup({
			listLoadedSongIds: () => loaded
		});
		controller.start();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		await controller.waitForReady();
		latestSource(sources).emit('generation.created', created('1', 'g-late'));
		await flush();
		expect(fetchCalls).toEqual([]);
		loaded = ['s1'];
		loadedWatch.notify?.();
		await flush();
		expect(fetchCalls).toEqual(['s1']);
		expect(upserted.at(-1)?.generations[0]?.id).toBe('g-from-server');
	});

	it('clears a live refresh error after a later fetch succeeds', async () => {
		let fail = true;
		const { controller, sources, store } = setup({
			fetchSong: async () => {
				if (fail) throw new Error('boom');
				return song({ generations: [gen('g1')] });
			}
		});
		controller.start();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		await controller.waitForReady();
		latestSource(sources).emit('generation.created', created('1', 'g1'));
		await flush();
		expect(get(store).status).toBe('error');
		fail = false;
		latestSource(sources).emit('generation.created', created('2', 'g2'));
		await flush();
		expect(get(store).status).toBe('live');
		expect(get(store).error).toBeNull();
	});

	it('revalidates the selected song on document visibilitychange', async () => {
		vi.useFakeTimers();
		const { controller, sources, fetchCalls } = setup({
			listLoadedSongIds: () => ['s1', 's2'],
			listPrioritySongIds: () => ['s1']
		});
		controller.start();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		await controller.waitForReady();
		const before = fetchCalls.length;
		Object.defineProperty(document, 'visibilityState', {
			configurable: true,
			value: 'visible'
		});
		document.dispatchEvent(new Event('visibilitychange'));
		document.dispatchEvent(new Event('visibilitychange'));
		await vi.advanceTimersByTimeAsync(RESOURCE_SYNC_VISIBILITY_DEBOUNCE_MS);
		await flush();
		expect(fetchCalls.slice(before)).toEqual(['s1']);
		vi.useRealTimers();
	});

	it('reopens the live stream only after a backoff delay, not immediately', async () => {
		vi.useFakeTimers();
		const { controller, sources, store } = setup();
		controller.start();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		await controller.waitForReady();
		const beforeError = sources.length;

		latestSource(sources).error();
		await flush();
		expect(get(store).status).toBe('reconnecting');
		expect(sources).toHaveLength(beforeError);

		await vi.advanceTimersByTimeAsync(SSE_RECONNECT_BASE_DELAY_MS - 1);
		expect(sources).toHaveLength(beforeError);

		await vi.advanceTimersByTimeAsync(SSE_RECONNECT_BASE_DELAY_MS * SSE_RECONNECT_JITTER_RATIO + 1);
		expect(sources).toHaveLength(beforeError + 1);
	});

	it('grows the backoff delay on successive live drops and resets after a hello', async () => {
		vi.useFakeTimers();
		const { controller, sources } = setup();
		controller.start();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		await controller.waitForReady();

		latestSource(sources).error();
		await flush();
		await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);
		expect(sources).toHaveLength(2);

		latestSource(sources).error();
		await flush();
		await vi.advanceTimersByTimeAsync(
			SSE_RECONNECT_BASE_DELAY_MS * (1 + SSE_RECONNECT_JITTER_RATIO)
		);
		expect(sources).toHaveLength(2);
		await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);
		expect(sources).toHaveLength(3);

		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		latestSource(sources).error();
		await flush();
		await vi.advanceTimersByTimeAsync(
			SSE_RECONNECT_BASE_DELAY_MS * (1 + SSE_RECONNECT_JITTER_RATIO)
		);
		expect(sources).toHaveLength(4);
	});

	it('cancels a pending reconnect when the owner stops', async () => {
		vi.useFakeTimers();
		const { controller, sources } = setup();
		controller.start();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		await controller.waitForReady();
		const beforeError = sources.length;

		latestSource(sources).error();
		await flush();
		controller.stop();
		await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);
		expect(sources).toHaveLength(beforeError);
	});

	it('drops a 404 song instead of retrying it forever', async () => {
		const { controller, sources, store, forgotten } = setup({
			fetchSong: async () => {
				throw new ApiError(404, 'Song not found', '/api/songs/s1');
			}
		});
		controller.start();
		latestSource(sources).emit('hello', { high_water_mark: '0' });
		await flush();
		await controller.waitForReady();
		latestSource(sources).emit('generation.created', created('1', 'g1'));
		await flush();
		expect(forgotten).toEqual(['s1']);
		expect(get(store).status).toBe('live');
		expect(get(store).error).toBeNull();
	});
});

function stubFetchOnce(status: number) {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: false,
			status,
			headers: { get: () => null },
			json: () => Promise.resolve({ detail: '' })
		})
	);
}

describe('probeResourceAuth', () => {
	it.each([
		[403, 'disabled'],
		[401, 'unauthorized'],
		[500, 'retryable']
	] as const)('uses the shared classifier for a %i auth probe', async (status, expected) => {
		stubFetchOnce(status);
		expect(await probeResourceAuth()).toBe(expected);
		expect(classifyAuthFailure).toHaveBeenCalledOnce();
	});
});

describe('library resource sync wiring', () => {
	it('starts a credentialed EventSource and stops it on demand', () => {
		vi.stubGlobal('EventSource', MockEventSource);
		startLibraryResourceSync();
		expect(MockEventSource.instances).toHaveLength(1);
		expect(MockEventSource.instances[0].url).toBe(RESOURCE_EVENT_STREAM_PATH);
		expect(MockEventSource.instances[0].withCredentials).toBe(true);
		stopLibraryResourceSync();
		expect(MockEventSource.instances[0].closed).toBe(true);
	});

	it('routes a 401 on its auth probe through the one shared session-lost reaction', async () => {
		vi.stubGlobal('EventSource', MockEventSource);
		vi.stubGlobal(
			'fetch',
			vi.fn().mockResolvedValue({
				ok: false,
				status: 401,
				headers: { get: () => null },
				json: () => Promise.resolve({ detail: 'Not authenticated' })
			})
		);
		currentUser.set({ id: 'u1', username: 'felix', role: 'user' } as AuthUser);

		startLibraryResourceSync();
		MockEventSource.instances[0].error();
		// Deeper chain than elsewhere here (a real apiFetch round trip plus
		// two dynamic imports), so one flush() isn't always enough ticks.
		await flush();
		await flush();

		expect(clearAuth).toHaveBeenCalledOnce();
		expect(goto).toHaveBeenCalledOnce();
		expect(vi.mocked(goto).mock.calls[0][0]).toMatch(/^\/login\?redirect=/);
	});
});

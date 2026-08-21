import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { get, writable } from 'svelte/store';

import type { GenerationItem, SongItem } from '$lib/api/types';
import type { GenerationCreatedEvent, ResourceStreamEvent } from '$lib/api/resourceEvents';
import { RESOURCE_SYNC_ERROR } from '$lib/constants';
import {
	EMPTY_RESOURCE_SYNC,
	ResourceSyncController,
	type ResourceSyncDeps,
	type ResourceSyncState
} from './resourceSync';

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
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
		scores: null,
		generation_params: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function created(sequence: number, generationId: string): GenerationCreatedEvent {
	return {
		type: 'generation.created',
		kind: 'generation.created',
		sequence,
		user_id: 'u1',
		resource_type: 'song',
		resource_id: 's1',
		song_id: 's1',
		generation_id: generationId,
		created_at: '2026-01-01T00:00:00+00:00'
	};
}

function createPushStream() {
	const queue: ResourceStreamEvent[] = [];
	const waiters: Array<() => void> = [];
	let closed = false;
	const lastEventIds: Array<number | null> = [];

	async function* open(
		lastEventId: number | null,
		signal: AbortSignal
	): AsyncGenerator<ResourceStreamEvent> {
		closed = false;
		lastEventIds.push(lastEventId);
		while (!closed && !signal.aborted) {
			if (queue.length > 0) {
				yield queue.shift() as ResourceStreamEvent;
				continue;
			}
			await new Promise<void>((resolve) => {
				const onAbort = () => {
					signal.removeEventListener('abort', onAbort);
					resolve();
				};
				signal.addEventListener('abort', onAbort, { once: true });
				waiters.push(() => {
					signal.removeEventListener('abort', onAbort);
					resolve();
				});
			});
		}
	}

	function push(event: ResourceStreamEvent): void {
		queue.push(event);
		for (const waiter of waiters.splice(0)) waiter();
	}

	function close(): void {
		closed = true;
		for (const waiter of waiters.splice(0)) waiter();
	}

	return { open, push, close, lastEventIds };
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
	for (let i = 0; i < 15; i++) {
		await Promise.resolve();
	}
	await vi.advanceTimersByTimeAsync(0);
}

function setup(options?: {
	openSongId?: string | null;
	loadVisibleLibrary?: ResourceSyncDeps['loadVisibleLibrary'];
	fetchSong?: ResourceSyncDeps['fetchSong'];
}) {
	const stream = createPushStream();
	const store = writable<ResourceSyncState>({ ...EMPTY_RESOURCE_SYNC });
	const upserted: SongItem[] = [];
	const fetchCalls: string[] = [];
	const snapshotStarts: number[] = [];
	const innerFetch =
		options?.fetchSong ??
		(async (songId: string) =>
			song({
				id: songId,
				generation_count: 1,
				generations: [gen('g-from-server')]
			}));
	const fetchSong = async (songId: string) => {
		fetchCalls.push(songId);
		return innerFetch(songId);
	};
	const loadVisibleLibrary =
		options?.loadVisibleLibrary ??
		(async () => {
			snapshotStarts.push(Date.now());
			return true;
		});
	const controller = new ResourceSyncController(
		{
			openStream: stream.open,
			fetchSong,
			upsertSong: (item) => {
				upserted.push(item);
			},
			loadVisibleLibrary,
			getOpenSongId: () => options?.openSongId ?? 's1',
			delay: async () => undefined
		},
		store
	);
	return { controller, stream, store, upserted, fetchCalls, snapshotStarts };
}

beforeEach(() => {
	vi.useFakeTimers();
});

afterEach(() => {
	vi.useRealTimers();
});

describe('resource sync handshake', () => {
	it('commit before hello is in the snapshot once', async () => {
		const { controller, stream, store, upserted, fetchCalls } = setup({
			fetchSong: async () =>
				song({ generation_count: 1, generations: [gen('g-before')] })
		});
		controller.start();
		stream.push({ type: 'hello', high_water_mark: 1 });
		stream.push(created(1, 'g-before'));
		await flush();
		await controller.waitForReady();
		expect(get(store).phase).toBe('live');
		expect(fetchCalls.filter((id) => id === 's1').length).toBe(1);
		expect(upserted[0].generations.map((g) => g.id)).toEqual(['g-before']);
	});

	it('commit between hello and snapshot is applied once after merge', async () => {
		const gate = deferred<boolean>();
		const { controller, stream, upserted, fetchCalls } = setup({
			loadVisibleLibrary: () => gate.promise,
			fetchSong: async () =>
				song({ generation_count: 1, generations: [gen('g-mid')] })
		});
		controller.start();
		stream.push({ type: 'hello', high_water_mark: 0 });
		await flush();
		stream.push(created(1, 'g-mid'));
		gate.resolve(true);
		await flush();
		await controller.waitForReady();
		expect(upserted.at(-1)?.generations.map((g) => g.id)).toEqual(['g-mid']);
		expect(fetchCalls.filter((id) => id === 's1').length).toBeGreaterThanOrEqual(1);
	});

	it('commit during snapshot is buffered and visible once', async () => {
		const gate = deferred<boolean>();
		const songsByFetch = [
			song({ generations: [] }),
			song({ generation_count: 1, generations: [gen('g-during')] })
		];
		const { controller, stream, upserted } = setup({
			loadVisibleLibrary: () => gate.promise,
			fetchSong: async () => songsByFetch.shift() ?? song()
		});
		controller.start();
		stream.push({ type: 'hello', high_water_mark: 0 });
		await flush();
		stream.push(created(1, 'g-during'));
		gate.resolve(true);
		await flush();
		await controller.waitForReady();
		const ids = upserted.flatMap((item) => item.generations.map((g) => g.id));
		expect(ids.filter((id) => id === 'g-during')).toEqual(['g-during']);
	});

	it('commit after snapshot is a live fetch without a toast owner', async () => {
		let snapshotDone = false;
		const { controller, stream, upserted } = setup({
			fetchSong: async () =>
				snapshotDone
					? song({ generation_count: 1, generations: [gen('g-live')] })
					: song({ generations: [] })
		});
		controller.start();
		stream.push({ type: 'hello', high_water_mark: 0 });
		await flush();
		await controller.waitForReady();
		snapshotDone = true;
		upserted.length = 0;
		stream.push(created(1, 'g-live'));
		await flush();
		expect(upserted).toHaveLength(1);
		expect(upserted[0].generations[0].id).toBe('g-live');
	});

	it('duplicate sequence and generation id stay idempotent', async () => {
		let snapshotDone = false;
		const { controller, stream, fetchCalls, upserted } = setup({
			fetchSong: async () =>
				snapshotDone
					? song({ generation_count: 1, generations: [gen('g-dup')] })
					: song({ generations: [] })
		});
		controller.start();
		stream.push({ type: 'hello', high_water_mark: 0 });
		await flush();
		await controller.waitForReady();
		snapshotDone = true;
		const fetchesAfterReady = fetchCalls.length;
		stream.push(created(1, 'g-dup'));
		stream.push(created(1, 'g-dup'));
		await flush();
		expect(fetchCalls.length - fetchesAfterReady).toBe(1);
		expect(upserted.filter((item) => item.generations[0]?.id === 'g-dup')).toHaveLength(
			1
		);
	});

	it('disconnect during snapshot does not mark the store live', async () => {
		const gate = deferred<boolean>();
		const { controller, stream, store } = setup({
			loadVisibleLibrary: () => gate.promise
		});
		const ready = controller.waitForReady();
		controller.start();
		stream.push({ type: 'hello', high_water_mark: 0 });
		await flush();
		stream.close();
		await flush();
		expect(get(store).phase).not.toBe('live');
		gate.resolve(true);
		await flush();
		expect(await ready).toBe(true);
		expect(get(store).phase).toBe('live');
		controller.stop();
	});

	it('resync during bootstrap reloads the snapshot before live', async () => {
		const loads: number[] = [];
		const { controller, stream, store } = setup({
			loadVisibleLibrary: async () => {
				loads.push(1);
				return true;
			}
		});
		controller.start();
		stream.push({ type: 'hello', high_water_mark: 0 });
		await flush();
		stream.push({ type: 'resync', high_water_mark: 4 });
		await flush();
		await controller.waitForReady();
		expect(loads.length).toBeGreaterThanOrEqual(2);
		expect(get(store).phase).toBe('live');
		expect(get(store).highWaterMark).toBe(4);
	});

	it('visibility revalidation fetches the open song', async () => {
		const { controller, stream, fetchCalls } = setup();
		controller.start();
		stream.push({ type: 'hello', high_water_mark: 0 });
		await flush();
		await controller.waitForReady();
		const before = fetchCalls.length;
		await controller.handleVisibility();
		expect(fetchCalls.length).toBe(before + 1);
		expect(fetchCalls.at(-1)).toBe('s1');
	});

	it('refresh errors are visible and retryable', async () => {
		let fail = true;
		const { controller, stream, store } = setup({
			fetchSong: async () => {
				if (fail) throw new Error('boom');
				return song({ generations: [gen('g1')] });
			}
		});
		controller.start();
		stream.push({ type: 'hello', high_water_mark: 0 });
		await flush();
		await controller.waitForReady();
		expect(get(store).phase).toBe('error');
		expect(get(store).error).toBe('boom');
		fail = false;
		const ready = controller.retry();
		await flush();
		stream.push({ type: 'hello', high_water_mark: 0 });
		await flush();
		const ok = await ready;
		expect(ok).toBe(true);
		expect(get(store).phase).toBe('live');
		expect(get(store).error).toBeNull();
	});

	it('reconnects with the applied cursor after live', async () => {
		const { controller, stream } = setup({
			fetchSong: async () => song({ generations: [gen('g1')] })
		});
		controller.start();
		stream.push({ type: 'hello', high_water_mark: 0 });
		await flush();
		await controller.waitForReady();
		stream.push(created(1, 'g1'));
		await flush();
		stream.close();
		expect(stream.lastEventIds[0]).toBeNull();
	});
});

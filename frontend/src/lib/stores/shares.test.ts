import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { ShareInventoryItem, SongItem } from '$lib/api/types';
import { ApiError } from '$lib/api/fetch';
import { API_ERROR_GENERIC_MESSAGE, LIBRARY_SHARES_ERROR } from '$lib/constants';

const fetchShares = vi.fn();

vi.mock('$lib/api/library', () => ({
	fetchShares: (...args: unknown[]) => fetchShares(...args)
}));

import {
	closeSharesInventory,
	loadShareInventory,
	loadMoreShares,
	openSharesInventory,
	patchSharesFromSong,
	refreshSharesAfterMutation,
	refreshShareCount,
	resetShares,
	setShareTypeFilter,
	shareCount,
	shareInventory,
	sharesViewOpen,
	toggleSharesInventory,
	watchShareStatus,
	watchShareView
} from './shares';

function page(
	overrides: Partial<{
		items: ShareInventoryItem[];
		total: number;
		offset: number;
		limit: number;
		has_more: boolean;
	}> = {}
) {
	return {
		items: [],
		total: 0,
		offset: 0,
		limit: 50,
		has_more: false,
		...overrides
	};
}

function item(overrides: Partial<ShareInventoryItem> = {}): ShareInventoryItem {
	return {
		type: 'album',
		id: 'a1',
		title: 'Nachtstrom',
		share_slug: 'slug-a',
		created_at: '2026-01-01T00:00:00+00:00',
		public_path: '/share/slug-a',
		...overrides
	};
}

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		slug: 'tide',
		title: 'Tide',
		album_id: 'a1',
		album_title: 'Nachtstrom',
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
		is_shared: true,
		share_slug: 'slug-s',
		...overrides
	};
}

beforeEach(() => {
	fetchShares.mockReset();
	fetchShares.mockResolvedValue(page());
	resetShares();
});

afterEach(() => {
	resetShares();
});

describe('share request failures', () => {
	it.each([
		['count', 'an API detail', new ApiError(400, 'server detail', '/api/shares'), 'server detail'],
		[
			'count',
			'an API message without a detail',
			new ApiError(400, '', '/api/shares'),
			API_ERROR_GENERIC_MESSAGE
		],
		['count', 'an unknown rejection', 'offline', LIBRARY_SHARES_ERROR],
		[
			'inventory',
			'an API detail',
			new ApiError(400, 'server detail', '/api/shares'),
			'server detail'
		],
		[
			'inventory',
			'an API message without a detail',
			new ApiError(400, '', '/api/shares'),
			API_ERROR_GENERIC_MESSAGE
		],
		['inventory', 'an unknown rejection', null, LIBRARY_SHARES_ERROR]
	])('shows %s request failure for %s', async (target, _caseName, failure, error) => {
		fetchShares.mockRejectedValueOnce(failure);

		const loaded =
			target === 'count' ? await refreshShareCount() : await loadShareInventory({ reset: true });
		const state = target === 'count' ? get(shareCount) : get(shareInventory);

		expect(loaded).toBe(false);
		expect(state).toMatchObject({ status: 'error', error });
	});
});

describe('share count', () => {
	it('does not report a total until a complete server response', async () => {
		let resolvePage: ((value: ReturnType<typeof page>) => void) | undefined;
		fetchShares.mockImplementationOnce(
			() =>
				new Promise((resolve) => {
					resolvePage = resolve;
				})
		);
		const pending = refreshShareCount();
		expect(get(shareCount)).toMatchObject({ status: 'loading', total: null });
		resolvePage?.(page({ total: 4 }));
		expect(await pending).toBe(true);
		expect(get(shareCount)).toMatchObject({ status: 'ready', total: 4 });
	});

	it('keeps a previous total on error instead of claiming zero', async () => {
		fetchShares.mockResolvedValueOnce(page({ total: 3 }));
		await refreshShareCount();
		fetchShares.mockRejectedValueOnce(new Error('offline'));
		expect(await refreshShareCount({ force: true })).toBe(false);
		expect(get(shareCount)).toMatchObject({ status: 'error', total: 3, error: 'offline' });
	});

	it('dedupes concurrent refreshes into a single request', async () => {
		fetchShares.mockResolvedValueOnce(page({ total: 5 }));

		await Promise.all([refreshShareCount(), refreshShareCount()]);

		expect(fetchShares).toHaveBeenCalledTimes(1);
		expect(get(shareCount)).toMatchObject({ status: 'ready', total: 5 });
	});

	it('reuses a still-fresh count instead of refetching on remount', async () => {
		vi.useFakeTimers();
		fetchShares.mockResolvedValueOnce(page({ total: 2 }));

		await refreshShareCount();
		vi.advanceTimersByTime(1_000);
		await refreshShareCount();

		expect(fetchShares).toHaveBeenCalledTimes(1);
		vi.useRealTimers();
	});

	it('refetches once the cached count goes stale', async () => {
		vi.useFakeTimers();
		fetchShares.mockResolvedValue(page({ total: 2 }));

		await refreshShareCount();
		vi.advanceTimersByTime(16_000);
		await refreshShareCount();

		expect(fetchShares).toHaveBeenCalledTimes(2);
		vi.useRealTimers();
	});

	it('force bypasses a still-fresh cached count', async () => {
		fetchShares.mockResolvedValue(page({ total: 2 }));

		await refreshShareCount();
		await refreshShareCount({ force: true });

		expect(fetchShares).toHaveBeenCalledTimes(2);
	});

	it('force bypasses an in-flight refresh so a second mutation wins', async () => {
		// Two quick share/unshare mutations both force-refresh the count. The
		// first's request must not be adopted by the second -- the request
		// that is still current when it resolves wins (#139).
		let resolveFirst: ((value: ReturnType<typeof page>) => void) | undefined;
		fetchShares.mockImplementationOnce(
			() =>
				new Promise((resolve) => {
					resolveFirst = resolve;
				})
		);
		fetchShares.mockResolvedValueOnce(page({ total: 9 }));

		const first = refreshShareCount({ force: true });
		const second = refreshShareCount({ force: true });
		expect(await second).toBe(true);
		resolveFirst?.(page({ total: 1 }));
		expect(await first).toBe(false);

		expect(fetchShares).toHaveBeenCalledTimes(2);
		expect(get(shareCount).total).toBe(9);
	});
});

describe('share inventory', () => {
	it('treats an empty complete page as empty and a partial page as not complete', async () => {
		fetchShares.mockResolvedValueOnce(page({ items: [], total: 0, has_more: false }));
		await loadShareInventory({ reset: true });
		expect(get(shareInventory).status).toBe('ready');
		expect(get(shareInventory).items).toEqual([]);
		expect(get(shareInventory).hasMore).toBe(false);

		fetchShares.mockResolvedValueOnce(page({ items: [item()], total: 4, has_more: true }));
		await loadShareInventory({ reset: true });
		expect(get(shareInventory).items).toHaveLength(1);
		expect(get(shareInventory).hasMore).toBe(true);
		expect(get(shareCount).total).toBe(4);
	});

	it('does not call an empty list complete while loading', async () => {
		let resolvePage: ((value: ReturnType<typeof page>) => void) | undefined;
		fetchShares.mockImplementationOnce(
			() =>
				new Promise((resolve) => {
					resolvePage = resolve;
				})
		);
		const pending = loadShareInventory({ reset: true });
		expect(get(shareInventory).status).toBe('loading');
		expect(get(shareInventory).items).toEqual([]);
		resolvePage?.(page({ total: 0 }));
		await pending;
		expect(get(shareInventory).status).toBe('ready');
	});

	it('surfaces a load error without inventing an empty complete list', async () => {
		fetchShares.mockRejectedValueOnce(new Error(LIBRARY_SHARES_ERROR));
		expect(await loadShareInventory({ reset: true })).toBe(false);
		expect(get(shareInventory)).toMatchObject({
			status: 'error',
			items: [],
			error: LIBRARY_SHARES_ERROR
		});
	});

	it('dedupes concurrent loads of the same page into a single request', async () => {
		fetchShares.mockResolvedValueOnce(page({ items: [item()], total: 1 }));

		await Promise.all([loadShareInventory({ reset: true }), loadShareInventory({ reset: true })]);

		expect(fetchShares).toHaveBeenCalledTimes(1);
		expect(get(shareInventory).items).toHaveLength(1);
	});

	it('force bypasses an in-flight load so a second mutation wins', async () => {
		let resolveFirst: ((value: ReturnType<typeof page>) => void) | undefined;
		fetchShares.mockImplementationOnce(
			() =>
				new Promise((resolve) => {
					resolveFirst = resolve;
				})
		);
		fetchShares.mockResolvedValueOnce(page({ items: [item({ id: 'second' })], total: 1 }));

		const first = loadShareInventory({ reset: true, force: true });
		const second = loadShareInventory({ reset: true, force: true });
		expect(await second).toBe(true);
		resolveFirst?.(page({ items: [item({ id: 'first' })], total: 1 }));
		expect(await first).toBe(false);

		expect(fetchShares).toHaveBeenCalledTimes(2);
		expect(get(shareInventory).items.map((row) => row.id)).toEqual(['second']);
	});

	it('keeps N from the server when a type filter is applied', async () => {
		fetchShares.mockResolvedValueOnce(page({ items: [item()], total: 4, has_more: false }));
		await setShareTypeFilter('album');
		expect(fetchShares).toHaveBeenCalledWith({
			offset: 0,
			limit: 50,
			type: 'album'
		});
		expect(get(shareCount).total).toBe(4);
		expect(get(shareInventory).typeFilter).toBe('album');
		expect(get(shareInventory).items).toHaveLength(1);
	});

	it('loads the next page at the current offset and retains earlier share rows', async () => {
		fetchShares
			.mockResolvedValueOnce(page({ items: [item({ id: 'first' })], total: 2, has_more: true }))
			.mockResolvedValueOnce(page({ items: [item({ id: 'second' })], total: 2 }));

		await loadShareInventory({ reset: true });
		const loaded = await loadMoreShares();

		expect(loaded).toBe(true);
		expect(fetchShares).toHaveBeenLastCalledWith({ offset: 1, limit: 50, type: null });
		expect(get(shareInventory)).toMatchObject({
			status: 'ready',
			offset: 2,
			hasMore: false
		});
		expect(get(shareInventory).items.map((row) => row.id)).toEqual(['first', 'second']);
	});

	it.each([
		['has no next page', page({ has_more: false }), false],
		['is already loading the next page', page({ has_more: true }), false]
	])('does not load more when the inventory %s', async (_caseName, firstPage, expected) => {
		fetchShares.mockResolvedValueOnce(firstPage);
		await loadShareInventory({ reset: true });
		if (firstPage.has_more) {
			fetchShares.mockImplementationOnce(() => new Promise(() => undefined));
			void loadMoreShares();
		}

		expect(await loadMoreShares()).toBe(expected);
	});
});

describe('shares view and patches', () => {
	it('opens and closes the inventory without a library section', () => {
		expect(get(sharesViewOpen)).toBe(false);
		openSharesInventory();
		expect(get(sharesViewOpen)).toBe(true);
		closeSharesInventory();
		expect(get(sharesViewOpen)).toBe(false);
	});

	it('toggles the inventory and returns its new visibility', () => {
		expect(toggleSharesInventory()).toBe(true);
		expect(toggleSharesInventory()).toBe(false);
	});

	it('patches titles of rows already in the inventory and does not insert new ones', async () => {
		fetchShares.mockResolvedValueOnce(
			page({
				items: [
					item({ type: 'song', id: 's1', title: 'Tide', public_path: '/share/song/slug-s' }),
					item({
						type: 'generation',
						id: 'g1',
						title: 'Tide',
						song_id: 's1',
						song_title: 'Tide',
						generation_number: 1,
						public_path: '/share/gen/slug-g'
					})
				],
				total: 2
			})
		);
		await loadShareInventory({ reset: true });
		patchSharesFromSong(
			song({
				id: 's1',
				title: 'Tide Updated',
				generations: [
					{
						id: 'g1',
						song_id: 's1',
						version_id: 'v1',
						version_number: 1,
						generation_number: 2,
						mp3_path: '/audio/g1.mp3',
						wav_path: null,
						seed: 1,
						status: 'complete',
						is_archived: true,
						is_picked: false,
						is_kept: false,
						is_shared: true,
						share_slug: 'slug-g',
						model_mode: 'base',
						whisper_text: null,
						whisper_cues: null,
						version_lyrics: null,
						scores: null,
						generation_params: null,
						audio_duration_sec: null,
						created_at: '2026-01-01T00:00:00+00:00'
					}
				]
			})
		);
		patchSharesFromSong(song({ id: 's-other', title: 'Other' }));
		expect(get(shareInventory).items.map((row) => row.id)).toEqual(['s1', 'g1']);
		expect(get(shareInventory).items[0]?.title).toBe('Tide Updated');
		expect(get(shareInventory).items[1]).toMatchObject({
			title: 'Tide Updated',
			song_title: 'Tide Updated',
			generation_number: 2,
			is_archived: true
		});
	});

	it('keeps existing slugs and patches a generation missing from the refreshed song', async () => {
		fetchShares.mockResolvedValueOnce(
			page({
				items: [
					item({ type: 'song', id: 's1', title: 'Tide', share_slug: 'existing-song' }),
					item({
						type: 'generation',
						id: 'g-missing',
						title: 'Tide',
						song_id: 's1',
						song_title: 'Tide',
						generation_number: 1,
						share_slug: 'existing-generation'
					})
				]
			})
		);
		await loadShareInventory({ reset: true });

		patchSharesFromSong(song({ title: 'Renamed', share_slug: null, generations: [] }));

		expect(get(shareInventory).items).toMatchObject([
			{ id: 's1', title: 'Renamed', share_slug: 'existing-song' },
			{
				id: 'g-missing',
				title: 'Renamed',
				song_title: 'Renamed',
				share_slug: 'existing-generation'
			}
		]);
	});
});

describe('share watchers', () => {
	it.each([
		['a status watcher', () => watchShareStatus(), { offset: 0, limit: 1 }],
		['a view watcher', () => watchShareView(), { offset: 0, limit: 50, type: null }]
	])('refreshes %s when the tab becomes visible', async (_caseName, watch, request) => {
		Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
		const stop = watch();
		await vi.waitFor(() => expect(fetchShares).toHaveBeenCalledTimes(1));
		vi.useFakeTimers();
		await vi.advanceTimersByTimeAsync(15_000);
		fetchShares.mockClear();

		Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
		document.dispatchEvent(new Event('visibilitychange'));

		await Promise.resolve();
		expect(fetchShares).toHaveBeenCalledWith(request);
		stop();
		vi.useRealTimers();
	});

	it('does not refresh after a stopped status watcher receives a visible-tab event', async () => {
		const stop = watchShareStatus();
		await vi.waitFor(() => expect(fetchShares).toHaveBeenCalledTimes(1));

		Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
		document.dispatchEvent(new Event('visibilitychange'));
		await Promise.resolve();
		expect(fetchShares).toHaveBeenCalledTimes(1);

		Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
		stop();
		document.dispatchEvent(new Event('visibilitychange'));
		await Promise.resolve();
		expect(fetchShares).toHaveBeenCalledTimes(1);
	});

	it.each([
		['the inventory is open', () => openSharesInventory(), () => undefined],
		['a view watcher is active', () => undefined, () => watchShareView()]
	])(
		'refreshes both count and inventory after a mutation when %s',
		async (_caseName, prepareOpen, startWatcher) => {
			prepareOpen();
			const stop = startWatcher();
			if (stop) await vi.waitFor(() => expect(fetchShares).toHaveBeenCalledTimes(1));
			fetchShares.mockClear();

			await refreshSharesAfterMutation();

			expect(fetchShares.mock.calls.map(([options]) => options)).toEqual([
				{ offset: 0, limit: 1 },
				{ offset: 0, limit: 50, type: null }
			]);
			stop?.();
		}
	);

	it('refreshes only the count after a mutation without an open inventory or view watcher', async () => {
		fetchShares.mockResolvedValueOnce(page({ total: 7 }));

		await refreshSharesAfterMutation();

		expect(fetchShares).toHaveBeenCalledWith({ offset: 0, limit: 1 });
		expect(fetchShares).toHaveBeenCalledTimes(1);
		expect(get(shareCount)).toMatchObject({ status: 'ready', total: 7 });
		expect(get(shareInventory)).toMatchObject({ status: 'idle', items: [] });
	});
});

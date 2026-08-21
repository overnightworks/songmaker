import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { ShareInventoryItem, SongItem } from '$lib/api/types';
import { LIBRARY_SHARES_ERROR } from '$lib/constants';

const fetchShares = vi.fn();

vi.mock('$lib/api/library', () => ({
	fetchShares: (...args: unknown[]) => fetchShares(...args)
}));

import {
	closeSharesInventory,
	loadShareInventory,
	openSharesInventory,
	patchSharesFromSong,
	refreshShareCount,
	resetSharesForTests,
	setShareTypeFilter,
	shareCount,
	shareInventory,
	sharesViewOpen
} from './shares';

function page(overrides: Partial<{
	items: ShareInventoryItem[];
	total: number;
	offset: number;
	limit: number;
	has_more: boolean;
}> = {}) {
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
	resetSharesForTests();
});

afterEach(() => {
	resetSharesForTests();
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
		expect(await refreshShareCount()).toBe(false);
		expect(get(shareCount)).toMatchObject({ status: 'error', total: 3, error: 'offline' });
	});
});

describe('share inventory', () => {
	it('treats an empty complete page as empty and a partial page as not complete', async () => {
		fetchShares.mockResolvedValueOnce(page({ items: [], total: 0, has_more: false }));
		await loadShareInventory({ reset: true });
		expect(get(shareInventory).status).toBe('ready');
		expect(get(shareInventory).items).toEqual([]);
		expect(get(shareInventory).hasMore).toBe(false);

		fetchShares.mockResolvedValueOnce(
			page({ items: [item()], total: 4, has_more: true })
		);
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

	it('keeps N from the server when a type filter is applied', async () => {
		fetchShares.mockResolvedValueOnce(
			page({ items: [item()], total: 4, has_more: false })
		);
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
});

describe('shares view and patches', () => {
	it('opens and closes the inventory without a library section', () => {
		expect(get(sharesViewOpen)).toBe(false);
		openSharesInventory();
		expect(get(sharesViewOpen)).toBe(true);
		closeSharesInventory();
		expect(get(sharesViewOpen)).toBe(false);
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
});

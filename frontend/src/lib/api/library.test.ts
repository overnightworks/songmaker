import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);
vi.mock('$lib/stores/auth', () => ({ clearAuth: vi.fn() }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import { LIBRARY_QUERY_REQUIRED } from '$lib/constants';
import { fetchLibraryContinue, fetchLibraryPoolQueue, searchLibrary } from './library';

function mockOk(data: unknown) {
	mockFetch.mockResolvedValueOnce({
		ok: true,
		json: () => Promise.resolve(data)
	});
}

beforeEach(() => {
	mockFetch.mockReset();
});

describe('searchLibrary', () => {
	it('calls GET /api/library/search with q, sort, limit, and cursor', async () => {
		mockOk({ items: [], next_cursor: null, has_more: false });
		await searchLibrary({ q: 'Nachtstrom', sort: 'newest', limit: 50, cursor: 'abc' });
		expect(mockFetch).toHaveBeenCalledWith(
			'/api/library/search?q=Nachtstrom&sort=newest&limit=50&cursor=abc',
			expect.objectContaining({ credentials: 'include' })
		);
	});

	it('does not send an empty query', async () => {
		await expect(searchLibrary({ q: '  ', sort: 'title', limit: 50 })).rejects.toThrow(
			LIBRARY_QUERY_REQUIRED
		);
		expect(mockFetch).not.toHaveBeenCalled();
	});

	it('returns song hits without generations from the API contract', async () => {
		mockOk({
			items: [
				{
					type: 'song',
					song: { id: 's1', title: 'Tide', album_id: 'a1', album_title: 'Nachtstrom' },
					album_id: 'a1',
					album_title: 'Nachtstrom'
				}
			],
			next_cursor: null,
			has_more: false
		});
		const resp = await searchLibrary({ q: 'tide', sort: 'newest', limit: 50 });
		expect(resp.items[0].type).toBe('song');
		if (resp.items[0].type === 'song') {
			expect(resp.items[0].song).not.toHaveProperty('generations');
			expect(resp.items[0].album_title).toBe('Nachtstrom');
		}
	});
});

describe('fetchLibraryContinue', () => {
	it('calls GET /api/library/continue', async () => {
		mockOk({ items: [] });

		await fetchLibraryContinue();

		expect(mockFetch).toHaveBeenCalledWith(
			'/api/library/continue',
			expect.objectContaining({ credentials: 'include' })
		);
	});
});

describe('fetchLibraryPoolQueue', () => {
	it('calls GET /api/library/pool-queue with pool, shuffle, and start take', async () => {
		mockOk({
			pool: 'mix',
			takes: [
				{
					generation_id: 'g1',
					song_id: 's1',
					song_title: 'Tide',
					artist: 'Artist',
					album_title: 'Nachtstrom',
					lyrics: null,
					generation_number: 1,
					mp3_path: 'a/g1.mp3',
					seed: 1,
					model_mode: 'sft',
					is_picked: true,
					is_kept: false
				}
			],
			skipped: [],
			skipped_complete: true
		});
		await fetchLibraryPoolQueue({
			pool: 'mix',
			shuffle: true,
			startGenerationId: 'g1'
		});
		expect(mockFetch).toHaveBeenCalledWith(
			'/api/library/pool-queue?pool=mix&shuffle=true&start_generation_id=g1',
			expect.objectContaining({ credentials: 'include' })
		);
	});
});

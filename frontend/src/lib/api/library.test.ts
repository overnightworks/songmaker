import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);
vi.mock('$lib/stores/auth', () => ({ clearAuth: vi.fn() }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import { LIBRARY_QUERY_REQUIRED } from '$lib/constants';
import { searchLibrary } from './library';

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

	it('fills missing generations on song hits', async () => {
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
			expect(resp.items[0].song.generations).toEqual([]);
			expect(resp.items[0].album_title).toBe('Nachtstrom');
		}
	});
});

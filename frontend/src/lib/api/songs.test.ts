import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);
vi.mock('$lib/stores/auth', () => ({ clearAuth: vi.fn() }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import { fetchSongs, recordSongListen } from './songs';

beforeEach(() => {
	mockFetch.mockReset();
	mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ status: 'ok' }) });
});

describe('recordSongListen', () => {
	it('posts the listen event to its song endpoint', async () => {
		await recordSongListen('song-1');

		expect(mockFetch).toHaveBeenCalledWith(
			'/api/songs/song-1/listen',
			expect.objectContaining({ method: 'POST', credentials: 'include' })
		);
	});
});

describe('song API adapter', () => {
	it('serializes list filters and normalizes omitted generation lists for consumers', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: () => Promise.resolve({ items: [{ id: 'song-1' }], total: 1 })
		});

		const result = await fetchSongs('album-1', 10, 25, { q: 'night drive', sort: 'newest' });

		expect(mockFetch.mock.calls[0]?.[0]).toBe(
			'/api/songs?offset=10&limit=25&album_id=album-1&q=night+drive&sort=newest'
		);
		expect(result.items[0]?.generations).toEqual([]);
	});
});

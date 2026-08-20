import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

import { fetchMemory, saveAlbumMemory, saveSongMemory, saveUserMemory } from './memory';

function mockOk(data: unknown) {
	mockFetch.mockResolvedValue({
		ok: true,
		json: () => Promise.resolve(data)
	});
}

describe('memory API', () => {
	beforeEach(() => {
		mockFetch.mockReset();
	});

	it('fetches the user and song scopes for the open song', async () => {
		const bundle = {
			user: { scope: 'user', target_id: 'u1', body: 'German', updated_at: null },
			song: { scope: 'song', target_id: 's1', body: 'locked chorus', updated_at: null },
			album: { scope: 'album', target_id: 'a1', body: '', updated_at: null }
		};
		mockOk(bundle);
		const result = await fetchMemory('s1');
		expect(result.song?.body).toBe('locked chorus');
		expect(mockFetch.mock.calls[0][0]).toBe('/api/memory?song_id=s1');
	});

	it('saves each scope to its own endpoint', async () => {
		mockOk({ scope: 'user', target_id: 'u1', body: 'x', updated_at: null });
		await saveUserMemory('x');
		expect(mockFetch.mock.calls[0][0]).toBe('/api/memory/user');
		expect(JSON.parse(mockFetch.mock.calls[0][1].body).body).toBe('x');

		mockOk({ scope: 'song', target_id: 's1', body: 'y', updated_at: null });
		await saveSongMemory('s1', 'y');
		expect(mockFetch.mock.calls[1][0]).toBe('/api/memory/songs/s1');

		mockOk({ scope: 'album', target_id: 'a1', body: 'z', updated_at: null });
		await saveAlbumMemory('a1', 'z');
		expect(mockFetch.mock.calls[2][0]).toBe('/api/memory/albums/a1');
	});
});

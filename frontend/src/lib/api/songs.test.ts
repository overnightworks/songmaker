import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);
vi.mock('$lib/stores/auth', () => ({ clearAuth: vi.fn() }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import { recordSongListen } from './songs';

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

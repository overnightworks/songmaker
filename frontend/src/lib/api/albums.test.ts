import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);
vi.mock('$lib/stores/auth', () => ({ clearAuth: vi.fn() }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import {
	createAlbumCoverSuggestions,
	discardAlbumCoverSuggestions,
	fetchAlbumCoverSuggestions,
	selectAlbumCoverSuggestion
} from './albums';

function mockOk(data: unknown): void {
	mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(data) });
}

beforeEach(() => {
	mockFetch.mockReset();
});

describe('album cover suggestions API', () => {
	it('creates and lists suggestions at the album owner', async () => {
		mockOk({ id: 'cover-job', type: 'cover', status: 'queued', progress: 0 });
		await createAlbumCoverSuggestions('night-drive');
		expect(mockFetch).toHaveBeenLastCalledWith(
			'/api/albums/night-drive/cover-suggestions',
			expect.objectContaining({ method: 'POST', credentials: 'include' })
		);

		mockOk({ job: null, suggestions: [], used_today: 0, daily_limit: 10 });
		await fetchAlbumCoverSuggestions('night-drive');
		expect(mockFetch).toHaveBeenLastCalledWith(
			'/api/albums/night-drive/cover-suggestions',
			expect.objectContaining({ credentials: 'include' })
		);
	});

	it('selects by suggestion id and discards every suggestion through the public endpoints', async () => {
		mockOk({ id: 'night-drive' });
		await selectAlbumCoverSuggestion('night-drive', { suggestion_id: 'suggestion-1' });
		const [selectionPath, selectionInit] = mockFetch.mock.calls[0];
		expect(selectionPath).toBe('/api/albums/night-drive/cover');
		expect(selectionInit.method).toBe('PUT');
		expect(selectionInit.headers['Content-Type']).toBe('application/json');
		expect(JSON.parse(selectionInit.body)).toEqual({ suggestion_id: 'suggestion-1' });

		mockOk({ status: 'ok' });
		await discardAlbumCoverSuggestions('night-drive');
		expect(mockFetch).toHaveBeenLastCalledWith(
			'/api/albums/night-drive/cover-suggestions',
			expect.objectContaining({ method: 'DELETE', credentials: 'include' })
		);
	});
});

import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);
vi.mock('$lib/stores/auth', () => ({ clearAuth: vi.fn() }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import {
	createAlbum,
	createAlbumCoverSuggestions,
	discardAlbumCoverSuggestions,
	fetchAlbums,
	fetchAlbumCoverSuggestions,
	selectAlbumCoverSuggestion,
	updateAlbum
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

describe('album API contract', () => {
	it('serializes paging, search, sorting and archived filters without empty query values', async () => {
		mockOk({ items: [], total: 0 });
		await fetchAlbums(10, 25, { q: 'night drive', sort: 'newest', archived: true });
		expect(mockFetch.mock.calls[0]?.[0]).toBe(
			'/api/albums?offset=10&limit=25&q=night+drive&sort=newest&archived=true'
		);
	});

	it('leaves empty and false filters out of the album query', async () => {
		mockOk({ items: [], total: 0 });
		await fetchAlbums(10, 25, { q: '', sort: undefined, archived: false });
		expect(mockFetch.mock.calls[0]?.[0]).toBe('/api/albums?offset=10&limit=25');
	});

	it('sends creation defaults and a partial update exactly as entered', async () => {
		mockOk({ id: 'album-1' });
		await createAlbum('Night drive');
		let [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
		expect(url).toBe('/api/albums');
		expect(init.method).toBe('POST');
		expect(JSON.parse(String(init.body))).toEqual({ title: 'Night drive', artist: '' });

		mockOk({ id: 'album-1' });
		await updateAlbum('album-1', { subtitle: '', year: null });
		[url, init] = mockFetch.mock.calls[1] as [string, RequestInit];
		expect(url).toBe('/api/albums/album-1');
		expect(init.method).toBe('PUT');
		expect(JSON.parse(String(init.body))).toEqual({ subtitle: '', year: null });
	});
});

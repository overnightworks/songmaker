import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);
vi.mock('$lib/stores/auth', () => ({ clearAuth: vi.fn() }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import {
	addAlbumToPlaylist,
	addGenerationToPlaylist,
	addSongToPlaylist,
	createPlaylist,
	deletePlaylistCover,
	reorderPlaylistEntry,
	uploadPlaylistCover,
	updatePlaylist
} from './playlists';

function acceptRequests(): void {
	mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
}

function request(): [string, RequestInit] {
	return mockFetch.mock.calls[0] as [string, RequestInit];
}

beforeEach(() => {
	mockFetch.mockReset();
	acceptRequests();
});

describe('playlist API contract', () => {
	it.each([
		[
			'creates a playlist',
			() => createPlaylist('Night drive'),
			'/api/playlists',
			'POST',
			{ title: 'Night drive' }
		],
		[
			'renames a playlist',
			() => updatePlaylist('p-1', 'Night drive'),
			'/api/playlists/p-1',
			'PUT',
			{ title: 'Night drive' }
		],
		[
			'adds a generation',
			() => addGenerationToPlaylist('p-1', 'g-1'),
			'/api/playlists/p-1/entries/generation',
			'POST',
			{ generation_id: 'g-1' }
		],
		[
			'adds a song',
			() => addSongToPlaylist('p-1', 's-1'),
			'/api/playlists/p-1/entries/song',
			'POST',
			{ song_id: 's-1' }
		],
		[
			'adds an album',
			() => addAlbumToPlaylist('p-1', 'a-1'),
			'/api/playlists/p-1/entries/album',
			'POST',
			{ album_id: 'a-1' }
		],
		[
			'reorders an entry',
			() => reorderPlaylistEntry('p-1', 'e-1', 4),
			'/api/playlists/p-1/entries/e-1/position',
			'PATCH',
			{ new_position: 4 }
		]
	])('%s through the matching public request', async (_name, send, url, method, payload) => {
		await send();
		const [actualUrl, init] = request();
		expect(actualUrl).toBe(url);
		expect(init.method).toBe(method);
		expect(JSON.parse(String(init.body))).toEqual(payload);
	});

	it('uploads a cover through the playlist cover endpoint', async () => {
		const file = new File(['cover'], 'cover.png', { type: 'image/png' });
		await uploadPlaylistCover('p-1', file);
		const [url, init] = request();
		expect(url).toBe('/api/playlists/p-1/cover');
		expect(init.method).toBe('PUT');
		expect(init.body).toBeInstanceOf(FormData);
		expect((init.body as FormData).get('file')).toBe(file);
	});

	it('removes a cover through the playlist cover endpoint', async () => {
		await deletePlaylistCover('p-1');
		const [url, init] = request();
		expect(url).toBe('/api/playlists/p-1/cover');
		expect(init.method).toBe('DELETE');
	});
});

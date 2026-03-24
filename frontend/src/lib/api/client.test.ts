import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('$lib/stores/settings', () => ({
	getClaudeKey: vi.fn().mockReturnValue('')
}));

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

import {
	fetchAlbums,
	fetchSongs,
	fetchSong,
	createSong,
	updateSong,
	fetchVersions,
	deleteVersion,
	deleteGeneration,
	generateSong,
	scoreGeneration,
	fetchJob,
	pickGeneration,
	unpickGeneration,
	cleanupAlbum,
	fetchCapabilities,
	fetchGenerationDefaults,
	updateGenerationDefaults,
	chatWithClaude
} from './client';

function mockOk(data: unknown) {
	mockFetch.mockResolvedValueOnce({
		ok: true,
		json: () => Promise.resolve(data)
	});
}

function mockError(status: number) {
	mockFetch.mockResolvedValueOnce({
		ok: false,
		status
	});
}

beforeEach(() => {
	mockFetch.mockReset();
});

describe('API client', () => {
	it('fetchAlbums calls GET /api/albums', async () => {
		mockOk([{ id: 'a1', title: 'Album' }]);
		const result = await fetchAlbums();
		expect(result).toHaveLength(1);
		expect(mockFetch).toHaveBeenCalledWith('/api/albums', undefined);
	});

	it('fetchSongs without album', async () => {
		mockOk([]);
		await fetchSongs();
		expect(mockFetch).toHaveBeenCalledWith('/api/songs', undefined);
	});

	it('fetchSongs with album filter', async () => {
		mockOk([]);
		await fetchSongs('a1');
		expect(mockFetch).toHaveBeenCalledWith('/api/songs?album_id=a1', undefined);
	});

	it('fetchSong by id', async () => {
		mockOk({ id: 's1', title: 'Song' });
		const result = await fetchSong('s1');
		expect(result.id).toBe('s1');
	});

	it('createSong sends POST', async () => {
		mockOk({ id: 's1' });
		await createSong({ title: 'New', album_id: 'a1' });
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/songs');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body)).toEqual({ title: 'New', album_id: 'a1' });
	});

	it('updateSong sends PUT with generation_params', async () => {
		mockOk({ id: 's1' });
		await updateSong('s1', { lyrics: 'new', generation_params: { shift: 2.0 } });
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/songs/s1');
		expect(init.method).toBe('PUT');
		const body = JSON.parse(init.body);
		expect(body.generation_params).toEqual({ shift: 2.0 });
	});

	it('fetchVersions calls correct URL', async () => {
		mockOk([]);
		await fetchVersions('s1');
		expect(mockFetch).toHaveBeenCalledWith('/api/songs/s1/versions', undefined);
	});

	it('deleteVersion sends DELETE', async () => {
		mockOk({});
		await deleteVersion('v1', true);
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/versions/v1?delete_generations=true');
		expect(init.method).toBe('DELETE');
	});

	it('deleteGeneration sends DELETE', async () => {
		mockOk({});
		await deleteGeneration('g1');
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/generations/g1');
		expect(init.method).toBe('DELETE');
	});

	it('generateSong sends POST with count', async () => {
		mockOk({ id: 'j1', type: 'generate' });
		const result = await generateSong('s1', 3);
		expect(result.type).toBe('generate');
		const body = JSON.parse(mockFetch.mock.calls[0][1].body);
		expect(body.count).toBe(3);
	});

	it('scoreGeneration sends POST', async () => {
		mockOk({ id: 'j1', type: 'score' });
		await scoreGeneration('g1');
		expect(mockFetch.mock.calls[0][0]).toBe('/api/generations/g1/score');
	});

	it('fetchJob calls correct URL', async () => {
		mockOk({ id: 'j1', status: 'completed' });
		const result = await fetchJob('j1');
		expect(result.status).toBe('completed');
	});

	it('pickGeneration sends POST', async () => {
		mockOk({});
		await pickGeneration('g1');
		expect(mockFetch.mock.calls[0][1].method).toBe('POST');
	});

	it('unpickGeneration sends POST', async () => {
		mockOk({});
		await unpickGeneration('g1');
		expect(mockFetch.mock.calls[0][0]).toBe('/api/generations/g1/unpick');
	});

	it('cleanupAlbum returns deleted count', async () => {
		mockOk({ deleted: 5 });
		const result = await cleanupAlbum('a1');
		expect(result.deleted).toBe(5);
	});

it('fetchCapabilities', async () => {
		mockOk({ generation: true, scoring: true });
		const result = await fetchCapabilities();
		expect(result.generation).toBe(true);
	});

	it('fetchGenerationDefaults', async () => {
		mockOk({ turbo: { shift: 3.0 } });
		const result = await fetchGenerationDefaults();
		expect(result.turbo.shift).toBe(3.0);
	});

	it('updateGenerationDefaults', async () => {
		mockOk({ turbo: { shift: 5.0 } });
		const result = await updateGenerationDefaults({ turbo: { shift: 5.0 } });
		expect(result.turbo.shift).toBe(5.0);
		expect(mockFetch.mock.calls[0][1].method).toBe('PUT');
	});

	it('throws on non-ok response', async () => {
		mockError(500);
		await expect(fetchAlbums()).rejects.toThrow('API /api/albums: 500');
	});
});

describe('chatWithClaude', () => {
	it('sends message and returns response', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			status: 200,
			json: () => Promise.resolve({ response: 'Hello from Claude' })
		});
		const result = await chatWithClaude('hi', 'context');
		expect(result).toBe('Hello from Claude');
	});

	it('throws on 503 unavailable', async () => {
		mockFetch.mockResolvedValueOnce({ ok: false, status: 503 });
		await expect(chatWithClaude('hi')).rejects.toThrow('Claude unavailable');
	});

	it('throws on other errors', async () => {
		mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });
		await expect(chatWithClaude('hi')).rejects.toThrow('Chat failed: 500');
	});
});

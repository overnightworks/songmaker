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
	chatWithClaude,
	checkSetupRequired,
	setupAdmin,
	login,
	logout,
	fetchMe,
	fetchUsers,
	createUser,
	updateUser,
	deactivateUser,
	fetchSessions,
	forceLogout,
	fetchLoginAttempts,
	changePassword,
	ApiError
} from './client';

function mockOk(data: unknown) {
	mockFetch.mockResolvedValueOnce({
		ok: true,
		json: () => Promise.resolve(data)
	});
}

function mockError(status: number, detail: string = '') {
	mockFetch.mockResolvedValueOnce({
		ok: false,
		status,
		json: () => Promise.resolve({ detail })
	});
}

beforeEach(() => {
	mockFetch.mockReset();
});

describe('API client', () => {
	it('fetchAlbums calls GET /api/albums with pagination', async () => {
		mockOk({ items: [{ id: 'a1', title: 'Album' }], total: 1, offset: 0, limit: 50 });
		const result = await fetchAlbums();
		expect(result.items).toHaveLength(1);
		expect(result.total).toBe(1);
		expect(mockFetch).toHaveBeenCalledWith(
			'/api/albums?offset=0&limit=50',
			expect.objectContaining({ credentials: 'include' })
		);
	});

	it('fetchSongs without album', async () => {
		mockOk({ items: [], total: 0, offset: 0, limit: 50 });
		await fetchSongs();
		expect(mockFetch).toHaveBeenCalledWith(
			'/api/songs?offset=0&limit=50',
			expect.objectContaining({ credentials: 'include' })
		);
	});

	it('fetchSongs with album filter', async () => {
		mockOk({ items: [], total: 0, offset: 0, limit: 50 });
		await fetchSongs('a1');
		expect(mockFetch).toHaveBeenCalledWith(
			'/api/songs?offset=0&limit=50&album_id=a1',
			expect.objectContaining({ credentials: 'include' })
		);
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
		expect(mockFetch).toHaveBeenCalledWith(
			'/api/songs/s1/versions',
			expect.objectContaining({ credentials: 'include' })
		);
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

	it('throws ApiError on non-ok response', async () => {
		mockError(500, 'Internal server error');
		await expect(fetchAlbums()).rejects.toThrow(ApiError);
	});

	it('ApiError carries status and detail', async () => {
		mockError(422, 'Validation failed');
		const err = (await fetchAlbums().catch((e: unknown) => e)) as ApiError;
		expect(err).toBeInstanceOf(ApiError);
		expect(err.status).toBe(422);
		expect(err.detail).toBe('Validation failed');
	});

	it('ApiError handles non-JSON response body', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 502,
			json: () => Promise.reject(new Error('not json'))
		});
		const err = (await fetchAlbums().catch((e: unknown) => e)) as ApiError;
		expect(err).toBeInstanceOf(ApiError);
		expect(err.status).toBe(502);
		expect(err.detail).toBe('');
	});
});

describe('chatWithClaude', () => {
	it('uses server endpoint when no user key', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			status: 200,
			json: () => Promise.resolve({ response: 'Hello from Claude' })
		});
		const result = await chatWithClaude('hi', 'context');
		expect(result).toBe('Hello from Claude');
		expect(mockFetch).toHaveBeenCalledWith(
			expect.stringContaining('/api/chat'),
			expect.objectContaining({ method: 'POST' })
		);
	});

	it('calls Anthropic API directly when user has key', async () => {
		const { getClaudeKey } = await import('$lib/stores/settings');
		vi.mocked(getClaudeKey).mockReturnValue('sk-ant-test');

		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: () => Promise.resolve({ content: [{ type: 'text', text: 'Direct response' }] })
		});
		const result = await chatWithClaude('hi');
		expect(result).toBe('Direct response');
		expect(mockFetch).toHaveBeenCalledWith(
			'https://api.anthropic.com/v1/messages',
			expect.objectContaining({
				method: 'POST',
				headers: expect.objectContaining({ 'x-api-key': 'sk-ant-test' })
			})
		);

		vi.mocked(getClaudeKey).mockReturnValue('');
	});

	it('throws ApiError on 503 unavailable from server', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 503,
			json: () => Promise.resolve({ detail: 'Claude unavailable' })
		});
		await expect(chatWithClaude('hi')).rejects.toThrow(ApiError);
	});

	it('throws ApiError on other server errors', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 500,
			json: () => Promise.resolve({ detail: 'Internal error' })
		});
		await expect(chatWithClaude('hi')).rejects.toThrow(ApiError);
	});

	it('throws on Anthropic API error with message', async () => {
		const { getClaudeKey } = await import('$lib/stores/settings');
		vi.mocked(getClaudeKey).mockReturnValue('sk-ant-bad');

		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 401,
			json: () => Promise.resolve({ error: { message: 'Invalid API key' } })
		});
		await expect(chatWithClaude('hi')).rejects.toThrow('Invalid API key');

		vi.mocked(getClaudeKey).mockReturnValue('');
	});
});

describe('Auth API', () => {
	it('checkSetupRequired', async () => {
		mockOk({ required: true });
		const result = await checkSetupRequired();
		expect(result.required).toBe(true);
	});

	it('setupAdmin sends POST', async () => {
		mockOk({ id: 'u1', username: 'admin', role: 'admin' });
		const result = await setupAdmin('admin', 'password123');
		expect(result.username).toBe('admin');
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/auth/setup');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body)).toEqual({ username: 'admin', password: 'password123' });
	});

	it('login sends POST', async () => {
		mockOk({ id: 'u1', username: 'alice', role: 'user' });
		const result = await login('alice', 'password123');
		expect(result.username).toBe('alice');
		expect(mockFetch.mock.calls[0][0]).toBe('/api/auth/login');
	});

	it('logout sends DELETE', async () => {
		mockOk({ status: 'ok' });
		await logout();
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/auth/session');
		expect(init.method).toBe('DELETE');
	});

	it('fetchMe calls GET /api/auth/me', async () => {
		mockOk({ id: 'u1', username: 'admin', role: 'admin' });
		const result = await fetchMe();
		expect(result.role).toBe('admin');
	});

	it('changePassword sends PUT', async () => {
		mockOk({ status: 'ok' });
		await changePassword('old', 'newpass123');
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/auth/password');
		expect(init.method).toBe('PUT');
		expect(JSON.parse(init.body)).toEqual({ current: 'old', new_password: 'newpass123' });
	});
});

describe('Admin API', () => {
	it('fetchUsers', async () => {
		mockOk([{ id: 'u1', username: 'admin' }]);
		const result = await fetchUsers();
		expect(result).toHaveLength(1);
	});

	it('createUser sends POST', async () => {
		mockOk({ id: 'u2', username: 'bob', role: 'user' });
		const result = await createUser('bob', 'password123', 'user');
		expect(result.username).toBe('bob');
		expect(mockFetch.mock.calls[0][1].method).toBe('POST');
	});

	it('updateUser sends PUT', async () => {
		mockOk({ id: 'u1', role: 'admin' });
		await updateUser('u1', { role: 'admin' });
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/admin/users/u1');
		expect(init.method).toBe('PUT');
	});

	it('deactivateUser sends DELETE', async () => {
		mockOk({ status: 'ok' });
		await deactivateUser('u1');
		expect(mockFetch.mock.calls[0][1].method).toBe('DELETE');
	});

	it('fetchSessions', async () => {
		mockOk({ items: [{ id: 's1', username: 'admin' }], total: 1, offset: 0, limit: 100 });
		const result = await fetchSessions();
		expect(result.items).toHaveLength(1);
	});

	it('forceLogout sends DELETE', async () => {
		mockOk({ status: 'ok' });
		await forceLogout('s1');
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/admin/sessions/s1');
		expect(init.method).toBe('DELETE');
	});

	it('fetchLoginAttempts', async () => {
		mockOk({ items: [{ id: 'a1', success: false }], total: 1, offset: 0, limit: 50 });
		const result = await fetchLoginAttempts(0, 50);
		expect(result.items).toHaveLength(1);
		expect(mockFetch.mock.calls[0][0]).toBe('/api/admin/login-attempts?offset=0&limit=50');
	});
});

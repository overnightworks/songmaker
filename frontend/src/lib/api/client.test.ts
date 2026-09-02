import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

const mockClearAuth = vi.fn();
const mockGoto = vi.fn();

vi.mock('$lib/stores/auth', () => {
	let user: { id: string } | null = null;
	const subscribers = new Set<(value: typeof user) => void>();
	const currentUser = {
		subscribe(fn: (value: typeof user) => void) {
			fn(user);
			subscribers.add(fn);
			return () => subscribers.delete(fn);
		},
		set(value: typeof user) {
			user = value;
			subscribers.forEach((fn) => fn(user));
		}
	};
	return {
		clearAuth: (...args: unknown[]) => {
			currentUser.set(null);
			return mockClearAuth(...args);
		},
		currentUser
	};
});
vi.mock('$app/navigation', () => ({ goto: (...args: unknown[]) => mockGoto(...args) }));

import { currentUser } from '$lib/stores/auth';
import type { AuthUser } from './types';
import {
	deleteAlbumCover,
	deleteSongCover,
	fetchAlbum,
	fetchAlbums,
	uploadAlbumCover,
	uploadSongCover,
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
	fetchHealth,
	pickGeneration,
	unpickGeneration,
	cleanupAlbum,
	fetchCapabilities,
	fetchGenerationDefaults,
	updateGenerationDefaults,
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
	mockClearAuth.mockReset();
	mockGoto.mockReset();
	currentUser.set(null);
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

	it('fetchAlbum calls GET /api/albums/:id', async () => {
		mockOk({ id: 'a1', title: 'Album' });
		const result = await fetchAlbum('a1');
		expect(result.id).toBe('a1');
		expect(mockFetch).toHaveBeenCalledWith(
			'/api/albums/a1',
			expect.objectContaining({ credentials: 'include' })
		);
	});

	it('fetchSongs without album', async () => {
		mockOk({ items: [], total: 0, offset: 0, limit: 200 });
		await fetchSongs();
		expect(mockFetch).toHaveBeenCalledWith(
			'/api/songs?offset=0&limit=200',
			expect.objectContaining({ credentials: 'include' })
		);
	});

	it('fetchSongs with album filter', async () => {
		mockOk({ items: [], total: 0, offset: 0, limit: 200 });
		await fetchSongs('a1');
		expect(mockFetch).toHaveBeenCalledWith(
			'/api/songs?offset=0&limit=200&album_id=a1',
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

	it('generateSong sends POST with count and model', async () => {
		mockOk({ id: 'j1', type: 'generate' });
		const result = await generateSong('s1', 3, 'sft');
		expect(result.type).toBe('generate');
		const body = JSON.parse(mockFetch.mock.calls[0][1].body);
		expect(body.count).toBe(3);
		expect(body.model).toBe('sft');
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

	it('fetchHealth returns the queue cap flag', async () => {
		mockOk({
			status: 'ok',
			queue_depth_cap_reached: true,
			music_queue_depth: 3,
			scoring_queue_depth: 2,
			acestep_workers_online: 1,
			acestep_workers_total: 1
		});
		const result = await fetchHealth();
		expect(mockFetch.mock.calls[0][0]).toBe('/health');
		expect(result.queue_depth_cap_reached).toBe(true);
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

// Fine-grained reaction behavior is pinned in api/fetch.test.ts; this suite
// only proves a client.ts wrapper still reaches that owner.
describe('401 session expiry handler', () => {
	it('routes a 401 from a client wrapper (not apiFetch directly) to the shared session-lost owner', async () => {
		currentUser.set({ id: 'u1', username: 'felix', role: 'user' } as AuthUser);
		mockError(401, 'Session expired');
		await expect(fetchAlbums()).rejects.toThrow(ApiError);
		expect(mockClearAuth).toHaveBeenCalledOnce();
		expect(mockGoto).toHaveBeenCalledOnce();
	});

	it('does not redirect on 401 from login endpoint', async () => {
		currentUser.set({ id: 'u1', username: 'felix', role: 'user' } as AuthUser);
		mockError(401, 'Invalid credentials');
		await expect(login('alice', 'wrong')).rejects.toThrow(ApiError);
		expect(mockClearAuth).not.toHaveBeenCalled();
		expect(mockGoto).not.toHaveBeenCalled();
	});

	it('does not redirect on 401 from setup endpoint', async () => {
		currentUser.set({ id: 'u1', username: 'felix', role: 'user' } as AuthUser);
		mockError(401, 'Bad request');
		await expect(setupAdmin('admin', 'pass')).rejects.toThrow(ApiError);
		expect(mockClearAuth).not.toHaveBeenCalled();
		expect(mockGoto).not.toHaveBeenCalled();
	});

	it('does not redirect on non-401 errors', async () => {
		currentUser.set({ id: 'u1', username: 'felix', role: 'user' } as AuthUser);
		mockError(500, 'Internal error');
		await expect(fetchAlbums()).rejects.toThrow(ApiError);
		expect(mockClearAuth).not.toHaveBeenCalled();
		expect(mockGoto).not.toHaveBeenCalled();
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

	it('uploadAlbumCover posts the file as multipart', async () => {
		mockOk({
			id: 'a1',
			cover: {
				card: '/api/albums/a1/cover?variant=card',
				detail: '/api/albums/a1/cover?variant=detail'
			}
		});
		const file = new File([new Uint8Array([1, 2, 3])], 'cover.jpg', { type: 'image/jpeg' });
		await uploadAlbumCover('a1', file);
		expect(mockFetch).toHaveBeenCalledWith(
			'/api/albums/a1/cover',
			expect.objectContaining({
				method: 'POST',
				body: expect.any(FormData),
				credentials: 'include'
			})
		);
	});

	it('deleteAlbumCover deletes the cover', async () => {
		mockOk({ id: 'a1', cover: null });
		await deleteAlbumCover('a1');
		expect(mockFetch).toHaveBeenCalledWith(
			'/api/albums/a1/cover',
			expect.objectContaining({ method: 'DELETE', credentials: 'include' })
		);
	});

	it('uploadSongCover posts the file as multipart', async () => {
		mockOk({
			id: 's1',
			cover: {
				card: '/api/songs/s1/cover?variant=card',
				detail: '/api/songs/s1/cover?variant=detail'
			}
		});
		const file = new File([new Uint8Array([1, 2, 3])], 'cover.jpg', { type: 'image/jpeg' });
		await uploadSongCover('s1', file);
		expect(mockFetch).toHaveBeenCalledWith(
			'/api/songs/s1/cover',
			expect.objectContaining({
				method: 'POST',
				body: expect.any(FormData),
				credentials: 'include'
			})
		);
	});

	it('deleteSongCover deletes the cover', async () => {
		mockOk({ id: 's1', cover: null });
		await deleteSongCover('s1');
		expect(mockFetch).toHaveBeenCalledWith(
			'/api/songs/s1/cover',
			expect.objectContaining({ method: 'DELETE', credentials: 'include' })
		);
	});
});

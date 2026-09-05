import { describe, expect, it, vi, beforeEach } from 'vitest';
import { get } from 'svelte/store';

const mockFetchMe = vi.fn();
const mockApiLogin = vi.fn();
const mockApiLogout = vi.fn();
const mockStopLibraryResourceSync = vi.fn();

vi.mock('$lib/api/client', async () => {
	const { ApiError } = await vi.importActual<typeof import('$lib/api/client')>('$lib/api/client');
	return {
		ApiError,
		fetchMe: (...args: unknown[]) => mockFetchMe(...args),
		login: (...args: unknown[]) => mockApiLogin(...args),
		logout: (...args: unknown[]) => mockApiLogout(...args)
	};
});

vi.mock('$lib/stores/resourceSync', () => ({
	stopLibraryResourceSync: (...args: unknown[]) => mockStopLibraryResourceSync(...args)
}));

import {
	currentUser,
	authLoading,
	authError,
	authCheckError,
	authNotice,
	isAdmin,
	checkAuth,
	classifyAuthFailure,
	login,
	logout,
	clearAuth
} from './auth';
import { ApiError } from '$lib/api/client';
import { playlistList, selectedPlaylistDetail } from '$lib/stores/playlists';
import { shareCount } from '$lib/stores/shares';
import { generationFailures } from '$lib/stores/jobs';

const AUTH_ME_PATH = '/api/auth/me';
const KNOWN_USER = { id: 'u1', username: 'admin', role: 'admin' as const };

beforeEach(() => {
	mockFetchMe.mockReset();
	mockApiLogin.mockReset();
	mockApiLogout.mockReset();
	mockStopLibraryResourceSync.mockReset();
	currentUser.set(null);
	authLoading.set(true);
	authError.set('');
	authCheckError.set(null);
	authNotice.set(null);
});

describe('auth store', () => {
	it('defaults to null user', () => {
		expect(get(currentUser)).toBeNull();
	});

	it('isAdmin derived from currentUser', () => {
		expect(get(isAdmin)).toBe(false);
		currentUser.set({ id: 'u1', username: 'admin', role: 'admin' });
		expect(get(isAdmin)).toBe(true);
		currentUser.set({ id: 'u2', username: 'user', role: 'user' });
		expect(get(isAdmin)).toBe(false);
	});
});

describe('classifyAuthFailure', () => {
	it.each([
		['a 401 ApiError', new ApiError(401, 'unauthorized', AUTH_ME_PATH), 'unauthorized'],
		['a 403 ApiError', new ApiError(403, 'Account disabled', AUTH_ME_PATH), 'disabled'],
		['a 429 ApiError', new ApiError(429, 'slow down', AUTH_ME_PATH), 'retryable'],
		['a 503 ApiError', new ApiError(503, 'unavailable', AUTH_ME_PATH), 'retryable'],
		['a network error', new TypeError('Failed to fetch'), 'retryable']
	])('classifies %s as %s', (_label, error, expected) => {
		expect(classifyAuthFailure(error)).toBe(expected);
	});
});

describe('checkAuth', () => {
	it('sets currentUser on success and clears any prior check error', async () => {
		authCheckError.set('stale error');
		authNotice.set('disabled');
		mockFetchMe.mockResolvedValueOnce({ id: 'u1', username: 'admin', role: 'admin' });
		const user = await checkAuth();
		expect(user).toEqual({ id: 'u1', username: 'admin', role: 'admin' });
		expect(get(currentUser)).toEqual(user);
		expect(get(authLoading)).toBe(false);
		expect(get(authCheckError)).toBeNull();
		expect(get(authNotice)).toBeNull();
	});

	it('logs out on a 401 and clears the known user', async () => {
		currentUser.set(KNOWN_USER);
		mockFetchMe.mockRejectedValueOnce(new ApiError(401, 'unauthorized', AUTH_ME_PATH));
		const user = await checkAuth();
		expect(user).toBeNull();
		expect(get(currentUser)).toBeNull();
		expect(get(authLoading)).toBe(false);
		expect(get(authCheckError)).toBeNull();
		expect(get(authNotice)).toBe('unauthorized');
	});

	it('logs out on a 403 (account disabled) and clears the known user', async () => {
		currentUser.set(KNOWN_USER);
		mockFetchMe.mockRejectedValueOnce(new ApiError(403, 'Account disabled', AUTH_ME_PATH));
		const user = await checkAuth();
		expect(user).toBeNull();
		expect(get(currentUser)).toBeNull();
		expect(get(authLoading)).toBe(false);
		expect(get(authCheckError)).toBeNull();
		expect(get(authNotice)).toBe('disabled');
	});

	it('keeps an unknown user null through a transient failure on first load', async () => {
		authNotice.set('disabled');
		mockFetchMe.mockRejectedValueOnce(new ApiError(429, 'slow down', AUTH_ME_PATH));
		const user = await checkAuth();
		expect(user).toBeNull();
		expect(get(currentUser)).toBeNull();
		expect(get(authCheckError)).not.toBeNull();
		expect(get(authNotice)).toBeNull();
	});

	it.each([
		['a 429 rate limit', new ApiError(429, 'slow down', AUTH_ME_PATH)],
		['a 503 outage', new ApiError(503, 'unavailable', AUTH_ME_PATH)],
		['a network error', new TypeError('Failed to fetch')]
	])('keeps the known user through %s and records a retryable error', async (_label, error) => {
		currentUser.set(KNOWN_USER);
		mockFetchMe.mockRejectedValueOnce(error);
		const user = await checkAuth();
		expect(user).toEqual(KNOWN_USER);
		expect(get(currentUser)).toEqual(KNOWN_USER);
		expect(get(authLoading)).toBe(false);
		expect(get(authCheckError)).not.toBeNull();
	});
});

describe('login', () => {
	it('sets currentUser on success', async () => {
		mockApiLogin.mockResolvedValueOnce({ id: 'u1', username: 'alice', role: 'user' });
		const user = await login('alice', 'password');
		expect(user.username).toBe('alice');
		expect(get(currentUser)).toEqual(user);
		expect(get(authError)).toBe('');
	});

	it('sets authError on 401', async () => {
		authNotice.set('disabled');
		mockApiLogin.mockRejectedValueOnce(new ApiError(401, 'Invalid credentials', '/api/auth/login'));
		await expect(login('alice', 'wrong')).rejects.toThrow();
		expect(get(authError)).toBe('Invalid username or password.');
		expect(get(authNotice)).toBeNull();
	});

	it('sets authError on 429', async () => {
		mockApiLogin.mockRejectedValueOnce(new ApiError(429, 'Too many requests', '/api/auth/login'));
		await expect(login('alice', 'x')).rejects.toThrow();
		expect(get(authError)).toBe('Too many attempts. Try again later.');
	});

	it('sets detail from ApiError on other status', async () => {
		mockApiLogin.mockRejectedValueOnce(new ApiError(403, 'Account disabled', '/api/auth/login'));
		await expect(login('alice', 'x')).rejects.toThrow();
		expect(get(authError)).toBe('Account disabled');
	});

	it('sets generic authError on non-API error', async () => {
		mockApiLogin.mockRejectedValueOnce(new Error('Network failure'));
		await expect(login('alice', 'x')).rejects.toThrow();
		expect(get(authError)).toBe('Network failure');
	});
});

describe('clearAuth', () => {
	it('sets currentUser to null', () => {
		currentUser.set({ id: 'u1', username: 'admin', role: 'admin' });
		clearAuth();
		expect(get(currentUser)).toBeNull();
	});

	it('wipes the per-user playlist, share, and generation-failure caches so the next session starts clean', () => {
		playlistList.set([
			{
				id: 'p1',
				title: 'Leftover',
				slug: 'leftover',
				entry_count: 1,
				is_shared: false,
				share_slug: null,
				album_covers: [],
				created_at: ''
			}
		]);
		selectedPlaylistDetail.set({
			id: 'p1',
			title: 'Leftover',
			slug: 'leftover',
			entry_count: 1,
			is_shared: false,
			share_slug: null,
			album_covers: [],
			created_at: '',
			entries: []
		});
		shareCount.set({ status: 'ready', error: null, total: 4 });
		generationFailures.set({ s1: 'Music generation failed' });

		clearAuth();

		expect(get(generationFailures)).toEqual({});
		expect(get(playlistList)).toEqual([]);
		expect(get(selectedPlaylistDetail)).toBeNull();
		expect(get(shareCount)).toMatchObject({ status: 'idle', total: null });
	});
});

describe('logout', () => {
	it('stops resource sync before the logout request', async () => {
		const order: string[] = [];
		mockStopLibraryResourceSync.mockImplementation(() => {
			order.push('stop');
		});
		mockApiLogout.mockImplementation(async () => {
			order.push('api');
		});
		currentUser.set({ id: 'u1', username: 'admin', role: 'admin' });
		await logout();
		expect(order).toEqual(['stop', 'api']);
		expect(get(currentUser)).toBeNull();
	});

	it('clears currentUser', async () => {
		currentUser.set({ id: 'u1', username: 'admin', role: 'admin' });
		mockApiLogout.mockResolvedValueOnce(undefined);
		await logout();
		expect(get(currentUser)).toBeNull();
	});

	it('clears user even if API fails', async () => {
		currentUser.set({ id: 'u1', username: 'admin', role: 'admin' });
		mockApiLogout.mockRejectedValueOnce(new Error('fail'));
		await logout();
		expect(get(currentUser)).toBeNull();
	});
});

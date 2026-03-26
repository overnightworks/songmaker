import { describe, expect, it, vi, beforeEach } from 'vitest';
import { get } from 'svelte/store';

const mockFetchMe = vi.fn();
const mockApiLogin = vi.fn();
const mockApiLogout = vi.fn();

vi.mock('$lib/api/client', async () => {
	const { ApiError } = await vi.importActual<typeof import('$lib/api/client')>('$lib/api/client');
	return {
		ApiError,
		fetchMe: (...args: unknown[]) => mockFetchMe(...args),
		login: (...args: unknown[]) => mockApiLogin(...args),
		logout: (...args: unknown[]) => mockApiLogout(...args)
	};
});

import { currentUser, authLoading, authError, isAdmin, checkAuth, login, logout } from './auth';
import { ApiError } from '$lib/api/client';

beforeEach(() => {
	mockFetchMe.mockReset();
	mockApiLogin.mockReset();
	mockApiLogout.mockReset();
	currentUser.set(null);
	authLoading.set(true);
	authError.set('');
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

describe('checkAuth', () => {
	it('sets currentUser on success', async () => {
		mockFetchMe.mockResolvedValueOnce({ id: 'u1', username: 'admin', role: 'admin' });
		const user = await checkAuth();
		expect(user).toEqual({ id: 'u1', username: 'admin', role: 'admin' });
		expect(get(currentUser)).toEqual(user);
		expect(get(authLoading)).toBe(false);
	});

	it('clears user on failure', async () => {
		mockFetchMe.mockRejectedValueOnce(new Error('401'));
		const user = await checkAuth();
		expect(user).toBeNull();
		expect(get(currentUser)).toBeNull();
		expect(get(authLoading)).toBe(false);
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
		mockApiLogin.mockRejectedValueOnce(new ApiError(401, 'Invalid credentials', '/api/auth/login'));
		await expect(login('alice', 'wrong')).rejects.toThrow();
		expect(get(authError)).toBe('Invalid username or password.');
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

describe('logout', () => {
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

import { writable, derived, get } from 'svelte/store';
import type { AuthUser } from '$lib/api/types';
import { ApiError, fetchMe, login as apiLogin, logout as apiLogout } from '$lib/api/client';
import {
	AUTH_CHECK_NETWORK_ERROR,
	AUTH_CHECK_RATE_LIMITED_ERROR,
	AUTH_CHECK_SERVER_ERROR
} from '$lib/constants/auth';
import { resetGenerationFailures } from '$lib/stores/jobs';
import { resetLibraryContinueItems } from '$lib/stores/libraryData';
import { resetPlaylists } from '$lib/stores/playlists';
import { resetShares } from '$lib/stores/shares';

export const currentUser = writable<AuthUser | null>(null);
export const authLoading = writable(true);
export const authError = writable('');
export const authCheckError = writable<string | null>(null);
export const isAdmin = derived(currentUser, (u) => u?.role === 'admin');

export type AuthFailureKind = 'unauthorized' | 'disabled' | 'retryable';
export type AuthNotice = Exclude<AuthFailureKind, 'retryable'>;

export const authNotice = writable<AuthNotice | null>(null);

export function classifyAuthFailure(error: unknown): AuthFailureKind {
	if (!(error instanceof ApiError)) return 'retryable';
	if (error.status === 401) return 'unauthorized';
	if (error.status === 403) return 'disabled';
	return 'retryable';
}

function describeAuthCheckFailure(error: unknown): string {
	if (error instanceof ApiError && error.status === 429) {
		return AUTH_CHECK_RATE_LIMITED_ERROR;
	}
	if (error instanceof ApiError) {
		return AUTH_CHECK_SERVER_ERROR;
	}
	return AUTH_CHECK_NETWORK_ERROR;
}

export async function checkAuth(): Promise<AuthUser | null> {
	authLoading.set(true);
	try {
		const user = await fetchMe();
		currentUser.set(user);
		authCheckError.set(null);
		authNotice.set(null);
		return user;
	} catch (err) {
		const failure = classifyAuthFailure(err);
		if (failure !== 'retryable') {
			authCheckError.set(null);
			authNotice.set(failure);
			currentUser.set(null);
			return null;
		}
		authNotice.set(null);
		authCheckError.set(describeAuthCheckFailure(err));
		return get(currentUser);
	} finally {
		authLoading.set(false);
	}
}

export async function login(username: string, password: string): Promise<AuthUser> {
	authError.set('');
	authNotice.set(null);
	try {
		const user = await apiLogin(username, password);
		currentUser.set(user);
		return user;
	} catch (err) {
		if (err instanceof ApiError) {
			if (err.status === 429) {
				authError.set('Too many attempts. Try again later.');
			} else if (err.status === 401) {
				authError.set('Invalid username or password.');
			} else {
				authError.set(err.detail || err.message);
			}
		} else {
			authError.set(err instanceof Error ? err.message : 'Login failed');
		}
		throw err;
	}
}

// Every per-user cache (playlist detail cache, share count/inventory
// cache) lives in module state, not the session -- without this, a
// logout/401 followed by a different user's login on the same tab could
// briefly serve the previous user's cached playlist or share data.
export function clearAuth(): void {
	currentUser.set(null);
	resetGenerationFailures();
	resetLibraryContinueItems();
	resetPlaylists();
	resetShares();
}

export async function logout(): Promise<void> {
	const { stopLibraryResourceSync } = await import('$lib/stores/resourceSync');
	stopLibraryResourceSync();
	try {
		await apiLogout();
	} catch {
		// swallow — always clear local state
	} finally {
		clearAuth();
	}
}

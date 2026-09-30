import { writable, derived, get } from 'svelte/store';
import type { AuthUser } from '$lib/api/types';
import { ApiError, fetchMe, login as apiLogin, logout as apiLogout } from '$lib/api/client';
import { NetworkError } from '$lib/api/fetch';
import { SERVER_UNREACHABLE_STATUSES } from '$lib/constants';
import {
	AUTH_CHECK_NETWORK_ERROR,
	AUTH_CHECK_RATE_LIMITED_ERROR,
	AUTH_CHECK_RETURN_PROBE_INTERVAL_MS,
	AUTH_CHECK_SERVER_ERROR
} from '$lib/constants/auth';
import { reportSessionCheckReachable } from '$lib/stores/connectivity';
import { resetGenerationFailures } from '$lib/stores/jobs';
import { resetLibraryOrder } from '$lib/stores/libraryOrder';
import { resetPlaylists } from '$lib/stores/playlists';
import { resetShares } from '$lib/stores/shares';

export const currentUser = writable<AuthUser | null>(null);
export const authLoading = writable(true);
export const authError = writable('');
export const authCheckError = writable<string | null>(null);
// A session check the server did not answer (#1118): the offline strip says
// it, and the gate that asked runs again until the server answers.
export const authCheckUnreachable = writable(false);
let sessionGate: () => void = () => {};
let pendingSessionCheck: ReturnType<typeof setTimeout> | null = null;
export const isAdmin = derived(currentUser, (u) => u?.role === 'admin');

type AuthNotice = 'unauthorized' | 'disabled';
// `unreachable`: the server could not be reached at all, so the connectivity
// owner says "offline". `retryable`: it answered, but not with the user
// (a rate limit, a server error) -- worth another try, not offline (#1099).
export type AuthFailureKind = AuthNotice | 'unreachable' | 'retryable';

export const authNotice = writable<AuthNotice | null>(null);

export function classifyAuthFailure(error: unknown): AuthFailureKind {
	if (error instanceof NetworkError) return 'unreachable';
	if (!(error instanceof ApiError)) return 'retryable';
	if (error.status === 401) return 'unauthorized';
	if (error.status === 403) return 'disabled';
	if (SERVER_UNREACHABLE_STATUSES.has(error.status)) return 'unreachable';
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

/**
 * `checkAgain` is the gate asking: while the server does not answer, the
 * gate runs again until it does, so its routing follows too.
 */
export async function checkAuth(checkAgain: () => void): Promise<AuthUser | null> {
	sessionGate = checkAgain;
	authLoading.set(true);
	try {
		const user = await fetchMe();
		forgetUnreachableSessionCheck();
		currentUser.set(user);
		authCheckError.set(null);
		authNotice.set(null);
		return user;
	} catch (err) {
		authNotice.set(null);
		authCheckError.set(null);
		if (err instanceof NetworkError) {
			rememberUnreachableSessionCheck();
			return get(currentUser);
		}
		forgetUnreachableSessionCheck();
		const failure = classifyAuthFailure(err);
		if (failure === 'unauthorized' || failure === 'disabled') {
			authNotice.set(failure);
			currentUser.set(null);
			return null;
		}
		authCheckError.set(describeAuthCheckFailure(err));
		return get(currentUser);
	} finally {
		authLoading.set(false);
	}
}

function rememberUnreachableSessionCheck(): void {
	stopPendingSessionCheck();
	authCheckUnreachable.set(true);
	reportSessionCheckReachable(false);
	pendingSessionCheck = setTimeout(() => {
		pendingSessionCheck = null;
		sessionGate();
	}, AUTH_CHECK_RETURN_PROBE_INTERVAL_MS);
}

function forgetUnreachableSessionCheck(): void {
	stopPendingSessionCheck();
	authCheckUnreachable.set(false);
	reportSessionCheckReachable(true);
}

function stopPendingSessionCheck(): void {
	if (pendingSessionCheck === null) return;
	clearTimeout(pendingSessionCheck);
	pendingSessionCheck = null;
}

export function resetAuthForTests(): void {
	forgetUnreachableSessionCheck();
	sessionGate = () => {};
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
// cache, Recent ranking) lives in module state, not the session -- without this, a
// logout/401 followed by a different user's login on the same tab could
// briefly serve the previous user's cached playlist or share data.
export function clearAuth(): void {
	currentUser.set(null);
	resetGenerationFailures();
	resetPlaylists();
	resetShares();
	resetLibraryOrder();
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

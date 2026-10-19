import { writable, derived, get } from 'svelte/store';
import type { AuthUser } from '$lib/api/types';
import { ApiError, fetchMe, login as apiLogin, logout as apiLogout } from '$lib/api/client';
import { NetworkError, SIGN_IN_PATH } from '$lib/api/fetch';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { RATE_LIMITED_STATUS, SERVER_UNREACHABLE_STATUSES } from '$lib/constants';
import { loadAfresh, reloadAfresh } from '$lib/history/historyController';
import {
	AUTH_CHECK_NETWORK_ERROR,
	AUTH_CHECK_RATE_LIMITED_ERROR,
	AUTH_CHECK_RETURN_PROBE_INTERVAL_MS,
	AUTH_CHECK_SERVER_ERROR,
	AUTH_SESSION_EXPIRED_DETAIL
} from '$lib/constants/auth';
import { reportSessionCheckReachable } from '$lib/stores/connectivity';

export const currentUser = writable<AuthUser | null>(null);
export const authLoading = writable(true);
export const authError = writable('');
export const authCheckError = writable<string | null>(null);
// A session check the server did not answer (#1118): the offline strip says
// it, and the gate that asked runs again until the server answers.
export const authCheckUnreachable = writable(false);
let sessionGate: () => void = () => {};
let pendingSessionCheck: ReturnType<typeof setTimeout> | null = null;
let signingOut = false;
export const isAdmin = derived(currentUser, (u) => u?.role === 'admin');

type AuthNotice = 'unauthorized' | 'disabled';
// `unreachable`: the server could not be reached at all, so the connectivity
// owner says "offline". `retryable`: it answered, but not with the user
// (a rate limit, a server error) -- worth another try, not offline (#1099).
export type AuthFailureKind = AuthNotice | 'unreachable' | 'retryable';

export const authNotice = writable<AuthNotice | null>(null);
// A sign-out the server did not confirm: the person is still signed in.
export const signOutFailed = writable(false);

export function classifyAuthFailure(error: unknown): AuthFailureKind {
	if (error instanceof NetworkError) return 'unreachable';
	if (!(error instanceof ApiError)) return 'retryable';
	if (error.status === 401) return 'unauthorized';
	if (error.status === 403) return 'disabled';
	if (SERVER_UNREACHABLE_STATUSES.has(error.status)) return 'unreachable';
	return 'retryable';
}

function describeAuthCheckFailure(error: unknown): string {
	if (error instanceof ApiError && error.status === RATE_LIMITED_STATUS) {
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
		const failure = classifyAuthFailure(err);
		noteFailedSessionCheck(err, failure);
		authCheckError.set(null);
		if (err instanceof NetworkError) {
			rememberUnreachableSessionCheck();
			return get(currentUser);
		}
		forgetUnreachableSessionCheck();
		if (failure === 'unauthorized' || failure === 'disabled') {
			currentUser.set(null);
			return null;
		}
		authCheckError.set(describeAuthCheckFailure(err));
		return get(currentUser);
	} finally {
		authLoading.set(false);
	}
}

// Only a 401 for a session the server no longer holds says the session
// expired: a request without a session cookie is a first visit or a signed-out
// deep link, and keeps whatever the session-lost reaction left (#1215).
function noteFailedSessionCheck(error: unknown, failure: AuthFailureKind): void {
	if (failure === 'disabled') authNotice.set('disabled');
	else if (failure !== 'unauthorized') authNotice.set(null);
	else if (error instanceof ApiError && error.detail === AUTH_SESSION_EXPIRED_DETAIL)
		authNotice.set('unauthorized');
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
	signingOut = false;
	signOutFailed.set(false);
}

export async function login(username: string, password: string): Promise<AuthUser> {
	authError.set('');
	authNotice.set(null);
	try {
		const user = await apiLogin(username, password);
		currentUser.set(user);
		signOutFailed.set(false);
		return user;
	} catch (err) {
		if (err instanceof ApiError) {
			if (err.status === RATE_LIMITED_STATUS) {
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

// A sign-out ends here only once the server confirms the session is gone: a
// shared device must not look signed out while the server still holds it
// (#1340, ruling A of 14.10.2026). A 401 confirms it as well -- that session
// was already gone. Confirmed, it forgets what was playing and what the
// player recorded, which a session that merely ran out keeps for the same
// user's next sign-in, and leaves by a fresh document load, so nothing the
// signed-in page held survives in memory. The player is unloaded first, so a
// save on the way out cannot write the record again (#1187).
// From the request on the user is still set but no longer has a session to
// lose: a request refused meanwhile -- a poll -- is this sign-out, not an
// expiry.
export async function logout(): Promise<void> {
	const { forgetPlaybackResume } = await import('$lib/stores/playbackResume');
	const user = get(currentUser);
	signingOut = true;
	signOutFailed.set(false);
	try {
		await apiLogout();
	} catch (error) {
		if (!(error instanceof ApiError && error.status === 401)) {
			signingOut = false;
			signOutFailed.set(true);
			return;
		}
	}
	audioPlayer.unload();
	if (user) {
		forgetPlaybackResume(user.id);
	}
	await loadAfresh(SIGN_IN_PATH);
}

// What a refused request asks before it reacts as a lost session.
function hasSessionToLose(): boolean {
	return get(currentUser) !== null && !signingOut;
}

// The one reaction to "the session is gone" (issue #385). The transport hands
// it every refused request (#925); player.ts's stream/media probe and
// resourceSync.ts's SSE-drop probe detect a lost session a way apiFetch never
// sees, so they call it too instead of redirecting on their own.
let sessionLostRun: Promise<void> | null = null;

export function handleSessionLost(): Promise<void> {
	if (!sessionLostRun) {
		sessionLostRun = reactToSessionLost().finally(() => {
			sessionLostRun = null;
		});
	}
	return sessionLostRun;
}

// No-ops when there is no session to lose (`hasSessionToLose`): the first
// load, a second caller that lost the in-flight race above, or a deliberate
// sign-out under way, which leaves for sign-in itself. This leaves
// +layout.svelte's own /login-vs-/setup routing, or the sign-out, to decide
// instead of forcing a redirect that could race it.
//
// A lost session loads the address history stands on afresh once history has
// come to rest -- the album a tap in the drawer opened, whichever of its
// requests the server refused first -- so nothing of the signed-in page stays
// in memory (#1340, ruling A). That load asks for the session as every load
// does: the server's answer sends it to sign-in, carrying the address back,
// and says whether the session expired (#1215). Over an open overlay's entry
// the load replaces it, so nothing steps back on the way (#1230).
async function reactToSessionLost(): Promise<void> {
	if (!hasSessionToLose()) return;
	await reloadAfresh();
}

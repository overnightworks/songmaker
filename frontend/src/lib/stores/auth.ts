import { writable, derived, get } from 'svelte/store';
import type { AuthUser } from '#lib/api/types.ts';
import { ApiError, fetchMe } from '#lib/api/client.ts';
import { NetworkError } from '#lib/api/fetch.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { RATE_LIMITED_STATUS, SERVER_UNREACHABLE_STATUSES } from '#lib/constants.ts';
import { leaveByPostingForm, reloadAfresh } from '#lib/history/historyController.ts';
import {
	AUTH_CHECK_NETWORK_ERROR,
	AUTH_CHECK_RATE_LIMITED_ERROR,
	AUTH_CHECK_RETURN_PROBE_INTERVAL_MS,
	AUTH_CHECK_SERVER_ERROR,
	LOGOUT_ADDRESS
} from '#lib/constants/auth.ts';
import { reportSessionCheckReachable } from '#lib/stores/connectivity.ts';

export const currentUser = writable<AuthUser | null>(null);
export const authLoading = writable(true);
export const authCheckError = writable<string | null>(null);
// A session check the server did not answer (#1118): the offline strip says
// it, and the gate that asked runs again until the server answers.
export const authCheckUnreachable = writable(false);
let sessionGate: () => void = () => {};
let pendingSessionCheck: ReturnType<typeof setTimeout> | null = null;
let signingOut = false;
export const isAdmin = derived(currentUser, (u) => u?.role === 'admin');

// `unauthorized`: the server holds no session for this browser. `unreachable`:
// the server could not be reached at all, so the connectivity owner says
// "offline". `retryable`: it answered, but not with the user (a rate limit, a
// server error) -- worth another try, not offline (#1099).
export type AuthFailureKind = 'unauthorized' | 'unreachable' | 'retryable';

// The sign-out could not reach the server (a network error or a 502, 503 or 504),
// so the person is still signed in.
export const signOutFailed = writable(false);

export function classifyAuthFailure(error: unknown): AuthFailureKind {
	if (error instanceof NetworkError) return 'unreachable';
	if (!(error instanceof ApiError)) return 'retryable';
	if (error.status === 401) return 'unauthorized';
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
		return user;
	} catch (err) {
		const failure = classifyAuthFailure(err);
		authCheckError.set(null);
		if (err instanceof NetworkError) {
			rememberUnreachableSessionCheck();
			return get(currentUser);
		}
		forgetUnreachableSessionCheck();
		if (failure === 'unauthorized') {
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
	signingOut = false;
	signOutFailed.set(false);
}

// A sign-out leaves only once the server answers: a shared device must not
// look signed out while nothing can end the session (#1340, ruling A of
// 14.10.2026). The check is the session read, which a session already gone
// (a 401) passes: the identity provider's session still has to end. Past the
// check it forgets what was playing and what the player recorded, which a
// session that merely ran out keeps for the same user's next sign-in, and
// leaves through a top-level form POST to the server, whose answer ends the
// identity provider's session too, so nothing the signed-in page held survives
// in memory. The player is unloaded first, so a save on the way out cannot
// write the record again (#1187).
// From the check on the user is still set but no longer has a session to
// lose: a request refused meanwhile -- a poll -- is this sign-out, not an
// expiry.
export async function logout(): Promise<void> {
	const { forgetPlaybackResume } = await import('#lib/stores/playbackResume.ts');
	const user = get(currentUser);
	signingOut = true;
	signOutFailed.set(false);
	try {
		await fetchMe();
	} catch (error) {
		if (classifyAuthFailure(error) === 'unreachable') {
			signingOut = false;
			signOutFailed.set(true);
			return;
		}
	}
	audioPlayer.unload();
	if (user) {
		forgetPlaybackResume(user.id);
	}
	await leaveByPostingForm(LOGOUT_ADDRESS);
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
// +layout.svelte's own sign-in routing, or the sign-out, to decide
// instead of forcing a redirect that could race it.
//
// A lost session loads the address history stands on afresh once history has
// come to rest -- the album a tap in the library list opened, whichever of its
// requests the server refused first -- so nothing of the signed-in page stays
// in memory (#1340, ruling A). That load asks for the session as every load
// does: the server's answer sends it to sign-in, carrying the address back,
// and says whether the session expired (#1215). Over an open overlay's entry
// the load replaces it, so nothing steps back on the way (#1230).
async function reactToSessionLost(): Promise<void> {
	if (!hasSessionToLose()) return;
	await reloadAfresh();
}

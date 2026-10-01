import { get } from 'svelte/store';
import type { JobItem } from './types';
import {
	API_ERROR_GENERIC_MESSAGE,
	RATE_LIMITED_TOAST_MESSAGE,
	SESSION_LOST_REDIRECT_PARAM
} from '$lib/constants';
import { addToast, toasts } from '$lib/stores/toast';
import { UserFacingError } from './userFacingError';

const API_TIMEOUT_MS = 30_000;

export class ApiError extends Error {
	constructor(
		public readonly status: number,
		public readonly detail: string,
		public readonly path: string,
		public readonly retryAfterSeconds: number | null = null,
		public readonly responseDetail: unknown = detail
	) {
		super(detail || API_ERROR_GENERIC_MESSAGE);
		this.name = 'ApiError';
	}
}

type NetworkFailureReason = 'unreachable' | 'timeout';

/**
 * The request got no answer at all -- offline, DNS, a refused connection --
 * so `fetch` itself rejected, the connection broke off while its body was
 * still being read, or no answer came before the client timeout. Only the
 * fetch boundary below knows that a rejection came from the network rather
 * than from the caller's own code.
 */
export class NetworkError extends Error {
	constructor(
		public readonly path: string,
		cause: TypeError | DOMException,
		public readonly reason: NetworkFailureReason = 'unreachable'
	) {
		super(reason === 'timeout' ? `No answer from ${path} before the timeout` : cause.message, {
			cause
		});
		this.name = 'NetworkError';
	}
}

/** How a caller's own rulings shape the words `describeFailure` chooses. */
interface FailureWording {
	/** Said instead of the fallback when the request got no answer at all. */
	offline?: string;
	/** For a caller ruled never to show the server's own detail. */
	withholdServerDetail?: boolean;
}

/**
 * The one place a failure becomes user-facing text: the caller's offline
 * wording when the request got no answer, the server's own words when it
 * answered with a reason (unless the caller withholds them), a module's own
 * worded failure, otherwise the caller's named fallback -- never a browser
 * error's text.
 */
export function describeFailure(
	err: unknown,
	fallback: string,
	wording: FailureWording = {}
): string {
	if (err instanceof NetworkError && wording.offline) return wording.offline;
	if (err instanceof ApiError && err.detail && !wording.withholdServerDetail) return err.detail;
	if (err instanceof UserFacingError) return err.message;
	return fallback;
}

async function readErrorDetail(response: Pick<Response, 'json'>): Promise<{
	detail: string;
	responseDetail: unknown;
}> {
	try {
		const body: unknown = await response.json();
		if (typeof body !== 'object' || body === null || !('detail' in body)) {
			return { detail: '', responseDetail: '' };
		}
		const responseDetail = body.detail;
		return {
			detail: typeof responseDetail === 'string' ? responseDetail : '',
			responseDetail
		};
	} catch {
		return { detail: '', responseDetail: '' };
	}
}

export function isNotFound(err: unknown): boolean {
	return err instanceof ApiError && err.status === 404;
}

function parseRetryAfterSeconds(resp: {
	headers?: { get: (name: string) => string | null };
}): number | null {
	const header = resp.headers?.get?.('Retry-After') ?? null;
	if (!header) return null;
	const seconds = Number(header);
	return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

function getCsrfToken(): string {
	const match = /(?:^|;\s*)csrf_token=([^;]*)/.exec(document.cookie);
	return match ? decodeURIComponent(match[1]) : '';
}

// A 401 from these refuses the credentials the person just typed -- a wrong
// password at sign-in, setup, or a password change (#1117) -- rather than
// saying the session is gone, so it never signs anyone out.
const AUTH_ENDPOINTS = new Set(['/api/auth/login', '/api/auth/setup', '/api/auth/password']);

// A path whose own 429 is already visible some other way, so the generic
// toast below would only repeat it. Kept as its own list, not
// derived from `AUTH_ENDPOINTS` above (that one exists for the unrelated
// 401-redirect suppression) -- a future path added there for its 401 reason
// should not silently also lose this toast.
//   - '/api/auth/login': `stores/auth.ts`'s `login()` turns a 429 into
//     "Too many attempts. Try again later." under the login form.
//   - '/api/auth/me': `stores/auth.ts`'s `checkAuth()` turns a 429 into the
//     full-page session-check retry banner.
//   - '/api/auth/setup': not auth.ts -- `routes/setup/+page.svelte`'s own
//     catch block shows the error inline via `err.message`.
//   - '/api/albums/<id>/cover-suggestions': `AlbumCoverEditor.svelte` shows
//     every refusal there itself -- the spent daily limit under the cover,
//     any other as its failure or error toast; nothing retries it, so
//     "it will continue in a moment" would be untrue there.
const RATE_LIMIT_TOAST_EXEMPT_PATHS: readonly RegExp[] = [
	/^\/api\/auth\/login$/,
	/^\/api\/auth\/me$/,
	/^\/api\/auth\/setup$/,
	/^\/api\/albums\/[^/]+\/cover-suggestions$/
];

/**
 * Never more than one throttle toast on screen at once, not one per
 * rejected request: a 429 burst calls this many times in a row, but a
 * toast already showing the same message is left alone instead of being
 * duplicated (issue #257). The toast auto-dismisses after 5s (`addToast`'s
 * 'info' type), so a burst that outlasts that raises a fresh toast every
 * ~5s for as long as it's still being throttled -- which reads as "still
 * throttled", not as a bug.
 */
function notifyIfRateLimited(status: number, path: string): void {
	if (status !== 429 || RATE_LIMIT_TOAST_EXEMPT_PATHS.some((exempt) => exempt.test(path))) return;
	const alreadyShown = get(toasts).some((toast) => toast.message === RATE_LIMITED_TOAST_MESSAGE);
	if (alreadyShown) return;
	addToast(RATE_LIMITED_TOAST_MESSAGE, 'info');
}

function isSessionLostResponse(status: number, path: string): boolean {
	return status === 401 && !AUTH_ENDPOINTS.has(path);
}

const SAFE_INTERNAL_PATH_FALLBACK = '/';
const SIGN_IN_PATH = '/login';

// A path of this app starts with exactly one slash. A second slash or a
// backslash makes it a foreign host; anything else -- an absolute URL even on
// this origin, a one-slash scheme, a relative path -- is no address the app
// hands out (#1230).
const SINGLE_SLASH_PATH = /^\/(?![/\\])/;

// Percent-encoded slashes count as slashes: decoded once more on the way, a
// /%2F%2F path would turn into a foreign host.
function isSingleSlashPath(candidate: string): boolean {
	try {
		return [candidate, decodeURIComponent(candidate)].every((form) => SINGLE_SLASH_PATH.test(form));
	} catch {
		return false;
	}
}

// No page to land on: the sign-in page would only ask for the password twice,
// and an API address would show its raw answer.
const NON_PAGE_PATH_PREFIXES = [`${SIGN_IN_PATH}/`, '/api/'];

// Judged decoded, the way the router and the server resolve it: URL parsing
// keeps %-escapes, so /%6Cogin would otherwise reach the sign-in page and
// /%61pi/... an API address. A single-slash path is already known decodable.
function isPagePath(encodedPathname: string): boolean {
	const pathname = decodeURIComponent(encodedPathname);
	return (
		pathname !== SIGN_IN_PATH &&
		!NON_PAGE_PATH_PREFIXES.some((prefix) => pathname.startsWith(prefix))
	);
}

// Normalize an address carried through sign-in. Resolving it still checks the
// origin: URL parsing drops tabs and newlines, so a single-slash path can turn
// into a foreign host on the way.
function safeInternalPath(candidate: string): string {
	if (!isSingleSlashPath(candidate)) return SAFE_INTERNAL_PATH_FALLBACK;
	const resolved = new URL(candidate, window.location.origin);
	if (resolved.origin !== window.location.origin) return SAFE_INTERNAL_PATH_FALLBACK;
	if (!isPagePath(resolved.pathname)) return SAFE_INTERNAL_PATH_FALLBACK;
	return resolved.pathname + resolved.search + resolved.hash;
}

// The sign-in page, asked to bring the person back to `returnTo` afterwards.
export function signInAddress(returnTo: string): string {
	const target = safeInternalPath(returnTo);
	if (target === SAFE_INTERNAL_PATH_FALLBACK) return SIGN_IN_PATH;
	return `${SIGN_IN_PATH}?${SESSION_LOST_REDIRECT_PARAM}=${encodeURIComponent(target)}`;
}

// Where a sign-in on `signInPage` lands: the address it was asked to return
// to when that stays on this origin, the library otherwise, so the redirect
// is never open.
export function signInReturnPath(signInPage: URL): string {
	const requested = signInPage.searchParams.get(SESSION_LOST_REDIRECT_PARAM);
	return requested === null ? SAFE_INTERNAL_PATH_FALLBACK : safeInternalPath(requested);
}

// The one reaction to "the session is gone" (issue #385). player.ts's
// stream/media probe and resourceSync.ts's SSE-drop probe detect a lost
// session a way apiFetch never sees, so they call this instead of
// redirecting on their own.
let sessionLostRun: Promise<void> | null = null;

export function handleSessionLost(): Promise<void> {
	if (!sessionLostRun) {
		sessionLostRun = reactToSessionLost().finally(() => {
			sessionLostRun = null;
		});
	}
	return sessionLostRun;
}

// No-ops when `currentUser` is already null: that caller has no session to
// lose (first load, or a second caller that lost the in-flight race above),
// so this leaves +layout.svelte's own /login-vs-/setup routing to decide
// instead of forcing a redirect that could race it.
//
// The library history stops before the shell goes, as on a sign-out: an
// overlay closing with the shell -- the phone drawer above all -- would
// otherwise step back off its history entry after the sign-in navigation
// below and land on the page the session was lost on (#1230).
async function reactToSessionLost(): Promise<void> {
	const [{ currentUser, clearAuth }, { forgetLayerEntries }] = await Promise.all([
		import('$lib/stores/auth'),
		import('$lib/history/historyController')
	]);
	if (get(currentUser) === null) return;
	forgetLayerEntries();
	clearAuth('unauthorized');
	const { goto } = await import('$app/navigation');
	await goto(signInAddress(window.location.pathname + window.location.search));
}

function abortOnCallerOrTimeout(
	callerSignal: AbortSignal | null | undefined,
	timeoutSignal: AbortSignal
): AbortSignal {
	return callerSignal ? AbortSignal.any([callerSignal, timeoutSignal]) : timeoutSignal;
}

function addCsrfToken(init: RequestInit, method: string): RequestInit {
	if (method === 'GET' || method === 'HEAD') return init;
	const token = getCsrfToken();
	if (!token) return init;
	return {
		...init,
		headers: { 'X-CSRF-Token': token, ...(init.headers as Record<string, string>) }
	};
}

async function throwForFailedResponse(response: Response, path: string): Promise<void> {
	if (response.ok) return;
	const { detail, responseDetail } = await readErrorDetail(response);
	notifyIfRateLimited(response.status, path);
	if (isSessionLostResponse(response.status, path)) await handleSessionLost();
	throw new ApiError(
		response.status,
		detail,
		path,
		parseRetryAfterSeconds(response),
		responseDetail
	);
}

async function orNetworkError<T>(
	path: string,
	timeoutSignal: AbortSignal,
	networkRead: Promise<T>
): Promise<T> {
	try {
		return await networkRead;
	} catch (err) {
		if (err instanceof TypeError) throw new NetworkError(path, err);
		if (timeoutSignal.aborted && err instanceof DOMException) {
			throw new NetworkError(path, err, 'timeout');
		}
		throw err;
	}
}

export async function apiFetch<T>(
	path: string,
	init?: RequestInit,
	timeoutMs?: number
): Promise<T> {
	const method = init?.method?.toUpperCase() ?? 'GET';
	const controller = new AbortController();
	const timeout = setTimeout(() => controller.abort(), timeoutMs ?? API_TIMEOUT_MS);
	const opts = addCsrfToken(
		{
			credentials: 'include',
			...init,
			signal: abortOnCallerOrTimeout(init?.signal, controller.signal)
		},
		method
	);
	try {
		const resp = await orNetworkError(path, controller.signal, fetch(path, opts));
		await throwForFailedResponse(resp, path);
		return await orNetworkError(path, controller.signal, resp.json() as Promise<T>);
	} finally {
		clearTimeout(timeout);
	}
}

export type JobStatus = JobItem;

async function* parseSseEvents<T>(
	path: string,
	timeoutSignal: AbortSignal,
	body: ReadableStream<Uint8Array>
): AsyncGenerator<T> {
	const reader = body.getReader();
	const decoder = new TextDecoder('utf-8');
	let buffer = '';
	while (true) {
		const { value, done } = await orNetworkError(path, timeoutSignal, reader.read());
		if (done) return;
		buffer += decoder.decode(value, { stream: true });
		let boundary = buffer.indexOf('\n\n');
		while (boundary !== -1) {
			const frame = buffer.slice(0, boundary);
			buffer = buffer.slice(boundary + 2);
			const line = frame.split('\n').find((entry) => entry.startsWith('data: '));
			if (line) {
				try {
					yield JSON.parse(line.slice('data: '.length)) as T;
				} catch {
					// drop malformed frame
				}
			}
			boundary = buffer.indexOf('\n\n');
		}
	}
}

export async function* sseFetch<T = unknown>(
	path: string,
	init: RequestInit,
	timeoutMs?: number
): AsyncGenerator<T> {
	const method = init.method?.toUpperCase() ?? 'GET';
	const controller = new AbortController();
	const timeout = setTimeout(() => controller.abort(), timeoutMs ?? API_TIMEOUT_MS);
	const opts = addCsrfToken(
		{
			credentials: 'include',
			...init,
			signal: abortOnCallerOrTimeout(init.signal, controller.signal),
			headers: {
				Accept: 'text/event-stream',
				...(init.headers as Record<string, string>)
			}
		},
		method
	);
	try {
		const resp = await orNetworkError(path, controller.signal, fetch(path, opts));
		await throwForFailedResponse(resp, path);
		if (resp.body) yield* parseSseEvents<T>(path, controller.signal, resp.body);
	} finally {
		clearTimeout(timeout);
	}
}

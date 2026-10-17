import type { JobItem } from './types';
import {
	API_ERROR_GENERIC_MESSAGE,
	RATE_LIMITED_STATUS,
	SERVER_ERROR_STATUS_FLOOR,
	SESSION_LOST_REDIRECT_PARAM
} from '$lib/constants';
import { HOME_ROUTE_PATH } from '$lib/routes/addresses';
import { UserFacingError } from './userFacingError';

const API_TIMEOUT_MS = 30_000;

interface RefusalReactions {
	/** A 429; whether the person hears of it is the reaction's to decide. */
	rateLimited: (path: string) => void;
}

const NO_REACTIONS: RefusalReactions = { rateLimited: () => undefined };
let installedReactions = NO_REACTIONS;

/**
 * The transport reports what the server answered; the app decides what a
 * refusal means to the person. Returns the uninstall, which puts back the set
 * that was installed before this one, so installs unwind in reverse order.
 */
export function installRefusalReactions(reactions: RefusalReactions): () => void {
	const previous = installedReactions;
	installedReactions = reactions;
	return () => {
		installedReactions = previous;
	};
}

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

/**
 * The one answer to "can asking again help?" for a server answer: a failing
 * server (5xx) and a rate limit (429) pass, so a retry can succeed. Any other
 * refusal is about the request itself and is refused the same way again.
 */
export function isTransientApiFailure(err: unknown): boolean {
	return (
		err instanceof ApiError &&
		(err.status >= SERVER_ERROR_STATUS_FLOOR || err.status === RATE_LIMITED_STATUS)
	);
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

// webauth sets the `__Host-` prefixed cookie when the static COOKIE_SECURE
// setting is true and falls back to the plain name otherwise
// (COOKIE_SECURE=false in e2e), so the reader checks the stronger name first
// and falls back to the plain one -- never both set with different values in
// practice, but `__Host-` wins if they ever are.
function getCsrfToken(): string {
	const hostPrefixed = /(?:^|;\s*)__Host-csrf_token=([^;]*)/.exec(document.cookie);
	if (hostPrefixed) return decodeURIComponent(hostPrefixed[1]);
	const plain = /(?:^|;\s*)csrf_token=([^;]*)/.exec(document.cookie);
	return plain ? decodeURIComponent(plain[1]) : '';
}

// A 401 from these refuses the credentials the person just typed -- a wrong
// password at sign-in, setup, or a password change (#1117) -- rather than
// saying the session is gone, so it never signs anyone out.
const AUTH_ENDPOINTS = new Set(['/api/auth/login', '/api/auth/setup', '/api/auth/password']);

function isSessionLostResponse(status: number, path: string): boolean {
	return status === 401 && !AUTH_ENDPOINTS.has(path);
}

const SAFE_INTERNAL_PATH_FALLBACK = HOME_ROUTE_PATH;
export const SIGN_IN_PATH = '/login';

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
const NON_PAGE_ROOTS = [SIGN_IN_PATH, '/api'];

// Judged decoded and lower-cased, so no spelling slips past: URL parsing keeps
// %-escapes and case, so /%6Cogin or /LOGIN would otherwise count as a page.
// A single-slash path is already known decodable.
function isPagePath(encodedPathname: string): boolean {
	const pathname = decodeURIComponent(encodedPathname).toLowerCase();
	return !NON_PAGE_ROOTS.some((root) => pathname === root || pathname.startsWith(`${root}/`));
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
	const [{ hasSessionToLose }, { reloadAfresh }] = await Promise.all([
		import('$lib/stores/auth'),
		import('$lib/history/historyController')
	]);
	if (!hasSessionToLose()) return;
	await reloadAfresh();
}

function abortOnCallerOrTimeout(
	callerSignal: AbortSignal | null | undefined,
	timeoutSignal: AbortSignal
): AbortSignal {
	return callerSignal ? AbortSignal.any([callerSignal, timeoutSignal]) : timeoutSignal;
}

export function addCsrfToken(init: RequestInit, method: string): RequestInit {
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
	if (response.status === RATE_LIMITED_STATUS) installedReactions.rateLimited(path);
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

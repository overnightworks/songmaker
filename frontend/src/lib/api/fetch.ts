import type { JobItem } from './types';
import {
	API_ERROR_GENERIC_MESSAGE,
	RATE_LIMITED_STATUS,
	SERVER_ERROR_STATUS_FLOOR,
	SIGN_IN_NEXT_PARAM
} from '#lib/constants.ts';
import { HOME_ROUTE_PATH } from '#lib/routes/addresses.ts';

const API_TIMEOUT_MS = 30_000;

// eslint-disable-next-line no-restricted-syntax -- transport internals
interface RefusalReactions {
	/**
	 * A 401 outside the sign-in forms and the public share reads; the request
	 * rejects only once this has settled.
	 */
	sessionLost: () => Promise<void>;
	/** A 429; whether the person hears of it is the reaction's to decide. */
	rateLimited: (path: string) => void;
}

const NO_REACTIONS: RefusalReactions = {
	sessionLost: () => Promise.resolve(),
	rateLimited: () => undefined
};
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
		public readonly responseDetail: unknown = detail,
		public readonly errorType: string | null = null,
		public readonly jobId: string | null = null
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
// eslint-disable-next-line no-restricted-syntax -- transport internals
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

// eslint-disable-next-line no-restricted-syntax -- transport internals
interface ErrorBody {
	detail: string;
	responseDetail: unknown;
	errorType: string | null;
	jobId: string | null;
}

const EMPTY_ERROR_BODY: ErrorBody = {
	detail: '',
	responseDetail: '',
	errorType: null,
	jobId: null
};

function stringField(body: object, key: string): string | null {
	const value: unknown = (body as Record<string, unknown>)[key];
	return typeof value === 'string' ? value : null;
}

async function readErrorBody(response: Pick<Response, 'json'>): Promise<ErrorBody> {
	try {
		const body: unknown = await response.json();
		if (typeof body !== 'object' || body === null || !('detail' in body)) {
			return EMPTY_ERROR_BODY;
		}
		const responseDetail = body.detail;
		return {
			detail: typeof responseDetail === 'string' ? responseDetail : '',
			responseDetail,
			errorType: stringField(body, 'error_type'),
			jobId: stringField(body, 'job_id')
		};
	} catch {
		return EMPTY_ERROR_BODY;
	}
}

export function isNotFound(err: unknown): boolean {
	return err instanceof ApiError && err.status === 404;
}

function parseRetryAfterSeconds(resp: Pick<Response, 'headers'>): number | null {
	const header = resp.headers?.get?.('Retry-After') ?? null;
	if (!header) return null;
	const seconds = Number(header);
	return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

// The public share reads (`/shared/*`, sharing_api.py) authenticate nobody, so
// a 401 there cannot mean that a session ended; the share player opts out the
// same way (`onAuthLost: null`).
export const PUBLIC_SHARE_PATH_PREFIX = '/shared/';

function isSessionLostResponse(status: number, path: string): boolean {
	return status === 401 && !path.startsWith(PUBLIC_SHARE_PATH_PREFIX);
}

const SAFE_INTERNAL_PATH_FALLBACK = HOME_ROUTE_PATH;
// The signed-out page: where a sign-out ends, never a redirect target.
export const SIGN_IN_PATH = '/login';
// The server route that starts the sign-in at the identity provider.
export const SIGN_IN_START_PATH = '/login/oidc';
// The pages of the sign-in itself; coming back to one would only loop.
export const NO_ACCESS_PATH = '/no-access';
export const SIGN_IN_FAILED_PATH = '/auth/callback';

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

// No page to land on: the sign-in pages would only ask again, and an API
// address would show its raw answer.
const NON_PAGE_ROOTS = [SIGN_IN_PATH, NO_ACCESS_PATH, SIGN_IN_FAILED_PATH, '/api'];

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

// The server's sign-in start, asked to bring the person back to `returnTo`
// afterwards.
export function signInAddress(returnTo: string): string {
	const target = safeInternalPath(returnTo);
	return `${SIGN_IN_START_PATH}?${SIGN_IN_NEXT_PARAM}=${encodeURIComponent(target)}`;
}

function abortOnCallerOrTimeout(
	callerSignal: AbortSignal | null | undefined,
	timeoutSignal: AbortSignal
): AbortSignal {
	return callerSignal ? AbortSignal.any([callerSignal, timeoutSignal]) : timeoutSignal;
}

async function throwForFailedResponse(response: Response, path: string): Promise<void> {
	if (response.ok) return;
	const { detail, responseDetail, errorType, jobId } = await readErrorBody(response);
	if (response.status === RATE_LIMITED_STATUS) installedReactions.rateLimited(path);
	if (isSessionLostResponse(response.status, path)) await installedReactions.sessionLost();
	throw new ApiError(
		response.status,
		detail,
		path,
		parseRetryAfterSeconds(response),
		responseDetail,
		errorType,
		jobId
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
	const controller = new AbortController();
	const timeout = setTimeout(() => controller.abort(), timeoutMs ?? API_TIMEOUT_MS);
	const opts: RequestInit = {
		credentials: 'include',
		...init,
		signal: abortOnCallerOrTimeout(init?.signal, controller.signal)
	};
	try {
		const resp = await orNetworkError(path, controller.signal, fetch(path, opts));
		await throwForFailedResponse(resp, path);
		return await orNetworkError(path, controller.signal, resp.json() as Promise<T>);
	} finally {
		clearTimeout(timeout);
	}
}

// The waveform read draws audio rather than sending a person's request. Its
// failure already shows as flat bars, so it must not trigger refusal reactions.
export async function fetchMediaBytes(url: string): Promise<ArrayBuffer> {
	const response = await fetch(url);
	if (!response.ok) throw new ApiError(response.status, '', url);
	return response.arrayBuffer();
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
	const controller = new AbortController();
	const timeout = setTimeout(() => controller.abort(), timeoutMs ?? API_TIMEOUT_MS);
	const opts: RequestInit = {
		credentials: 'include',
		...init,
		signal: abortOnCallerOrTimeout(init.signal, controller.signal),
		headers: {
			Accept: 'text/event-stream',
			...(init.headers as Record<string, string>)
		}
	};
	try {
		const resp = await orNetworkError(path, controller.signal, fetch(path, opts));
		await throwForFailedResponse(resp, path);
		if (resp.body) yield* parseSseEvents<T>(path, controller.signal, resp.body);
	} finally {
		clearTimeout(timeout);
	}
}

import { derived, get, readable, writable, type Readable } from 'svelte/store';

import { describeFailure, NetworkError } from '$lib/api/fetch';
import { UNREACHABLE_RELOAD_DELAYS_MS } from '$lib/constants';

/**
 * The one answer to "can this page reach the server right now" (#1039).
 * The browser's own network state says it first; the library's live stream
 * and, before any library runs, the session check add the case the browser
 * cannot see — online, but the server does not answer (#1118). A stream cut
 * while the page is hidden is no such evidence: a phone readily cuts a hidden
 * page's stream though audio still plays (#1200), so it counts only once the
 * page is visible again. Surfaces read `offline` and never decide on their own.
 */
const browserOnline = readable(true, (set) => {
	if (typeof window === 'undefined') return;
	const sync = (): void => set(navigator.onLine);
	sync();
	window.addEventListener('online', sync);
	window.addEventListener('offline', sync);
	return () => {
		window.removeEventListener('online', sync);
		window.removeEventListener('offline', sync);
	};
});

const pageVisible = readable(true, (set) => {
	if (typeof document === 'undefined') return;
	const sync = (): void => set(document.visibilityState === 'visible');
	sync();
	document.addEventListener('visibilitychange', sync);
	return () => document.removeEventListener('visibilitychange', sync);
});

type ResourceStream = 'reachable' | 'cut-while-visible' | 'cut-while-hidden';

const resourceStream = writable<ResourceStream>('reachable');

function streamAfterReport(current: ResourceStream, reachable: boolean): ResourceStream {
	if (reachable) return 'reachable';
	if (get(pageVisible)) return 'cut-while-visible';
	return current === 'reachable' ? 'cut-while-hidden' : current;
}

export function reportResourceStreamReachable(reachable: boolean): void {
	resourceStream.update((current) => streamAfterReport(current, reachable));
}

const resourceStreamReachable = derived(
	[resourceStream, pageVisible],
	([stream, visible]) => stream === 'reachable' || (stream === 'cut-while-hidden' && !visible)
);

const sessionCheckReachable = writable(true);

export function reportSessionCheckReachable(reachable: boolean): void {
	sessionCheckReachable.set(reachable);
}

export const offline: Readable<boolean> = derived(
	[browserOnline, resourceStreamReachable, sessionCheckReachable],
	([online, streamReachable, sessionReachable]) => !online || !streamReachable || !sessionReachable
);

/**
 * Calls `callback` each time the connection comes back after it was lost, so
 * a surface that hid what it could not load reads it again without a tap.
 * Returns the function that stops listening.
 */
export function whenBackOnline(callback: () => void): () => void {
	let wasOffline = get(offline);
	return offline.subscribe((isOffline) => {
		if (wasOffline && !isOffline) callback();
		wasOffline = isOffline;
	});
}

/**
 * What happens to a load the network swallowed (#1107):
 * - `on-reconnect`: the offline strip says it; the load runs again once the
 *   connection is back.
 * - `scheduled`: no strip says it (a timeout, a refused connection), so the
 *   load runs again on a bounded backoff.
 * - `exhausted`: that backoff is spent; the surface names the failure and
 *   offers its Retry. Should the connection drop and come back, the load
 *   still runs again by itself.
 */
type UnreachableReload = 'on-reconnect' | 'scheduled' | 'exhausted';

interface UnreachableReloads {
	afterNetworkFailure(): UnreachableReload;
	/**
	 * A lost network schedules the reload and says which; any other failure
	 * stops the reloads and answers null.
	 */
	afterLoadFailure(err: unknown): UnreachableReload | null;
	/**
	 * Records a failed load for `loadFailure` and returns the words it shows
	 * right now: a lost network stays unnamed while the strip says it or a
	 * reload is coming, and is named `fallback` once the backoff is spent;
	 * any other failure stops the reloads and shows the server's reason,
	 * else `fallback`.
	 */
	nameLoadFailure(err: unknown, fallback: string): string | null;
	/**
	 * The words the last named failure shows, or null while it needs none.
	 * A spent backoff hides again while the strip says the connection is
	 * lost; the failure is forgotten once the load runs again or stops.
	 */
	readonly loadFailure: Readable<string | null>;
	/** The load answered, or the surface moved on: forget the reloads. */
	stop(): void;
}

interface NamedLoadFailure {
	words: string;
	networkLost: boolean;
}

function shownLoadFailure(named: NamedLoadFailure | null, isOffline: boolean): string | null {
	if (named === null || (named.networkLost && isOffline)) return null;
	return named.words;
}

export function reloadWhileUnreachable(reload: () => void): UnreachableReloads {
	let reloadsSpent = 0;
	let cancelPending: (() => void) | null = null;
	const namedFailure = writable<NamedLoadFailure | null>(null);

	function stopPending(): void {
		cancelPending?.();
		cancelPending = null;
	}

	function runPending(): void {
		stopPending();
		namedFailure.set(null);
		reload();
	}

	function afterNetworkFailure(): UnreachableReload {
		stopPending();
		if (get(offline)) {
			reloadsSpent = 0;
			cancelPending = whenBackOnline(runPending);
			return 'on-reconnect';
		}
		const delay = UNREACHABLE_RELOAD_DELAYS_MS[reloadsSpent];
		if (delay === undefined) {
			reloadsSpent = 0;
			cancelPending = whenBackOnline(runPending);
			return 'exhausted';
		}
		reloadsSpent += 1;
		const timer = setTimeout(runPending, delay);
		cancelPending = () => clearTimeout(timer);
		return 'scheduled';
	}

	function stop(): void {
		stopPending();
		reloadsSpent = 0;
		namedFailure.set(null);
	}

	function afterLoadFailure(err: unknown): UnreachableReload | null {
		if (err instanceof NetworkError) return afterNetworkFailure();
		stop();
		return null;
	}

	return {
		afterNetworkFailure,
		afterLoadFailure,
		nameLoadFailure(err, fallback) {
			const named = failureToName(afterLoadFailure(err), err, fallback);
			namedFailure.set(named);
			return shownLoadFailure(named, get(offline));
		},
		loadFailure: derived([namedFailure, offline], ([named, isOffline]) =>
			shownLoadFailure(named, isOffline)
		),
		stop
	};
}

function failureToName(
	reload: UnreachableReload | null,
	err: unknown,
	fallback: string
): NamedLoadFailure | null {
	if (reload === null) return { words: describeFailure(err, fallback), networkLost: false };
	return reload === 'exhausted' ? { words: fallback, networkLost: true } : null;
}

export function resetConnectivityForTests(): void {
	resourceStream.set('reachable');
	sessionCheckReachable.set(true);
}

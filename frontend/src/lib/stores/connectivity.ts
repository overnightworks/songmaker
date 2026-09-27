import { derived, get, readable, writable, type Readable } from 'svelte/store';

import { describeFailure, NetworkError } from '$lib/api/fetch';
import { UNREACHABLE_RELOAD_DELAYS_MS } from '$lib/constants';

/**
 * The one answer to "can this page reach the server right now" (#1039).
 * The browser's own network state says it first; the library's live stream
 * adds the case the browser cannot see — online, but the server does not
 * answer when the stream tries to reopen. Surfaces read `offline` and never
 * decide on their own.
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

const resourceStreamReachable = writable(true);

export function reportResourceStreamReachable(reachable: boolean): void {
	resourceStreamReachable.set(reachable);
}

export const offline: Readable<boolean> = derived(
	[browserOnline, resourceStreamReachable],
	([online, reachable]) => !online || !reachable
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
	 * The words a failed load shows, or null while it needs none: a lost
	 * network stays unnamed while the strip says it or a reload is coming,
	 * and is named `fallback` once the backoff is spent; any other failure
	 * stops the reloads and shows the server's reason, else `fallback`.
	 */
	nameLoadFailure(err: unknown, fallback: string): string | null;
	/** The load answered, or the surface moved on: forget the reloads. */
	stop(): void;
}

export function reloadWhileUnreachable(reload: () => void): UnreachableReloads {
	let reloadsSpent = 0;
	let cancelPending: (() => void) | null = null;

	function stopPending(): void {
		cancelPending?.();
		cancelPending = null;
	}

	function runPending(): void {
		stopPending();
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
	}

	return {
		afterNetworkFailure,
		nameLoadFailure(err, fallback) {
			if (err instanceof NetworkError) {
				return afterNetworkFailure() === 'exhausted' ? fallback : null;
			}
			stop();
			return describeFailure(err, fallback);
		},
		stop
	};
}

export function resetConnectivityForTests(): void {
	resourceStreamReachable.set(true);
}

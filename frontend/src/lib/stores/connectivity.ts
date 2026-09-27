import { derived, get, readable, writable, type Readable } from 'svelte/store';

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

export function resetConnectivityForTests(): void {
	resourceStreamReachable.set(true);
}

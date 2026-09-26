import {
	SSE_RECONNECT_BACKOFF_FACTOR,
	SSE_RECONNECT_BASE_DELAY_MS,
	SSE_RECONNECT_JITTER_RATIO,
	SSE_RECONNECT_MAX_DELAY_MS
} from '$lib/constants';

/**
 * How long to wait before the `attempt`th reconnect of a dropped SSE
 * connection (1-indexed: the delay before the first retry is `attempt=1`).
 *
 * Shared by `jobs.ts` (one EventSource per job) and `resourceSync.ts` (the
 * library live-sync stream) so both back off the same way instead of each
 * inventing its own pacing — see the budget math on the constants in
 * `lib/constants.ts`.
 */
export function nextReconnectDelayMs(attempt: number): number {
	const exponential = SSE_RECONNECT_BASE_DELAY_MS * SSE_RECONNECT_BACKOFF_FACTOR ** (attempt - 1);
	const capped = Math.min(exponential, SSE_RECONNECT_MAX_DELAY_MS);
	const jitter = capped * SSE_RECONNECT_JITTER_RATIO * Math.random(); // NOSONAR S2245: reconnect pacing has no security context.
	return Math.round(capped + jitter);
}

/**
 * Calls `reconnectNow` whenever the page has a fresh chance to reach the
 * server: the tab or phone screen becomes visible again, the window regains
 * focus, or the browser reports the network back. A stream that dropped
 * while the phone was away then reopens at once instead of sitting out the
 * rest of its backoff (#1032). Returns the function that stops watching.
 */
export function watchReconnectOpportunities(reconnectNow: () => void): () => void {
	if (typeof window === 'undefined') return () => {};
	const reconnectWhenVisible = (): void => {
		if (document.visibilityState === 'visible') reconnectNow();
	};
	window.addEventListener('focus', reconnectNow);
	window.addEventListener('online', reconnectNow);
	document.addEventListener('visibilitychange', reconnectWhenVisible);
	return () => {
		window.removeEventListener('focus', reconnectNow);
		window.removeEventListener('online', reconnectNow);
		document.removeEventListener('visibilitychange', reconnectWhenVisible);
	};
}

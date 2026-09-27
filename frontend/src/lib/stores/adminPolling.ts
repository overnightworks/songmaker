import { writable, type Readable } from 'svelte/store';
import { whenBackOnline } from './connectivity';

const DEFAULT_MAX_ERRORS = 5;

interface PollingStore<T> {
	data: Readable<T | null>;
	error: Readable<Error | null>;
	loading: Readable<boolean>;
	refresh: () => Promise<void>;
	start: () => void;
	stop: () => void;
}

interface PollingOptions {
	isHidden?: () => boolean;
	maxErrors?: number;
}

export function createPollingStore<T>(
	fetcher: () => Promise<T>,
	intervalMs: number,
	options: PollingOptions = {}
): PollingStore<T> {
	const isHidden = options.isHidden ?? (() => typeof document !== 'undefined' && document.hidden);
	const maxErrors = options.maxErrors ?? DEFAULT_MAX_ERRORS;

	const data = writable<T | null>(null);
	const error = writable<Error | null>(null);
	const loading = writable<boolean>(false);

	let consecutiveErrors = 0;
	let intervalId: ReturnType<typeof setInterval> | null = null;
	let visibilityListener: (() => void) | null = null;
	let stopListeningForReconnect: (() => void) | null = null;
	let active = false;

	async function tick(): Promise<void> {
		if (isHidden()) return;
		loading.set(true);
		try {
			const result = await fetcher();
			data.set(result);
			error.set(null);
			consecutiveErrors = 0;
		} catch (e) {
			consecutiveErrors++;
			error.set(e instanceof Error ? e : new Error(String(e)));
			if (consecutiveErrors >= maxErrors) {
				halt();
			}
		} finally {
			loading.set(false);
		}
	}

	// The connection coming back reads at once, and resumes a polling its
	// failures halted: a lost network is no reason to stay stale (#1107).
	function start(): void {
		stopListeningForReconnect ??= whenBackOnline(readAgain);
		if (active) return;
		active = true;
		consecutiveErrors = 0;
		void tick();
		intervalId = setInterval(() => {
			void tick();
		}, intervalMs);
		if (typeof document !== 'undefined') {
			visibilityListener = () => {
				if (!document.hidden) void tick();
			};
			document.addEventListener('visibilitychange', visibilityListener);
		}
	}

	function readAgain(): void {
		if (active) void tick();
		else start();
	}

	function stop(): void {
		stopListeningForReconnect?.();
		stopListeningForReconnect = null;
		halt();
	}

	function halt(): void {
		if (!active) return;
		active = false;
		if (intervalId !== null) {
			clearInterval(intervalId);
			intervalId = null;
		}
		if (visibilityListener !== null && typeof document !== 'undefined') {
			document.removeEventListener('visibilitychange', visibilityListener);
			visibilityListener = null;
		}
	}

	return {
		data: { subscribe: data.subscribe },
		error: { subscribe: error.subscribe },
		loading: { subscribe: loading.subscribe },
		refresh: tick,
		start,
		stop
	};
}

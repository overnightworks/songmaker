import { writable, type Readable } from 'svelte/store';

const DEFAULT_MAX_ERRORS = 5;

export interface PollingStore<T> {
	data: Readable<T | null>;
	error: Readable<Error | null>;
	loading: Readable<boolean>;
	refresh: () => Promise<void>;
	start: () => void;
	stop: () => void;
}

export interface PollingOptions {
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
				stop();
			}
		} finally {
			loading.set(false);
		}
	}

	function start(): void {
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

	function stop(): void {
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

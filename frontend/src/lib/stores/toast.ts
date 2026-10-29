import { get, writable, type Readable } from 'svelte/store';

import { NetworkError } from '#lib/api/fetch.ts';
import { offline, whenBackOnline } from '#lib/stores/connectivity.ts';

const TOAST_DURATION_MS = 5000;

/** How long Undo stays offered: a few seconds for a light change, a longer grace for a deletion. */
type UndoToastLength = 'brief' | 'long';

const UNDO_TOAST_DURATION_MS: Record<UndoToastLength, number> = {
	brief: TOAST_DURATION_MS,
	long: 30000
};

type ToastType = 'error' | 'success' | 'info';

interface ToastAction {
	label: string;
	handler: () => void | Promise<void>;
}

/**
 * An undo that can stop holding before its toast times out -- once it would
 * restore nothing, its toast closes, so a shown Undo always restores. While
 * its raiser sets it aside, the toast leaves the screen and its time stands
 * still, so it comes back with the time it had left. A raiser learns through
 * `expire` that its toast's time is up, so the offer ends with it.
 */
interface UndoAction extends ToastAction {
	holds?: Readable<boolean>;
	setAside?: Readable<boolean>;
	expire?: () => void;
}

interface Toast {
	id: number;
	message: string;
	type: ToastType;
	action?: ToastAction;
}

let nextId = 0;

const endUndoToast = new Map<number, () => void>();

/** A countdown that stands still while paused, so it resumes with the time it had left. */
interface Countdown {
	pause: () => void;
	resume: () => void;
	cancel: () => void;
}

function startCountdown(durationMs: number, onDone: () => void): Countdown {
	let remainingMs = durationMs;
	let startedAt = Date.now();
	let timer: ReturnType<typeof setTimeout> | null = setTimeout(onDone, remainingMs);
	const stop = () => {
		if (timer !== null) clearTimeout(timer);
		timer = null;
	};
	return {
		pause: () => {
			if (timer === null) return;
			stop();
			remainingMs -= Date.now() - startedAt;
		},
		resume: () => {
			if (timer !== null) return;
			startedAt = Date.now();
			timer = setTimeout(onDone, remainingMs);
		},
		cancel: stop
	};
}

export const toasts = writable<Toast[]>([]);

// Unmigrated callers retain offline-time clearing until they pass a cause.
const failuresToClearOnReturn = new Set<number>();
let stopWaitingForReturn: (() => void) | null = null;

function clearOnReturn(id: number): void {
	failuresToClearOnReturn.add(id);
	stopWaitingForReturn ??= whenBackOnline(clearFailuresOnReturn);
}

function clearFailuresOnReturn(): void {
	toasts.update((t) => t.filter((toast) => !failuresToClearOnReturn.has(toast.id)));
	failuresToClearOnReturn.clear();
	stopWaitingForReturn?.();
	stopWaitingForReturn = null;
}

/** Answers the toast's id, so its raiser can dismiss it once it no longer holds. */
export function addToast(
	message: string,
	type: ToastType = 'info',
	...cause: [] | [unknown]
): number {
	const id = nextId++;
	toasts.update((t) => [...t, { id, message, type }]);
	if (type === 'error') {
		if (cause.length === 0 ? get(offline) : cause[0] instanceof NetworkError) clearOnReturn(id);
		return id;
	}
	setTimeout(() => {
		toasts.update((t) => t.filter((toast) => toast.id !== id));
	}, TOAST_DURATION_MS);
	return id;
}

export function addUndoToast(
	message: string,
	action: UndoAction,
	length: UndoToastLength = 'long'
): void {
	const id = nextId++;
	const toast: Toast = {
		id,
		message,
		type: 'info',
		action: {
			label: action.label,
			handler: async () => {
				dismissToast(id);
				await action.handler();
			}
		}
	};
	const countdown = startCountdown(UNDO_TOAST_DURATION_MS[length], () => {
		dismissToast(id);
		action.expire?.();
	});
	const endings: Array<() => void> = [countdown.cancel];
	endUndoToast.set(id, () => endings.forEach((end) => end()));
	toasts.update((t) => [...t, toast]);
	if (action.setAside) {
		endings.push(
			action.setAside.subscribe((setAside) => {
				if (setAside) {
					countdown.pause();
					toasts.update((t) => t.filter((shown) => shown.id !== id));
				} else {
					toasts.update((t) => (t.some((shown) => shown.id === id) ? t : [...t, toast]));
					countdown.resume();
				}
			})
		);
	}
	if (action.holds) {
		endings.push(
			action.holds.subscribe((holds) => {
				if (!holds) dismissToast(id);
			})
		);
	}
}

export function dismissToast(id: number): void {
	failuresToClearOnReturn.delete(id);
	if (failuresToClearOnReturn.size === 0) {
		stopWaitingForReturn?.();
		stopWaitingForReturn = null;
	}
	endUndoToast.get(id)?.();
	endUndoToast.delete(id);
	toasts.update((t) => t.filter((toast) => toast.id !== id));
}

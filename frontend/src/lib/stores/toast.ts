import { get, writable } from 'svelte/store';

import { offline, whenBackOnline } from '$lib/stores/connectivity';

const TOAST_DURATION_MS = 5000;

/** How long Undo stays offered: a few seconds for a light change, a longer grace for a deletion. */
export type UndoToastLength = 'brief' | 'long';

const UNDO_TOAST_DURATION_MS: Record<UndoToastLength, number> = {
	brief: TOAST_DURATION_MS,
	long: 30000
};

type ToastType = 'error' | 'success' | 'info';

interface ToastAction {
	label: string;
	handler: () => void | Promise<void>;
}

interface Toast {
	id: number;
	message: string;
	type: ToastType;
	action?: ToastAction;
}

let nextId = 0;

export const toasts = writable<Toast[]>([]);

/**
 * Failures raised while the page could not reach the server name the lost
 * connection, which the offline strip already says; they go by themselves
 * once it is back, so the page is calm again without a tap (#1141).
 */
const failuresRaisedOffline = new Set<number>();
let stopWaitingForReturn: (() => void) | null = null;

function clearOnReturn(id: number): void {
	failuresRaisedOffline.add(id);
	stopWaitingForReturn ??= whenBackOnline(clearFailuresRaisedOffline);
}

function clearFailuresRaisedOffline(): void {
	toasts.update((t) => t.filter((toast) => !failuresRaisedOffline.has(toast.id)));
	failuresRaisedOffline.clear();
	stopWaitingForReturn?.();
	stopWaitingForReturn = null;
}

/** Answers the toast's id, so its raiser can dismiss it once it no longer holds. */
export function addToast(message: string, type: ToastType = 'info'): number {
	const id = nextId++;
	toasts.update((t) => [...t, { id, message, type }]);
	if (type === 'error') {
		if (get(offline)) clearOnReturn(id);
		return id;
	}
	setTimeout(() => {
		toasts.update((t) => t.filter((toast) => toast.id !== id));
	}, TOAST_DURATION_MS);
	return id;
}

export function addUndoToast(
	message: string,
	action: ToastAction,
	length: UndoToastLength = 'long'
): void {
	const id = nextId++;
	const wrapped: ToastAction = {
		label: action.label,
		handler: async () => {
			dismissToast(id);
			await action.handler();
		}
	};
	toasts.update((t) => [...t, { id, message, type: 'info', action: wrapped }]);
	setTimeout(() => {
		toasts.update((t) => t.filter((toast) => toast.id !== id));
	}, UNDO_TOAST_DURATION_MS[length]);
}

export function dismissToast(id: number): void {
	toasts.update((t) => t.filter((toast) => toast.id !== id));
}

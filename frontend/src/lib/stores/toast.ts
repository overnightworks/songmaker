import { writable } from 'svelte/store';

const TOAST_DURATION_MS = 5000;
const UNDO_TOAST_DURATION_MS = 30000;

export type ToastType = 'error' | 'success' | 'info';

export interface ToastAction {
	label: string;
	handler: () => void | Promise<void>;
}

export interface Toast {
	id: number;
	message: string;
	type: ToastType;
	action?: ToastAction;
}

let nextId = 0;

export const toasts = writable<Toast[]>([]);

export function addToast(message: string, type: ToastType = 'info'): void {
	const id = nextId++;
	toasts.update((t) => [...t, { id, message, type }]);
	setTimeout(() => {
		toasts.update((t) => t.filter((toast) => toast.id !== id));
	}, TOAST_DURATION_MS);
}

export function addUndoToast(message: string, action: ToastAction): void {
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
	}, UNDO_TOAST_DURATION_MS);
}

export function dismissToast(id: number): void {
	toasts.update((t) => t.filter((toast) => toast.id !== id));
}

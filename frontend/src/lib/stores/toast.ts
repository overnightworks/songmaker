import { writable } from 'svelte/store';

const TOAST_DURATION_MS = 5000;

export type ToastType = 'error' | 'success' | 'info';

export interface Toast {
	id: number;
	message: string;
	type: ToastType;
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

export function dismissToast(id: number): void {
	toasts.update((t) => t.filter((toast) => toast.id !== id));
}

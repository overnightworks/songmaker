import { writable } from 'svelte/store';

export type QueuePlaybackMode = 'classic' | 'stream';

const STORAGE_KEY = 'queuePlaybackMode';
const VALID_MODES: ReadonlySet<string> = new Set<QueuePlaybackMode>(['classic', 'stream']);

function getInitialMode(): QueuePlaybackMode {
	if (typeof window === 'undefined') return 'classic';
	const stored = localStorage.getItem(STORAGE_KEY);
	if (stored && VALID_MODES.has(stored)) return stored as QueuePlaybackMode;
	localStorage.setItem(STORAGE_KEY, 'classic');
	return 'classic';
}

export const queuePlaybackMode = writable<QueuePlaybackMode>(getInitialMode());

export function setQueuePlaybackMode(mode: QueuePlaybackMode): void {
	queuePlaybackMode.set(mode);
	if (typeof window !== 'undefined') localStorage.setItem(STORAGE_KEY, mode);
}

export function shouldUseQueueStream(mode: QueuePlaybackMode): boolean {
	return mode === 'stream';
}

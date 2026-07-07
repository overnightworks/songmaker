import { writable } from 'svelte/store';

export type QueuePlaybackMode = 'classic' | 'stream';

const STORAGE_KEY = 'queuePlaybackMode';
// Set only when the user picks a mode in Settings. Earlier builds eagerly
// wrote 'classic' on first visit, so a bare stored value is a default
// artifact, not a choice — without this flag it must not survive migration.
const CHOICE_KEY = 'queuePlaybackModeChosen';
const VALID_MODES: ReadonlySet<string> = new Set<QueuePlaybackMode>(['classic', 'stream']);

function getInitialMode(): QueuePlaybackMode {
	if (typeof window === 'undefined') return 'stream';
	const stored = localStorage.getItem(STORAGE_KEY);
	const chosen = localStorage.getItem(CHOICE_KEY) === 'true';
	if (stored && VALID_MODES.has(stored) && chosen) return stored as QueuePlaybackMode;
	localStorage.setItem(STORAGE_KEY, 'stream');
	return 'stream';
}

export const queuePlaybackMode = writable<QueuePlaybackMode>(getInitialMode());

export function setQueuePlaybackMode(mode: QueuePlaybackMode): void {
	queuePlaybackMode.set(mode);
	if (typeof window !== 'undefined') {
		localStorage.setItem(STORAGE_KEY, mode);
		localStorage.setItem(CHOICE_KEY, 'true');
	}
}

export function shouldUseQueueStream(mode: QueuePlaybackMode): boolean {
	return mode === 'stream';
}

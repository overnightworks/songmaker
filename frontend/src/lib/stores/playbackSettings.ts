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

// The pool trio is one inclusivity scale, Picks -> + Keeps -> All takes.
// "Keeps-only" is dropped from the UI; the backend pool value `mix` (Pick
// union Keep) stays and now means "+ Keeps" here.
export const LIBRARY_TAKE_POOLS = ['picks', 'mix', 'all'] as const;
export type LibraryTakePool = (typeof LIBRARY_TAKE_POOLS)[number];
export const DEFAULT_LIBRARY_TAKE_POOL: LibraryTakePool = 'picks';

export const LIBRARY_TAKE_POOL_LABELS: Record<LibraryTakePool, string> = {
	picks: 'Picks',
	mix: '+ Keeps',
	all: 'All takes'
};

const POOL_STORAGE_KEY = 'libraryTakePool';
const VALID_POOLS: ReadonlySet<string> = new Set<string>(LIBRARY_TAKE_POOLS);
// A pool value from before the trio migration: 'keeps' (keeps-only) is no
// longer offered, and its closest surviving meaning is 'mix' (+ Keeps).
const LEGACY_POOL_MIGRATIONS: Readonly<Record<string, LibraryTakePool>> = { keeps: 'mix' };

function readStoredPool(): LibraryTakePool {
	if (typeof window === 'undefined') return DEFAULT_LIBRARY_TAKE_POOL;
	const stored = localStorage.getItem(POOL_STORAGE_KEY);
	if (stored && VALID_POOLS.has(stored)) return stored as LibraryTakePool;
	const migrated = stored ? LEGACY_POOL_MIGRATIONS[stored] : undefined;
	if (migrated) {
		localStorage.setItem(POOL_STORAGE_KEY, migrated);
		return migrated;
	}
	return DEFAULT_LIBRARY_TAKE_POOL;
}

export const libraryTakePool = writable<LibraryTakePool>(readStoredPool());

export function setLibraryTakePool(pool: LibraryTakePool): void {
	libraryTakePool.set(pool);
	if (typeof window !== 'undefined') {
		localStorage.setItem(POOL_STORAGE_KEY, pool);
	}
}

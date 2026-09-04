import { writable } from 'svelte/store';
import { NOW_PLAYING_SURFACE_KINDS, type NowPlayingSurfaceKind } from '$lib/constants/now-playing';

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

// Docked panel or full screen is the listener's choice wherever a desktop-sized
// viewport has room for both, and it survives the session so the next open
// lands where they last were. A compact viewport offers only the full surface
// and never writes here.
export const DEFAULT_DESKTOP_NOW_PLAYING_SURFACE: NowPlayingSurfaceKind = 'docked';

const DESKTOP_SURFACE_STORAGE_KEY = 'nowPlayingDesktopSurface';
const VALID_DESKTOP_SURFACES: ReadonlySet<string> = new Set<string>(NOW_PLAYING_SURFACE_KINDS);

function readStoredDesktopSurface(): NowPlayingSurfaceKind {
	if (typeof window === 'undefined') return DEFAULT_DESKTOP_NOW_PLAYING_SURFACE;
	const stored = localStorage.getItem(DESKTOP_SURFACE_STORAGE_KEY);
	if (stored && VALID_DESKTOP_SURFACES.has(stored)) return stored as NowPlayingSurfaceKind;
	return DEFAULT_DESKTOP_NOW_PLAYING_SURFACE;
}

export const desktopNowPlayingSurface = writable<NowPlayingSurfaceKind>(readStoredDesktopSurface());

export function setDesktopNowPlayingSurface(surface: NowPlayingSurfaceKind): void {
	desktopNowPlayingSurface.set(surface);
	if (typeof window !== 'undefined') {
		localStorage.setItem(DESKTOP_SURFACE_STORAGE_KEY, surface);
	}
}

// The compressed library row is one shared frame around an album and its
// songs. A missing value deliberately means "use this surface's default":
// desktop starts open, while the narrow song/take surface starts closed.
// Once a listener changes it, that choice follows the same per-browser
// localStorage path as the desktop Now Playing surface.
const LIBRARY_ROW_OPEN_STORAGE_KEY = 'libraryRowOpen';

function readStoredLibraryRowOpen(): boolean | null {
	if (typeof window === 'undefined') return null;
	const stored = localStorage.getItem(LIBRARY_ROW_OPEN_STORAGE_KEY);
	if (stored === 'true') return true;
	if (stored === 'false') return false;
	return null;
}

export const libraryRowOpenPreference = writable<boolean | null>(readStoredLibraryRowOpen());

export function setLibraryRowOpen(open: boolean): void {
	libraryRowOpenPreference.set(open);
	if (typeof window !== 'undefined') {
		localStorage.setItem(LIBRARY_ROW_OPEN_STORAGE_KEY, String(open));
	}
}

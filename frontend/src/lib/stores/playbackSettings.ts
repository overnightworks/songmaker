import { writable } from 'svelte/store';
import {
	NOW_PLAYING_SURFACE_KINDS,
	type NowPlayingSurfaceKind
} from '#lib/constants/now-playing.ts';
import type { TextKey } from '#lib/utils/page-words.ts';
import { readStorage, removeStorage, writeStorage } from '#lib/utils/storage.ts';

// The stream/classic queue choice is gone: a take row always starts a queue
// and a share plays its stream. Devices that stored the old choice still
// carry its keys, so they are cleared once when the app loads.
const RETIRED_QUEUE_PLAYBACK_MODE_KEYS = ['queuePlaybackMode', 'queuePlaybackModeChosen'] as const;

function forgetRetiredQueuePlaybackMode(): void {
	if (typeof window === 'undefined') return;
	for (const key of RETIRED_QUEUE_PLAYBACK_MODE_KEYS) removeStorage(key);
}

forgetRetiredQueuePlaybackMode();

// The pool trio is one inclusivity scale, Picks -> + Keeps -> All takes.
// "Keeps-only" is dropped from the UI; the backend pool value `mix` (Pick
// union Keep) stays and now means "+ Keeps" here.
export const LIBRARY_TAKE_POOLS = ['picks', 'mix', 'all'] as const;
export type LibraryTakePool = (typeof LIBRARY_TAKE_POOLS)[number];
const DEFAULT_LIBRARY_TAKE_POOL: LibraryTakePool = 'picks';

export const LIBRARY_TAKE_POOL_LABELS = {
	picks: 'nowPlaying.poolPicks',
	mix: 'nowPlaying.poolKeeps',
	all: 'nowPlaying.poolAll'
} as const satisfies Record<LibraryTakePool, TextKey>;

const POOL_STORAGE_KEY = 'libraryTakePool';
const VALID_POOLS: ReadonlySet<string> = new Set<string>(LIBRARY_TAKE_POOLS);

function readStoredPool(): LibraryTakePool {
	if (typeof window === 'undefined') return DEFAULT_LIBRARY_TAKE_POOL;
	const stored = readStorage(POOL_STORAGE_KEY);
	if (stored && VALID_POOLS.has(stored)) return stored as LibraryTakePool;
	return DEFAULT_LIBRARY_TAKE_POOL;
}

export const libraryTakePool = writable<LibraryTakePool>(readStoredPool());

export function setLibraryTakePool(pool: LibraryTakePool): void {
	libraryTakePool.set(pool);
	if (typeof window !== 'undefined') {
		writeStorage(POOL_STORAGE_KEY, pool);
	}
}

// Docked panel or full screen is the listener's choice wherever a desktop-sized
// viewport has room for both, and it survives the session so the next open
// lands where they last were. A compact viewport offers only the full surface
// and never writes here.
const DEFAULT_DESKTOP_NOW_PLAYING_SURFACE: NowPlayingSurfaceKind = 'docked';

const DESKTOP_SURFACE_STORAGE_KEY = 'nowPlayingDesktopSurface';
const VALID_DESKTOP_SURFACES: ReadonlySet<string> = new Set<string>(NOW_PLAYING_SURFACE_KINDS);

function readStoredDesktopSurface(): NowPlayingSurfaceKind {
	if (typeof window === 'undefined') return DEFAULT_DESKTOP_NOW_PLAYING_SURFACE;
	const stored = readStorage(DESKTOP_SURFACE_STORAGE_KEY);
	if (stored && VALID_DESKTOP_SURFACES.has(stored)) return stored as NowPlayingSurfaceKind;
	return DEFAULT_DESKTOP_NOW_PLAYING_SURFACE;
}

export const desktopNowPlayingSurface = writable<NowPlayingSurfaceKind>(readStoredDesktopSurface());

export function setDesktopNowPlayingSurface(surface: NowPlayingSurfaceKind): void {
	desktopNowPlayingSurface.set(surface);
	if (typeof window !== 'undefined') {
		writeStorage(DESKTOP_SURFACE_STORAGE_KEY, surface);
	}
}

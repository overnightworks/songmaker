import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import {
	DEFAULT_DESKTOP_NOW_PLAYING_SURFACE,
	DEFAULT_LIBRARY_TAKE_POOL,
	LIBRARY_TAKE_POOL_LABELS,
	LIBRARY_TAKE_POOLS,
	setDesktopNowPlayingSurface,
	setLibraryTakePool
} from './playbackSettings';

const POOL_STORAGE_KEY = 'libraryTakePool';
const DESKTOP_SURFACE_STORAGE_KEY = 'nowPlayingDesktopSurface';

beforeEach(() => {
	localStorage.clear();
});

describe('library take pool trio', () => {
	it('orders the trio Picks -> + Keeps -> All takes', () => {
		expect(LIBRARY_TAKE_POOLS).toEqual(['picks', 'mix', 'all']);
	});

	it('labels mix as "+ Keeps"', () => {
		expect(LIBRARY_TAKE_POOL_LABELS.mix).toBe('+ Keeps');
		expect(LIBRARY_TAKE_POOL_LABELS.picks).toBe('Picks');
		expect(LIBRARY_TAKE_POOL_LABELS.all).toBe('All takes');
	});

	it('defaults to Picks', () => {
		expect(DEFAULT_LIBRARY_TAKE_POOL).toBe('picks');
	});

	it('reads a legacy stored "keeps" pool as "mix" and rewrites storage', async () => {
		localStorage.setItem(POOL_STORAGE_KEY, 'keeps');
		vi.resetModules();
		const fresh = await import('./playbackSettings');
		expect(get(fresh.libraryTakePool)).toBe('mix');
		expect(localStorage.getItem(POOL_STORAGE_KEY)).toBe('mix');
	});

	it('falls back to the default for an unrecognized stored value', async () => {
		localStorage.setItem(POOL_STORAGE_KEY, 'bogus');
		vi.resetModules();
		const fresh = await import('./playbackSettings');
		expect(get(fresh.libraryTakePool)).toBe('picks');
	});

	it('setLibraryTakePool persists the chosen pool', () => {
		setLibraryTakePool('all');
		expect(localStorage.getItem(POOL_STORAGE_KEY)).toBe('all');
	});
});

describe('remembered desktop Now Playing surface', () => {
	it('defaults to the docked panel', () => {
		expect(DEFAULT_DESKTOP_NOW_PLAYING_SURFACE).toBe('docked');
	});

	it('persists the chosen surface', () => {
		setDesktopNowPlayingSurface('full');
		expect(localStorage.getItem(DESKTOP_SURFACE_STORAGE_KEY)).toBe('full');
	});

	it('reads back a stored surface on the next visit', async () => {
		localStorage.setItem(DESKTOP_SURFACE_STORAGE_KEY, 'full');
		vi.resetModules();
		const fresh = await import('./playbackSettings');
		expect(get(fresh.desktopNowPlayingSurface)).toBe('full');
	});

	it('falls back to the default for an unrecognized stored value', async () => {
		localStorage.setItem(DESKTOP_SURFACE_STORAGE_KEY, 'bogus');
		vi.resetModules();
		const fresh = await import('./playbackSettings');
		expect(get(fresh.desktopNowPlayingSurface)).toBe('docked');
	});
});

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import {
	DEFAULT_LIBRARY_TAKE_POOL,
	LIBRARY_TAKE_POOL_LABELS,
	LIBRARY_TAKE_POOLS,
	setLibraryTakePool
} from './playbackSettings';

const POOL_STORAGE_KEY = 'libraryTakePool';

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

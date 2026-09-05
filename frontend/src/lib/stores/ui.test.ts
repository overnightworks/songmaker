import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

beforeEach(() => {
	localStorage.clear();
	vi.resetModules();
});

describe('railCollapsed', () => {
	it('starts expanded when this browser has no rail preference', async () => {
		const { railCollapsed } = await import('./ui');

		expect(get(railCollapsed)).toBe(false);
	});

	it('restores the browser preference after a reload', async () => {
		localStorage.setItem('songmaker.rail-collapsed', 'true');
		const { initRailCollapsed, railCollapsed } = await import('./ui');

		expect(get(railCollapsed)).toBe(true);
		railCollapsed.set(false);
		initRailCollapsed();
		expect(get(railCollapsed)).toBe(true);
	});

	it('persists each edge-control toggle', async () => {
		const { railCollapsed, toggleRailCollapsed, RAIL_COLLAPSED_STORAGE_KEY } = await import('./ui');

		toggleRailCollapsed();
		expect(get(railCollapsed)).toBe(true);
		expect(localStorage.getItem(RAIL_COLLAPSED_STORAGE_KEY)).toBe('true');

		toggleRailCollapsed();
		expect(get(railCollapsed)).toBe(false);
		expect(localStorage.getItem(RAIL_COLLAPSED_STORAGE_KEY)).toBe('false');
	});
});

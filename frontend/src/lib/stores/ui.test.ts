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

describe('railWidth', () => {
	it('starts at the default width when this browser has no rail preference', async () => {
		const { railWidth } = await import('./ui');

		expect(get(railWidth)).toBe(264);
	});

	it('clamps and persists width changes at the store boundary', async () => {
		const {
			railWidth,
			setRailWidth,
			RAIL_MAX_WIDTH_PX,
			RAIL_MIN_WIDTH_PX,
			RAIL_WIDTH_STORAGE_KEY
		} = await import('./ui');

		setRailWidth(RAIL_MAX_WIDTH_PX + 20);
		expect(get(railWidth)).toBe(RAIL_MAX_WIDTH_PX);
		expect(localStorage.getItem(RAIL_WIDTH_STORAGE_KEY)).toBe(String(RAIL_MAX_WIDTH_PX));

		setRailWidth(RAIL_MIN_WIDTH_PX - 20);
		expect(get(railWidth)).toBe(RAIL_MIN_WIDTH_PX);
		expect(localStorage.getItem(RAIL_WIDTH_STORAGE_KEY)).toBe(String(RAIL_MIN_WIDTH_PX));
	});

	it('restores a clamped browser preference after a reload', async () => {
		localStorage.setItem('songmaker.rail-width', '480');
		const { initRailWidth, railWidth } = await import('./ui');

		expect(get(railWidth)).toBe(360);
		railWidth.set(264);
		initRailWidth();
		expect(get(railWidth)).toBe(360);
	});
});

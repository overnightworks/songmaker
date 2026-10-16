import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { LibraryListenItem } from '$lib/api/library';
import { HOME_PAGE_LABEL, LIBRARY_NEW_MENU_LABEL } from '$lib/constants';

const fetchLibraryListen = vi.fn();

vi.mock('$lib/api/library', () => ({
	fetchLibraryListen: (...args: unknown[]) => fetchLibraryListen(...args)
}));
vi.mock('$lib/stores/navigation', () => ({
	openAlbum: vi.fn(),
	openPlaylist: vi.fn(),
	selectSong: vi.fn()
}));

import LibraryHome from './LibraryHome.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

const listened: LibraryListenItem = {
	type: 'album',
	id: 'album-1',
	title: 'Open Windows',
	cover: null,
	album_covers: [],
	song_id: null,
	song_title: null,
	song_number: null,
	played_at: '2026-09-27T03:47:00Z'
};

beforeEach(() => {
	fetchLibraryListen.mockReset().mockResolvedValue({ items: [listened] });
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(LibraryHome, { target }));
	await vi.waitFor(() => expect(target.querySelector('.continue-item')).not.toBeNull());
	await tick();
	return target;
}

describe('LibraryHome', () => {
	it('1354_rule_31: heads the page Home and shows Continue under it', async () => {
		const target = await render();

		expect(target.querySelector('h1')?.textContent).toBe(HOME_PAGE_LABEL);
		expect(target.querySelector('[aria-label="Continue"]')).not.toBeNull();
		expect(target.querySelector('.continue-item')?.getAttribute('aria-label')).toBe(
			'Open album Open Windows'
		);
	});

	it('1354_rule_31: shows no wall of albums and no + New', async () => {
		const target = await render();

		expect(target.querySelector('.tile-grid, .wall-tile, .library-wall')).toBeNull();
		expect(target.querySelector(`[aria-label="${LIBRARY_NEW_MENU_LABEL}"]`)).toBeNull();
	});
});

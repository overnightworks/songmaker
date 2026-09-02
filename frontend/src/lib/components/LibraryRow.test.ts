import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, PlaylistItem } from '$lib/api/types';
import { openCollection } from '$lib/stores/collection';
import { resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { albumList } from '$lib/stores/libraryData';
import { playlistList, playlistLoad, resetPlaylists } from '$lib/stores/playlists';

const fetchSongs = vi.fn();
const fetchPlaylists = vi.fn();
const fetchPlaylist = vi.fn();

vi.mock('$app/navigation', () => ({ goto: vi.fn().mockResolvedValue(undefined) }));
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('$lib/api/songs', () => ({
	fetchSong: vi.fn(),
	fetchSongs: (...args: unknown[]) => fetchSongs(...args)
}));
vi.mock('$lib/api/client', () => ({
	fetchPlaylists: (...args: unknown[]) => fetchPlaylists(...args),
	fetchPlaylist: (...args: unknown[]) => fetchPlaylist(...args)
}));

import LibraryRow from './LibraryRow.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

function album(overrides: Partial<AlbumItem> = {}): AlbumItem {
	return {
		id: 'a-1',
		title: 'Anfield',
		artist: 'Artist',
		subtitle: '',
		year: '',
		colors: {},
		song_count: 2,
		picked_count: 0,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		is_archived: false,
		...overrides
	};
}

function playlist(overrides: Partial<PlaylistItem> = {}): PlaylistItem {
	return {
		id: 'p-1',
		title: 'Sommer 2026',
		slug: 'sommer-2026',
		entry_count: 8,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function stubMomentumTiming() {
	// Only needs to keep the row's own requestAnimationFrame loop from ever
	// firing a real frame -- the catch-click test asserts on the click that
	// happens while the row still believes it is animating, never on the
	// momentum math itself, so the stub only has to exist, not tick.
	vi.stubGlobal(
		'requestAnimationFrame',
		vi.fn(() => 1)
	);
	vi.stubGlobal('cancelAnimationFrame', vi.fn());
	vi.stubGlobal('performance', { now: () => 0 });
}

function firePointer(
	target: EventTarget,
	type: 'pointerdown' | 'pointerup',
	pos: number,
	t: number
) {
	const event = new PointerEvent(type, {
		pointerId: 1,
		pointerType: 'mouse',
		button: 0,
		bubbles: true,
		cancelable: true,
		clientX: pos
	});
	Object.defineProperty(event, 'timeStamp', { value: t, configurable: true });
	target.dispatchEvent(event);
}

beforeEach(() => {
	fetchSongs
		.mockReset()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false });
	fetchPlaylists.mockReset().mockResolvedValue([]);
	fetchPlaylist.mockReset();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylists();
	albumList.set([
		album({ id: 'a-1', title: 'Anfield' }),
		album({ id: 'a-2', title: 'Sommerluft' })
	]);
	playlistList.set([playlist({ id: 'p-1' }), playlist({ id: 'p-2', title: 'Für Thomas' })]);
	playlistLoad.set({ status: 'ready', error: null });
	openCollection.set({ kind: 'album', id: 'a-1' });
	history.replaceState(null, '', '/');
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylists();
	vi.unstubAllGlobals();
});

async function render(collection: {
	kind: 'album' | 'playlist';
	id: string;
}): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(LibraryRow, { target, props: { collection } }));
	await tick();
	return target;
}

describe('LibraryRow', () => {
	it('renders one tile per sibling album and marks the open one', async () => {
		const root = await render({ kind: 'album', id: 'a-1' });
		const titles = Array.from(root.querySelectorAll('.row-tile-title')).map((el) => el.textContent);
		expect(titles).toEqual(['Anfield', 'Sommerluft']);
		const active = root.querySelector('.row-tile.active');
		expect(active?.getAttribute('data-tile-id')).toBe('a-1');
		expect(active?.getAttribute('aria-current')).toBe('true');
	});

	it('renders one tile per sibling playlist when a playlist is open', async () => {
		const root = await render({ kind: 'playlist', id: 'p-1' });
		const titles = Array.from(root.querySelectorAll('.row-tile-title')).map((el) => el.textContent);
		expect(titles).toEqual(['Sommer 2026', 'Für Thomas']);
	});

	it('opens a neighbour album directly on click', async () => {
		const root = await render({ kind: 'album', id: 'a-1' });
		const neighbour = root.querySelector<HTMLButtonElement>('[data-tile-id="a-2"]');
		neighbour?.click();
		await tick();
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a-2' });
	});

	it('does not open a tile when the click only catches a still-scrolling row', async () => {
		stubMomentumTiming();
		const root = await render({ kind: 'album', id: 'a-1' });
		const row = root.querySelector<HTMLElement>('.library-row');
		if (!row) throw new Error('Expected .library-row to be rendered');

		row.dispatchEvent(new WheelEvent('wheel', { deltaY: 300, bubbles: true, cancelable: true }));

		firePointer(row, 'pointerdown', 100, 1000);
		firePointer(row, 'pointerup', 100, 1000);

		const neighbour = root.querySelector<HTMLButtonElement>('[data-tile-id="a-2"]');
		neighbour?.click();
		await tick();

		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a-1' });
	});
});

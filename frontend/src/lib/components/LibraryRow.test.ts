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

// A user (or assistive tech) finds a tile by the name it shows, never by an
// internal hook -- data-tile-id exists only for kineticScroll's own click
// handler, the same way TakeStrip's data-generation-id does.
function findTileByTitle(root: ParentNode, title: string): HTMLButtonElement {
	const heading = Array.from(root.querySelectorAll<HTMLElement>('.tile-title')).find(
		(el) => el.textContent === title
	);
	const button = heading?.closest<HTMLButtonElement>('.row-tile');
	if (!button) throw new Error(`Expected a tile titled "${title}"`);
	return button;
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
	it('renders one tile per sibling album, naming the open one for assistive tech', async () => {
		const root = await render({ kind: 'album', id: 'a-1' });
		const titles = Array.from(root.querySelectorAll('.tile-title')).map((el) => el.textContent);
		expect(titles).toEqual(['Anfield', 'Sommerluft']);

		const openMarkers = root.querySelectorAll('[aria-current="true"]');
		expect(openMarkers).toHaveLength(1);
		expect(findTileByTitle(root, 'Anfield').getAttribute('aria-current')).toBe('true');
	});

	it('renders one tile per sibling playlist when a playlist is open', async () => {
		const root = await render({ kind: 'playlist', id: 'p-1' });
		const titles = Array.from(root.querySelectorAll('.tile-title')).map((el) => el.textContent);
		expect(titles).toEqual(['Sommer 2026', 'Für Thomas']);
	});

	it('shows an album the store adds after mount', async () => {
		const root = await render({ kind: 'album', id: 'a-1' });
		albumList.update((list) => [...list, album({ id: 'a-3', title: 'Vernissage' })]);
		await tick();
		const titles = Array.from(root.querySelectorAll('.tile-title')).map((el) => el.textContent);
		expect(titles).toContain('Vernissage');
	});

	it("does not drag the browser's own image ghost from a covered tile", async () => {
		albumList.set([
			album({
				id: 'a-1',
				title: 'Anfield',
				cover: { card: 'https://x/a.jpg', detail: 'https://x/a-full.jpg' }
			})
		]);
		const root = await render({ kind: 'album', id: 'a-1' });
		const img = findTileByTitle(root, 'Anfield').querySelector('img');
		expect(img?.getAttribute('draggable')).toBe('false');
	});

	it('opens a neighbour album directly on click, changing the address', async () => {
		const root = await render({ kind: 'album', id: 'a-1' });
		findTileByTitle(root, 'Sommerluft').click();

		await vi.waitFor(() => {
			expect(window.location.pathname).toBe('/album/a-2');
		});
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

		findTileByTitle(root, 'Sommerluft').click();
		await tick();

		expect(window.location.pathname).toBe('/');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a-1' });
	});

	it('shows no overflow scrim for a short list that already fits', async () => {
		const root = await render({ kind: 'album', id: 'a-1' });
		expect(root.querySelector('.library-row-scrim')?.classList.contains('has-overflow')).toBe(
			false
		);
	});

	it('shows the overflow scrim once the row genuinely has more to scroll to', async () => {
		const root = await render({ kind: 'album', id: 'a-1' });
		const row = root.querySelector<HTMLElement>('.library-row');
		if (!row) throw new Error('Expected .library-row to be rendered');
		Object.defineProperty(row, 'clientWidth', { value: 100, configurable: true });
		Object.defineProperty(row, 'scrollWidth', { value: 400, configurable: true });
		row.dispatchEvent(new Event('scroll'));
		await tick();

		expect(root.querySelector('.library-row-scrim')?.classList.contains('has-overflow')).toBe(true);
	});

	it('moves focus between tiles with the arrow keys', async () => {
		const root = await render({ kind: 'album', id: 'a-1' });
		const row = root.querySelector<HTMLElement>('.library-row');
		if (!row) throw new Error('Expected .library-row to be rendered');

		findTileByTitle(root, 'Anfield').focus();
		row.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));

		expect(document.activeElement).toBe(findTileByTitle(root, 'Sommerluft'));
	});

	it('centres the open tile, including right after mounting on a distant one', async () => {
		const scrollIntoView = vi.fn();
		HTMLElement.prototype.scrollIntoView = scrollIntoView;
		try {
			const many = Array.from({ length: 12 }, (_, i) =>
				album({ id: `a-${i}`, title: `Album ${i}` })
			);
			albumList.set(many);

			await render({ kind: 'album', id: 'a-9' });
			expect(scrollIntoView).toHaveBeenCalledWith(
				expect.objectContaining({ inline: 'center', block: 'nearest' })
			);

			scrollIntoView.mockClear();
			await render({ kind: 'album', id: 'a-1' });
			expect(scrollIntoView).toHaveBeenCalledWith(
				expect.objectContaining({ inline: 'center', block: 'nearest' })
			);
		} finally {
			// jsdom never had this method to begin with (see kineticScroll's own
			// guard) -- restoring "absent" keeps every other test's environment
			// exactly as it found it, not merely undoing this assignment.
			delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView;
		}
	});
});

import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, PlaylistItem } from '$lib/api/types';
import { openCollection } from '$lib/stores/collection';
import { resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { albumList, updateAlbumInList } from '$lib/stores/libraryData';
import { playlistList, playlistLoad, resetPlaylists } from '$lib/stores/playlists';
import { libraryRowOpenPreference } from '$lib/stores/playbackSettings';

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

import LibraryRowHarness from './LibraryRow.harness.svelte';
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

// A user (or assistive tech) finds a tile by its role and its visible name --
// the button carries no separate aria-label (that would silently drop the
// subtitle from the accessible name a screen reader announces), so the
// button's own accessible name is its rendered text, title included.
// data-tile-id exists only for kineticScroll's own click handler, the same
// way TakeStrip's data-generation-id does, and is never a lookup key here.
function findTileByName(root: ParentNode, name: string): HTMLButtonElement {
	const button = Array.from(root.querySelectorAll<HTMLButtonElement>('button')).find((el) =>
		(el.textContent ?? '').includes(name)
	);
	if (!button) throw new Error(`Expected a tile named "${name}"`);
	return button;
}

interface ScrollIntoViewCall {
	receiver: Element;
	options: ScrollIntoViewOptions;
	edgeInset: string | undefined;
}

// jsdom ships no scrollIntoView at all (confirmed against a fresh JSDOM
// instance -- kineticScroll's own guard exists for exactly this). A plain
// vi.fn() records that *a* call happened but not which element it was called
// on; recording `this` is what lets a test tell "the row centred some tile"
// apart from "the row centred the one that just became open".
function stubScrollIntoView(): ScrollIntoViewCall[] {
	const calls: ScrollIntoViewCall[] = [];
	HTMLElement.prototype.scrollIntoView = function (
		this: HTMLElement,
		options?: boolean | ScrollIntoViewOptions
	) {
		calls.push({
			receiver: this,
			options: (options ?? {}) as ScrollIntoViewOptions,
			edgeInset: this.parentElement?.style.getPropertyValue('--row-edge-inset')
		});
	};
	return calls;
}

function restoreScrollIntoView(): void {
	delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView;
}

function stubResizeObserver(): () => void {
	const callbacks: ResizeObserverCallback[] = [];
	vi.stubGlobal(
		'ResizeObserver',
		class {
			constructor(callback: ResizeObserverCallback) {
				callbacks.push(callback);
			}
			observe(): void {}
			disconnect(): void {}
		}
	);
	return () => {
		for (const callback of callbacks) callback([], {} as ResizeObserver);
	};
}

function setRowLayout(row: HTMLElement, tileCount: number, clientWidth: number): void {
	Object.defineProperty(row, 'clientWidth', { value: clientWidth, configurable: true });
	Array.from(row.querySelectorAll<HTMLElement>('.row-tile')).forEach((tile, index) => {
		Object.defineProperties(tile, {
			offsetLeft: { value: index * 92, configurable: true },
			offsetWidth: { value: 84, configurable: true }
		});
		tile.hidden = index >= tileCount;
	});
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
	libraryRowOpenPreference.set(null);
	localStorage.removeItem('libraryRowOpen');
	history.replaceState(null, '', '/');
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylists();
	libraryRowOpenPreference.set(null);
	localStorage.removeItem('libraryRowOpen');
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

async function render(collection: {
	kind: 'album' | 'playlist';
	id: string;
}): Promise<HTMLElement> {
	openCollection.set(collection);
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(LibraryRowHarness, { target }));
	await tick();
	return target;
}

function renderCollapsibleRow(compact: boolean): HTMLElement {
	vi.stubGlobal('matchMedia', () => ({
		matches: compact,
		addEventListener: vi.fn(),
		removeEventListener: vi.fn()
	}));
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(
		mount(LibraryRow, {
			target,
			props: { collection: { kind: 'album', id: 'a-1' }, collapsible: true }
		})
	);
	return target;
}

describe('LibraryRow', () => {
	it('keeps the same row owner collapsible on song and take surfaces', async () => {
		const root = renderCollapsibleRow(false);
		await tick();

		const header = root.querySelector('.library-row-bar');
		expect(header).not.toBeNull();
		expect(header?.textContent).toContain('Albums');
		expect(header?.textContent).toContain('Anfield · 2 songs');
		expect(header?.querySelector('[aria-label="Collapse albums"]')).not.toBeNull();
		expect(root.querySelector('.library-row-filter-input')).toBeNull();

		root.querySelector<HTMLButtonElement>('[aria-label="Collapse albums"]')?.click();
		await tick();

		expect(header?.textContent).toContain('Anfield · 2 songs');
		expect(header?.querySelector('[aria-label="Expand albums"]')).not.toBeNull();
		expect(root.querySelector('.library-row-filter-input')).toBeNull();
		expect(localStorage.getItem('libraryRowOpen')).toBe('false');
	});

	it('starts a mobile song or take row collapsed before its first settled frame', () => {
		const root = renderCollapsibleRow(true);

		const header = root.querySelector('.library-row-bar');
		expect(header?.textContent).toContain('Anfield · 2 songs');
		expect(header?.querySelector('[aria-label="Expand albums"]')).not.toBeNull();
		expect(root.querySelector('.library-row-filter-input')).toBeNull();
	});

	it('renders one tile per sibling album, marking the open one for assistive tech', async () => {
		const root = await render({ kind: 'album', id: 'a-1' });
		const titles = Array.from(root.querySelectorAll('.tile-title')).map((el) => el.textContent);
		expect(titles).toEqual(['Anfield', 'Sommerluft']);

		expect(root.querySelectorAll('[aria-current="true"]')).toHaveLength(1);
		expect(findTileByName(root, 'Anfield').getAttribute('aria-current')).toBe('true');
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
		expect(() => findTileByName(root, 'Vernissage')).not.toThrow();
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
		const img = findTileByName(root, 'Anfield').querySelector('img');
		expect(img?.getAttribute('draggable')).toBe('false');
	});

	it('opens a neighbour album directly on click, changing the address', async () => {
		const root = await render({ kind: 'album', id: 'a-1' });
		findTileByName(root, 'Sommerluft').click();

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

		findTileByName(root, 'Sommerluft').click();
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

	it('keeps a few tiles flush left instead of adding a leading centring inset', async () => {
		const resize = stubResizeObserver();
		albumList.set([
			album({ id: 'a-1', title: 'Anfield' }),
			album({ id: 'a-2', title: 'Sommerluft' }),
			album({ id: 'a-3', title: 'Vernissage' })
		]);
		const root = await render({ kind: 'album', id: 'a-1' });
		const row = root.querySelector<HTMLElement>('.library-row');
		if (!row) throw new Error('Expected .library-row to be rendered');
		setRowLayout(row, 3, 400);
		resize();

		expect(row.style.getPropertyValue('--row-edge-inset')).toBe('0px');
	});

	it('adds exactly the inset needed to centre edge tiles once the row overflows', async () => {
		const resize = stubResizeObserver();
		albumList.set(
			Array.from({ length: 12 }, (_, index) => album({ id: `a-${index}`, title: `Album ${index}` }))
		);
		const root = await render({ kind: 'album', id: 'a-6' });
		const row = root.querySelector<HTMLElement>('.library-row');
		if (!row) throw new Error('Expected .library-row to be rendered');
		setRowLayout(row, 12, 400);
		resize();

		expect(row.style.getPropertyValue('--row-edge-inset')).toBe('158px');
	});

	it('sets the overflow inset before centring an open middle tile', async () => {
		const calls = stubScrollIntoView();
		try {
			albumList.set(
				Array.from({ length: 12 }, (_, index) =>
					album({ id: `a-${index}`, title: `Album ${index}` })
				)
			);
			const root = await render({ kind: 'album', id: 'a-6' });
			const row = root.querySelector<HTMLElement>('.library-row');
			if (!row) throw new Error('Expected .library-row to be rendered');
			setRowLayout(row, 12, 400);
			calls.length = 0;

			// A newly visible tile makes the row reflow. The open tile must be
			// centred in the padded coordinate space, not before that space exists.
			albumList.update((albums) => [...albums, album({ id: 'a-12', title: 'Album 12' })]);
			await tick();

			expect(calls.at(-1)?.receiver).toBe(findTileByName(root, 'Album 6'));
			expect(calls.at(-1)?.edgeInset).toBe('158px');
		} finally {
			restoreScrollIntoView();
		}
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

		findTileByName(root, 'Anfield').focus();
		row.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));

		expect(document.activeElement).toBe(findTileByName(root, 'Sommerluft'));
	});

	it('centres whichever tile owns the open collection, on mount and again after switching within the same instance', async () => {
		const calls = stubScrollIntoView();
		try {
			// Letters, not numbers -- "Album 1" would also match "Album 10"/"Album
			// 11" under findTileByName's substring search, which is exactly the
			// ambiguity a real screen-reader user's visible name never has here
			// because every title actually is distinct.
			const many = Array.from({ length: 12 }, (_, i) =>
				album({ id: `a-${i}`, title: `Album ${String.fromCharCode(65 + i)}` })
			);
			albumList.set(many);

			const root = await render({ kind: 'album', id: 'a-9' });
			expect(calls.at(-1)?.receiver).toBe(findTileByName(root, 'Album J'));
			expect(calls.at(-1)?.options).toMatchObject({ inline: 'center', block: 'nearest' });

			calls.length = 0;
			openCollection.set({ kind: 'album', id: 'a-1' });
			await tick();

			expect(calls.at(-1)?.receiver).toBe(findTileByName(root, 'Album B'));
		} finally {
			restoreScrollIntoView();
		}
	});

	it("does not recentre when a sibling's metadata changes without the open id moving", async () => {
		const calls = stubScrollIntoView();
		try {
			const root = await render({ kind: 'album', id: 'a-1' });
			expect(calls.length).toBeGreaterThan(0);
			calls.length = 0;

			// a-1 stays open and stays first in creation order; only a-2's own
			// title changes, so the active tile's position never moves.
			updateAlbumInList('a-2', (a) => ({ ...a, title: 'Renamed while open' }));
			await tick();

			expect(calls).toHaveLength(0);
			expect(findTileByName(root, 'Renamed while open')).toBeDefined();
		} finally {
			restoreScrollIntoView();
		}
	});
});

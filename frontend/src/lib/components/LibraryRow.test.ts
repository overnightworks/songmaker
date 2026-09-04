import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, PlaylistItem } from '$lib/api/types';
import { openCollection } from '$lib/stores/collection';
import { resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { albumList, updateAlbumInList } from '$lib/stores/libraryData';
import { playlistList, playlistLoad, resetPlaylists } from '$lib/stores/playlists';
import { LIBRARY_ROW_FILTER_EMPTY } from '$lib/constants';
import { searchQuery } from '$lib/stores/filter';
import { libraryRowOpenPreference } from '$lib/stores/playbackSettings';
import libraryRowSource from './LibraryRow.svelte?raw';

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
		calls.push({ receiver: this, options: (options ?? {}) as ScrollIntoViewOptions });
	};
	return calls;
}

function restoreScrollIntoView(): void {
	delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView;
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

		expect(root.querySelector('[aria-label="Collapse albums"]')).not.toBeNull();
		expect(root.querySelector('.library-row-filter-input')).not.toBeNull();

		root.querySelector<HTMLButtonElement>('[aria-label="Collapse albums"]')?.click();
		await tick();

		expect(root.querySelector('[aria-label="Expand albums"]')).not.toBeNull();
		expect(root.querySelector('.library-row-filter-input')).toBeNull();
		expect(root.textContent).toContain('Anfield · 2 songs');
		expect(localStorage.getItem('libraryRowOpen')).toBe('false');
	});

	it('starts a mobile song or take row collapsed before its first settled frame', () => {
		const root = renderCollapsibleRow(true);

		expect(root.querySelector('[aria-label="Expand albums"]')).not.toBeNull();
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

	function filterField(root: HTMLElement): HTMLInputElement {
		const input = root.querySelector<HTMLInputElement>('input');
		if (!input) throw new Error('Expected the row filter field to render');
		return input;
	}

	async function typeFilter(root: HTMLElement, text: string): Promise<void> {
		const input = filterField(root);
		input.value = text;
		input.dispatchEvent(new Event('input'));
		await tick();
	}

	it('narrows the row to only its own matches, keeping the open tile pinned', async () => {
		albumList.set([
			album({ id: 'a-1', title: 'Anfield' }),
			album({ id: 'a-2', title: 'Sommerluft' }),
			album({ id: 'a-3', title: 'Vernissage' })
		]);
		const root = await render({ kind: 'album', id: 'a-1' });

		await typeFilter(root, 'verniss');

		expect(findTileByName(root, 'Vernissage').hidden).toBe(false);
		expect(findTileByName(root, 'Sommerluft').hidden).toBe(true);
	});

	interface FilterMatchCase {
		name: string;
		targetTitle: string;
		targetSongCount?: number;
		decoyTitle: string;
		decoySongCount?: number;
		query: string;
	}

	// Matching is plain substring search on lower-cased text, never
	// `new RegExp(query)` -- a user's own text (a title with "(", ".", or a
	// bare "*") must filter literally, not be reinterpreted as a pattern. A
	// bare "*" would even throw as an invalid regex, so that case also
	// proves the row survives it.
	const filterMatchCases: FilterMatchCase[] = [
		{
			name: 'matches on the subtitle text, not just the title',
			targetTitle: 'Vault',
			targetSongCount: 7,
			decoyTitle: 'Crate',
			decoySongCount: 3,
			query: '7 songs'
		},
		{
			name: 'matches regardless of letter case',
			targetTitle: 'Anfield',
			decoyTitle: 'Sommerluft',
			query: 'ANFIELD'
		},
		{
			name: 'ignores leading and trailing whitespace in the typed query',
			targetTitle: 'Anfield',
			decoyTitle: 'Sommerluft',
			query: '  anfield  '
		},
		{
			name: 'treats a dot in the query as a literal character, not a wildcard',
			targetTitle: 'a.b Sessions',
			decoyTitle: 'aXb Sessions',
			query: 'a.b'
		},
		{
			name: 'treats a bare asterisk as a literal character without throwing',
			targetTitle: 'Take 5 * Remix',
			decoyTitle: 'Take 5 Only',
			query: '*'
		},
		{
			name: 'treats parentheses in the query as literal characters',
			targetTitle: 'Anfield (Live)',
			decoyTitle: 'Anfield Studio',
			query: '(Live)'
		}
	];

	it.each(filterMatchCases)(
		'$name',
		async ({ targetTitle, targetSongCount, decoyTitle, decoySongCount, query }) => {
			albumList.set([
				album({ id: 'a-open', title: 'Open Anchor' }),
				album({ id: 'a-target', title: targetTitle, song_count: targetSongCount ?? 2 }),
				album({ id: 'a-decoy', title: decoyTitle, song_count: decoySongCount ?? 2 })
			]);
			const root = await render({ kind: 'album', id: 'a-open' });

			await typeFilter(root, query);

			expect(findTileByName(root, targetTitle).hidden).toBe(false);
			expect(findTileByName(root, decoyTitle).hidden).toBe(true);
		}
	);

	it('keeps the open tile visible and marked even when the filter does not match it', async () => {
		albumList.set([
			album({ id: 'a-1', title: 'Anfield' }),
			album({ id: 'a-2', title: 'Sommerluft' })
		]);
		const root = await render({ kind: 'album', id: 'a-1' });

		await typeFilter(root, 'sommer');

		const openTile = findTileByName(root, 'Anfield');
		expect(openTile.hidden).toBe(false);
		expect(openTile.getAttribute('aria-current')).toBe('true');
	});

	it('restores every tile once the filter is cleared', async () => {
		albumList.set([
			album({ id: 'a-1', title: 'Anfield' }),
			album({ id: 'a-2', title: 'Sommerluft' })
		]);
		const root = await render({ kind: 'album', id: 'a-1' });
		await typeFilter(root, 'sommer');
		expect(findTileByName(root, 'Anfield').hidden).toBe(false);

		await typeFilter(root, '');

		expect(findTileByName(root, 'Anfield').hidden).toBe(false);
		expect(findTileByName(root, 'Sommerluft').hidden).toBe(false);
	});

	it('shows a short line when nothing matches the filter', async () => {
		const root = await render({ kind: 'album', id: 'a-1' });
		expect(root.textContent).not.toContain(LIBRARY_ROW_FILTER_EMPTY);

		await typeFilter(root, 'zzz-nothing-matches');

		expect(root.textContent).toContain(LIBRARY_ROW_FILTER_EMPTY);
	});

	it('clears the filter on Escape', async () => {
		albumList.set([
			album({ id: 'a-1', title: 'Anfield' }),
			album({ id: 'a-2', title: 'Sommerluft' }),
			album({ id: 'a-3', title: 'Vernissage' })
		]);
		const root = await render({ kind: 'album', id: 'a-1' });
		await typeFilter(root, 'sommer');
		expect(findTileByName(root, 'Vernissage').hidden).toBe(true);

		filterField(root).dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await tick();

		expect(filterField(root).value).toBe('');
		expect(findTileByName(root, 'Vernissage').hidden).toBe(false);
	});

	it('lets Tab move from the filter field straight into the row, skipping the clear button', async () => {
		const root = await render({ kind: 'album', id: 'a-1' });
		await typeFilter(root, 'a');

		const tabbable = Array.from(root.querySelectorAll<HTMLElement>('input, button')).filter(
			(el) => el.tabIndex !== -1
		);
		expect(tabbable[0]).toBe(filterField(root));
		expect(tabbable[1].classList.contains('row-tile')).toBe(true);
	});

	it('never calls fetch or the wall grid search while typing, and never touches the wall search state or the address', async () => {
		albumList.set([
			album({ id: 'a-1', title: 'Anfield' }),
			album({ id: 'a-2', title: 'Sommerluft' }),
			album({ id: 'a-3', title: 'Vernissage' })
		]);
		const root = await render({ kind: 'album', id: 'a-1' });
		// fetchSongs/fetchPlaylists/fetchPlaylist are file-wide vi.mock wrappers
		// that never touch globalThis.fetch at all -- the fetch spy below can
		// only see a real fetch call, so these three are cleared and asserted
		// on separately, the same way the row's own mount-time calls to them
		// are cleared before every other test in this describe block.
		fetchSongs.mockClear();
		fetchPlaylists.mockClear();
		fetchPlaylist.mockClear();
		const searchLibraryModule = await import('$lib/api/library');
		const fetchSpy = vi
			.spyOn(globalThis, 'fetch')
			.mockRejectedValue(new Error('LibraryRow filter must never call fetch'));
		const searchLibrarySpy = vi
			.spyOn(searchLibraryModule, 'searchLibrary')
			.mockRejectedValue(new Error('LibraryRow filter must never call the grid search'));
		const searchQueryBefore = get(searchQuery);
		const addressBefore = window.location.href;

		await typeFilter(root, 'verniss');

		expect(findTileByName(root, 'Vernissage').hidden).toBe(false);
		expect(findTileByName(root, 'Sommerluft').hidden).toBe(true);
		expect(fetchSpy).not.toHaveBeenCalled();
		expect(searchLibrarySpy).not.toHaveBeenCalled();
		expect(fetchSongs).not.toHaveBeenCalled();
		expect(fetchPlaylists).not.toHaveBeenCalled();
		expect(fetchPlaylist).not.toHaveBeenCalled();
		expect(get(searchQuery)).toBe(searchQueryBefore);
		expect(window.location.href).toBe(addressBefore);
	});

	it('recentres on the open tile only when its visible neighbours actually change, not on every keystroke', async () => {
		const calls = stubScrollIntoView();
		try {
			albumList.set([
				album({ id: 'a-1', title: 'Anfield' }),
				album({ id: 'a-2', title: 'Sommerluft' })
			]);
			const root = await render({ kind: 'album', id: 'a-1' });
			await typeFilter(root, 'an');
			calls.length = 0;

			// 'an' and 'anf' both match only the open tile ('Anfield') and hide
			// the same neighbour ('Sommerluft') -- the set of visible tiles is
			// identical across the two keystrokes, so nothing here should
			// justify a second scrollIntoView call.
			await typeFilter(root, 'anf');

			expect(calls).toHaveLength(0);
		} finally {
			restoreScrollIntoView();
		}
	});

	it('recentres once a filter keystroke actually changes which tiles are visible', async () => {
		const calls = stubScrollIntoView();
		try {
			albumList.set([
				album({ id: 'a-1', title: 'Anfield' }),
				album({ id: 'a-2', title: 'Sommerluft' })
			]);
			const root = await render({ kind: 'album', id: 'a-1' });
			await typeFilter(root, 'an');
			calls.length = 0;

			// Clearing the filter brings 'Sommerluft' back into view -- the
			// visible set changes, so the row must recentre on the open tile
			// again.
			await typeFilter(root, '');

			expect(calls.at(-1)?.receiver).toBe(findTileByName(root, 'Anfield'));
		} finally {
			restoreScrollIntoView();
		}
	});

	it("does not recentre when a sibling's metadata changes under the same filter query", async () => {
		const calls = stubScrollIntoView();
		try {
			albumList.set([
				album({ id: 'a-1', title: 'Anfield' }),
				album({ id: 'a-2', title: 'Sommerluft' })
			]);
			const root = await render({ kind: 'album', id: 'a-1' });
			await typeFilter(root, 'an');
			calls.length = 0;

			// 'Sommerluft' stays hidden before and after the rename -- the
			// visible set is unchanged, so this must not recentre either, the
			// same guarantee the unfiltered-row test above pins for renames.
			updateAlbumInList('a-2', (a) => ({ ...a, title: 'Renamed while hidden' }));
			await tick();

			expect(calls).toHaveLength(0);
		} finally {
			restoreScrollIntoView();
		}
	});

	it("keeps a hidden tile out of the flex flow in a real cascade, not just marked via the 'hidden' IDL property", () => {
		// element.hidden staying true (asserted throughout this file) only
		// proves the attribute is set -- it says nothing about what a real
		// browser paints, because jsdom computes neither layout nor the
		// CSS-origin precedence rule that decides this: author-origin CSS
		// (`.row-tile { display: flex }`) always wins over the user agent's
		// own `[hidden] { display: none }`, regardless of selector
		// specificity, unless the author stylesheet says so itself. A live
		// Playwright pass against a real stack caught exactly this: 48 of 50
		// filtered tiles stayed visible with computed `display: flex` (#402
		// review) before `.row-tile[hidden]` existed below. getComputedStyle
		// in jsdom cannot re-prove that (no real layout engine), so this
		// pins the stylesheet rule's own source instead; the live behaviour
		// is proven by the Playwright pass, not by this unit test.
		expect(libraryRowSource).toMatch(/\.row-tile\[hidden\]\s*\{[^}]*display:\s*none/);
	});
});

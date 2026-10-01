import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { HITBOX_FREQUENT_PX, RAIL_SEARCH_CLEAR_LABEL, RAIL_SEARCH_LABEL } from '$lib/constants';
import { clearComponentStyles, injectComponentStyles } from '$lib/test-utils/component-styles';
import {
	clearHitboxStyles,
	clearPointer,
	injectHitboxStyles,
	minHeightPx,
	minSquarePx,
	setPointer
} from '$lib/test-utils/hitbox';

import { railTreeQuery } from '$lib/stores/librarySearch';
import { railSearch, resetRailSearchForTests } from '$lib/stores/railSearch';
import { playlistList } from '$lib/stores/playlists';
import {
	buildAlbumSearchHit,
	buildPlaylist,
	buildSongSearchHit,
	createComponentMount,
	requireElement
} from './rail-test-fixtures';
import RailSearch from './RailSearch.svelte';
import railSearchSource from './RailSearch.svelte?raw';

const navigation = vi.hoisted(() => ({ openRailSearchTarget: vi.fn() }));
vi.mock('$lib/stores/navigation', () => navigation);

const { render, cleanup } = createComponentMount(RailSearch);

const scrollIntoView = vi.fn();
const TOUCH_RESULT_ROW_PX = 48;
const TOUCH_RESULT_PICTURE_PX = 32;

function showVernissageResults(): void {
	railTreeQuery.set('verni');
	playlistList.set([buildPlaylist({ id: 'p1', title: 'Vernissage picks', entry_count: 9 })]);
	railSearch.set({
		query: 'verni',
		status: 'ready',
		error: null,
		hits: [
			buildAlbumSearchHit({
				id: 'a1',
				title: 'Vernissage',
				song_count: 6,
				cover: { card: '/covers/a1-card.webp', detail: '/covers/a1.webp' }
			}),
			buildSongSearchHit({ id: 's1', title: 'Vernissage' }, 'Vernissage'),
			buildSongSearchHit({ id: 's2', title: 'After the Vernissage' }, 'Whoever You Are')
		]
	});
}

function press(root: HTMLElement, key: string): KeyboardEvent {
	const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
	requireElement<HTMLInputElement>(root, 'input').dispatchEvent(event);
	return event;
}

function resultRows(root: HTMLElement): HTMLElement[] {
	return Array.from(root.querySelectorAll<HTMLElement>('[role="option"]'));
}

function selectedRows(root: HTMLElement): HTMLElement[] {
	return resultRows(root).filter((row) => row.getAttribute('aria-selected') === 'true');
}

function activeRowTitle(root: HTMLElement): string | undefined {
	return requireElement(root, '[aria-selected="true"] .rail-search-title').textContent?.trim();
}

function expectSelectedRow(root: HTMLElement, index: number): void {
	expect(selectedRows(root)).toEqual([resultRows(root)[index]]);
	expect(requireElement(root, 'input').getAttribute('aria-activedescendant')).toBe(
		resultRows(root)[index]?.id
	);
}

beforeEach(() => {
	HTMLElement.prototype.scrollIntoView = scrollIntoView;
	scrollIntoView.mockClear();
	navigation.openRailSearchTarget.mockClear();
	railTreeQuery.set('');
	playlistList.set([]);
	resetRailSearchForTests();
});
afterEach(async () => {
	railTreeQuery.set('');
	playlistList.set([]);
	resetRailSearchForTests();
	clearComponentStyles();
	clearHitboxStyles();
	clearPointer();
	await cleanup();
});

describe('RailSearch', () => {
	it('updates the transient rail query as the person types', async () => {
		const root = await render();
		const input = requireElement<HTMLInputElement>(root, 'input');

		input.value = 'stadion';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();

		expect(input.getAttribute('aria-label')).toBe(RAIL_SEARCH_LABEL);
		expect(get(railTreeQuery)).toBe('stadion');
	});

	it('clears the query on Escape without submitting a form', async () => {
		railTreeQuery.set('stadion');
		const root = await render();
		const input = requireElement<HTMLInputElement>(root, 'input');
		const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });

		input.dispatchEvent(escape);
		await tick();

		expect(escape.defaultPrevented).toBe(true);
		expect(input.value).toBe('');
		expect(get(railTreeQuery)).toBe('');
		expect(root.querySelector('form')).toBeNull();
	});

	it('groups albums, songs, playlists and pages, each row led by its picture and kind word', async () => {
		showVernissageResults();
		const root = await render();

		expect(
			Array.from(root.querySelectorAll('[role="group"]'), (group) =>
				requireElement(
					root,
					`#${CSS.escape(group.getAttribute('aria-labelledby') ?? '')}`
				).textContent?.trim()
			)
		).toEqual(['Albums', 'Songs', 'Playlists']);
		const [album, titleSong, otherSong, playlist] = resultRows(root);
		expect(album?.querySelector('img')?.getAttribute('src')).toBe('/covers/a1-card.webp');
		expect(titleSong?.querySelector('.rail-search-glyph')?.textContent).toBe('♪');
		expect(playlist?.querySelector('.playlist-cover')).not.toBeNull();
		expect(resultRows(root).map((row) => row.querySelector('small')?.textContent)).toEqual([
			'Album · 6 songs',
			'Song · Vernissage',
			'Song · Whoever You Are',
			'Playlist · 9 songs'
		]);
		expect(otherSong?.querySelector('mark')?.textContent).toBe('Verni');
	});

	it('shows a page with its glyph and names it a page', async () => {
		railTreeQuery.set('gen');
		railSearch.set({ query: 'gen', status: 'ready', error: null, hits: [] });
		const root = await render();

		const [page] = resultRows(root);
		expect(page?.querySelector('.rail-search-glyph')?.textContent).toBe('⚙');
		expect(page?.querySelector('small')?.textContent).toBe('Page · Settings');
	});

	it('marks the matched letters of a page found by its section', async () => {
		railTreeQuery.set('set');
		railSearch.set({ query: 'set', status: 'ready', error: null, hits: [] });
		const root = await render();

		const [page] = resultRows(root);
		expect(page?.querySelector('small')?.textContent).toBe('Page · Settings');
		expect(page?.querySelector('small mark')?.textContent).toBe('Set');
		expect(page?.querySelector('.rail-search-title mark')).toBeNull();
	});

	it('opens a clicked result', async () => {
		showVernissageResults();
		const root = await render();

		resultRows(root)[1]?.click();
		await tick();

		expect(navigation.openRailSearchTarget).toHaveBeenCalledWith({ kind: 'song', id: 's1' });
	});

	it('gives the first hit the focus edge and opens it on Enter', async () => {
		showVernissageResults();
		const root = await render();

		expect(activeRowTitle(root)).toBe('Vernissage');
		expectSelectedRow(root, 0);
		const enter = press(root, 'Enter');
		await tick();

		expect(enter.defaultPrevented).toBe(true);
		expect(navigation.openRailSearchTarget).toHaveBeenCalledWith({ kind: 'album', id: 'a1' });
	});

	it('moves the focus edge across the groups with the arrow keys and opens that hit on Enter', async () => {
		showVernissageResults();
		const root = await render();

		const down = press(root, 'ArrowDown');
		await tick();
		expect(down.defaultPrevented).toBe(true);
		expectSelectedRow(root, 1);
		expect(scrollIntoView).toHaveBeenCalledWith({ block: 'nearest' });

		press(root, 'ArrowDown');
		press(root, 'ArrowDown');
		press(root, 'ArrowDown');
		await tick();
		expectSelectedRow(root, 3);

		press(root, 'ArrowUp');
		await tick();
		press(root, 'Enter');
		await tick();
		expect(navigation.openRailSearchTarget).toHaveBeenCalledWith({ kind: 'song', id: 's2' });
	});

	it('announces the search field as a combobox that owns a listbox of grouped options', async () => {
		showVernissageResults();
		const root = await render();
		const input = requireElement<HTMLInputElement>(root, 'input');

		expect(input.getAttribute('role')).toBe('combobox');
		expect(input.getAttribute('aria-expanded')).toBe('true');
		const listbox = requireElement(
			root,
			`#${CSS.escape(input.getAttribute('aria-controls') ?? '')}`
		);
		expect(listbox.getAttribute('role')).toBe('listbox');
		expect(listbox.querySelectorAll('[role="group"] > [role="option"]')).toHaveLength(
			resultRows(root).length
		);
		expect(resultRows(root).map((row) => row.getAttribute('aria-selected'))).toEqual([
			'true',
			'false',
			'false',
			'false'
		]);
	});

	it('names the arrow-key row as the active descendant and selected option', async () => {
		showVernissageResults();
		const root = await render();

		press(root, 'ArrowDown');
		press(root, 'ArrowDown');
		await tick();
		expectSelectedRow(root, 2);
		expect(activeRowTitle(root)).toBe('After the Vernissage');

		press(root, 'ArrowUp');
		await tick();
		expectSelectedRow(root, 1);
	});

	it('collapses the combobox when the query is cleared', async () => {
		showVernissageResults();
		const root = await render();
		const input = requireElement<HTMLInputElement>(root, 'input');

		press(root, 'Escape');
		await tick();

		expect(input.getAttribute('aria-expanded')).toBe('false');
		expect(input.hasAttribute('aria-activedescendant')).toBe(false);
		expect(resultRows(root)).toHaveLength(0);
	});

	it('keeps one selected row while the pointer hovers another, and a click opens the hovered one', async () => {
		showVernissageResults();
		const root = await render();
		press(root, 'ArrowDown');
		await tick();

		const hovered = resultRows(root)[3];
		hovered?.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
		await tick();
		expectSelectedRow(root, 1);

		hovered?.click();
		await tick();
		expect(navigation.openRailSearchTarget).toHaveBeenCalledWith({ kind: 'playlist', id: 'p1' });
	});

	it('returns the focus edge to the first hit when the query changes', async () => {
		showVernissageResults();
		const root = await render();
		press(root, 'ArrowDown');
		await tick();

		const input = requireElement<HTMLInputElement>(root, 'input');
		input.value = 'vern';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();

		expectSelectedRow(root, 0);
	});

	it('clears the query with the × in the bar and keeps the field focused', async () => {
		showVernissageResults();
		const root = await render();
		const input = requireElement<HTMLInputElement>(root, 'input');

		requireElement<HTMLButtonElement>(
			root,
			`button[aria-label="${RAIL_SEARCH_CLEAR_LABEL}"]`
		).click();
		await tick();

		expect(get(railTreeQuery)).toBe('');
		expect(input.value).toBe('');
		expect(document.activeElement).toBe(input);
		expect(root.querySelector(`button[aria-label="${RAIL_SEARCH_CLEAR_LABEL}"]`)).toBeNull();
	});

	async function renderResultsOnTouchScreen(): Promise<HTMLElement> {
		showVernissageResults();
		const root = await render();
		injectHitboxStyles();
		injectComponentStyles(
			railSearchSource,
			'RailSearch.svelte',
			requireElement(root, '.rail-search')
		);
		setPointer('coarse');
		return root;
	}

	it('is one 44 px bar on a touch screen, not a padded box around the field', async () => {
		const root = await renderResultsOnTouchScreen();
		const bar = requireElement<HTMLElement>(root, '.rail-search');

		const barStyle = getComputedStyle(bar);
		expect([barStyle.paddingTop, barStyle.paddingBottom]).toEqual(['0px', '0px']);
		expect(barStyle.borderTopStyle).toBe('none');
		expect(minHeightPx(requireElement(root, '.rail-search input'), 'rail search field')).toBe(
			HITBOX_FREQUENT_PX
		);
		expect(minSquarePx(requireElement(root, '.rail-search-clear'), 'rail search clear')).toEqual({
			width: HITBOX_FREQUENT_PX,
			height: HITBOX_FREQUENT_PX
		});
	});

	it('gives every result a 48 px row with a 32 px picture on a touch screen', async () => {
		const root = await renderResultsOnTouchScreen();

		expect(minHeightPx(requireElement(root, '.rail-search-result'), 'rail search result')).toBe(
			TOUCH_RESULT_ROW_PX
		);
		expect(
			getComputedStyle(requireElement(root, '.rail-search-region')).getPropertyValue(
				'--rail-search-picture'
			)
		).toBe(`${TOUCH_RESULT_PICTURE_PX}px`);
	});

	it('names its loading, empty, and error states', async () => {
		railTreeQuery.set('missing');
		railSearch.set({ query: 'missing', status: 'loading', error: null, hits: [] });
		const root = await render();
		expect(root.textContent).toContain('Searching…');

		railSearch.set({ query: 'missing', status: 'ready', error: null, hits: [] });
		await tick();
		expect(root.textContent).toContain('No results for “missing”.');

		railSearch.set({ query: 'missing', status: 'error', error: 'Offline', hits: [] });
		await tick();
		expect(root.querySelector('[role="alert"]')?.textContent).toContain('Offline');
	});

	it('keeps local page results available while the server search fails', async () => {
		railTreeQuery.set('voices');
		railSearch.set({ query: 'voices', status: 'error', error: 'Offline', hits: [] });
		const root = await render();

		expect(root.querySelector('[role="alert"]')?.textContent).toContain('Offline');
		expect(root.textContent).toContain('Voices');
		requireElement<HTMLInputElement>(root, 'input').dispatchEvent(
			new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
		);
		await tick();

		expect(navigation.openRailSearchTarget).toHaveBeenCalledWith({
			kind: 'page',
			href: '/settings/voices'
		});
	});
});

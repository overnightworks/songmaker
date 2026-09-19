import { makeSongSummary as songSummary } from '$lib/test-utils/factories';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { RAIL_SEARCH_LABEL } from '$lib/constants';

import { railTreeQuery } from '$lib/stores/librarySearch';
import { railSearch, resetRailSearchForTests } from '$lib/stores/railSearch';
import { playlistList } from '$lib/stores/playlists';
import { createComponentMount, requireElement } from './rail-test-fixtures';
import RailSearch from './RailSearch.svelte';

const navigation = vi.hoisted(() => ({ openRailSearchTarget: vi.fn() }));
vi.mock('$lib/stores/navigation', () => navigation);

const { render, cleanup } = createComponentMount(RailSearch);

beforeEach(() => {
	railTreeQuery.set('');
	playlistList.set([]);
	resetRailSearchForTests();
});
afterEach(async () => {
	railTreeQuery.set('');
	playlistList.set([]);
	resetRailSearchForTests();
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

	it('renders grouped result targets and chooses the first one on click or Enter', async () => {
		railTreeQuery.set('stadion');
		playlistList.set([
			{
				id: 'p1',
				title: 'Stadion nights',
				slug: 'stadion-nights',
				entry_count: 2,
				is_shared: false,
				share_slug: null,
				album_covers: [],
				created_at: '2026-01-01T00:00:00+00:00'
			}
		]);
		railSearch.set({
			query: 'stadion',
			status: 'ready',
			error: null,
			hits: [
				{
					type: 'song',
					album_id: 'a1',
					album_title: 'Anfield',
					song: songSummary({
						bpm: 120,
						audio_duration: 180,
						key_scale: 'Am',
						generation_params: null,
						share_slug: null,
						best_scores: null,
						best_rating: null,
						cover: null
					})
				}
			]
		});
		const root = await render();
		const song = requireElement<HTMLButtonElement>(root, '.rail-search-result');

		expect(root.textContent).toContain('Library');
		expect(root.textContent).toContain('Playlists');
		expect(root.textContent).toContain('Stadion nights');
		song.click();
		await tick();

		expect(navigation.openRailSearchTarget).toHaveBeenCalledWith({ kind: 'song', id: 's1' });
		navigation.openRailSearchTarget.mockClear();
		requireElement<HTMLInputElement>(root, 'input').dispatchEvent(
			new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
		);
		await tick();
		expect(navigation.openRailSearchTarget).toHaveBeenCalledWith({ kind: 'song', id: 's1' });
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
		railTreeQuery.set('playback');
		railSearch.set({ query: 'playback', status: 'error', error: 'Offline', hits: [] });
		const root = await render();

		expect(root.querySelector('[role="alert"]')?.textContent).toContain('Offline');
		expect(root.textContent).toContain('Playback');
		requireElement<HTMLInputElement>(root, 'input').dispatchEvent(
			new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
		);
		await tick();

		expect(navigation.openRailSearchTarget).toHaveBeenCalledWith({
			kind: 'page',
			href: '/settings/playback'
		});
	});
});

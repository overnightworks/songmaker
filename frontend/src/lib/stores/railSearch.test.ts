import { makeSongSummary as songSummary } from '$lib/test-utils/factories';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

const searchLibrary = vi.fn();
vi.mock('$lib/api/library', () => ({
	searchLibrary: (...args: unknown[]) => searchLibrary(...args)
}));

import { LIBRARY_SEARCH_DEBOUNCE_MS } from '$lib/constants';
import {
	firstRailSearchTarget,
	groupRailSearchResults,
	railSearch,
	resetRailSearchForTests,
	retryRailSearch,
	syncRailSearch,
	visibleRailSearchPages
} from './railSearch';

const playlist = {
	id: 'p1',
	title: 'Stadion nights',
	slug: 'stadion-nights',
	entry_count: 2,
	is_shared: false,
	share_slug: null,
	album_covers: [],
	created_at: '2026-01-01T00:00:00+00:00'
};

beforeEach(() => {
	vi.useFakeTimers();
	searchLibrary.mockReset();
	resetRailSearchForTests();
});

afterEach(() => {
	vi.useRealTimers();
	resetRailSearchForTests();
});

describe('syncRailSearch', () => {
	it('debounces one server request for a 100-album search instead of querying each result', async () => {
		searchLibrary.mockResolvedValue({
			items: Array.from({ length: 100 }, (_, index) => ({
				type: 'album' as const,
				album: {
					id: `a${index}`,
					title: `Stadion ${index}`,
					artist: 'Artist',
					subtitle: '',
					year: '',
					colors: {},
					song_count: 0,
					picked_count: 0,
					is_shared: false,
					share_slug: null,
					created_at: '2026-01-01T00:00:00+00:00',
					is_archived: false
				}
			})),
			next_cursor: null,
			has_more: false
		});

		syncRailSearch('s');
		syncRailSearch('st');
		syncRailSearch('stadion');
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);

		expect(searchLibrary).toHaveBeenCalledTimes(1);
		expect(searchLibrary).toHaveBeenCalledWith({ q: 'stadion', sort: 'newest', limit: 100 });
		expect(get(railSearch).hits).toHaveLength(100);
	});

	it('clears a pending search without calling the server', async () => {
		syncRailSearch('stadion');
		syncRailSearch(' ');
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);

		expect(searchLibrary).not.toHaveBeenCalled();
		expect(get(railSearch)).toMatchObject({ query: '', status: 'idle' });
	});

	it('records a server error and retries the same query', async () => {
		searchLibrary.mockRejectedValueOnce(new Error('Offline'));
		syncRailSearch('stadion');
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);
		expect(get(railSearch)).toMatchObject({ query: 'stadion', status: 'error', error: 'Offline' });

		searchLibrary.mockResolvedValueOnce({ items: [], next_cursor: null, has_more: false });
		retryRailSearch();
		await vi.runAllTimersAsync();
		expect(get(railSearch)).toMatchObject({
			query: 'stadion',
			status: 'ready' as const,
			error: null
		});
	});
});

describe('groupRailSearchResults', () => {
	it('excludes admin-only pages for non-administrators', () => {
		expect(visibleRailSearchPages(false).map((page) => page.label)).not.toContain('Admin');
		expect(visibleRailSearchPages(false).map((page) => page.label)).not.toContain('Cleanup');
		expect(visibleRailSearchPages(true).map((page) => page.label)).toEqual(
			expect.arrayContaining(['Admin', 'Cleanup'])
		);
	});

	it('groups library, playlist, and page targets without giving a result two actions', () => {
		const state = {
			query: 'stadion',
			status: 'ready' as const,
			error: null,
			hits: [
				{
					type: 'song' as const,
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
		};
		const pages = [{ label: 'Stadion guide', href: '/settings/playback', keywords: [] }] as const;

		const groups = groupRailSearchResults(state, [playlist], pages);

		expect(groups.map((group) => group.label)).toEqual(['Library', 'Playlists', 'Pages']);
		expect(groups[0]?.results[0]?.target).toEqual({ kind: 'song', id: 's1' });
		expect(groups[1]?.results[0]?.target).toEqual({ kind: 'playlist', id: 'p1' });
		expect(groups[2]?.results[0]?.target).toEqual({ kind: 'page', href: '/settings/playback' });
		expect(firstRailSearchTarget(state, [playlist], pages)).toEqual({ kind: 'song', id: 's1' });
	});
});

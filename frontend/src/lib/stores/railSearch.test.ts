import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

const searchLibrary = vi.fn();
vi.mock('$lib/api/library', () => ({
	searchLibrary: (...args: unknown[]) => searchLibrary(...args)
}));

import { LIBRARY_SEARCH_DEBOUNCE_MS } from '$lib/constants';
import {
	buildAlbumSearchHit,
	buildPlaylist,
	buildSongSearchHit
} from '$lib/components/shell/rail-test-fixtures';
import {
	groupRailSearchResults,
	railSearch,
	resetRailSearchForTests,
	retryRailSearch,
	syncRailSearch,
	visibleRailSearchPages
} from './railSearch';

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

	it('still searches when a trailing space follows the word before the debounce fires', async () => {
		searchLibrary.mockResolvedValue({ items: [], next_cursor: null, has_more: false });

		syncRailSearch('Vernissage');
		syncRailSearch('Vernissage ');
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);

		expect(searchLibrary).toHaveBeenCalledTimes(1);
		expect(searchLibrary).toHaveBeenCalledWith({ q: 'Vernissage', sort: 'newest', limit: 100 });
		expect(get(railSearch)).toMatchObject({ query: 'Vernissage', status: 'ready' });
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
	const vernissageState = {
		query: 'verni',
		status: 'ready' as const,
		error: null,
		hits: [
			buildSongSearchHit({ id: 's1', title: 'After the Vernissage' }, 'Whoever You Are'),
			buildAlbumSearchHit({
				id: 'a1',
				title: 'Vernissage',
				song_count: 6,
				cover: { card: '/covers/a1-card.webp', detail: '/covers/a1.webp' }
			}),
			buildSongSearchHit({ id: 's2', title: 'Vernissage' }, 'Vernissage')
		]
	};
	const picks = buildPlaylist({ id: 'p1', title: 'Vernissage picks', entry_count: 9 });

	it('excludes admin-only pages for non-administrators', () => {
		expect(visibleRailSearchPages(false).map((page) => page.label)).not.toContain('Admin');
		expect(visibleRailSearchPages(false).map((page) => page.label)).not.toContain('Cleanup');
		expect(visibleRailSearchPages(true).map((page) => page.label)).toEqual(
			expect.arrayContaining(['Admin', 'Cleanup'])
		);
	});

	it('orders the groups Albums, Songs, Playlists, Pages and gives each result one target', () => {
		const pages = [
			{ label: 'Vernissage guide', href: '/settings/playback', keywords: [] }
		] as const;

		const groups = groupRailSearchResults(vernissageState, [picks], pages);

		expect(groups.map((group) => group.label)).toEqual(['Albums', 'Songs', 'Playlists', 'Pages']);
		expect(groups.map((group) => group.results.map((result) => result.target))).toEqual([
			[{ kind: 'album', id: 'a1' }],
			[
				{ kind: 'song', id: 's2' },
				{ kind: 'song', id: 's1' }
			],
			[{ kind: 'playlist', id: 'p1' }],
			[{ kind: 'page', href: '/settings/playback' }]
		]);
	});

	it('lists titles that start with the query before titles that only contain it, newest first within each', () => {
		const state = {
			...vernissageState,
			hits: [
				buildSongSearchHit({ id: 'newest-contains', title: 'After the Vernissage' }),
				buildSongSearchHit({ id: 'newest-prefix', title: 'Vernissage II' }),
				buildSongSearchHit({ id: 'older-contains', title: 'Before the Vernissage' }),
				buildSongSearchHit({ id: 'older-prefix', title: 'Vernissage' })
			]
		};
		const playlists = [
			buildPlaylist({ id: 'old-prefix', title: 'Vernissage', created_at: '2026-01-01T00:00:00Z' }),
			buildPlaylist({
				id: 'new-contains',
				title: 'My Vernissage',
				created_at: '2026-03-01T00:00:00Z'
			}),
			buildPlaylist({
				id: 'new-prefix',
				title: 'Vernissage picks',
				created_at: '2026-02-01T00:00:00Z'
			})
		];

		const ids = groupRailSearchResults(state, playlists).map((group) =>
			group.results.map((result) => result.id)
		);

		expect(ids).toEqual([
			['song:newest-prefix', 'song:older-prefix', 'song:newest-contains', 'song:older-contains'],
			['playlist:new-prefix', 'playlist:old-prefix', 'playlist:new-contains']
		]);
	});

	it.each([
		['an album', 'a1', 'Album', '6 songs'],
		['a song', 's2', 'Song', 'Vernissage'],
		['a playlist', 'p1', 'Playlist', '9 songs']
	])('names %s by its kind word before its detail', (_, id, kindWord, detail) => {
		const results = groupRailSearchResults(vernissageState, [picks]).flatMap(
			(group) => group.results
		);

		expect(
			results.find((result) => result.target.kind !== 'page' && result.target.id === id)
		).toMatchObject({ kindWord, detail });
	});

	it('names a settings page as a Settings page and the library as a plain page', () => {
		const settings = groupRailSearchResults({ ...vernissageState, query: 'gen', hits: [] }, []);
		const library = groupRailSearchResults({ ...vernissageState, query: 'libr', hits: [] }, []);

		expect(settings[0]?.results[0]).toMatchObject({
			label: 'Generation',
			kindWord: 'Page',
			detail: 'Settings'
		});
		expect(library[0]?.results[0]).toMatchObject({
			label: 'Library',
			kindWord: 'Page',
			detail: null
		});
	});

	it('carries the picture that tells an album from a song of the same name', () => {
		const results = groupRailSearchResults(vernissageState, [picks]).flatMap(
			(group) => group.results
		);

		expect(results.map((result) => result.picture)).toEqual([
			{ kind: 'album', cover: { card: '/covers/a1-card.webp', detail: '/covers/a1.webp' } },
			{ kind: 'song', glyph: '♪' },
			{ kind: 'song', glyph: '♪' },
			{ kind: 'playlist', covers: [], cover: null }
		]);
	});

	it.each([
		[
			'Vernissage',
			'verni',
			[
				{ text: 'Verni', matched: true },
				{ text: 'ssage', matched: false }
			]
		],
		[
			'After the Vernissage',
			'VERNI',
			[
				{ text: 'After the ', matched: false },
				{ text: 'Verni', matched: true },
				{ text: 'ssage', matched: false }
			]
		],
		['Playback', 'settings', [{ text: 'Playback', matched: false }]]
	])('highlights the letters of %s that match %s', (label, query, parts) => {
		const page = { label, href: '/settings/playback', keywords: ['settings'] } as const;
		const [group] = groupRailSearchResults({ ...vernissageState, query, hits: [] }, [], [page]);

		expect(group?.results[0]?.labelParts).toEqual(parts);
	});
});

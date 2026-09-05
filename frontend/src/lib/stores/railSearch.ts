import { get, writable } from 'svelte/store';

import { searchLibrary, type LibrarySearchHit } from '$lib/api/library';
import type { PlaylistItem } from '$lib/api/types';
import { LIBRARY_SEARCH_DEBOUNCE_MS } from '$lib/constants';

const RAIL_SEARCH_RESULT_LIMIT = 100;

export type RailSearchStatus = 'idle' | 'loading' | 'ready' | 'error';

export type RailSearchPageHref =
	| '/'
	| '/settings/generation'
	| '/settings/playback'
	| '/settings/voices'
	| '/settings/account'
	| '/settings/users'
	| '/settings/cleanup'
	| '/settings/legal';

export type RailSearchTarget =
	| { kind: 'album'; id: string }
	| { kind: 'song'; id: string }
	| { kind: 'playlist'; id: string }
	| { kind: 'page'; href: RailSearchPageHref };

export interface RailSearchPage {
	label: string;
	href: RailSearchPageHref;
	keywords: readonly string[];
	adminOnly?: boolean;
}

export interface RailSearchResult {
	id: string;
	label: string;
	meta: string | null;
	target: RailSearchTarget;
}

export interface RailSearchGroup {
	label: 'Library' | 'Playlists' | 'Pages';
	results: RailSearchResult[];
}

export interface RailSearchState {
	query: string;
	status: RailSearchStatus;
	error: string | null;
	hits: LibrarySearchHit[];
}

export const RAIL_SEARCH_PAGES: readonly RailSearchPage[] = [
	{ label: 'Library', href: '/', keywords: ['albums', 'songs'] },
	{ label: 'Generation', href: '/settings/generation', keywords: ['settings'] },
	{ label: 'Playback', href: '/settings/playback', keywords: ['settings'] },
	{ label: 'Voices', href: '/settings/voices', keywords: ['settings'] },
	{ label: 'Account', href: '/settings/account', keywords: ['settings'] },
	{ label: 'Admin', href: '/settings/users', keywords: ['settings'], adminOnly: true },
	{ label: 'Cleanup', href: '/settings/cleanup', keywords: ['settings'], adminOnly: true },
	{ label: 'Legal', href: '/settings/legal', keywords: ['settings'] }
];

const EMPTY_RAIL_SEARCH: RailSearchState = {
	query: '',
	status: 'idle',
	error: null,
	hits: []
};

export const railSearch = writable<RailSearchState>({ ...EMPTY_RAIL_SEARCH });

let searchTimer: ReturnType<typeof setTimeout> | null = null;
let searchGeneration = 0;

export function syncRailSearch(rawQuery: string): void {
	const query = rawQuery.trim();
	if (searchTimer !== null) {
		clearTimeout(searchTimer);
		searchTimer = null;
	}
	if (!query) {
		searchGeneration += 1;
		railSearch.set({ ...EMPTY_RAIL_SEARCH });
		return;
	}
	const current = get(railSearch);
	if (current.query === query && (current.status === 'loading' || current.status === 'ready'))
		return;
	setRailSearchLoading(query);
	searchTimer = setTimeout(() => {
		searchTimer = null;
		void runRailSearch(query);
	}, LIBRARY_SEARCH_DEBOUNCE_MS);
}

export function retryRailSearch(): void {
	const { query } = get(railSearch);
	if (!query) return;
	if (searchTimer !== null) {
		clearTimeout(searchTimer);
		searchTimer = null;
	}
	setRailSearchLoading(query);
	void runRailSearch(query);
}

export function groupRailSearchResults(
	state: RailSearchState,
	playlists: PlaylistItem[],
	pages: readonly RailSearchPage[] = RAIL_SEARCH_PAGES
): RailSearchGroup[] {
	if (!state.query) return [];
	const query = state.query.toLocaleLowerCase();
	const library = state.hits.map(libraryResult);
	const playlistResults = playlists
		.filter((playlist) => playlist.title.toLocaleLowerCase().includes(query))
		.map((playlist) => ({
			id: `playlist:${playlist.id}`,
			label: playlist.title,
			meta: pluralize(playlist.entry_count, 'entry'),
			target: { kind: 'playlist' as const, id: playlist.id }
		}));
	const pageResults = pages
		.filter((page) => pageMatches(page, query))
		.map((page) => ({
			id: `page:${page.href}`,
			label: page.label,
			meta: page.href === '/' ? null : 'Settings',
			target: { kind: 'page' as const, href: page.href }
		}));
	const groups: RailSearchGroup[] = [
		{ label: 'Library', results: library },
		{ label: 'Playlists', results: playlistResults },
		{ label: 'Pages', results: pageResults }
	];
	return groups.filter((group) => group.results.length > 0);
}

export function visibleRailSearchPages(admin: boolean): readonly RailSearchPage[] {
	return RAIL_SEARCH_PAGES.filter((page) => !page.adminOnly || admin);
}

export function firstRailSearchTarget(
	state: RailSearchState,
	playlists: PlaylistItem[],
	pages: readonly RailSearchPage[] = RAIL_SEARCH_PAGES
): RailSearchTarget | null {
	return groupRailSearchResults(state, playlists, pages)[0]?.results[0]?.target ?? null;
}

export function resetRailSearchForTests(): void {
	if (searchTimer !== null) {
		clearTimeout(searchTimer);
		searchTimer = null;
	}
	searchGeneration += 1;
	resetRailSearch();
}

function setRailSearchLoading(query: string): void {
	railSearch.set({ query, status: 'loading', error: null, hits: [] });
}

function resetRailSearch(): void {
	railSearch.set({ ...EMPTY_RAIL_SEARCH });
}

async function runRailSearch(query: string): Promise<void> {
	const generation = ++searchGeneration;
	try {
		const response = await searchLibrary({
			q: query,
			sort: 'newest',
			limit: RAIL_SEARCH_RESULT_LIMIT
		});
		if (generation !== searchGeneration) return;
		railSearch.set({ query, status: 'ready', error: null, hits: response.items });
	} catch (error) {
		if (generation !== searchGeneration) return;
		railSearch.set({
			query,
			status: 'error',
			error: error instanceof Error ? error.message : 'Search failed',
			hits: []
		});
	}
}

function libraryResult(hit: LibrarySearchHit): RailSearchResult {
	if (hit.type === 'album') {
		return {
			id: `album:${hit.album.id}`,
			label: hit.album.title,
			meta: pluralize(hit.album.song_count, 'song'),
			target: { kind: 'album', id: hit.album.id }
		};
	}
	return {
		id: `song:${hit.song.id}`,
		label: hit.song.title,
		meta: hit.album_title,
		target: { kind: 'song', id: hit.song.id }
	};
}

function pageMatches(page: RailSearchPage, query: string): boolean {
	return [page.label, ...page.keywords].some((value) => value.toLocaleLowerCase().includes(query));
}

function pluralize(count: number, noun: string): string {
	return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

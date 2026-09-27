import { get, writable } from 'svelte/store';

import { searchLibrary, type LibrarySearchHit } from '$lib/api/library';
import type { AlbumCoverUrls, PlaylistItem } from '$lib/api/types';
import { LIBRARY_SEARCH_DEBOUNCE_MS } from '$lib/constants';

const RAIL_SEARCH_RESULT_LIMIT = 100;

type RailSearchStatus = 'idle' | 'loading' | 'ready' | 'error';

type RailSearchPageHref =
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

interface RailSearchPage {
	label: string;
	href: RailSearchPageHref;
	keywords: readonly string[];
	adminOnly?: boolean;
}

type RailSearchKind = RailSearchTarget['kind'];

type RailSearchPicture =
	| { kind: 'album'; cover: AlbumCoverUrls | null }
	| { kind: 'song'; glyph: string }
	| { kind: 'playlist'; covers: AlbumCoverUrls[]; cover: AlbumCoverUrls | null }
	| { kind: 'page'; glyph: string };

interface RailSearchLabelPart {
	text: string;
	matched: boolean;
}

interface RailSearchResult {
	id: string;
	label: string;
	labelParts: RailSearchLabelPart[];
	kindWord: string;
	detail: string | null;
	picture: RailSearchPicture;
	target: RailSearchTarget;
}

interface RailSearchGroup {
	label: string;
	results: RailSearchResult[];
}

interface RailSearchState {
	query: string;
	status: RailSearchStatus;
	error: string | null;
	hits: LibrarySearchHit[];
}

const RAIL_SEARCH_PAGES: readonly RailSearchPage[] = [
	{ label: 'Library', href: '/', keywords: ['albums', 'songs'] },
	{ label: 'Generation', href: '/settings/generation', keywords: ['settings'] },
	{ label: 'Playback', href: '/settings/playback', keywords: ['settings'] },
	{ label: 'Voices', href: '/settings/voices', keywords: ['settings'] },
	{ label: 'Account', href: '/settings/account', keywords: ['settings'] },
	{ label: 'Admin', href: '/settings/users', keywords: ['settings'], adminOnly: true },
	{ label: 'Cleanup', href: '/settings/cleanup', keywords: ['settings'], adminOnly: true },
	{ label: 'Legal', href: '/settings/legal', keywords: ['settings'] }
];

const RAIL_SEARCH_KINDS: Readonly<Record<RailSearchKind, { group: string; word: string }>> = {
	album: { group: 'Albums', word: 'Album' },
	song: { group: 'Songs', word: 'Song' },
	playlist: { group: 'Playlists', word: 'Playlist' },
	page: { group: 'Pages', word: 'Page' }
};

const RAIL_SEARCH_GROUP_ORDER: readonly RailSearchKind[] = ['album', 'song', 'playlist', 'page'];

const SONG_GLYPH = '♪';
const LIBRARY_PAGE_GLYPH = '▦';
const SETTINGS_PAGE_GLYPH = '⚙';

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
	if (isRailSearchUnderwayFor(query)) return;
	cancelPendingRailSearch();
	if (!query) {
		searchGeneration += 1;
		railSearch.set({ ...EMPTY_RAIL_SEARCH });
		return;
	}
	setRailSearchLoading(query);
	searchTimer = setTimeout(() => {
		searchTimer = null;
		void runRailSearch(query);
	}, LIBRARY_SEARCH_DEBOUNCE_MS);
}

export function retryRailSearch(): void {
	const { query } = get(railSearch);
	if (!query) return;
	cancelPendingRailSearch();
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
	const results = [
		...state.hits.map((hit) => libraryResult(hit, query)),
		...newestPlaylistsFirst(playlists)
			.filter((playlist) => playlist.title.toLocaleLowerCase().includes(query))
			.map((playlist) => playlistResult(playlist, query)),
		...pages.filter((page) => pageMatches(page, query)).map((page) => pageResult(page, query))
	];
	return RAIL_SEARCH_GROUP_ORDER.map((kind) => ({
		label: RAIL_SEARCH_KINDS[kind].group,
		results: prefixMatchesFirst(
			results.filter((result) => result.target.kind === kind),
			query
		)
	})).filter((group) => group.results.length > 0);
}

function newestPlaylistsFirst(playlists: PlaylistItem[]): PlaylistItem[] {
	return [...playlists].sort(
		(left, right) => Date.parse(right.created_at) - Date.parse(left.created_at)
	);
}

function prefixMatchesFirst(results: RailSearchResult[], query: string): RailSearchResult[] {
	return [...results].sort(
		(left, right) => titleMatchRank(left.label, query) - titleMatchRank(right.label, query)
	);
}

function titleMatchRank(label: string, query: string): number {
	const title = label.toLocaleLowerCase();
	if (title.startsWith(query)) return 0;
	return title.includes(query) ? 1 : 2;
}

function railSearchLabelParts(label: string, query: string): RailSearchLabelPart[] {
	const start = label.toLocaleLowerCase().indexOf(query.toLocaleLowerCase());
	if (start < 0) return [{ text: label, matched: false }];
	const end = start + query.length;
	return [
		{ text: label.slice(0, start), matched: false },
		{ text: label.slice(start, end), matched: true },
		{ text: label.slice(end), matched: false }
	].filter((part) => part.text.length > 0);
}

export function visibleRailSearchPages(admin: boolean): readonly RailSearchPage[] {
	return RAIL_SEARCH_PAGES.filter((page) => !page.adminOnly || admin);
}

export function resetRailSearchForTests(): void {
	cancelPendingRailSearch();
	searchGeneration += 1;
	resetRailSearch();
}

function isRailSearchUnderwayFor(query: string): boolean {
	const current = get(railSearch);
	return current.query === query && (current.status === 'loading' || current.status === 'ready');
}

function cancelPendingRailSearch(): void {
	if (searchTimer === null) return;
	clearTimeout(searchTimer);
	searchTimer = null;
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

type RailSearchResultSource = Omit<RailSearchResult, 'labelParts' | 'kindWord'>;

function libraryResult(hit: LibrarySearchHit, query: string): RailSearchResult {
	if (hit.type === 'album') {
		return searchResult(query, {
			id: `album:${hit.album.id}`,
			label: hit.album.title,
			detail: pluralize(hit.album.song_count, 'song'),
			picture: { kind: 'album', cover: hit.album.cover ?? null },
			target: { kind: 'album', id: hit.album.id }
		});
	}
	return searchResult(query, {
		id: `song:${hit.song.id}`,
		label: hit.song.title,
		detail: hit.album_title,
		picture: { kind: 'song', glyph: SONG_GLYPH },
		target: { kind: 'song', id: hit.song.id }
	});
}

function playlistResult(playlist: PlaylistItem, query: string): RailSearchResult {
	return searchResult(query, {
		id: `playlist:${playlist.id}`,
		label: playlist.title,
		detail: pluralize(playlist.entry_count, 'song'),
		picture: { kind: 'playlist', covers: playlist.album_covers, cover: playlist.cover ?? null },
		target: { kind: 'playlist', id: playlist.id }
	});
}

function pageResult(page: RailSearchPage, query: string): RailSearchResult {
	const isLibrary = page.href === '/';
	return searchResult(query, {
		id: `page:${page.href}`,
		label: page.label,
		detail: isLibrary ? null : 'Settings',
		picture: { kind: 'page', glyph: isLibrary ? LIBRARY_PAGE_GLYPH : SETTINGS_PAGE_GLYPH },
		target: { kind: 'page', href: page.href }
	});
}

function searchResult(query: string, source: RailSearchResultSource): RailSearchResult {
	return {
		...source,
		labelParts: railSearchLabelParts(source.label, query),
		kindWord: RAIL_SEARCH_KINDS[source.target.kind].word
	};
}

function pageMatches(page: RailSearchPage, query: string): boolean {
	return [page.label, ...page.keywords].some((value) => value.toLocaleLowerCase().includes(query));
}

function pluralize(count: number, noun: string): string {
	return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

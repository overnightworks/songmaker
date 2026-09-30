import type { Pathname } from '$app/types';
import { get, writable } from 'svelte/store';

import { describeFailure, NetworkError } from '$lib/api/fetch';
import { searchLibrary, type LibrarySearchHit } from '$lib/api/library';
import type { AlbumCoverUrls, PlaylistItem } from '$lib/api/types';
import {
	LIBRARY_SEARCH_DEBOUNCE_MS,
	RAIL_LIBRARY_LABEL,
	RAIL_SETTINGS_LABEL
} from '$lib/constants';
import { visibleSettingsSections } from '$lib/settingsSections';
import { reloadWhileUnreachable } from '$lib/stores/connectivity';
import { compareByCreatedAt } from '$lib/utils/recency';

const RAIL_SEARCH_RESULT_LIMIT = 100;

type RailSearchStatus = 'idle' | 'loading' | 'ready' | 'error' | 'unreachable';

export type RailSearchTarget =
	| { kind: 'album'; id: string }
	| { kind: 'song'; id: string }
	| { kind: 'playlist'; id: string }
	| { kind: 'page'; href: Pathname };

interface RailSearchPage {
	label: string;
	href: Pathname;
	section: string | null;
}

type RailSearchKind = RailSearchTarget['kind'];

type RailSearchPicture =
	| { kind: 'album'; cover: AlbumCoverUrls | null }
	| { kind: 'song'; glyph: string }
	| { kind: 'playlist'; covers: AlbumCoverUrls[]; cover: AlbumCoverUrls | null }
	| { kind: 'page'; glyph: string };

export interface RailSearchTextPart {
	text: string;
	matched: boolean;
}

interface RailSearchResult {
	id: string;
	label: string;
	labelParts: RailSearchTextPart[];
	kindWord: string;
	detailParts: RailSearchTextPart[];
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

const SEARCH_FAILED_MESSAGE = 'Search failed';

const LIBRARY_PAGE: RailSearchPage = { label: RAIL_LIBRARY_LABEL, href: '/', section: null };

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
const railSearchReloads = reloadWhileUnreachable(searchCurrentQueryAgain);

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
	cancelPendingRailSearch();
	searchCurrentQueryAgain();
}

function searchCurrentQueryAgain(): void {
	const { query } = get(railSearch);
	if (!query) return;
	setRailSearchLoading(query);
	void runRailSearch(query);
}

export function groupRailSearchResults(
	state: RailSearchState,
	playlists: PlaylistItem[],
	pages: readonly RailSearchPage[] = visibleRailSearchPages(true)
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
	return [...playlists].sort((left, right) => compareByCreatedAt(left, right, 'newest'));
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

function railSearchTextParts(text: string, query: string): RailSearchTextPart[] {
	const start = text.toLocaleLowerCase().indexOf(query.toLocaleLowerCase());
	if (start < 0) return [{ text, matched: false }];
	const end = start + query.length;
	return [
		{ text: text.slice(0, start), matched: false },
		{ text: text.slice(start, end), matched: true },
		{ text: text.slice(end), matched: false }
	].filter((part) => part.text.length > 0);
}

export function visibleRailSearchPages(admin: boolean): readonly RailSearchPage[] {
	const settingsPages = visibleSettingsSections(admin).map(({ label, href }) => ({
		label,
		href,
		section: RAIL_SETTINGS_LABEL
	}));
	return [LIBRARY_PAGE, ...settingsPages];
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
	railSearchReloads.stop();
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
		railSearchReloads.stop();
		railSearch.set({ query, status: 'ready', error: null, hits: response.items });
	} catch (error) {
		if (generation !== searchGeneration) return;
		if (error instanceof NetworkError) {
			const reload = railSearchReloads.afterNetworkFailure();
			if (reload === 'on-reconnect') {
				railSearch.set({ query, status: 'unreachable', error: null, hits: [] });
				return;
			}
			if (reload === 'scheduled') return;
		}
		railSearch.set({
			query,
			status: 'error',
			error: describeFailure(error, SEARCH_FAILED_MESSAGE),
			hits: []
		});
	}
}

type RailSearchResultSource = Omit<RailSearchResult, 'labelParts' | 'kindWord' | 'detailParts'> & {
	detail: string | null;
};

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
	return searchResult(query, {
		id: `page:${page.href}`,
		label: page.label,
		detail: page.section,
		picture: { kind: 'page', glyph: page.section ? SETTINGS_PAGE_GLYPH : LIBRARY_PAGE_GLYPH },
		target: { kind: 'page', href: page.href }
	});
}

function searchResult(query: string, source: RailSearchResultSource): RailSearchResult {
	const { detail, ...shown } = source;
	const labelParts = railSearchTextParts(source.label, query);
	const titleMatched = labelParts.some((part) => part.matched);
	return {
		...shown,
		labelParts,
		kindWord: RAIL_SEARCH_KINDS[source.target.kind].word,
		detailParts: detailTextParts(detail, titleMatched ? null : query)
	};
}

function detailTextParts(detail: string | null, query: string | null): RailSearchTextPart[] {
	if (detail === null) return [];
	return query === null ? [{ text: detail, matched: false }] : railSearchTextParts(detail, query);
}

function pageMatches(page: RailSearchPage, query: string): boolean {
	return [page.label, page.section]
		.filter((value) => value !== null)
		.some((value) => value.toLocaleLowerCase().includes(query));
}

function pluralize(count: number, noun: string): string {
	return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

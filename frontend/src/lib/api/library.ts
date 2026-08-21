import type { AlbumItem, SongItem } from './types';
import { apiFetch } from './fetch';
import { LIBRARY_QUERY_REQUIRED } from '$lib/constants';
import type { CreatedSort } from '$lib/utils/recency';

export type LibrarySort = CreatedSort;

export type LibraryAlbumHit = {
	type: 'album';
	album: AlbumItem;
};

export type LibrarySongHit = {
	type: 'song';
	song: SongItem;
	album_id: string;
	album_title: string;
};

export type LibrarySearchHit = LibraryAlbumHit | LibrarySongHit;

export interface LibrarySearchResponse {
	items: LibrarySearchHit[];
	next_cursor: string | null;
	has_more: boolean;
}

export interface LibraryListOptions {
	q?: string;
	sort?: LibrarySort;
}

export async function searchLibrary(options: {
	q: string;
	sort: LibrarySort;
	limit: number;
	cursor?: string | null;
}): Promise<LibrarySearchResponse> {
	const q = options.q.trim();
	if (!q) {
		throw new Error(LIBRARY_QUERY_REQUIRED);
	}
	const params = new URLSearchParams({
		q,
		sort: options.sort,
		limit: String(options.limit)
	});
	if (options.cursor) params.set('cursor', options.cursor);
	const resp = await apiFetch<LibrarySearchResponse>(`/api/library/search?${params}`);
	return {
		...resp,
		items: resp.items.map(normalizeHit)
	};
}

function normalizeHit(hit: LibrarySearchHit): LibrarySearchHit {
	if (hit.type === 'album') return hit;
	return {
		...hit,
		song: { ...hit.song, generations: hit.song.generations ?? [] }
	};
}

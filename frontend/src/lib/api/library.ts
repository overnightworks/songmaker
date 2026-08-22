import type {
	AlbumItem,
	LibraryPoolQueue,
	PaginatedResponse,
	ShareInventoryItem,
	SongItem
} from './types';
import { apiFetch } from './fetch';
import { LIBRARY_QUERY_REQUIRED, LIBRARY_SHARES_PAGE_SIZE } from '$lib/constants';
import type { ShareInventoryType } from '$lib/constants';
import type { CreatedSort } from '$lib/utils/recency';

const LIBRARY_POOL_QUEUE_PATH = '/api/library/pool-queue';
const DEFAULT_LIBRARY_POOL: LibraryPoolQueue['pool'] = 'mix';

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

export async function fetchLibraryPoolQueue(options?: {
	startGenerationId?: string | null;
	shuffle?: boolean;
	pool?: LibraryPoolQueue['pool'];
	signal?: AbortSignal;
}): Promise<LibraryPoolQueue> {
	const params = new URLSearchParams({
		pool: options?.pool ?? DEFAULT_LIBRARY_POOL,
		shuffle: String(options?.shuffle ?? false)
	});
	if (options?.startGenerationId) {
		params.set('start_generation_id', options.startGenerationId);
	}
	return apiFetch<LibraryPoolQueue>(`${LIBRARY_POOL_QUEUE_PATH}?${params}`, {
		signal: options?.signal
	});
}

export async function fetchShares(options?: {
	offset?: number;
	limit?: number;
	type?: ShareInventoryType | null;
}): Promise<PaginatedResponse<ShareInventoryItem>> {
	const params = new URLSearchParams({
		offset: String(options?.offset ?? 0),
		limit: String(options?.limit ?? LIBRARY_SHARES_PAGE_SIZE)
	});
	if (options?.type) params.set('type', options.type);
	return apiFetch<PaginatedResponse<ShareInventoryItem>>(`/api/library/shares?${params}`);
}

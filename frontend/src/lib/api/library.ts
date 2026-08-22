import type {
	AlbumItem,
	LibraryPoolQueue,
	PaginatedResponse,
	ShareInventoryItem,
	SongItem
} from './types';
import { API_TIMEOUT_MS, apiFetch } from './fetch';
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

function mergeAbortSignals(userSignal: AbortSignal | undefined): {
	signal: AbortSignal;
	dispose: () => void;
} {
	const timeoutController = new AbortController();
	const timeout = setTimeout(() => timeoutController.abort(), API_TIMEOUT_MS);
	if (!userSignal) {
		return { signal: timeoutController.signal, dispose: () => clearTimeout(timeout) };
	}
	if (userSignal.aborted) {
		timeoutController.abort();
		return { signal: userSignal, dispose: () => clearTimeout(timeout) };
	}
	const merged = new AbortController();
	const abortMerged = () => merged.abort();
	userSignal.addEventListener('abort', abortMerged);
	timeoutController.signal.addEventListener('abort', abortMerged);
	return {
		signal: merged.signal,
		dispose: () => {
			clearTimeout(timeout);
			userSignal.removeEventListener('abort', abortMerged);
			timeoutController.signal.removeEventListener('abort', abortMerged);
		}
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
	const { signal, dispose } = mergeAbortSignals(options?.signal);
	try {
		return await apiFetch<LibraryPoolQueue>(`${LIBRARY_POOL_QUEUE_PATH}?${params}`, { signal });
	} finally {
		dispose();
	}
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

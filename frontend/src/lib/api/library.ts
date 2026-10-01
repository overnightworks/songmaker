import type { LibrarySearchResponse, LibraryContinueResponse, LibraryPoolQueue } from './types';
import { apiFetch } from './fetch';
import { LIBRARY_QUERY_REQUIRED } from '$lib/constants';
import type { CreatedSort } from '$lib/utils/recency';

const LIBRARY_POOL_QUEUE_PATH = '/api/library/pool-queue';
const DEFAULT_LIBRARY_POOL: LibraryPoolQueue['pool'] = 'mix';

export type LibrarySort = CreatedSort;

export type { LibrarySearchResponse } from './types';
export type LibrarySearchHit = LibrarySearchResponse['items'][number];
export type LibraryContinueItem = LibraryContinueResponse['items'][number];

export interface LibraryListOptions {
	q?: string;
	sort?: LibrarySort;
	archived?: boolean;
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
	return apiFetch<LibrarySearchResponse>(`/api/library/search?${params}`);
}

export async function fetchLibraryContinue(page?: {
	offset: number;
	limit: number;
}): Promise<LibraryContinueResponse> {
	const query =
		page === undefined
			? ''
			: `?${new URLSearchParams({ offset: String(page.offset), limit: String(page.limit) })}`;
	return apiFetch<LibraryContinueResponse>(`/api/library/continue${query}`);
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

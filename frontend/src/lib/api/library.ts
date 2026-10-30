import type {
	LibrarySearchResponse,
	LibraryListenResponse,
	LibraryPoolQueue,
	LibraryWriteResponse
} from './types';
import { apiFetch } from './fetch';
import { LIBRARY_QUERY_REQUIRED } from '#lib/constants.ts';
import type { CreatedSort } from '#lib/utils/recency.ts';

const LIBRARY_POOL_QUEUE_PATH = '/api/library/pool-queue';
const DEFAULT_LIBRARY_POOL: LibraryPoolQueue['pool'] = 'mix';

export type LibrarySort = CreatedSort;

export type { LibrarySearchResponse } from './types';
export type LibrarySearchHit = LibrarySearchResponse['items'][number];
export type LibraryListenItem = LibraryListenResponse['items'][number];

// eslint-disable-next-line no-restricted-syntax -- query arguments of one call, not a body
export interface LibraryListOptions {
	q?: string;
	sort?: LibrarySort;
	archived?: boolean;
}

// eslint-disable-next-line no-restricted-syntax -- query arguments of one call, not a body
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

// eslint-disable-next-line no-restricted-syntax -- query arguments of one call, not a body
export async function fetchLibraryListen(page: {
	offset: number;
	limit: number;
}): Promise<LibraryListenResponse> {
	const query = new URLSearchParams({ offset: String(page.offset), limit: String(page.limit) });
	return apiFetch<LibraryListenResponse>(`/api/library/listen?${query}`);
}

// eslint-disable-next-line no-restricted-syntax -- query arguments of one call, not a body
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

export async function fetchLibraryWrite(): Promise<LibraryWriteResponse> {
	return apiFetch<LibraryWriteResponse>('/api/library/write');
}

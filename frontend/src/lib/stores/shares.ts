import { get, writable } from 'svelte/store';
import { ApiError } from '$lib/api/fetch';
import * as libraryApi from '$lib/api/library';
import type { PaginatedResponse, ShareInventoryItem, SongItem } from '$lib/api/types';
import {
	LIBRARY_SHARES_ERROR,
	LIBRARY_SHARES_PAGE_SIZE,
	type ShareInventoryType
} from '$lib/constants';

export type ShareLoadStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface ShareCountState {
	status: ShareLoadStatus;
	error: string | null;
	total: number | null;
}

export interface ShareInventoryState {
	status: ShareLoadStatus;
	error: string | null;
	items: ShareInventoryItem[];
	offset: number;
	hasMore: boolean;
	typeFilter: ShareInventoryType | null;
}

const EMPTY_COUNT: ShareCountState = { status: 'idle', error: null, total: null };

const EMPTY_INVENTORY: ShareInventoryState = {
	status: 'idle',
	error: null,
	items: [],
	offset: 0,
	hasMore: false,
	typeFilter: null
};

export const sharesViewOpen = writable(false);
export const shareCount = writable<ShareCountState>({ ...EMPTY_COUNT });
export const shareInventory = writable<ShareInventoryState>({ ...EMPTY_INVENTORY });

let countGeneration = 0;
let inventoryGeneration = 0;
let statusWatchers = 0;
let viewWatchers = 0;
let visibilityBound = false;

export function openSharesInventory(): void {
	sharesViewOpen.set(true);
}

export function closeSharesInventory(): void {
	sharesViewOpen.set(false);
}

export function toggleSharesInventory(): boolean {
	const next = !get(sharesViewOpen);
	sharesViewOpen.set(next);
	return next;
}

export function resetSharesForTests(): void {
	countGeneration += 1;
	inventoryGeneration += 1;
	statusWatchers = 0;
	viewWatchers = 0;
	releaseVisibility();
	sharesViewOpen.set(false);
	shareCount.set({ ...EMPTY_COUNT });
	shareInventory.set({ ...EMPTY_INVENTORY });
}

export function watchShareStatus(): () => void {
	statusWatchers += 1;
	ensureVisibility();
	void refreshShareCount();
	return () => {
		statusWatchers = Math.max(0, statusWatchers - 1);
		releaseVisibility();
	};
}

export function watchShareView(): () => void {
	viewWatchers += 1;
	ensureVisibility();
	void loadShareInventory({ reset: true });
	return () => {
		viewWatchers = Math.max(0, viewWatchers - 1);
		releaseVisibility();
	};
}

export async function refreshShareCount(): Promise<boolean> {
	const generation = ++countGeneration;
	const previous = get(shareCount);
	if (previous.total === null) {
		shareCount.set({ status: 'loading', error: null, total: null });
	}
	try {
		const page = await requestShares({ offset: 0, limit: 1 });
		if (generation !== countGeneration) return false;
		shareCount.set({ status: 'ready', error: null, total: page.total });
		return true;
	} catch (err) {
		if (generation !== countGeneration) return false;
		shareCount.set({
			status: 'error',
			error: shareErrorMessage(err),
			total: previous.total
		});
		return false;
	}
}

export async function loadShareInventory(options: { reset: boolean }): Promise<boolean> {
	const generation = ++inventoryGeneration;
	const current = get(shareInventory);
	const typeFilter = current.typeFilter;
	const offset = options.reset ? 0 : current.offset;
	shareInventory.update((state) => ({
		...state,
		status: 'loading',
		error: null,
		...(options.reset && state.items.length === 0 ? { items: [], offset: 0, hasMore: false } : {})
	}));
	try {
		const page = await requestShares({
			offset,
			limit: LIBRARY_SHARES_PAGE_SIZE,
			type: typeFilter
		});
		if (generation !== inventoryGeneration) return false;
		shareCount.set({ status: 'ready', error: null, total: page.total });
		shareInventory.set({
			status: 'ready',
			error: null,
			items: options.reset ? page.items : [...current.items, ...page.items],
			offset: offset + page.items.length,
			hasMore: page.has_more,
			typeFilter
		});
		return true;
	} catch (err) {
		if (generation !== inventoryGeneration) return false;
		shareInventory.update((state) => ({
			...state,
			status: 'error',
			error: shareErrorMessage(err)
		}));
		return false;
	}
}

export async function loadMoreShares(): Promise<boolean> {
	const current = get(shareInventory);
	if (!current.hasMore || current.status === 'loading') return false;
	return loadShareInventory({ reset: false });
}

export async function setShareTypeFilter(type: ShareInventoryType | null): Promise<boolean> {
	shareInventory.update((state) => ({
		...state,
		typeFilter: type,
		items: [],
		offset: 0,
		hasMore: false,
		status: 'loading',
		error: null
	}));
	return loadShareInventory({ reset: true });
}

export async function refreshSharesAfterMutation(): Promise<void> {
	await refreshShareCount();
	if (get(sharesViewOpen) || viewWatchers > 0) {
		await loadShareInventory({ reset: true });
	}
}

export function patchSharesFromSong(song: SongItem): void {
	shareInventory.update((state) => {
		if (state.items.length === 0) return state;
		return {
			...state,
			items: state.items.map((item) => patchShareItemFromSong(item, song))
		};
	});
}

function patchShareItemFromSong(item: ShareInventoryItem, song: SongItem): ShareInventoryItem {
	if (item.type === 'song' && item.id === song.id) {
		return {
			...item,
			title: song.title,
			share_slug: song.share_slug ?? item.share_slug
		};
	}
	if (item.type !== 'generation' || item.song_id !== song.id) return item;
	const generation = song.generations.find((candidate) => candidate.id === item.id);
	if (!generation) {
		return { ...item, title: song.title, song_title: song.title };
	}
	return {
		...item,
		title: song.title,
		song_title: song.title,
		share_slug: generation.share_slug ?? item.share_slug,
		generation_number: generation.generation_number,
		is_archived: generation.is_archived
	};
}

function requestShares(options: {
	offset?: number;
	limit?: number;
	type?: ShareInventoryType | null;
}): Promise<PaginatedResponse<ShareInventoryItem>> {
	if (typeof libraryApi.fetchShares !== 'function') {
		throw new Error(LIBRARY_SHARES_ERROR);
	}
	return libraryApi.fetchShares(options);
}

function shareErrorMessage(err: unknown): string {
	if (err instanceof ApiError) return err.detail || err.message;
	if (err instanceof Error) return err.message;
	return LIBRARY_SHARES_ERROR;
}

function onVisibility(): void {
	if (document.visibilityState !== 'visible') return;
	if (viewWatchers > 0) {
		void loadShareInventory({ reset: true });
		return;
	}
	if (statusWatchers > 0) void refreshShareCount();
}

function ensureVisibility(): void {
	if (visibilityBound || typeof document === 'undefined') return;
	document.addEventListener('visibilitychange', onVisibility);
	visibilityBound = true;
}

function releaseVisibility(): void {
	if (statusWatchers > 0 || viewWatchers > 0) return;
	if (!visibilityBound || typeof document === 'undefined') return;
	document.removeEventListener('visibilitychange', onVisibility);
	visibilityBound = false;
}

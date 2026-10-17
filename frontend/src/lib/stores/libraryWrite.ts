import { get, readonly, writable } from 'svelte/store';
import { fetchLibraryWrite } from '$lib/api/library';
import type { LibraryWriteItem } from '$lib/api/types';

type WriteReadState = 'unread' | 'failed' | 'ready' | 'outdated';
type RemovedKind = 'song' | 'album';
const rows = writable<readonly LibraryWriteItem[]>([]);
const state = writable<WriteReadState>('unread');
const loading = writable(false);
export const libraryWriteItems = readonly(rows);
export const libraryWriteState = readonly(state);
export const libraryWriteLoading = readonly(loading);
let generation = 0;
let pending: Promise<boolean> | null = null;
let outdatedDuringRead = false;
// Remember removals even when their rows were never loaded. Undo arrives
// through the shared library seam, independently of the visible song list.
const removed = { song: new Set<string>(), album: new Set<string>() };

export function readLibraryWrite(): Promise<boolean> {
	if (pending !== null) return pending;
	const startedGeneration = generation;
	outdatedDuringRead = false;
	loading.set(true);
	pending = fetchLibraryWrite()
		.then(
			(answer) => {
				if (startedGeneration !== generation) return false;
				rows.set(
					answer.items.filter(
						(row) => !removed.song.has(row.song_id) && !removed.album.has(row.album_id)
					)
				);
				state.set(outdatedDuringRead ? 'outdated' : 'ready');
				return true;
			},
			() => {
				if (startedGeneration !== generation) return false;
				state.update((value) => (value === 'unread' || value === 'failed' ? 'failed' : 'outdated'));
				return false;
			}
		)
		.finally(() => {
			if (startedGeneration !== generation) return;
			pending = null;
			loading.set(false);
		});
	return pending;
}

export function ensureLibraryWriteRead(): Promise<boolean> {
	if (pending !== null) return pending;
	return get(state) === 'ready' ? Promise.resolve(true) : readLibraryWrite();
}

// Foreground and online callers invalidate explicitly before asking for rows.
export function outdateLibraryWrite(): void {
	if (pending !== null) outdatedDuringRead = true;
	state.update((value) => (value === 'ready' ? 'outdated' : value));
}

async function refillWritten(): Promise<boolean> {
	const startedGeneration = generation;
	if (pending !== null) await pending;
	if (startedGeneration !== generation) return false;
	outdateLibraryWrite();
	return ensureLibraryWriteRead();
}

export function forgetWritten(kind: RemovedKind, id: string): void {
	removed[kind].add(id);
	rows.update((items) =>
		items.filter((row) => (kind === 'song' ? row.song_id : row.album_id) !== id)
	);
	void refillWritten();
}

export async function restoreWritten(kind: RemovedKind, ids: readonly string[]): Promise<boolean> {
	const restored = ids.filter((id) => removed[kind].has(id));
	if (restored.length === 0) return true;
	const startedGeneration = generation;
	if (pending !== null) await pending;
	if (startedGeneration !== generation) return false;
	for (const id of restored) removed[kind].delete(id);
	outdateLibraryWrite();
	return ensureLibraryWriteRead();
}

export function resetLibraryWriteForTests(): void {
	generation++;
	pending = null;
	outdatedDuringRead = false;
	removed.song.clear();
	removed.album.clear();
	rows.set([]);
	state.set('unread');
	loading.set(false);
}

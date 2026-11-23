import { get, writable } from 'svelte/store';
import type { GenerationItem } from '#lib/api/types.ts';
import { selectedSongId } from '#lib/stores/player.ts';
import { IMPORTED_KEY, type TakeGroupKey, type TakeGroups } from '#lib/utils/takeGroups.ts';

interface TakeFoldState {
	songId: string | null;
	open: ReadonlySet<TakeGroupKey>;
	// Imported's initial default is decided once per remembered song.
	importedSettled: boolean;
	currentKey: TakeGroupKey | null;
}

const EMPTY_STATE: TakeFoldState = {
	songId: null,
	open: new Set(),
	importedSettled: false,
	currentKey: null
};

export const takeFolds = writable<TakeFoldState>(EMPTY_STATE);

function importedStartsOpen(groups: TakeGroups): boolean {
	return groups.earlier.some((group) => group.key === IMPORTED_KEY) && !hasVersionedTake(groups);
}

function hasVersionedTake(groups: TakeGroups): boolean {
	return (
		(groups.current?.generations.length ?? 0) > 0 ||
		groups.earlier.some((group) => group.key !== IMPORTED_KEY)
	);
}

function openKeys(state: TakeFoldState, groups: TakeGroups): Set<TakeGroupKey> {
	const open = new Set(state.open);
	if (!state.importedSettled && importedStartsOpen(groups)) open.add(IMPORTED_KEY);
	return open;
}

export function isGroupOpen(state: TakeFoldState, groups: TakeGroups, key: TakeGroupKey): boolean {
	return openKeys(state, groups).has(key);
}

// The takes on screen: the current version's, and those of every unfolded version.
export function renderedTakes(state: TakeFoldState, groups: TakeGroups): GenerationItem[] {
	const open = openKeys(state, groups);
	return [
		...(groups.current?.generations ?? []),
		...groups.earlier.filter((group) => open.has(group.key)).flatMap((group) => group.generations)
	];
}

// Records what the list decided from its takes: Imported's initial default, and
// which version is current, which can never sit in the open set.
export function settleTakeFolds(groups: TakeGroups): void {
	takeFolds.update((state) => {
		const open = openKeys(state, groups);
		const currentKey = groups.current?.key ?? null;
		if (currentKey) open.delete(currentKey);
		const takeCount = groups.earlier.length + (groups.current?.generations.length ?? 0);
		const importedSettled = state.importedSettled || takeCount > 0;
		if (
			importedSettled === state.importedSettled &&
			currentKey === state.currentKey &&
			open.size === state.open.size
		) {
			return state;
		}
		return { ...state, open, importedSettled, currentKey };
	});
}

export function toggleTakeGroup(key: TakeGroupKey, groups: TakeGroups): void {
	takeFolds.update((state) => {
		const open = openKeys(state, groups);
		if (open.has(key)) open.delete(key);
		else open.add(key);
		return { ...state, open, importedSettled: true };
	});
}

// A link to a take inside a folded version opens that version first.
export function revealTakeGroup(key: TakeGroupKey): void {
	takeFolds.update((state) => {
		if (key === state.currentKey || state.open.has(key)) return state;
		return { ...state, open: new Set(state.open).add(key) };
	});
}

// Folds belong to the song they were made on; a different song starts with only
// its current version open. Watching the store keeps this true while no take
// list is mounted (Edit, co-writer).
selectedSongId.subscribe((songId) => {
	if (songId === null || songId === get(takeFolds).songId) return;
	takeFolds.set({ ...EMPTY_STATE, songId });
});

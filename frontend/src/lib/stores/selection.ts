import { writable, derived, get } from 'svelte/store';
import type { GenerationItem } from '$lib/api/types';

export const selectedIds = writable<Set<string>>(new Set());
export const selectionMode = writable(false);

export const selectionCount = derived(selectedIds, ($ids) => $ids.size);

export function enterSelectionMode(): void {
	selectionMode.set(true);
}

export function exitSelectionMode(): void {
	selectionMode.set(false);
	selectedIds.set(new Set());
}

export function toggleSelection(id: string): void {
	selectedIds.update((ids) => {
		const next = new Set(ids);
		if (next.has(id)) {
			next.delete(id);
		} else {
			next.add(id);
		}
		if (next.size === 0) {
			selectionMode.set(false);
		} else if (!get(selectionMode)) {
			selectionMode.set(true);
		}
		return next;
	});
}

export function selectAll(ids: string[]): void {
	selectedIds.update((current) => {
		const next = new Set(current);
		for (const id of ids) {
			next.add(id);
		}
		return next;
	});
	if (!get(selectionMode)) {
		selectionMode.set(true);
	}
}

export function selectAllUnkept(generations: GenerationItem[]): void {
	const ids = generations.filter((g) => !g.is_picked && !g.is_kept).map((g) => g.id);
	selectAll(ids);
}

export function clearSelection(): void {
	selectedIds.set(new Set());
	selectionMode.set(false);
}

export function isSelected(id: string): boolean {
	return get(selectedIds).has(id);
}

import { writable, derived, get } from 'svelte/store';
import {
	listLoras,
	getLora,
	createLora as apiCreateLora,
	softDeleteLora as apiSoftDeleteLora,
	trainLora as apiTrainLora
} from '$lib/api/loras';
import type { UserLoraItem } from '$lib/api/types';

export const LORA_STATUS_DRAFT = 'draft';
export const LORA_STATUS_QUEUED = 'queued';
export const LORA_STATUS_PREPROCESSING = 'preprocessing';
export const LORA_STATUS_TRAINING = 'training';
export const LORA_STATUS_EXPORTING = 'exporting';
export const LORA_STATUS_READY = 'ready';
export const LORA_STATUS_FAILED = 'failed';

export const LORA_ACTIVE_STATUSES: readonly string[] = [
	LORA_STATUS_QUEUED,
	LORA_STATUS_PREPROCESSING,
	LORA_STATUS_TRAINING,
	LORA_STATUS_EXPORTING
];

export function isLoraActive(status: string): boolean {
	return LORA_ACTIVE_STATUSES.includes(status);
}

export const loras = writable<UserLoraItem[]>([]);
export const lorasLoading = writable<boolean>(false);
export const lorasError = writable<string | null>(null);

export const readyLoras = derived(loras, ($loras) =>
	$loras.filter((lora) => lora.status === LORA_STATUS_READY && lora.deleted_at === null)
);

export const anyLoraActive = derived(loras, ($loras) =>
	$loras.some((lora) => isLoraActive(lora.status))
);

export async function loadLoras(includeDeleted: boolean = false): Promise<UserLoraItem[]> {
	lorasLoading.set(true);
	try {
		const items = await listLoras(includeDeleted);
		loras.set(items);
		lorasError.set(null);
		return items;
	} catch (e) {
		lorasError.set(e instanceof Error ? e.message : 'Failed to load voices');
		throw e;
	} finally {
		lorasLoading.set(false);
	}
}

export async function refreshLora(loraId: string): Promise<UserLoraItem> {
	const updated = await getLora(loraId);
	loras.update((list) => {
		const idx = list.findIndex((l) => l.id === loraId);
		if (idx === -1) return [...list, updated];
		const copy = list.slice();
		copy[idx] = updated;
		return copy;
	});
	return updated;
}

export async function createLora(name: string): Promise<UserLoraItem> {
	const created = await apiCreateLora(name);
	loras.update((list) => [...list, created]);
	return created;
}

export async function softDeleteLora(loraId: string): Promise<void> {
	await apiSoftDeleteLora(loraId);
	loras.update((list) =>
		list.map((l) => (l.id === loraId ? { ...l, deleted_at: new Date().toISOString() } : l))
	);
}

export async function trainLora(loraId: string): Promise<UserLoraItem> {
	const updated = await apiTrainLora(loraId);
	loras.update((list) => list.map((l) => (l.id === loraId ? updated : l)));
	return updated;
}

export function applyLoraUpdate(updated: UserLoraItem): void {
	loras.update((list) => {
		const idx = list.findIndex((l) => l.id === updated.id);
		if (idx === -1) return [...list, updated];
		const copy = list.slice();
		copy[idx] = updated;
		return copy;
	});
}

export function getLoraById(loraId: string): UserLoraItem | undefined {
	return get(loras).find((l) => l.id === loraId);
}

import { writable, derived } from 'svelte/store';
import {
	listLoras,
	getLora,
	createLora as apiCreateLora,
	softDeleteLora as apiSoftDeleteLora,
	trainLora as apiTrainLora
} from '$lib/api/loras';
import type { UserLoraItem } from '$lib/api/types';

const LORA_STATUS_QUEUED = 'queued';
const LORA_STATUS_PREPROCESSING = 'preprocessing';
const LORA_STATUS_TRAINING = 'training';
const LORA_STATUS_EXPORTING = 'exporting';

const LORA_ACTIVE_STATUSES: readonly string[] = [
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

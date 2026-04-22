import type { UserLoraItem, UserLoraListResponse, UserLoraSampleItem } from './types';
import { apiFetch } from './fetch';

const SAMPLE_UPLOAD_TIMEOUT_MS = 120_000;

export async function listLoras(includeDeleted: boolean = false): Promise<UserLoraItem[]> {
	const qs = includeDeleted ? '?include_deleted=true' : '';
	const result = await apiFetch<UserLoraListResponse>(`/api/loras${qs}`);
	return result.loras;
}

export async function getLora(loraId: string): Promise<UserLoraItem> {
	return apiFetch<UserLoraItem>(`/api/loras/${loraId}`);
}

export async function createLora(name: string): Promise<UserLoraItem> {
	return apiFetch<UserLoraItem>('/api/loras', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ name })
	});
}

export async function softDeleteLora(loraId: string): Promise<void> {
	await apiFetch(`/api/loras/${loraId}`, { method: 'DELETE' });
}

export async function addLoraSample(
	loraId: string,
	audioFile: File,
	caption: string,
	lyrics: string,
	position?: number
): Promise<UserLoraSampleItem> {
	const form = new FormData();
	form.append('audio', audioFile);
	form.append('caption', caption);
	form.append('lyrics', lyrics);
	if (position !== undefined) form.append('position', String(position));
	return apiFetch<UserLoraSampleItem>(
		`/api/loras/${loraId}/samples`,
		{ method: 'POST', body: form },
		SAMPLE_UPLOAD_TIMEOUT_MS
	);
}

export interface LoraSamplePatch {
	caption?: string;
	lyrics?: string;
	position?: number;
}

export async function patchLoraSample(
	loraId: string,
	sampleId: string,
	patch: LoraSamplePatch
): Promise<UserLoraSampleItem> {
	return apiFetch<UserLoraSampleItem>(`/api/loras/${loraId}/samples/${sampleId}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(patch)
	});
}

export async function deleteLoraSample(loraId: string, sampleId: string): Promise<void> {
	await apiFetch(`/api/loras/${loraId}/samples/${sampleId}`, {
		method: 'DELETE'
	});
}

export async function trainLora(loraId: string): Promise<UserLoraItem> {
	return apiFetch<UserLoraItem>(`/api/loras/${loraId}/train`, { method: 'POST' });
}

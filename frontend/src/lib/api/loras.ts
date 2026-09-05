import type {
	OwnPlayableTakeListResponse,
	OwnPlayableTakeResponse,
	UserLoraItem,
	UserLoraListResponse,
	UserLoraSampleItem
} from './types';
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

/**
 * The musician's own playable takes. This deliberately does not use the
 * Library queue: the server is the single owner of the private take policy.
 */
export async function listOwnPlayableTakes(): Promise<OwnPlayableTakeResponse[]> {
	const result = await apiFetch<OwnPlayableTakeListResponse>('/api/loras/own-takes');
	return result.takes;
}

/**
 * Ask the server to copy one of the caller's own takes into this voice.
 * Sending the generation id keeps the audio private and avoids a client-side
 * download/re-upload round trip.
 */
export async function addLoraSampleFromGeneration(
	loraId: string,
	generationId: string
): Promise<UserLoraSampleItem> {
	return apiFetch<UserLoraSampleItem>(`/api/loras/${loraId}/samples/from-generation`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ generation_id: generationId })
	});
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

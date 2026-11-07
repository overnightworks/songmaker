import type {
	ReferenceListResponse,
	ReferenceRecordingResponse,
	ReferenceUsesResponse
} from './types';
import { apiFetch, apiSend, apiUpload } from './fetch';

export async function uploadReference(
	file: File,
	onProgress?: (fractionSent: number) => void
): Promise<ReferenceRecordingResponse> {
	const formData = new FormData();
	formData.append('file', file);
	if (onProgress)
		return apiUpload<ReferenceRecordingResponse>('/api/references', formData, onProgress);
	return apiFetch<ReferenceRecordingResponse>('/api/references', {
		method: 'POST',
		body: formData
	});
}

export async function listReferences(): Promise<ReferenceListResponse> {
	return apiFetch<ReferenceListResponse>('/api/references');
}

export async function getReferenceUses(referenceId: string): Promise<ReferenceUsesResponse> {
	return apiFetch<ReferenceUsesResponse>(`/api/references/${encodeURIComponent(referenceId)}/uses`);
}

export function referenceAudioUrl(referenceId: string): string {
	return `/api/references/${encodeURIComponent(referenceId)}/audio`;
}

export async function deleteReference(referenceId: string): Promise<void> {
	await apiSend(`/api/references/${encodeURIComponent(referenceId)}`, {
		method: 'DELETE'
	});
}

export async function keepReference(referenceId: string): Promise<void> {
	await apiFetch(`/api/references/${encodeURIComponent(referenceId)}/keep`, { method: 'POST' });
}

export async function unkeepReference(referenceId: string): Promise<void> {
	await apiFetch(`/api/references/${encodeURIComponent(referenceId)}/unkeep`, { method: 'POST' });
}

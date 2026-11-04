import type { ReferenceListResponse, ReferenceRecordingResponse } from './types';
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

export function referenceAudioUrl(referenceId: string): string {
	return `/api/references/${encodeURIComponent(referenceId)}/audio`;
}

export async function deleteReference(referenceId: string): Promise<void> {
	await apiSend(`/api/references/${encodeURIComponent(referenceId)}`, {
		method: 'DELETE'
	});
}

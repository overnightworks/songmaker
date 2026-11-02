import type { ReferenceRecordingResponse } from './types';
import { apiFetch } from './fetch';

export async function uploadReference(file: File): Promise<ReferenceRecordingResponse> {
	const formData = new FormData();
	formData.append('file', file);
	return apiFetch<ReferenceRecordingResponse>('/api/references', {
		method: 'POST',
		body: formData
	});
}

export async function listReferences(): Promise<ReferenceRecordingResponse[]> {
	return apiFetch<ReferenceRecordingResponse[]>('/api/references');
}

export function referenceAudioUrl(referenceId: string): string {
	return `/api/references/${encodeURIComponent(referenceId)}/audio`;
}

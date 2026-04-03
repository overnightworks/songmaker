import type { RateResult, ShareResult } from './types';
import { apiFetch, type JobStatus } from './fetch';

export async function generateSong(
	songId: string,
	count: number = 1,
	model?: string | null,
	versionId?: string | null,
	seed?: number | null
): Promise<JobStatus> {
	const payload: Record<string, unknown> = { count };
	if (model) payload.model = model;
	if (versionId) payload.version_id = versionId;
	if (seed != null) payload.seed = seed;
	return apiFetch<JobStatus>(`/api/songs/${songId}/generate`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload)
	});
}

export async function repaintGeneration(
	genId: string,
	repaintingStart: number,
	repaintingEnd: number,
	lyrics?: string | null,
	prompt?: string | null,
	model?: string | null,
	seed?: number | null,
	versionId?: string | null,
	count?: number
): Promise<JobStatus> {
	const payload: Record<string, unknown> = {
		src_generation_id: genId,
		repainting_start: repaintingStart,
		repainting_end: repaintingEnd
	};
	if (lyrics != null) payload.lyrics = lyrics;
	if (prompt != null) payload.prompt = prompt;
	if (model) payload.model = model;
	if (seed != null) payload.seed = seed;
	if (versionId) payload.version_id = versionId;
	if (count != null && count > 1) payload.count = count;
	return apiFetch<JobStatus>(`/api/generations/${genId}/repaint`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload)
	});
}

export async function coverGeneration(
	genId: string,
	audioCoverStrength: number,
	lyrics?: string | null,
	prompt?: string | null,
	model?: string | null,
	seed?: number | null,
	versionId?: string | null,
	count?: number
): Promise<JobStatus> {
	const payload: Record<string, unknown> = {
		src_generation_id: genId,
		audio_cover_strength: audioCoverStrength
	};
	if (lyrics != null) payload.lyrics = lyrics;
	if (prompt != null) payload.prompt = prompt;
	if (model) payload.model = model;
	if (seed != null) payload.seed = seed;
	if (versionId) payload.version_id = versionId;
	if (count != null && count > 1) payload.count = count;
	return apiFetch<JobStatus>(`/api/generations/${genId}/cover`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload)
	});
}

export interface ReferenceAudioResult {
	path: string;
	filename: string;
}

export async function uploadReferenceAudio(file: File): Promise<ReferenceAudioResult> {
	const formData = new FormData();
	formData.append('file', file);
	return apiFetch<ReferenceAudioResult>('/api/audio/upload', {
		method: 'POST',
		body: formData
	});
}

export async function rateGeneration(
	genId: string,
	rating: number,
	notes: string = ''
): Promise<RateResult> {
	return apiFetch<RateResult>(`/api/generations/${genId}/rate`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ rating, notes })
	});
}

export async function scoreGeneration(genId: string): Promise<JobStatus> {
	return apiFetch<JobStatus>(`/api/generations/${genId}/score`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({})
	});
}

export async function deleteGeneration(genId: string): Promise<void> {
	await apiFetch(`/api/generations/${genId}`, { method: 'DELETE' });
}

export interface BulkDeleteResult {
	deleted: number;
}

export async function bulkDeleteGenerations(generationIds: string[]): Promise<BulkDeleteResult> {
	return apiFetch<BulkDeleteResult>('/api/generations/bulk-delete', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ generation_ids: generationIds })
	});
}

export async function pickGeneration(genId: string): Promise<void> {
	await apiFetch(`/api/generations/${genId}/pick`, { method: 'POST' });
}

export async function unpickGeneration(genId: string): Promise<void> {
	await apiFetch(`/api/generations/${genId}/unpick`, { method: 'POST' });
}

export async function keepGeneration(genId: string): Promise<void> {
	await apiFetch(`/api/generations/${genId}/keep`, { method: 'POST' });
}

export async function unkeepGeneration(genId: string): Promise<void> {
	await apiFetch(`/api/generations/${genId}/unkeep`, { method: 'POST' });
}

export async function shareGeneration(genId: string): Promise<ShareResult> {
	return apiFetch<ShareResult>(`/api/generations/${genId}/share`, { method: 'POST' });
}

export async function unshareGeneration(genId: string): Promise<void> {
	await apiFetch(`/api/generations/${genId}/share`, { method: 'DELETE' });
}

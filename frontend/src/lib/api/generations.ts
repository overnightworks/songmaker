import type { RateResult, ShareResult } from './types';
import { apiFetch, type JobStatus } from './fetch';

export async function generateSong(
	songId: string,
	count: number = 1,
	model: string,
	versionId?: string | null,
	seed?: number | null
): Promise<JobStatus> {
	const payload: Record<string, unknown> = { count, model };
	if (versionId) payload.version_id = versionId;
	if (seed != null) payload.seed = seed;
	return apiFetch<JobStatus>(`/api/songs/${songId}/generate`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload)
	});
}

export interface RepaintOptions {
	lyrics?: string | null;
	prompt?: string | null;
	model: string;
	seed?: number | null;
	versionId?: string | null;
	count?: number;
	repaintMode?: string | null;
	repaintStrength?: number | null;
	repaintLatentCrossfadeFrames?: number | null;
	repaintWavCrossfadeSec?: number | null;
}

export async function repaintGeneration(
	genId: string,
	repaintingStart: number,
	repaintingEnd: number,
	opts: RepaintOptions
): Promise<JobStatus> {
	const payload: Record<string, unknown> = {
		src_generation_id: genId,
		repainting_start: repaintingStart,
		repainting_end: repaintingEnd,
		model: opts.model
	};
	if (opts.lyrics != null) payload.lyrics = opts.lyrics;
	if (opts.prompt != null) payload.prompt = opts.prompt;
	if (opts.seed != null) payload.seed = opts.seed;
	if (opts.versionId) payload.version_id = opts.versionId;
	if (opts.count != null && opts.count > 1) payload.count = opts.count;
	if (opts.repaintMode) payload.repaint_mode = opts.repaintMode;
	if (opts.repaintStrength != null) payload.repaint_strength = opts.repaintStrength;
	if (opts.repaintLatentCrossfadeFrames != null)
		payload.repaint_latent_crossfade_frames = opts.repaintLatentCrossfadeFrames;
	if (opts.repaintWavCrossfadeSec != null)
		payload.repaint_wav_crossfade_sec = opts.repaintWavCrossfadeSec;
	return apiFetch<JobStatus>(`/api/generations/${genId}/repaint`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload)
	});
}

export interface CoverOptions {
	lyrics?: string | null;
	prompt?: string | null;
	model: string;
	seed?: number | null;
	versionId?: string | null;
	count?: number;
	coverNoiseStrength?: number | null;
}

export async function coverGeneration(
	genId: string,
	audioCoverStrength: number,
	opts: CoverOptions
): Promise<JobStatus> {
	const payload: Record<string, unknown> = {
		src_generation_id: genId,
		audio_cover_strength: audioCoverStrength,
		model: opts.model
	};
	if (opts.lyrics != null) payload.lyrics = opts.lyrics;
	if (opts.prompt != null) payload.prompt = opts.prompt;
	if (opts.seed != null) payload.seed = opts.seed;
	if (opts.versionId) payload.version_id = opts.versionId;
	if (opts.count != null && opts.count > 1) payload.count = opts.count;
	if (opts.coverNoiseStrength != null) payload.cover_noise_strength = opts.coverNoiseStrength;
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

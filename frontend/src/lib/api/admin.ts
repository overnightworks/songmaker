import type {
	AdminUserLoraItem,
	GenerationRetentionReport,
	JobItem,
	RegistryResponse,
	WorkerPoolResponse
} from './types';
import { apiFetch } from './fetch';

export async function fetchAdminVoices(): Promise<AdminUserLoraItem[]> {
	return apiFetch<AdminUserLoraItem[]>('/api/admin/voices');
}

export async function listWorkers(): Promise<WorkerPoolResponse> {
	return apiFetch<WorkerPoolResponse>('/api/admin/workers');
}

export async function getRegistry(): Promise<RegistryResponse> {
	return apiFetch<RegistryResponse>('/api/admin/registry');
}

export async function loadModelOnWorker(workerId: string, mode: string): Promise<JobItem> {
	return apiFetch<JobItem>(`/api/admin/workers/${workerId}/load_model`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ mode })
	});
}

export async function evictModelOnWorker(workerId: string, mode: string): Promise<void> {
	await apiFetch(`/api/admin/workers/${workerId}/evict_model`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ mode })
	});
}

export async function downloadModel(mode: string): Promise<JobItem> {
	return apiFetch<JobItem>(`/api/admin/registry/${encodeURIComponent(mode)}/download`, {
		method: 'POST'
	});
}

export async function restartWorker(workerId: string): Promise<void> {
	await apiFetch(`/api/admin/workers/${workerId}/restart`, { method: 'POST' });
}

export async function pinModelOnWorker(workerId: string, mode: string): Promise<void> {
	await apiFetch(`/api/admin/workers/${workerId}/pin_model`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ mode })
	});
}

export async function unpinModelOnWorker(workerId: string, mode: string): Promise<void> {
	await apiFetch(`/api/admin/workers/${workerId}/unpin_model`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ mode })
	});
}

export async function previewGenerationRetention(): Promise<GenerationRetentionReport> {
	return apiFetch<GenerationRetentionReport>('/api/admin/generation-retention/preview');
}

export async function runGenerationRetention(): Promise<GenerationRetentionReport> {
	return apiFetch<GenerationRetentionReport>('/api/admin/generation-retention/run', {
		method: 'POST'
	});
}

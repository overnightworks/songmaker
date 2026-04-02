import { apiFetch, type JobStatus } from './fetch';

export async function fetchJob(jobId: string): Promise<JobStatus> {
	return apiFetch<JobStatus>(`/api/jobs/${jobId}`);
}

export async function cancelJob(jobId: string): Promise<JobStatus> {
	return apiFetch<JobStatus>(`/api/jobs/${jobId}/cancel`, { method: 'POST' });
}

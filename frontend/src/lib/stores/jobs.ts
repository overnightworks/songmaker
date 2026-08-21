import { writable } from 'svelte/store';
import type { JobStatus } from '$lib/api/client';
import { addToast } from '$lib/stores/toast';

const MAX_POLL_ERRORS = 10;

export interface ActiveJob {
	job: JobStatus;
	songId?: string;
	genId?: string;
	workerId?: string;
	mode?: string;
}

export const activeJobs = writable<ActiveJob[]>([]);

const eventSources = new Map<string, EventSource>();

export function trackJob(
	job: JobStatus,
	context: { songId?: string; genId?: string; workerId?: string; mode?: string }
): void {
	activeJobs.update((jobs) => [...jobs, { job, ...context }]);
	streamJob(job.id);
}

export function removeJob(jobId: string): void {
	stopTracking(jobId);
	activeJobs.update((jobs) => jobs.filter((j) => j.job.id !== jobId));
}

export function stopTracking(jobId: string): void {
	const source = eventSources.get(jobId);
	if (source) {
		source.close();
		eventSources.delete(jobId);
	}
}

function streamJob(jobId: string): void {
	let errorCount = 0;

	const source = new EventSource(`/api/jobs/${jobId}/stream`, { withCredentials: true });
	eventSources.set(jobId, source);

	source.onmessage = (event: MessageEvent) => {
		errorCount = 0;
		const updated: JobStatus = JSON.parse(event.data);

		activeJobs.update((jobs) => jobs.map((j) => (j.job.id === jobId ? { ...j, job: updated } : j)));

		if (
			updated.status === 'completed' ||
			updated.status === 'partial' ||
			updated.status === 'failed' ||
			updated.status === 'cancelled'
		) {
			source.close();
			eventSources.delete(jobId);

			if (updated.status === 'completed') {
				addToast(`${updated.type} completed`, 'success');
			} else if (updated.status === 'partial') {
				addToast(updated.error || `${updated.type} partially completed`, 'info');
			} else if (updated.status === 'cancelled') {
				addToast(`${updated.type} cancelled`, 'info');
			} else {
				const isRestart = updated.error_type === 'server_restart';
				addToast(
					isRestart ? 'Server restarted — please retry' : updated.error || `${updated.type} failed`,
					'error'
				);
			}

			activeJobs.update((jobs) => jobs.filter((j) => j.job.id !== jobId));
		}
	};

	source.onerror = () => {
		errorCount++;
		if (errorCount >= MAX_POLL_ERRORS) {
			source.close();
			eventSources.delete(jobId);
			activeJobs.update((jobs) => jobs.filter((j) => j.job.id !== jobId));
			addToast('Lost connection to server', 'error');
		}
	};
}

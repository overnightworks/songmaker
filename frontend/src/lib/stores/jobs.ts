import { writable, get } from 'svelte/store';
import type { JobStatus } from '$lib/api/client';
import { JOB_TYPE_GENERATE } from '$lib/constants';
import { requestSongRefresh } from '$lib/stores/resourceSync';
import { addToast } from '$lib/stores/toast';

const MAX_POLL_ERRORS = 10;
const SERVER_RESTART_MESSAGE = 'Server restarted — please retry';

export interface ActiveJob {
	job: JobStatus;
	songId?: string;
	genId?: string;
	workerId?: string;
	mode?: string;
}

export const activeJobs = writable<ActiveJob[]>([]);

/**
 * The cause of the last failed generation, per song.
 *
 * A failed job leaves `activeJobs` right away, so without this its
 * error would only ever flash by in a toast. The song's take list keeps
 * showing the cause until the next generation starts or the user
 * dismisses it.
 */
export const generationFailures = writable<Record<string, string>>({});

export function dismissGenerationFailure(songId: string): void {
	generationFailures.update((failures) =>
		Object.fromEntries(Object.entries(failures).filter(([id]) => id !== songId))
	);
}

function failureMessage(job: JobStatus): string {
	if (job.error_type === 'server_restart') return SERVER_RESTART_MESSAGE;
	return job.error || `${job.type} failed`;
}

const eventSources = new Map<string, EventSource>();

export function trackJob(
	job: JobStatus,
	context: { songId?: string; genId?: string; workerId?: string; mode?: string }
): void {
	activeJobs.update((jobs) => [...jobs, { job, ...context }]);
	if (context.songId) dismissGenerationFailure(context.songId);
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
			const songId = get(activeJobs).find((j) => j.job.id === jobId)?.songId;

			if (updated.status === 'completed') {
				if (updated.type !== JOB_TYPE_GENERATE && songId) {
					void requestSongRefresh(songId);
				}
				addToast(`${updated.type} completed`, 'success');
			} else if (updated.status === 'partial') {
				if (updated.type !== JOB_TYPE_GENERATE && songId) {
					void requestSongRefresh(songId);
				}
				addToast(updated.error || `${updated.type} partially completed`, 'info');
			} else if (updated.status === 'cancelled') {
				addToast(`${updated.type} cancelled`, 'info');
			} else {
				const message = failureMessage(updated);
				if (songId && updated.type === JOB_TYPE_GENERATE) {
					generationFailures.update((failures) => ({ ...failures, [songId]: message }));
				}
				addToast(message, 'error');
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

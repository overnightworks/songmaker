import { writable, get } from 'svelte/store';
import { fetchJob, fetchSong, type JobStatus } from '$lib/api/client';
import { songList } from '$lib/stores/player';

const POLL_INTERVAL = 2000;
const MAX_POLL_ERRORS = 10;

export interface ActiveJob {
	job: JobStatus;
	songId?: string;
	genId?: string;
}

export const activeJobs = writable<ActiveJob[]>([]);

export function trackJob(job: JobStatus, context: { songId?: string; genId?: string }): void {
	activeJobs.update((jobs) => [...jobs, { job, ...context }]);
	pollJob(job.id);
}

async function pollJob(jobId: string): Promise<void> {
	let errorCount = 0;

	const poll = async (): Promise<void> => {
		try {
			const updated = await fetchJob(jobId);
			errorCount = 0;
			activeJobs.update((jobs) =>
				jobs.map((j) => (j.job.id === jobId ? { ...j, job: updated } : j))
			);

			if (updated.status === 'completed' || updated.status === 'failed') {
				if (updated.status === 'completed') {
					await refreshSongData(jobId);
				}
				setTimeout(() => {
					activeJobs.update((jobs) => jobs.filter((j) => j.job.id !== jobId));
				}, 5000);
				return;
			}

			setTimeout(poll, POLL_INTERVAL);
		} catch {
			errorCount++;
			if (errorCount >= MAX_POLL_ERRORS) {
				activeJobs.update((jobs) =>
					jobs.map((j) =>
						j.job.id === jobId
							? { ...j, job: { ...j.job, status: 'failed', error: 'Lost connection' } }
							: j
					)
				);
				setTimeout(() => {
					activeJobs.update((jobs) => jobs.filter((j) => j.job.id !== jobId));
				}, 5000);
				return;
			}
			setTimeout(poll, POLL_INTERVAL);
		}
	};

	setTimeout(poll, POLL_INTERVAL);
}

async function refreshSongData(jobId: string): Promise<void> {
	const jobs = get(activeJobs);
	const activeJob = jobs.find((j) => j.job.id === jobId);
	if (!activeJob?.songId) return;

	try {
		const updated = await fetchSong(activeJob.songId);
		songList.update((songs) => songs.map((s) => (s.id === updated.id ? updated : s)));
	} catch {
		// song refresh failed silently — user can manually reload
	}
}

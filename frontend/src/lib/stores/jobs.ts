import { writable, get } from 'svelte/store';
import { fetchJob, fetchSong, type JobStatus } from '$lib/api/client';
import { songList } from '$lib/stores/player';
import { addToast } from '$lib/stores/toast';

const POLL_INTERVAL_FAST = 2000;
const POLL_INTERVAL_SLOW = 8000;
const POLL_BACKOFF_AFTER = 30_000;
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
	const startTime = Date.now();

	function interval(): number {
		return Date.now() - startTime > POLL_BACKOFF_AFTER ? POLL_INTERVAL_SLOW : POLL_INTERVAL_FAST;
	}

	const poll = async (): Promise<void> => {
		try {
			const updated = await fetchJob(jobId);
			errorCount = 0;
			activeJobs.update((jobs) =>
				jobs.map((j) => (j.job.id === jobId ? { ...j, job: updated } : j))
			);

			if (
				updated.status === 'completed' ||
				updated.status === 'partial' ||
				updated.status === 'failed'
			) {
				if (updated.status === 'completed') {
					await refreshSongData(jobId);
					addToast(`${updated.type} completed`, 'success');
				} else if (updated.status === 'partial') {
					await refreshSongData(jobId);
					addToast(updated.error || `${updated.type} partially completed`, 'info');
				} else {
					const isRestart = updated.error_type === 'server_restart';
					addToast(
						isRestart
							? 'Server restarted — please retry'
							: (updated.error || `${updated.type} failed`),
						isRestart ? 'info' : 'error'
					);
				}
				setTimeout(() => {
					activeJobs.update((jobs) => jobs.filter((j) => j.job.id !== jobId));
				}, 5000);
				return;
			}

			setTimeout(poll, interval());
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
				addToast('Lost connection to server', 'error');
				setTimeout(() => {
					activeJobs.update((jobs) => jobs.filter((j) => j.job.id !== jobId));
				}, 5000);
				return;
			}
			setTimeout(poll, interval());
		}
	};

	setTimeout(poll, POLL_INTERVAL_FAST);
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

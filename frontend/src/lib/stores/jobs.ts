import { writable, get } from 'svelte/store';
import { fetchLastFailedGeneration, type JobStatus } from '$lib/api/client';
import { JOB_TYPE_GENERATE } from '$lib/constants';
import { requestSongRefresh } from '$lib/stores/resourceSync';
import { nextReconnectDelayMs } from '$lib/stores/sseReconnect';
import { addToast } from '$lib/stores/toast';

const MAX_POLL_ERRORS = 10;
const SERVER_RESTART_MESSAGE = 'Server restarted — please retry';

export interface ActiveJob {
	job: JobStatus;
	songId?: string;
	albumId?: string;
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

// Bumped whenever a song's failure is resolved live (dismissed, or a fresh
// generate starts). hydrateGenerationFailure captures the epoch before its
// fetch and discards a late-arriving result once it no longer matches --
// a live update always wins over the page-load hydration fetch below.
const hydrationEpoch = new Map<string, number>();

export function dismissGenerationFailure(songId: string): void {
	hydrationEpoch.set(songId, (hydrationEpoch.get(songId) ?? 0) + 1);
	generationFailures.update((failures) =>
		Object.fromEntries(Object.entries(failures).filter(([id]) => id !== songId))
	);
}

// Wipes the per-song failure causes -- called both by tests and, in
// production, by clearAuth() on logout/401 so the next session never
// sees another user's failure. Also forgets which songs have had a live
// resolution, so the next session's hydration fetches are unblocked too.
export function resetGenerationFailures(): void {
	generationFailures.set({});
	hydrationEpoch.clear();
}

function failureMessage(job: JobStatus): string {
	if (job.error_type === 'server_restart') return SERVER_RESTART_MESSAGE;
	return job.error || `${job.type} failed`;
}

/**
 * Recovers a song's failure banner after a reload or a later visit, when
 * the live SSE stream that would have reported it (see `streamJob` below)
 * is long gone. Queries the last failed generate job for the song; the
 * backend already suppresses it once a newer job or a newer non-archived
 * take exists.
 *
 * Once a song has had any live resolution this session (a dismiss, or a
 * fresh generate starting -- both bump its epoch), hydration for it is
 * skipped for the rest of the session: the live path is now the source of
 * truth and a dismiss must stick without a stale re-fetch reviving it. A
 * reload starts a fresh session (this module's state resets), so the fetch
 * runs again then. Never overwrites a failure a live update already set
 * (`songId in failures` check), and discards its result entirely once the
 * song's epoch has moved on from a live resolution while the fetch was in
 * flight.
 */
export async function hydrateGenerationFailure(songId: string): Promise<void> {
	if (songId in get(generationFailures)) return;
	if ((hydrationEpoch.get(songId) ?? 0) > 0) return;
	const result = await fetchLastFailedGeneration(songId).catch(() => null);
	if (!result?.job || (hydrationEpoch.get(songId) ?? 0) > 0) return;
	const message = failureMessage(result.job);
	generationFailures.update((failures) =>
		songId in failures ? failures : { ...failures, [songId]: message }
	);
}

const eventSources = new Map<string, EventSource>();
const reconnectTimers = new Map<string, ReturnType<typeof setTimeout>>();

function isTerminalJobStatus(status: JobStatus['status']): boolean {
	return (
		status === 'completed' || status === 'partial' || status === 'failed' || status === 'cancelled'
	);
}

function refreshSongAfterTerminalJob(job: JobStatus, songId: string | undefined): void {
	if (job.type !== JOB_TYPE_GENERATE && songId) {
		void requestSongRefresh(songId);
	}
}

function notifyTerminalJob(job: JobStatus, songId: string | undefined): void {
	if (job.status === 'completed') {
		refreshSongAfterTerminalJob(job, songId);
		addToast(`${job.type} completed`, 'success');
		return;
	}
	if (job.status === 'partial') {
		refreshSongAfterTerminalJob(job, songId);
		addToast(job.error || `${job.type} partially completed`, 'info');
		return;
	}
	if (job.status === 'cancelled') {
		addToast(`${job.type} cancelled`, 'info');
		return;
	}
	const message = failureMessage(job);
	if (songId && job.type === JOB_TYPE_GENERATE) {
		generationFailures.update((failures) => ({ ...failures, [songId]: message }));
	}
	addToast(message, 'error');
}

function completeTrackedJob(jobId: string, job: JobStatus, source: EventSource): void {
	source.close();
	eventSources.delete(jobId);
	const songId = get(activeJobs).find((active) => active.job.id === jobId)?.songId;
	notifyTerminalJob(job, songId);
	activeJobs.update((jobs) => jobs.filter((active) => active.job.id !== jobId));
}

export function trackJob(
	job: JobStatus,
	context: { songId?: string; albumId?: string; genId?: string; workerId?: string; mode?: string }
): void {
	const existing = get(activeJobs).some((active) => active.job.id === job.id);
	if (existing) {
		activeJobs.update((jobs) =>
			jobs.map((active) => (active.job.id === job.id ? { ...active, ...context, job } : active))
		);
		return;
	}
	activeJobs.update((jobs) => [...jobs, { job, ...context }]);
	if (context.songId && job.type === JOB_TYPE_GENERATE) dismissGenerationFailure(context.songId);
	streamJob(job.id);
}

export function removeJob(jobId: string): void {
	stopTracking(jobId);
	activeJobs.update((jobs) => jobs.filter((j) => j.job.id !== jobId));
}

export function stopTracking(jobId: string): void {
	const timer = reconnectTimers.get(jobId);
	if (timer !== undefined) {
		clearTimeout(timer);
		reconnectTimers.delete(jobId);
	}
	const source = eventSources.get(jobId);
	if (source) {
		source.close();
		eventSources.delete(jobId);
	}
}

/**
 * Opens the job's SSE connection and owns its reconnection: a dropped
 * connection closes itself here rather than leaning on the browser's flat
 * native EventSource retry (that flat retry across several concurrently
 * failing job streams is what produced the operator's ERR_QUIC storm --
 * issue #257) and reopens after `nextReconnectDelayMs`, counting up `attempt`
 * the same way `errorCount` used to. Any message resets the count, so a
 * connection that recovers goes back to the short delay on its next drop.
 */
function streamJob(jobId: string, attempt = 0): void {
	let currentAttempt = attempt;

	const source = new EventSource(`/api/jobs/${jobId}/stream`, { withCredentials: true });
	eventSources.set(jobId, source);

	source.onmessage = (event: MessageEvent) => {
		currentAttempt = 0;
		const updated: JobStatus = JSON.parse(event.data);

		activeJobs.update((jobs) => jobs.map((j) => (j.job.id === jobId ? { ...j, job: updated } : j)));

		if (isTerminalJobStatus(updated.status)) {
			completeTrackedJob(jobId, updated, source);
		}
	};

	source.onerror = () => {
		source.close();
		eventSources.delete(jobId);
		const nextAttempt = currentAttempt + 1;
		if (nextAttempt >= MAX_POLL_ERRORS) {
			activeJobs.update((jobs) => jobs.filter((j) => j.job.id !== jobId));
			addToast('Lost connection to server', 'error');
			return;
		}
		const delay = nextReconnectDelayMs(nextAttempt);
		reconnectTimers.set(
			jobId,
			setTimeout(() => {
				reconnectTimers.delete(jobId);
				streamJob(jobId, nextAttempt);
			}, delay)
		);
	};
}

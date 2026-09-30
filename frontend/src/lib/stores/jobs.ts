import { writable, get } from 'svelte/store';
import {
	fetchActiveGeneration,
	fetchJob,
	fetchLastFailedGeneration,
	type JobStatus
} from '$lib/api/client';
import { isNotFound } from '$lib/api/fetch';
import {
	GENERATE_TAKE_ARRIVAL_WAIT_MS,
	JOB_STREAM_MAX_CONNECTION_ERRORS,
	JOB_TYPE_GENERATE
} from '$lib/constants';
import { offline } from '$lib/stores/connectivity';
import { requestSongRefresh } from '$lib/stores/resourceSync';
import {
	ImmediateReopenGap,
	nextReconnectDelayMs,
	watchReconnectOpportunities
} from '$lib/stores/sseReconnect';
import { addToast } from '$lib/stores/toast';

const SERVER_RESTART_MESSAGE = 'Server restarted — please retry';

export interface ActiveJob {
	job: JobStatus;
	songId?: string;
	albumId?: string;
	genId?: string;
	workerId?: string;
	mode?: string;
	/** A generate job that ended with takes, held until they are in its song's list. */
	awaitingTakes?: boolean;
	/**
	 * The job's stream failed and has not spoken since, so `job` is only what
	 * it last said -- online as much as offline (#1161 R1).
	 */
	streamStale?: boolean;
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

/**
 * Where a job stream stands in its reconnection: `attempt` paces the backoff,
 * `spentFailures` counts what the give-up budget has used, and
 * `spendsOnFailure` says whether this connection's failure may use it.
 */
interface StreamRetry {
	attempt: number;
	spentFailures: number;
	spendsOnFailure: boolean;
}

const FRESH_STREAM: StreamRetry = { attempt: 1, spentFailures: 0, spendsOnFailure: true };

interface PendingReconnect {
	timer: ReturnType<typeof setTimeout>;
	attempt: number;
	spentFailures: number;
	reopenGap: ImmediateReopenGap;
}

const eventSources = new Map<string, EventSource>();
const pendingReconnects = new Map<string, PendingReconnect>();
const takeArrivalWaits = new Map<string, () => void>();
let stopWatchingReconnectOpportunities: (() => void) | null = null;

function isTerminalJobStatus(status: JobStatus['status']): boolean {
	return (
		status === 'completed' || status === 'partial' || status === 'failed' || status === 'cancelled'
	);
}

function endedWithTakes(job: JobStatus): boolean {
	return job.status === 'completed' || job.status === 'partial';
}

function notifyTerminalJob(job: JobStatus, songId: string | undefined): void {
	if (job.status === 'completed') {
		addToast(`${job.type} completed`, 'success');
		return;
	}
	if (job.status === 'partial') {
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

/**
 * A generate job that made takes stays tracked, with its end status, until a
 * song refresh its end asked for has run while the page could reach the
 * server: the job's card is what the musician sees until the take replaces
 * it, so letting the job go at once -- or when a refresh failed offline --
 * would leave a moment with neither (#1039 O3). The generate owner hides the
 * card as soon as the take is in the list; the wait, counted only while
 * online, bounds how long a refresh that never runs can keep it. The job says
 * it ended only when it goes, so a card still waiting for its take is the one
 * signal until then (#1106 N3).
 */
function keepUntilSongRefreshed(
	jobId: string,
	job: JobStatus,
	songId: string,
	songRefresh: Promise<void>
): void {
	activeJobs.update((jobs) =>
		jobs.map((active) => (active.job.id === jobId ? { ...active, awaitingTakes: true } : active))
	);
	const letGo = (): void => {
		removeJob(jobId);
		notifyTerminalJob(job, songId);
	};
	let bound: ReturnType<typeof setTimeout> | undefined;
	const stopWatchingConnectivity = offline.subscribe((isOffline) => {
		clearTimeout(bound);
		bound = isOffline ? undefined : setTimeout(letGo, GENERATE_TAKE_ARRIVAL_WAIT_MS);
	});
	const stopWaiting = (): void => {
		clearTimeout(bound);
		stopWatchingConnectivity();
	};
	takeArrivalWaits.set(jobId, stopWaiting);
	const stillWaiting = (): boolean => takeArrivalWaits.get(jobId) === stopWaiting;
	void refreshedWhileOnline(songId, songRefresh, stillWaiting).then(() => {
		if (stillWaiting()) letGo();
	});
}

async function refreshedWhileOnline(
	songId: string,
	songRefresh: Promise<void>,
	stillWaiting: () => boolean
): Promise<void> {
	await songRefresh;
	while (get(offline)) {
		await backOnline();
		if (!stillWaiting()) return;
		await requestSongRefresh(songId);
	}
}

function backOnline(): Promise<void> {
	return new Promise((resolve) => {
		const stop = offline.subscribe((isOffline) => {
			if (isOffline) return;
			queueMicrotask(() => stop());
			resolve();
		});
	});
}

// A job that made takes refreshes its song too, not only the
// `generation.created` resource event: that event can fall into a gap while
// the resource stream reconnects (a phone's screen going off), and the take
// would then stay missing until the next navigation (#1020). Both triggers are
// idempotent: the resource-sync owner refetches the song and skips a take it
// already has.
function completeTrackedJob(jobId: string, job: JobStatus): void {
	closeStream(jobId);
	const songId = get(activeJobs).find((active) => active.job.id === jobId)?.songId;
	if (songId && endedWithTakes(job)) {
		const songRefresh = requestSongRefresh(songId);
		if (job.type === JOB_TYPE_GENERATE) {
			keepUntilSongRefreshed(jobId, job, songId, songRefresh);
			return;
		}
	}
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

export async function hydrateActiveGeneration(songId: string): Promise<void> {
	const job = await fetchActiveGeneration(songId);
	if (job) trackJob(job, { songId });
}

export function removeJob(jobId: string): void {
	stopTracking(jobId);
	activeJobs.update((jobs) => jobs.filter((j) => j.job.id !== jobId));
}

function stopTracking(jobId: string): void {
	cancelPendingReconnect(jobId);
	takeArrivalWaits.get(jobId)?.();
	takeArrivalWaits.delete(jobId);
	closeStream(jobId);
}

function closeStream(jobId: string): void {
	eventSources.get(jobId)?.close();
	eventSources.delete(jobId);
}

function isTracked(jobId: string): boolean {
	return get(activeJobs).some((active) => active.job.id === jobId);
}

/**
 * Opens the job's SSE connection and owns its reconnection: a dropped
 * connection closes itself here rather than leaning on the browser's flat
 * native EventSource retry (that flat retry across several concurrently
 * failing job streams is what produced the operator's ERR_QUIC storm --
 * issue #257) and reopens after `nextReconnectDelayMs`, or at once when the
 * page gets a fresh chance to reach the server (`watchReconnectOpportunities`).
 *
 * The give-up budget counts only failures of timed retries while the page can
 * reach the server: a failure while `offline` says the connection is lost
 * never spends it, however many outages a take runs through (#1141), and a
 * reopen the page asked for (visible again, focus, back online) never spends
 * it either, so returning to the app during an outage cannot drop a running
 * job sooner (#1032). A connection that opens gives the budget back; a
 * message also puts the backoff back to its short first delay. When the
 * budget does run out online, the job is read again over REST
 * (`rereadAfterSpentBudget`) rather than dropped. `reopenGap` travels with the
 * job across every reopen, so the page's chances reopen it at most once per
 * gap however often the musician switches apps (#1099).
 */
function streamJob(
	jobId: string,
	retry: StreamRetry = FRESH_STREAM,
	reopenGap = new ImmediateReopenGap()
): void {
	let current = retry;

	const source = new EventSource(`/api/jobs/${jobId}/stream`, { withCredentials: true });
	eventSources.set(jobId, source);

	source.onopen = () => {
		current = { ...current, spentFailures: 0, spendsOnFailure: true };
	};

	source.onmessage = (event: MessageEvent) => {
		current = FRESH_STREAM;
		const updated: JobStatus = JSON.parse(event.data);

		activeJobs.update((jobs) =>
			jobs.map((active) => (active.job.id === jobId ? withFreshStatus(active, updated) : active))
		);

		if (isTerminalJobStatus(updated.status)) {
			completeTrackedJob(jobId, updated);
		}
	};

	source.onerror = () => {
		closeStream(jobId);
		markStreamStale(jobId);
		const spendsBudget = current.spendsOnFailure && !get(offline);
		const spentFailures = current.spentFailures + (spendsBudget ? 1 : 0);
		if (spentFailures >= JOB_STREAM_MAX_CONNECTION_ERRORS) {
			void rereadAfterSpentBudget(jobId, current.attempt, reopenGap);
			return;
		}
		scheduleReconnect(jobId, current.attempt, spentFailures, reopenGap);
	};
}

function withFreshStatus(active: ActiveJob, job: JobStatus): ActiveJob {
	const { streamStale: _wasStale, ...tracked } = active;
	return { ...tracked, job };
}

// A re-read end is final; a job the re-read finds still running stays stale
// until its reopened stream speaks, so the card does not flip live between
// two refused reopens.
function afterReread(active: ActiveJob, job: JobStatus): ActiveJob {
	return isTerminalJobStatus(job.status) ? withFreshStatus(active, job) : { ...active, job };
}

function markStreamStale(jobId: string): void {
	activeJobs.update((jobs) =>
		jobs.map((active) =>
			active.job.id === jobId && !active.streamStale ? { ...active, streamStale: true } : active
		)
	);
}

/**
 * The job stream failed its whole budget while the page was online, so the
 * job's own record answers instead: an ended job finishes as if its stream had
 * said so, a running one keeps its card and its stream starts a fresh budget,
 * and a re-read that fails for any other reason than a 404 (a lost network, a
 * 5xx, a 429) keeps following it. A job the server no longer knows goes
 * without a word of its own; its song refresh shows what is really there.
 */
async function rereadAfterSpentBudget(
	jobId: string,
	attempt: number,
	reopenGap: ImmediateReopenGap
): Promise<void> {
	let job: JobStatus;
	try {
		job = await fetchJob(jobId);
	} catch (err) {
		if (!isTracked(jobId)) return;
		if (isNotFound(err)) letUnknownJobGo(jobId);
		else scheduleReconnect(jobId, attempt, 0, reopenGap);
		return;
	}
	if (!isTracked(jobId)) return;
	activeJobs.update((jobs) =>
		jobs.map((active) => (active.job.id === jobId ? afterReread(active, job) : active))
	);
	if (isTerminalJobStatus(job.status)) completeTrackedJob(jobId, job);
	else scheduleReconnect(jobId, attempt, 0, reopenGap);
}

function letUnknownJobGo(jobId: string): void {
	const songId = get(activeJobs).find((active) => active.job.id === jobId)?.songId;
	removeJob(jobId);
	if (songId) void requestSongRefresh(songId);
}

function scheduleReconnect(
	jobId: string,
	attempt: number,
	spentFailures: number,
	reopenGap: ImmediateReopenGap
): void {
	const timer = setTimeout(() => retryAfterBackoff(jobId), nextReconnectDelayMs(attempt));
	pendingReconnects.set(jobId, { timer, attempt, spentFailures, reopenGap });
	stopWatchingReconnectOpportunities ??= watchReconnectOpportunities(reconnectAllWaitingJobs);
}

function retryAfterBackoff(jobId: string): void {
	const pending = takePendingReconnect(jobId);
	if (pending === undefined) return;
	const retry = {
		attempt: pending.attempt + 1,
		spentFailures: pending.spentFailures,
		spendsOnFailure: true
	};
	streamJob(jobId, retry, pending.reopenGap);
}

function reconnectNow(jobId: string): void {
	const pending = pendingReconnects.get(jobId);
	pending?.reopenGap.run(() => {
		cancelPendingReconnect(jobId);
		const retry = {
			attempt: pending.attempt,
			spentFailures: pending.spentFailures,
			spendsOnFailure: false
		};
		streamJob(jobId, retry, pending.reopenGap);
	});
}

function takePendingReconnect(jobId: string): PendingReconnect | undefined {
	const pending = pendingReconnects.get(jobId);
	cancelPendingReconnect(jobId);
	return pending;
}

function reconnectAllWaitingJobs(): void {
	for (const jobId of [...pendingReconnects.keys()]) reconnectNow(jobId);
}

function cancelPendingReconnect(jobId: string): void {
	const pending = pendingReconnects.get(jobId);
	if (pending === undefined) return;
	clearTimeout(pending.timer);
	pendingReconnects.delete(jobId);
	if (pendingReconnects.size > 0) return;
	stopWatchingReconnectOpportunities?.();
	stopWatchingReconnectOpportunities = null;
}

import { derived, get, writable } from 'svelte/store';
import { fetchAlbumCoverSuggestions, type CoverSuggestionDiscard } from '$lib/api/albums';
import { describeFailure, NetworkError } from '$lib/api/fetch';
import type { CoverSuggestionsResponse, JobItem } from '$lib/api/types';
import { ALBUM_COVER_SUGGESTION_FAILED_FALLBACK } from '$lib/constants';
import { reloadWhileUnreachable } from '$lib/stores/connectivity';
import { releaseCoverSuggestions } from '$lib/stores/coverRuns';
import { activeJobs, trackJob } from '$lib/stores/jobs';

/**
 * The one owner of the watched album's cover state: its suggestions, its run
 * and whether a cover save is under way. The cover editor and the closed
 * cover's mark both read it, so two snapshots never overwrite each other. It
 * only reads: stopping and deleting stays with ×, USE and Upload.
 */
interface CoverActivity {
	albumId: string;
	data: CoverSuggestionsResponse | null;
	failure: string | null;
	unreachable: boolean;
	limitNote: string | null;
	isLoading: boolean;
	/** The unreachable reloads ran out; the person may retry. */
	reloadsExhausted: boolean;
	/** The run this page knows and would stop on a discard. */
	runId: string | null;
}

type CoverActivityOutcome = Pick<CoverActivity, 'failure' | 'unreachable' | 'limitNote'>;

const COVER_ACTIVITY_SETTLED: CoverActivityOutcome = {
	failure: null,
	unreachable: false,
	limitNote: null
};

const NOTHING_KNOWN: CoverSuggestionDiscard = { suggestionIds: [], jobIds: [] };

export const coverActivity = writable<CoverActivity | null>(null);

/** The album a Use save is under way for; it outlives the editor that began it. */
export const savingCoverAlbumId = writable<string | null>(null);

/** What the closed cover and the editor's stage say about the album's run. */
interface CoverStanding {
	albumId: string;
	running: boolean;
	startedAt: string | null;
	waiting: number;
}

export const coverStanding = derived(
	[coverActivity, activeJobs],
	([activity, jobs]): CoverStanding | null => {
		if (!activity) return null;
		const active = jobs.find((entry) => entry.albumId === activity.albumId) ?? null;
		const latest = activity.data?.job ?? null;
		const running = Boolean(active) || (latest !== null && isRunning(latest));
		return {
			albumId: activity.albumId,
			running,
			startedAt: active?.job.started_at ?? latest?.started_at ?? null,
			waiting: activity.data?.suggestions.length ?? 0
		};
	}
);

let watchedAlbumId: string | null = null;
let latestRead = 0;
let unreachableReloads: ReturnType<typeof reloadWhileUnreachable> | null = null;

function isRunning(job: JobItem): boolean {
	return job.status === 'queued' || job.status === 'running';
}

/**
 * Watches an album's cover state: reads it now, again whenever the page comes
 * back to the foreground, and again when a run this page follows ends. Nothing
 * polls in the background. Returns the stop.
 */
export function watchCoverActivity(albumId: string): () => void {
	watchedAlbumId = albumId;
	latestRead += 1;
	const reloads = reloadWhileUnreachable(() => void readCoverActivity(albumId));
	unreachableReloads = reloads;
	coverActivity.set({
		albumId,
		data: null,
		...COVER_ACTIVITY_SETTLED,
		isLoading: true,
		reloadsExhausted: false,
		runId: null
	});
	void readCoverActivity(albumId);

	const readWhenForeground = (): void => {
		if (document.visibilityState === 'visible') void readCoverActivity(albumId);
	};
	document.addEventListener('visibilitychange', readWhenForeground);
	window.addEventListener('focus', readWhenForeground);
	const stopRunWatch = readWhenRunEnds(albumId);

	return () => {
		document.removeEventListener('visibilitychange', readWhenForeground);
		window.removeEventListener('focus', readWhenForeground);
		stopRunWatch();
		reloads.dispose();
		if (watchedAlbumId !== albumId) return;
		watchedAlbumId = null;
		unreachableReloads = null;
		latestRead += 1;
	};
}

function readWhenRunEnds(albumId: string): () => void {
	let followed = false;
	return activeJobs.subscribe((jobs) => {
		if (jobs.some((entry) => entry.albumId === albumId)) {
			followed = true;
			return;
		}
		if (!followed) return;
		followed = false;
		void readCoverActivity(albumId);
	});
}

/**
 * Reads the album's suggestions and run. An answer from before a newer read,
 * a stop or another album is dropped. A running job is handed to the job
 * tracker.
 */
export async function readCoverActivity(albumId: string): Promise<void> {
	if (albumId !== watchedAlbumId) return;
	const read = ++latestRead;
	updateCoverActivity(albumId, (state) => ({ ...state, isLoading: true, reloadsExhausted: false }));
	try {
		const response = await fetchAlbumCoverSuggestions(albumId);
		if (read !== latestRead || albumId !== watchedAlbumId) return;
		const running = response.job && isRunning(response.job) ? response.job : null;
		coverActivity.set({
			albumId,
			data: response,
			...COVER_ACTIVITY_SETTLED,
			isLoading: false,
			reloadsExhausted: false,
			runId: running?.id ?? null
		});
		unreachableReloads?.stop();
		if (running) trackJob(running, { albumId });
	} catch (error) {
		if (read !== latestRead || albumId !== watchedAlbumId) return;
		showCoverActivityFailure(albumId, error, { keepData: false });
	}
}

/** Shows how a read or a Suggest failed; an unreachable server is retried. */
export function showCoverActivityFailure(
	albumId: string,
	error: unknown,
	options: { keepData: boolean }
): void {
	const outcome: CoverActivityOutcome =
		error instanceof NetworkError
			? { ...COVER_ACTIVITY_SETTLED, unreachable: true }
			: {
					...COVER_ACTIVITY_SETTLED,
					failure: describeFailure(error, ALBUM_COVER_SUGGESTION_FAILED_FALLBACK)
				};
	updateCoverActivity(albumId, (state) => ({
		...state,
		...outcome,
		data: options.keepData ? state.data : null,
		isLoading: false
	}));
	if (!outcome.unreachable) {
		unreachableReloads?.stop();
		return;
	}
	const reloadsExhausted = unreachableReloads?.afterNetworkFailure() === 'exhausted';
	updateCoverActivity(albumId, (state) => ({ ...state, reloadsExhausted }));
}

export function retryCoverActivity(albumId: string): void {
	updateCoverActivity(albumId, (state) => ({ ...state, ...COVER_ACTIVITY_SETTLED }));
	void readCoverActivity(albumId);
}

export function updateCoverActivity(
	albumId: string,
	update: (state: CoverActivity) => CoverActivity
): void {
	coverActivity.update((state) => (state?.albumId === albumId ? update(state) : state));
}

/**
 * Suggest was pressed. A read still on its way is dropped, so its older
 * answer cannot erase the job Suggest creates; the page waits on the POST.
 */
export function beginCoverSuggestion(albumId: string): void {
	latestRead += 1;
	unreachableReloads?.stop();
	updateCoverActivity(albumId, (state) => ({
		...state,
		...COVER_ACTIVITY_SETTLED,
		isLoading: true
	}));
}

/** Follows a run this page just started or found: tracked, and known to a discard. */
export function followCoverRun(job: JobItem, albumId: string): void {
	trackJob(job, { albumId });
	updateCoverActivity(albumId, (state) => ({ ...state, runId: job.id }));
}

/**
 * What ×, USE and Upload release: the suggestions shown and the run this page
 * follows. A run it has not learned of yet keeps going and waits.
 */
export function knownCoverSuggestions(albumId: string): CoverSuggestionDiscard {
	const state = get(coverActivity);
	if (state?.albumId !== albumId) return NOTHING_KNOWN;
	return {
		suggestionIds: state.data?.suggestions.map((suggestion) => suggestion.id) ?? [],
		jobIds: state.runId ? [state.runId] : []
	};
}

/**
 * What a save that finished releases: the suggestions known when it began and
 * the run known now, since a run whose answer came during the save is followed
 * by then.
 */
export function knownAfterSave(
	albumId: string,
	knownAtStart: CoverSuggestionDiscard
): CoverSuggestionDiscard {
	return {
		suggestionIds: knownAtStart.suggestionIds,
		jobIds: knownCoverSuggestions(albumId).jobIds
	};
}

/**
 * Stops the run and deletes the suggestions a discard names. A read answering
 * from before the stop would track the job being cancelled again, so it is
 * dropped; a stop that fails leaves the run known.
 */
export async function discardCoverSuggestions(
	albumId: string,
	known: CoverSuggestionDiscard
): Promise<void> {
	const runToStop = known.jobIds[0] ?? null;
	if (runToStop) {
		latestRead += 1;
		updateCoverActivity(albumId, (state) => ({ ...state, runId: null }));
	}
	try {
		await releaseCoverSuggestions(albumId, known);
	} catch (error) {
		if (runToStop) updateCoverActivity(albumId, (state) => ({ ...state, runId: runToStop }));
		throw error;
	}
}

export function beginCoverSave(albumId: string): void {
	savingCoverAlbumId.set(albumId);
}

export function endCoverSave(albumId: string): void {
	savingCoverAlbumId.update((saving) => (saving === albumId ? null : saving));
}

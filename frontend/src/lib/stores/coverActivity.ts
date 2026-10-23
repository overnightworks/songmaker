import { derived, get, writable } from 'svelte/store';
import { fetchAlbumCoverSuggestions, type CoverSuggestionDiscard } from '$lib/api/albums';
import { describeFailure, NetworkError } from '$lib/api/fetch';
import type { CoverSuggestionsResponse, JobItem } from '$lib/api/types';
import { ALBUM_COVER_SUGGESTION_FAILED_FALLBACK } from '$lib/constants';
import { reloadWhileUnreachable } from '$lib/stores/connectivity';
import {
	discardMarkOf,
	markCoverSuggestionsDiscarded,
	namesNothing,
	releaseCoverSuggestions
} from '$lib/stores/coverRuns';
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
	/** A Suggest POST is on its way; no read may end the wait before it answers. */
	suggesting: boolean;
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

/** The albums a cover save is under way for; each outlives the editor that began it. */
export const savingCoverAlbumIds = writable<ReadonlySet<string>>(new Set());

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
let unreachableReloads: ReturnType<typeof reloadWhileUnreachable> | null = null;

/**
 * Each album's newest read. A stop, a Suggest or a discard on one album drops
 * only that album's reads still on their way, never another album's.
 */
const newestReads = new Map<string, number>();

function supersedeReads(albumId: string): number {
	const read = (newestReads.get(albumId) ?? 0) + 1;
	newestReads.set(albumId, read);
	return read;
}

function isNewestRead(albumId: string, read: number): boolean {
	return newestReads.get(albumId) === read && albumId === watchedAlbumId;
}

/** The unreachable reloads belong to the watched album alone. */
function reloadsOf(albumId: string): ReturnType<typeof reloadWhileUnreachable> | null {
	return albumId === watchedAlbumId ? unreachableReloads : null;
}

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
	supersedeReads(albumId);
	const reloads = reloadWhileUnreachable(() => void readCoverActivity(albumId));
	unreachableReloads = reloads;
	coverActivity.set({
		albumId,
		data: null,
		...COVER_ACTIVITY_SETTLED,
		isLoading: true,
		suggesting: false,
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
		supersedeReads(albumId);
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
	const read = supersedeReads(albumId);
	updateCoverActivity(albumId, (state) => ({ ...state, isLoading: true, reloadsExhausted: false }));
	try {
		const response = await fetchAlbumCoverSuggestions(albumId);
		if (!isNewestRead(albumId, read)) return;
		const running = response.job && isRunning(response.job) ? response.job : null;
		coverActivity.update((state) => ({
			albumId,
			data: response,
			...COVER_ACTIVITY_SETTLED,
			isLoading: state?.albumId === albumId && state.suggesting,
			suggesting: state?.albumId === albumId && state.suggesting,
			reloadsExhausted: false,
			runId: running?.id ?? null
		}));
		reloadsOf(albumId)?.stop();
		if (running) trackJob(running, { albumId });
	} catch (error) {
		if (!isNewestRead(albumId, read)) return;
		showCoverActivityFailure(albumId, error, { keepData: true });
		updateCoverActivity(albumId, (state) => ({ ...state, isLoading: state.suggesting }));
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
	const reloads = reloadsOf(albumId);
	if (!outcome.unreachable) {
		reloads?.stop();
		return;
	}
	const reloadsExhausted = reloads?.afterNetworkFailure() === 'exhausted';
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

/** A Suggest on its way, named by the discard mark it began under. */
type CoverAsk = number;

/**
 * Suggest was pressed. A read still on its way is dropped, so its older
 * answer cannot erase the job Suggest creates; the page waits on the POST.
 * Returns the ask, which a later ×, USE or Upload retires.
 */
export function beginCoverSuggestion(albumId: string): CoverAsk {
	supersedeReads(albumId);
	reloadsOf(albumId)?.stop();
	updateCoverActivity(albumId, (state) => ({
		...state,
		...COVER_ACTIVITY_SETTLED,
		isLoading: true,
		suggesting: true
	}));
	return discardMarkOf(albumId);
}

/** A retired ask releases what it made and changes nothing of what came after. */
export function isCoverAskRetired(albumId: string, ask: CoverAsk): boolean {
	return discardMarkOf(albumId) !== ask;
}

/** The Suggest POST answered or failed; a read may end the wait again. */
export function endCoverSuggestion(albumId: string): void {
	updateCoverActivity(albumId, (state) => ({ ...state, suggesting: false }));
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
 * What a save that finished releases: the suggestions and runs known when it
 * began, and any run learned of since for the same album, since a run whose
 * answer came during the save is followed by then.
 */
export function knownAfterSave(
	albumId: string,
	knownAtStart: CoverSuggestionDiscard
): CoverSuggestionDiscard {
	return {
		suggestionIds: knownAtStart.suggestionIds,
		jobIds: [...new Set([...knownAtStart.jobIds, ...knownCoverSuggestions(albumId).jobIds])]
	};
}

/**
 * What ×, USE and Upload do: retire the ask still on its way, so it frees
 * Suggest now and stops its run as it answers; stop the run and delete the
 * suggestions the discard names, if it names any, then read the state again
 * whatever the outcome. A read answering from before the stop would track the
 * job being cancelled again, and one sent before the delete would keep the
 * deleted suggestions, so both are dropped; a stop that fails leaves the run
 * known.
 */
export async function discardCoverSuggestions(
	albumId: string,
	known: CoverSuggestionDiscard
): Promise<void> {
	markCoverSuggestionsDiscarded(albumId);
	updateCoverActivity(albumId, (state) =>
		state.suggesting ? { ...state, suggesting: false, isLoading: false } : state
	);
	if (namesNothing(known)) return;
	const runToStop = known.jobIds[0] ?? null;
	if (runToStop) {
		supersedeReads(albumId);
		updateCoverActivity(albumId, (state) => ({ ...state, runId: null }));
	}
	try {
		await releaseCoverSuggestions(albumId, known);
	} catch (error) {
		if (runToStop) updateCoverActivity(albumId, (state) => ({ ...state, runId: runToStop }));
		throw error;
	} finally {
		void readCoverActivity(albumId);
	}
}

export function beginCoverSave(albumId: string): void {
	savingCoverAlbumIds.update((saving) => new Set(saving).add(albumId));
}

export function endCoverSave(albumId: string): void {
	savingCoverAlbumIds.update((saving) => {
		const remaining = new Set(saving);
		remaining.delete(albumId);
		return remaining;
	});
}

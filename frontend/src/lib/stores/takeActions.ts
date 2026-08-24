import { derived, get, writable } from 'svelte/store';
import {
	fetchSong,
	keepGeneration,
	pickGeneration,
	rateGeneration,
	scoreGeneration,
	unkeepGeneration,
	unpickGeneration
} from '$lib/api/client';
import { JOB_TYPE_SCORE, TAKE_RESCORE_QUEUED_TOAST } from '$lib/constants';
import { pinnedSeed } from '$lib/stores/editor';
import { activeJobs, trackJob } from '$lib/stores/jobs';
import { upsertSongInList } from '$lib/stores/libraryData';
import { addToast } from '$lib/stores/toast';

// The one mutation owner for a generation's judged state (pick, keep, rating,
// pinned seed, re-score) shared by every surface that judges a take. Each
// mutation refreshes the song from the server and folds it back into songList via
// upsertSongInList, so a take opened outside the album/library walk (a
// playlist entry, a shared link) still lands in the list instead of being
// silently dropped.

async function refreshSong(songId: string): Promise<void> {
	const updated = await fetchSong(songId);
	upsertSongInList(updated);
}

// Returns whether the pick actually landed — a failed request still only
// toasts here rather than throwing (every existing caller relies on that),
// but curation's auto-advance (NowPlaying.svelte) needs to tell a real pick
// from a swallowed failure before it moves on to the next song.
export async function setPick(songId: string, genId: string, picked: boolean): Promise<boolean> {
	try {
		if (picked) await pickGeneration(genId);
		else await unpickGeneration(genId);
		await refreshSong(songId);
		return true;
	} catch (e) {
		addToast(e instanceof Error ? e.message : 'Pick failed', 'error');
		return false;
	}
}

export async function setKeep(songId: string, genId: string, kept: boolean): Promise<void> {
	try {
		if (kept) await keepGeneration(genId);
		else await unkeepGeneration(genId);
		await refreshSong(songId);
	} catch (e) {
		addToast(e instanceof Error ? e.message : 'Keep failed', 'error');
	}
}

export async function rate(
	songId: string,
	genId: string,
	rating: number,
	notes: string = ''
): Promise<void> {
	try {
		await rateGeneration(genId, rating, notes);
		await refreshSong(songId);
		addToast('Rating saved', 'success');
	} catch (e) {
		addToast(e instanceof Error ? e.message : 'Rating failed', 'error');
	}
}

// A take is marked as re-scoring from the moment the request leaves, not from
// the moment a job comes back: the server does not deduplicate scoring jobs, so
// a second click during the round trip would buy a second run of the whole
// scorer pipeline. trackJob takes over synchronously on success, which keeps
// rescoringTakeIds continuous across the handover.
const rescoreRequestsInFlight = writable(new Set<string>());

function markRequestInFlight(genId: string): void {
	rescoreRequestsInFlight.update((ids) => new Set(ids).add(genId));
}

function clearRequestInFlight(genId: string): void {
	rescoreRequestsInFlight.update((ids) => {
		const remaining = new Set(ids);
		remaining.delete(genId);
		return remaining;
	});
}

// Scoring runs as a background job, so this returns once the job is accepted,
// not once the take has its new scores. The job's own completion refreshes the
// song (stores/jobs.ts), which is what puts the fresh scores and whisper cues
// on the take.
export async function rescore(songId: string, genId: string): Promise<void> {
	if (get(rescoreRequestsInFlight).has(genId)) return;
	markRequestInFlight(genId);
	try {
		const job = await scoreGeneration(genId);
		trackJob(job, { songId, genId });
		addToast(TAKE_RESCORE_QUEUED_TOAST, 'info');
	} catch (e) {
		addToast(e instanceof Error ? e.message : 'Re-score failed', 'error');
	} finally {
		clearRequestInFlight(genId);
	}
}

// Which takes the user is still waiting on a re-score for: the request is in
// flight, or its job is.
export const rescoringTakeIds = derived(
	[activeJobs, rescoreRequestsInFlight],
	([jobs, inFlight]) => {
		const ids = new Set(inFlight);
		for (const entry of jobs) {
			if (entry.job.type === JOB_TYPE_SCORE && entry.genId) ids.add(entry.genId);
		}
		return ids;
	}
);

export function pinSeed(seed: number): void {
	pinnedSeed.set(seed);
	addToast(`Seed ${seed} pinned for next generation`, 'success');
}

import { derived } from 'svelte/store';
import {
	fetchSong,
	keepGeneration,
	pickGeneration,
	rateGeneration,
	scoreGeneration,
	unkeepGeneration,
	unpickGeneration
} from '$lib/api/client';
import { JOB_TYPE_SCORE, TAKE_RESCORING_LABEL } from '$lib/constants';
import { pinnedSeed } from '$lib/stores/editor';
import { activeJobs, trackJob } from '$lib/stores/jobs';
import { upsertSongInList } from '$lib/stores/player';
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

export async function setPick(songId: string, genId: string, picked: boolean): Promise<void> {
	try {
		if (picked) await pickGeneration(genId);
		else await unpickGeneration(genId);
		await refreshSong(songId);
	} catch (e) {
		addToast(e instanceof Error ? e.message : 'Pick failed', 'error');
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

// Scoring runs as a background job, so this returns once the job is accepted,
// not once the take has its new scores. The job's own completion refreshes the
// song (stores/jobs.ts), which is what puts the fresh scores and whisper cues
// on the take.
export async function rescore(songId: string, genId: string): Promise<void> {
	try {
		const job = await scoreGeneration(genId);
		trackJob(job, { songId, genId });
		addToast(TAKE_RESCORING_LABEL, 'info');
	} catch (e) {
		addToast(e instanceof Error ? e.message : 'Re-score failed', 'error');
	}
}

// Which takes the user is still waiting on a re-score for.
export const rescoringTakeIds = derived(activeJobs, (jobs) => {
	const ids = new Set<string>();
	for (const entry of jobs) {
		if (entry.job.type === JOB_TYPE_SCORE && entry.genId) ids.add(entry.genId);
	}
	return ids;
});

export function pinSeed(seed: number): void {
	pinnedSeed.set(seed);
	addToast(`Seed ${seed} pinned for next generation`, 'success');
}

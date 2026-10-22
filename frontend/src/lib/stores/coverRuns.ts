import { ApiError } from '$lib/api/fetch';
import { cancelJob } from '$lib/api/jobs';
import { removeJob } from '$lib/stores/jobs';

const HTTP_CONFLICT = 409;

const discardMarks = new Map<string, number>();
const latestAskMarks = new Map<string, number>();

/**
 * Stops a cover suggestion run and stops following it. A run that already
 * ended answers 409, which is the outcome asked for; any other failure leaves
 * the run going and is raised.
 */
export async function stopCoverRun(jobId: string): Promise<void> {
	try {
		await cancelJob(jobId);
	} catch (error) {
		const alreadyEnded = error instanceof ApiError && error.status === HTTP_CONFLICT;
		if (!alreadyEnded) throw error;
	}
	removeJob(jobId);
}

/**
 * Records that ×, USE or Upload released this album's suggestions. A Suggest
 * whose POST answers after the mark was taken is stopped as it arrives.
 */
export function markCoverSuggestionsDiscarded(albumId: string): void {
	discardMarks.set(albumId, discardMarkOf(albumId) + 1);
}

/**
 * Records that a Suggest is being asked for on this album and returns the
 * discard mark it was asked under.
 */
export function recordCoverSuggestionAsked(albumId: string): number {
	const mark = discardMarkOf(albumId);
	latestAskMarks.set(albumId, mark);
	return mark;
}

/**
 * Whether a Suggest was asked for after the discard that followed `mark`. The
 * only way to delete suggestions is album-wide, so a late cleanup of an older
 * run must not delete the suggestions that Suggest has made since.
 */
export function coverSuggestionAskedAfter(albumId: string, mark: number): boolean {
	return (latestAskMarks.get(albumId) ?? mark) > mark;
}

export function discardMarkOf(albumId: string): number {
	return discardMarks.get(albumId) ?? 0;
}

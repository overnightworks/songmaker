import type { CoverSuggestionRefusal, JobItem } from '#lib/api/types.ts';

/** The one of the agent's four problems a cover suggestion ended with or was refused for. */
export type CoverProblem = CoverSuggestionRefusal['problem'];

export const COVER_PROBLEM_TEXTS: Record<CoverProblem, string> = {
	busy: 'Cover suggestions are busy. Try again when Suggest opens.',
	not_enabled: 'Cover suggestions are not enabled for your account. Ask an admin to enable them.',
	unavailable: 'Cover suggestions are unavailable right now. Try again later.',
	sign_in_again: 'Log in again to get cover suggestions'
};

const COVER_PROBLEMS: ReadonlySet<string> = new Set(Object.keys(COVER_PROBLEM_TEXTS));
// Only the person can end these two, so they hold only for the run this page followed:
// a later load, a new sign-in or joining the group starts with Suggest open again.
const PERSONAL_PROBLEMS: ReadonlySet<CoverProblem> = new Set(['not_enabled', 'sign_in_again']);
const MS_PER_SECOND = 1000;

function asCoverProblem(value: unknown): CoverProblem | null {
	return typeof value === 'string' && COVER_PROBLEMS.has(value) ? (value as CoverProblem) : null;
}

/** The problem a 403 or 503 at the Suggest click names under `detail`; null for any other body. */
export function coverRefusalProblem(detail: unknown): CoverProblem | null {
	if (typeof detail !== 'object' || detail === null) return null;
	return asCoverProblem((detail as Partial<CoverSuggestionRefusal>).problem);
}

/** Whole seconds until a busy run's wait ends, counted from when the run ended and never above the wait it was given. */
export function coverBusyWaitSeconds(job: JobItem | null, now: number): number {
	const wait = job?.error_type === 'busy' ? (job.retry_after_seconds ?? 0) : 0;
	if (wait <= 0 || !job?.completed_at) return 0;
	const opensAt = Date.parse(job.completed_at) + wait * MS_PER_SECOND;
	return Math.min(wait, Math.max(0, Math.ceil((opensAt - now) / MS_PER_SECOND)));
}

/**
 * What the latest run's end says on this load. Any failure that is not one of
 * the four reads unavailable.
 */
export function coverRunProblem(
	job: JobItem | null,
	seen: { followed: boolean },
	now: number
): CoverProblem | null {
	if (job?.status !== 'failed') return null;
	const problem = asCoverProblem(job.error_type) ?? 'unavailable';
	if (problem === 'busy') return coverBusyWaitSeconds(job, now) > 0 ? problem : null;
	if (PERSONAL_PROBLEMS.has(problem) && !seen.followed) return null;
	return problem;
}

export function coverProblemClosesSuggest(problem: CoverProblem | null): boolean {
	return problem !== null && problem !== 'unavailable';
}

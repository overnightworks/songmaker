import { get } from 'svelte/store';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '$lib/api/fetch';
import type { JobItem } from '$lib/api/types';
import {
	coverSuggestionAskedAfter,
	discardMarkOf,
	markCoverSuggestionsDiscarded,
	recordCoverSuggestionAsked,
	stopCoverRun
} from './coverRuns';
import { activeJobs } from './jobs';

const cancelJob = vi.fn();
vi.mock('$lib/api/jobs', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/jobs')>()),
	cancelJob: (...args: unknown[]) => cancelJob(...args)
}));

function coverJob(): JobItem {
	return { id: 'cover-job', type: 'cover', status: 'running', progress: 0 };
}

beforeEach(() => {
	cancelJob.mockReset().mockResolvedValue({ ...coverJob(), status: 'cancelled' });
	activeJobs.set([{ job: coverJob(), albumId: 'a-local' }]);
});

describe('stopCoverRun', () => {
	it('cancels the run and stops following it', async () => {
		await stopCoverRun('cover-job');

		expect(cancelJob).toHaveBeenCalledWith('cover-job');
		expect(get(activeJobs)).toEqual([]);
	});

	it('treats a run that already ended as stopped', async () => {
		cancelJob.mockRejectedValue(
			new ApiError(409, 'Job already finished', '/api/jobs/cover-job/cancel')
		);

		await stopCoverRun('cover-job');

		expect(get(activeJobs)).toEqual([]);
	});

	it('raises any other failure and keeps following the run', async () => {
		cancelJob.mockRejectedValue(new ApiError(500, 'Server error', '/api/jobs/cover-job/cancel'));

		await expect(stopCoverRun('cover-job')).rejects.toBeInstanceOf(ApiError);

		expect(get(activeJobs)).toHaveLength(1);
	});
});

describe('discard marks', () => {
	it('moves only the marked album', () => {
		const before = discardMarkOf('a-marked');
		const otherBefore = discardMarkOf('a-other');

		markCoverSuggestionsDiscarded('a-marked');

		expect(discardMarkOf('a-marked')).toBe(before + 1);
		expect(discardMarkOf('a-other')).toBe(otherBefore);
	});
});

describe('coverSuggestionAskedAfter', () => {
	it('is false for a Suggest asked before the discard it is compared with', () => {
		const markAtAsking = recordCoverSuggestionAsked('a-asked-before');
		markCoverSuggestionsDiscarded('a-asked-before');

		expect(coverSuggestionAskedAfter('a-asked-before', markAtAsking)).toBe(false);
	});

	it('is true once a Suggest was asked after that discard', () => {
		const markAtFirstAsking = recordCoverSuggestionAsked('a-asked-after');
		markCoverSuggestionsDiscarded('a-asked-after');
		recordCoverSuggestionAsked('a-asked-after');

		expect(coverSuggestionAskedAfter('a-asked-after', markAtFirstAsking)).toBe(true);
	});

	it('is false for an album nothing was asked on', () => {
		expect(coverSuggestionAskedAfter('a-never-asked', 0)).toBe(false);
	});
});

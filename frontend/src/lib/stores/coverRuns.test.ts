import { get } from 'svelte/store';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '$lib/api/fetch';
import type { JobItem } from '$lib/api/types';
import {
	discardMarkOf,
	markCoverSuggestionsDiscarded,
	releaseCoverSuggestions,
	stopCoverRun
} from './coverRuns';
import { activeJobs } from './jobs';

const cancelJob = vi.fn();
vi.mock('$lib/api/jobs', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/jobs')>()),
	cancelJob: (...args: unknown[]) => cancelJob(...args)
}));
const discardAlbumCoverSuggestions = vi.fn();
vi.mock('$lib/api/albums', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/albums')>()),
	discardAlbumCoverSuggestions: (...args: unknown[]) => discardAlbumCoverSuggestions(...args)
}));

function coverJob(): JobItem {
	return { id: 'cover-job', type: 'cover', status: 'running', progress: 0 };
}

beforeEach(() => {
	cancelJob.mockReset().mockResolvedValue({ ...coverJob(), status: 'cancelled' });
	discardAlbumCoverSuggestions.mockReset().mockResolvedValue(undefined);
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

describe('releaseCoverSuggestions', () => {
	it('stops the named run before it discards what it names', async () => {
		const discard = { suggestionIds: ['one'], jobIds: ['cover-job'] };

		await releaseCoverSuggestions('a-local', discard);

		expect(discardAlbumCoverSuggestions).toHaveBeenCalledWith('a-local', discard);
		expect(cancelJob.mock.invocationCallOrder[0]).toBeLessThan(
			discardAlbumCoverSuggestions.mock.invocationCallOrder[0]
		);
	});

	it('sends nothing when it names nothing', async () => {
		await releaseCoverSuggestions('a-local', { suggestionIds: [], jobIds: [] });

		expect(cancelJob).not.toHaveBeenCalled();
		expect(discardAlbumCoverSuggestions).not.toHaveBeenCalled();
	});
});

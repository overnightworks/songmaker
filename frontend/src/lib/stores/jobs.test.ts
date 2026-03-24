import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';

vi.mock('$lib/api/client', () => ({
	fetchJob: vi.fn(),
	fetchSong: vi.fn()
}));

vi.mock('$lib/stores/player', () => {
	const { writable } = require('svelte/store');
	return { songList: writable([]) };
});

import { activeJobs, trackJob } from './jobs';
import type { JobStatus } from '$lib/api/client';

function makeJob(overrides: Partial<JobStatus> = {}): JobStatus {
	return {
		id: 'j1',
		type: 'generate',
		status: 'queued',
		progress: 0,
		error: null,
		started_at: null,
		completed_at: null,
		...overrides
	};
}

beforeEach(() => {
	activeJobs.set([]);
	vi.clearAllMocks();
	vi.useFakeTimers();
});

afterEach(() => {
	vi.restoreAllMocks();
	vi.useRealTimers();
});

describe('jobs store', () => {
	it('trackJob adds job to activeJobs', () => {
		const job = makeJob();
		trackJob(job, { songId: 's1' });
		const jobs = get(activeJobs);
		expect(jobs).toHaveLength(1);
		expect(jobs[0].job.id).toBe('j1');
		expect(jobs[0].songId).toBe('s1');
	});

	it('trackJob starts polling and updates on completion', async () => {
		const { fetchJob } = await import('$lib/api/client');
		const mockFetch = vi.mocked(fetchJob);
		mockFetch.mockResolvedValue(makeJob({ status: 'completed', progress: 1.0 }));

		trackJob(makeJob(), { songId: 's1' });

		await vi.advanceTimersByTimeAsync(2100);

		expect(mockFetch).toHaveBeenCalledWith('j1');
	});
});

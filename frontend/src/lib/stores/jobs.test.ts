import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';

const mockFetchJob = vi.fn();
const mockFetchSong = vi.fn();

vi.mock('$lib/api/client', () => ({
	fetchJob: (...args: unknown[]) => mockFetchJob(...args),
	fetchSong: (...args: unknown[]) => mockFetchSong(...args)
}));

vi.mock('$lib/stores/player', async () => {
	const { writable } = await import('svelte/store');
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
		error_type: null,
		started_at: null,
		completed_at: null,
		...overrides
	};
}

beforeEach(() => {
	activeJobs.set([]);
	mockFetchJob.mockReset();
	mockFetchSong.mockReset();
	vi.useFakeTimers();
});

afterEach(() => {
	vi.useRealTimers();
});

describe('jobs store', () => {
	it('trackJob adds job to activeJobs', () => {
		mockFetchJob.mockResolvedValue(makeJob({ status: 'completed' }));
		trackJob(makeJob(), { songId: 's1' });
		const jobs = get(activeJobs);
		expect(jobs).toHaveLength(1);
		expect(jobs[0].job.id).toBe('j1');
		expect(jobs[0].songId).toBe('s1');
	});

	it('polls and removes completed job immediately', async () => {
		mockFetchJob.mockResolvedValue(makeJob({ status: 'completed', progress: 1.0 }));
		mockFetchSong.mockRejectedValue(new Error('no song'));

		trackJob(makeJob(), {});
		await vi.advanceTimersByTimeAsync(2100);

		expect(mockFetchJob).toHaveBeenCalledWith('j1');
		expect(get(activeJobs)).toHaveLength(0);
	});

	it('removes failed job after 5s delay', async () => {
		mockFetchJob.mockResolvedValue(makeJob({ status: 'failed', error: 'boom' }));

		trackJob(makeJob(), {});
		await vi.advanceTimersByTimeAsync(2100);
		expect(get(activeJobs)[0].job.status).toBe('failed');

		await vi.advanceTimersByTimeAsync(5100);
		expect(get(activeJobs)).toHaveLength(0);
	});

	it('continues polling for running jobs', async () => {
		mockFetchJob
			.mockResolvedValueOnce(makeJob({ status: 'running', progress: 0.5 }))
			.mockResolvedValueOnce(makeJob({ status: 'completed', progress: 1.0 }));

		trackJob(makeJob(), {});

		await vi.advanceTimersByTimeAsync(2100);
		expect(mockFetchJob).toHaveBeenCalledTimes(1);
		expect(get(activeJobs)[0].job.progress).toBe(0.5);

		await vi.advanceTimersByTimeAsync(2100);
		expect(mockFetchJob).toHaveBeenCalledTimes(2);
		expect(get(activeJobs)).toHaveLength(0);
	});

	it('retries on fetch error', async () => {
		mockFetchJob
			.mockRejectedValueOnce(new Error('network'))
			.mockResolvedValueOnce(makeJob({ status: 'completed' }));

		trackJob(makeJob(), {});

		await vi.advanceTimersByTimeAsync(2100);
		expect(mockFetchJob).toHaveBeenCalledTimes(1);

		await vi.advanceTimersByTimeAsync(2100);
		expect(mockFetchJob).toHaveBeenCalledTimes(2);
	});

	it('slows polling after 30 seconds', async () => {
		mockFetchJob.mockResolvedValue(makeJob({ status: 'running', progress: 0.5 }));

		trackJob(makeJob(), {});

		vi.setSystemTime(Date.now() + 31_000);
		await vi.advanceTimersByTimeAsync(2100);
		expect(mockFetchJob).toHaveBeenCalledTimes(1);

		await vi.advanceTimersByTimeAsync(2100);
		expect(mockFetchJob).toHaveBeenCalledTimes(1);

		await vi.advanceTimersByTimeAsync(6000);
		expect(mockFetchJob).toHaveBeenCalledTimes(2);
	});

	it('marks job failed after max poll errors', async () => {
		mockFetchJob.mockRejectedValue(new Error('network'));

		trackJob(makeJob(), {});

		for (let i = 0; i < 10; i++) {
			await vi.advanceTimersByTimeAsync(2100);
		}

		const jobs = get(activeJobs);
		expect(jobs[0].job.status).toBe('failed');
		expect(jobs[0].job.error).toBe('Lost connection');

		await vi.advanceTimersByTimeAsync(5100);
		expect(get(activeJobs)).toHaveLength(0);
	});

	it('refreshes song data on completion with songId', async () => {
		mockFetchJob.mockResolvedValue(makeJob({ status: 'completed' }));
		mockFetchSong.mockResolvedValue({ id: 's1', title: 'Updated' });

		trackJob(makeJob(), { songId: 's1' });
		await vi.advanceTimersByTimeAsync(2100);

		expect(mockFetchSong).toHaveBeenCalledWith('s1');
	});

	it('handles refreshSongData failure silently', async () => {
		mockFetchJob.mockResolvedValue(makeJob({ status: 'completed' }));
		mockFetchSong.mockRejectedValue(new Error('refresh failed'));

		trackJob(makeJob(), { songId: 's1' });
		await vi.advanceTimersByTimeAsync(2100);

		expect(get(activeJobs)).toHaveLength(0);
	});

	it('skips refresh when no songId', async () => {
		mockFetchJob.mockResolvedValue(makeJob({ status: 'completed' }));

		trackJob(makeJob(), {});
		await vi.advanceTimersByTimeAsync(2100);

		expect(mockFetchSong).not.toHaveBeenCalled();
	});
});

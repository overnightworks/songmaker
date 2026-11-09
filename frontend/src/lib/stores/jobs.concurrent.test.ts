import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { JOB_STREAM_MAX_CONNECTION_ERRORS } from '#lib/constants/jobs.ts';
import {
	SSE_RECONNECT_JITTER_RATIO,
	SSE_RECONNECT_MAX_DELAY_MS
} from '#lib/constants/sse-reconnect.ts';

const mockRequestSongRefresh = vi.fn();
const mockFetchLastFailedGeneration = vi.fn();
const mockFetchActiveGeneration = vi.fn();
const mockFetchJob = vi.fn();

vi.mock('#lib/stores/resourceSync.ts', () => ({
	requestSongRefresh: (...args: unknown[]) => mockRequestSongRefresh(...args)
}));
vi.mock('#lib/api/client.ts', () => ({
	fetchActiveGeneration: (...args: unknown[]) => mockFetchActiveGeneration(...args),
	fetchJob: (...args: unknown[]) => mockFetchJob(...args),
	fetchLastFailedGeneration: (...args: unknown[]) => mockFetchLastFailedGeneration(...args)
}));

import {
	activeJobs,
	generationFailures,
	hydrateGenerationFailure,
	removeJob,
	resetGenerationFailuresForTests,
	trackJob
} from './jobs';
import { reportResourceStreamReachable, resetConnectivityForTests } from './connectivity';
import { toasts } from './toast';
import type { JobStatus } from '#lib/api/client.ts';
import { ApiError } from '#lib/api/fetch.ts';
import { deferred } from '#lib/test-utils/deferred.ts';

const SAFE_RECONNECT_ADVANCE_MS = SSE_RECONNECT_MAX_DELAY_MS * (1 + SSE_RECONNECT_JITTER_RATIO);

// Only what the store reads of an EventSource; `jobs.test.ts` keeps its own
// fake, which that file does not export.
class FakeJobStream {
	static instances: FakeJobStream[] = [];
	onopen: (() => void) | null = null;
	onmessage: ((event: MessageEvent) => void) | null = null;
	onerror: (() => void) | null = null;
	closed = false;

	constructor(readonly url: string) {
		FakeJobStream.instances.push(this);
	}

	close(): void {
		this.closed = true;
	}

	say(job: JobStatus): void {
		this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(job) }));
	}

	fail(): void {
		this.onerror?.();
	}
}

function generateJob(overrides: Partial<JobStatus> = {}): JobStatus {
	return {
		id: 'j1',
		type: 'generate',
		status: 'running',
		progress: 0,
		take_index: null,
		take_count: null,
		error: null,
		error_type: null,
		started_at: null,
		completed_at: null,
		...overrides
	};
}

function streamOf(jobId: string): FakeJobStream {
	const stream = FakeJobStream.instances.findLast((candidate) => candidate.url.includes(jobId));
	if (stream === undefined) throw new Error(`no stream opened for ${jobId}`);
	return stream;
}

function progressByJob(): Record<string, number> {
	return Object.fromEntries(get(activeJobs).map((active) => [active.job.id, active.job.progress]));
}

async function spendTheBudgetOnline(jobId: string): Promise<void> {
	for (let attempt = 1; attempt < JOB_STREAM_MAX_CONNECTION_ERRORS; attempt++) {
		streamOf(jobId).fail();
		await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);
	}
	streamOf(jobId).fail();
	await vi.advanceTimersByTimeAsync(0);
}

beforeEach(() => {
	activeJobs.set([]);
	toasts.set([]);
	resetGenerationFailuresForTests();
	mockRequestSongRefresh.mockReset();
	mockRequestSongRefresh.mockResolvedValue(undefined);
	mockFetchLastFailedGeneration.mockReset();
	mockFetchActiveGeneration.mockReset();
	mockFetchJob.mockReset();
	FakeJobStream.instances = [];
	vi.stubGlobal('EventSource', FakeJobStream);
	vi.useFakeTimers();
});

afterEach(() => {
	resetConnectivityForTests();
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

describe('two songs generating at once', () => {
	beforeEach(() => {
		trackJob(generateJob({ id: 'j-a', progress: 0.1 }), { songId: 'song-a' });
		trackJob(generateJob({ id: 'j-b', progress: 0.2 }), { songId: 'song-b' });
	});

	it("changes only a job's own progress when it speaks", () => {
		streamOf('j-a').say(generateJob({ id: 'j-a', progress: 0.5 }));

		expect(progressByJob()).toEqual({ 'j-a': 0.5, 'j-b': 0.2 });
	});

	it("changes only a job's own context when it is tracked again", () => {
		trackJob(generateJob({ id: 'j-a', progress: 0.3 }), { songId: 'song-a', workerId: 'worker-1' });

		expect(get(activeJobs).map((active) => [active.job.id, active.workerId])).toEqual([
			['j-a', 'worker-1'],
			['j-b', undefined]
		]);
		expect(progressByJob()).toEqual({ 'j-a': 0.3, 'j-b': 0.2 });
	});

	it("holds only the ended job's card for its take", async () => {
		mockRequestSongRefresh.mockReturnValue(new Promise<void>(() => {}));

		streamOf('j-a').say(generateJob({ id: 'j-a', status: 'completed', progress: 1 }));
		await vi.advanceTimersByTimeAsync(0);

		expect(get(activeJobs).map((active) => [active.job.id, active.awaitingTakes])).toEqual([
			['j-a', true],
			['j-b', undefined]
		]);
	});

	it("updates only the re-read job when its stream's budget runs out", async () => {
		mockFetchJob.mockResolvedValue(generateJob({ id: 'j-a', progress: 0.7 }));

		await spendTheBudgetOnline('j-a');

		expect(progressByJob()).toEqual({ 'j-a': 0.7, 'j-b': 0.2 });
	});

	it("leaves the other job's reconnect running when one job's is cancelled", async () => {
		streamOf('j-a').fail();
		streamOf('j-b').fail();
		removeJob('j-a');
		const opened = FakeJobStream.instances.length;

		await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);

		expect(FakeJobStream.instances).toHaveLength(opened + 1);
		expect(streamOf('j-b').closed).toBe(false);
		streamOf('j-b').say(generateJob({ id: 'j-b', progress: 0.9 }));
		expect(progressByJob()).toEqual({ 'j-b': 0.9 });
	});

	it("still reopens the other job's stream at once when the network returns", () => {
		streamOf('j-a').fail();
		streamOf('j-b').fail();
		removeJob('j-a');
		const opened = FakeJobStream.instances.length;

		window.dispatchEvent(new Event('online'));

		expect(FakeJobStream.instances).toHaveLength(opened + 1);
		expect(streamOf('j-b').closed).toBe(false);
	});
});

describe('a job removed while its re-read is in flight', () => {
	const rereads = [
		{
			answer: 'fails',
			settle: (reread: ReturnType<typeof deferred<JobStatus>>) =>
				reread.reject(new ApiError(503, 'Service Unavailable', '/api/jobs/j1'))
		},
		{
			answer: 'finds the job ended',
			settle: (reread: ReturnType<typeof deferred<JobStatus>>) =>
				reread.resolve(generateJob({ status: 'completed' }))
		}
	];

	it.each(rereads)('stays gone when the re-read $answer', async ({ settle }) => {
		const reread = deferred<JobStatus>();
		mockFetchJob.mockReturnValue(reread.promise);
		trackJob(generateJob(), { songId: 'song-1' });
		await spendTheBudgetOnline('j1');
		const opened = FakeJobStream.instances.length;

		removeJob('j1');
		settle(reread);
		await vi.advanceTimersByTimeAsync(0);
		expect(get(toasts)).toEqual([]);

		await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);
		expect(get(activeJobs)).toEqual([]);
		expect(FakeJobStream.instances).toHaveLength(opened);
	});
});

describe('a job tracked without a song', () => {
	it('goes without a word when the server no longer knows it', async () => {
		mockFetchJob.mockRejectedValue(new ApiError(404, 'Not Found', '/api/jobs/j1'));
		trackJob(generateJob(), {});

		await spendTheBudgetOnline('j1');

		expect(get(activeJobs)).toEqual([]);
		expect(mockRequestSongRefresh).not.toHaveBeenCalled();
	});
});

describe('a take-arrival wait superseded while offline', () => {
	it('asks for no further refresh when the connection returns', async () => {
		mockRequestSongRefresh.mockResolvedValue(undefined);
		trackJob(generateJob(), { songId: 'song-1' });
		reportResourceStreamReachable(false);
		streamOf('j1').say(generateJob({ status: 'completed', progress: 1 }));
		await vi.advanceTimersByTimeAsync(0);
		expect(get(activeJobs).map((active) => active.awaitingTakes)).toEqual([true]);
		const refreshes = mockRequestSongRefresh.mock.calls.length;

		removeJob('j1');
		reportResourceStreamReachable(true);
		await vi.advanceTimersByTimeAsync(0);

		expect(get(activeJobs)).toEqual([]);
		expect(mockRequestSongRefresh).toHaveBeenCalledTimes(refreshes);
	});
});

describe('a failure hydration in flight while a live failure arrives', () => {
	it("keeps the live failure when the song's job was tracked without its song first", async () => {
		const hydration = deferred<{ job: JobStatus | null }>();
		mockFetchLastFailedGeneration.mockReturnValue(hydration.promise);
		const hydrating = hydrateGenerationFailure('song-1');

		trackJob(generateJob(), {});
		trackJob(generateJob(), { songId: 'song-1' });
		streamOf('j1').say(generateJob({ status: 'failed', error: 'live cause' }));
		await vi.advanceTimersByTimeAsync(0);
		hydration.resolve({ job: generateJob({ id: 'j-old', status: 'failed', error: 'old cause' }) });
		await hydrating;

		expect(get(generationFailures)['song-1']).toEqual({
			message: 'live cause',
			unavailable: false
		});
	});
});

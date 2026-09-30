import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';

const VRAM_CAUSE =
	'Music generation failed: Insufficient free VRAM: need ~2.0 GB, only 1.3 GB available';

const mockRequestSongRefresh = vi.fn();

vi.mock('$lib/stores/resourceSync', () => ({
	requestSongRefresh: (...args: unknown[]) => mockRequestSongRefresh(...args)
}));

const mockFetchLastFailedGeneration = vi.fn();
const mockFetchActiveGeneration = vi.fn();
const mockFetchJob = vi.fn();

vi.mock('$lib/api/client', () => ({
	fetchActiveGeneration: (...args: unknown[]) => mockFetchActiveGeneration(...args),
	fetchJob: (...args: unknown[]) => mockFetchJob(...args),
	fetchLastFailedGeneration: (...args: unknown[]) => mockFetchLastFailedGeneration(...args)
}));

import {
	activeJobs,
	dismissGenerationFailure,
	generationFailures,
	hydrateActiveGeneration,
	hydrateGenerationFailure,
	removeJob,
	resetGenerationFailures,
	trackJob
} from './jobs';
import { toasts } from './toast';
import { reportResourceStreamReachable, resetConnectivityForTests } from './connectivity';
import type { JobStatus } from '$lib/api/client';
import { ApiError, NetworkError } from '$lib/api/fetch';
import {
	GENERATE_TAKE_ARRIVAL_WAIT_MS,
	JOB_STREAM_MAX_CONNECTION_ERRORS,
	SSE_IMMEDIATE_REOPEN_MIN_GAP_MS,
	SSE_RECONNECT_BASE_DELAY_MS,
	SSE_RECONNECT_JITTER_RATIO,
	SSE_RECONNECT_MAX_DELAY_MS
} from '$lib/constants';

// Jitter only adds to the exponential delay (never subtracts, see
// `sseReconnect.ts`), so a delay at the backoff ceiling can run up to
// `SSE_RECONNECT_MAX_DELAY_MS * (1 + SSE_RECONNECT_JITTER_RATIO)` -- the
// safe amount to advance fake timers by when a test just needs "long enough
// for any pending reconnect, at any attempt count, to have fired".
const SAFE_RECONNECT_ADVANCE_MS = SSE_RECONNECT_MAX_DELAY_MS * (1 + SSE_RECONNECT_JITTER_RATIO);

type EventSourceHandler = ((event: MessageEvent) => void) | null;
type ErrorHandler = (() => void) | null;

class MockEventSource {
	static instances: MockEventSource[] = [];
	url: string;
	withCredentials: boolean;
	onopen: ErrorHandler = null;
	onmessage: EventSourceHandler = null;
	onerror: ErrorHandler = null;
	closed = false;

	constructor(url: string, init?: { withCredentials?: boolean }) {
		this.url = url;
		this.withCredentials = init?.withCredentials ?? false;
		MockEventSource.instances.push(this);
	}

	close(): void {
		this.closed = true;
	}

	simulateOpen(): void {
		if (this.onopen) {
			this.onopen();
		}
	}

	simulateMessage(data: JobStatus): void {
		if (this.onmessage) {
			this.onmessage(new MessageEvent('message', { data: JSON.stringify(data) }));
		}
	}

	simulateError(): void {
		if (this.onerror) {
			this.onerror();
		}
	}
}

function makeJob(overrides: Partial<JobStatus> = {}): JobStatus {
	return {
		id: 'j1',
		type: 'generate',
		status: 'queued',
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

function latestSource(): MockEventSource {
	return MockEventSource.instances[MockEventSource.instances.length - 1];
}

beforeEach(() => {
	activeJobs.set([]);
	resetGenerationFailures();
	mockRequestSongRefresh.mockReset();
	mockRequestSongRefresh.mockResolvedValue(undefined);
	mockFetchLastFailedGeneration.mockReset();
	mockFetchActiveGeneration.mockReset();
	mockFetchJob.mockReset();
	MockEventSource.instances = [];
	vi.stubGlobal('EventSource', MockEventSource);
	vi.useFakeTimers();
});

afterEach(() => {
	resetConnectivityForTests();
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

describe('jobs store', () => {
	it.each(['queued', 'running'] as const)(
		'hydrates a %s generation after reload and receives live progress',
		async (status) => {
			const job = makeJob({
				status,
				take_index: 1,
				take_count: 2,
				remaining_time_estimate: status === 'queued' ? 'calculating' : 100
			});
			mockFetchActiveGeneration.mockResolvedValue(job);

			await hydrateActiveGeneration('s1');

			expect(mockFetchActiveGeneration).toHaveBeenCalledWith('s1');
			expect(get(activeJobs)).toEqual([{ job, songId: 's1' }]);
			expect(latestSource().url).toBe('/api/jobs/j1/stream');
			expect(latestSource().withCredentials).toBe(true);
			const update = {
				...job,
				status: 'running' as const,
				progress: 0.75,
				take_index: 2,
				remaining_time_estimate: 30
			};
			latestSource().simulateMessage(update);
			expect(get(activeJobs)).toEqual([{ job: update, songId: 's1' }]);
		}
	);

	it('leaves tracking empty when the song has no active generation', async () => {
		mockFetchActiveGeneration.mockResolvedValue(null);

		await hydrateActiveGeneration('s1');

		expect(get(activeJobs)).toEqual([]);
		expect(MockEventSource.instances).toHaveLength(0);
	});

	it('reuses the stream when an active generation is hydrated twice', async () => {
		const job = makeJob({ status: 'running' });
		mockFetchActiveGeneration.mockResolvedValue(job);

		await hydrateActiveGeneration('s1');
		await hydrateActiveGeneration('s1');

		expect(get(activeJobs)).toEqual([{ job, songId: 's1' }]);
		expect(MockEventSource.instances).toHaveLength(1);
	});

	it('surfaces an active generation lookup failure', async () => {
		const error = new Error('Service unavailable');
		mockFetchActiveGeneration.mockRejectedValue(error);

		await expect(hydrateActiveGeneration('s1')).rejects.toThrow(error);
		expect(get(activeJobs)).toEqual([]);
		expect(MockEventSource.instances).toHaveLength(0);
	});

	it('trackJob adds job to activeJobs and opens EventSource', () => {
		trackJob(makeJob(), { songId: 's1' });
		const jobs = get(activeJobs);
		expect(jobs).toHaveLength(1);
		expect(jobs[0].job.id).toBe('j1');
		expect(jobs[0].songId).toBe('s1');
		expect(MockEventSource.instances).toHaveLength(1);
		expect(latestSource().url).toBe('/api/jobs/j1/stream');
	});

	it('trackJob stores workerId and mode in context', () => {
		trackJob(makeJob({ type: 'load_model_on_worker' }), {
			workerId: 'acestep-worker-0',
			mode: 'xl-sft'
		});
		const jobs = get(activeJobs);
		expect(jobs[0].workerId).toBe('acestep-worker-0');
		expect(jobs[0].mode).toBe('xl-sft');
		expect(jobs[0].job.type).toBe('load_model_on_worker');
	});

	it('tracks a rehydrated job id once while enriching its context', () => {
		trackJob(makeJob({ type: 'cover' }), {});
		trackJob(makeJob({ type: 'cover', status: 'running', progress: 0.5 }), {
			albumId: 'a-local'
		});

		expect(get(activeJobs)).toEqual([
			{
				job: makeJob({ type: 'cover', status: 'running', progress: 0.5 }),
				albumId: 'a-local'
			}
		]);
		expect(MockEventSource.instances).toHaveLength(1);
	});

	it('updates job on SSE message', () => {
		trackJob(makeJob(), {});
		latestSource().simulateMessage(makeJob({ status: 'running', progress: 0.5 }));
		expect(get(activeJobs)[0].job.status).toBe('running');
		expect(get(activeJobs)[0].job.progress).toBe(0.5);
	});

	it('closes EventSource and removes job on completed', async () => {
		trackJob(makeJob(), {});
		const source = latestSource();
		latestSource().simulateMessage(makeJob({ status: 'completed', progress: 1.0 }));
		await vi.advanceTimersByTimeAsync(0);
		expect(source.closed).toBe(true);
		expect(get(activeJobs)).toHaveLength(0);
	});

	it('removes failed job immediately', async () => {
		trackJob(makeJob(), {});
		latestSource().simulateMessage(makeJob({ status: 'failed', error: 'boom' }));
		await vi.advanceTimersByTimeAsync(0);
		expect(get(activeJobs)).toHaveLength(0);
	});

	it('handles partial completion', async () => {
		trackJob(makeJob(), {});
		latestSource().simulateMessage(
			makeJob({ status: 'partial', error: 'some generations failed' })
		);
		await vi.advanceTimersByTimeAsync(0);
		expect(latestSource().closed).toBe(true);
		expect(get(activeJobs)).toHaveLength(0);
	});

	it('handles cancelled status', async () => {
		trackJob(makeJob(), {});
		latestSource().simulateMessage(makeJob({ status: 'cancelled' }));
		await vi.advanceTimersByTimeAsync(0);
		expect(latestSource().closed).toBe(true);
		expect(get(activeJobs)).toHaveLength(0);
	});

	async function failEveryReopen(times: number): Promise<void> {
		for (let i = 0; i < times; i++) {
			latestSource().simulateError();
			await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);
		}
	}

	async function spendTheBudgetOnline(): Promise<void> {
		await failEveryReopen(JOB_STREAM_MAX_CONNECTION_ERRORS - 1);
		latestSource().simulateError();
		await vi.advanceTimersByTimeAsync(0);
	}

	function lostConnectionToasts(): string[] {
		return get(toasts)
			.map((toast) => toast.message)
			.filter((message) => message === 'Lost connection to server');
	}

	it('keeps a running job through three outages with no message in between', async () => {
		toasts.set([]);
		trackJob(makeJob({ status: 'running', progress: 0.3 }), { songId: 'song-1' });
		for (let outage = 0; outage < 3; outage++) {
			reportResourceStreamReachable(false);
			await failEveryReopen(JOB_STREAM_MAX_CONNECTION_ERRORS);
			reportResourceStreamReachable(true);
			window.dispatchEvent(new Event('online'));
			latestSource().simulateOpen();
		}

		expect(get(activeJobs).map((active) => active.job.progress)).toEqual([0.3]);
		latestSource().simulateMessage(makeJob({ status: 'running', progress: 0.6 }));
		expect(get(activeJobs).map((active) => active.job.progress)).toEqual([0.6]);
		expect(mockFetchJob).not.toHaveBeenCalled();
		expect(lostConnectionToasts()).toEqual([]);
	});

	it('never spends the give-up budget on failures while offline', async () => {
		trackJob(makeJob({ status: 'running' }), { songId: 'song-1' });
		await failEveryReopen(JOB_STREAM_MAX_CONNECTION_ERRORS - 1);
		reportResourceStreamReachable(false);
		await failEveryReopen(JOB_STREAM_MAX_CONNECTION_ERRORS * 2);

		expect(get(activeJobs)).toHaveLength(1);
		expect(mockFetchJob).not.toHaveBeenCalled();
	});

	it('resets the give-up budget when a stream opens, even without a message', async () => {
		trackJob(makeJob({ status: 'running' }), { songId: 'song-1' });
		await failEveryReopen(JOB_STREAM_MAX_CONNECTION_ERRORS - 1);
		latestSource().simulateOpen();
		await failEveryReopen(JOB_STREAM_MAX_CONNECTION_ERRORS - 1);

		expect(get(activeJobs)).toHaveLength(1);
		expect(mockFetchJob).not.toHaveBeenCalled();
	});

	it('re-reads a job whose budget runs out online and finishes it as the server reports', async () => {
		toasts.set([]);
		mockFetchJob.mockResolvedValue(makeJob({ status: 'completed' }));
		mockRequestSongRefresh.mockReturnValue(new Promise<void>(() => {}));
		trackJob(makeJob({ status: 'running' }), { songId: 'song-1' });
		await spendTheBudgetOnline();

		expect(mockFetchJob).toHaveBeenCalledWith('j1');
		expect(get(activeJobs)).toEqual([
			{ job: makeJob({ status: 'completed' }), songId: 'song-1', awaitingTakes: true }
		]);
		expect(mockRequestSongRefresh).toHaveBeenCalledWith('song-1');
		expect(lostConnectionToasts()).toEqual([]);
	});

	it('keeps following a job the server still runs after the budget runs out online', async () => {
		toasts.set([]);
		mockFetchJob.mockResolvedValue(makeJob({ status: 'running', progress: 0.7 }));
		trackJob(makeJob({ status: 'running', progress: 0.2 }), { songId: 'song-1' });
		await spendTheBudgetOnline();

		expect(get(activeJobs).map((active) => active.job.progress)).toEqual([0.7]);
		const opensAfterTheReread = MockEventSource.instances.length;
		await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);
		expect(MockEventSource.instances).toHaveLength(opensAfterTheReread + 1);
		await failEveryReopen(JOB_STREAM_MAX_CONNECTION_ERRORS - 1);
		expect(get(activeJobs)).toHaveLength(1);
		latestSource().simulateMessage(makeJob({ status: 'running', progress: 0.8 }));
		expect(get(activeJobs).map((active) => active.job.progress)).toEqual([0.8]);
		expect(lostConnectionToasts()).toEqual([]);
	});

	it.each([
		['the network swallowed', new NetworkError('/api/jobs/j1', new TypeError('offline'))],
		['the server answered 503', new ApiError(503, 'Service Unavailable', '/api/jobs/j1')]
	])('keeps following a job whose re-read %s', async (_reason, rereadFailure) => {
		mockFetchJob.mockRejectedValue(rereadFailure);
		trackJob(makeJob({ status: 'running', progress: 0.2 }), { songId: 'song-1' });
		await spendTheBudgetOnline();

		expect(get(activeJobs).map((active) => active.job.progress)).toEqual([0.2]);
		await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);
		latestSource().simulateMessage(makeJob({ status: 'running', progress: 0.5 }));
		expect(get(activeJobs).map((active) => active.job.progress)).toEqual([0.5]);
	});

	it('lets a job the server no longer knows go quietly and refreshes its song', async () => {
		toasts.set([]);
		mockFetchJob.mockRejectedValue(new ApiError(404, 'Job not found', '/api/jobs/j1'));
		trackJob(makeJob({ status: 'running' }), { songId: 'song-1' });
		await spendTheBudgetOnline();

		expect(get(activeJobs)).toEqual([]);
		expect(mockRequestSongRefresh).toHaveBeenCalledWith('song-1');
		expect(get(toasts)).toEqual([]);
		const opens = MockEventSource.instances.length;
		await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);
		expect(MockEventSource.instances).toHaveLength(opens);
	});

	describe("while the page is online but the job's stream is down", () => {
		const streamIsStale = (): boolean | undefined => get(activeJobs)[0].streamStale;

		it('marks the job stale from its first stream failure, through refused reopens', async () => {
			trackJob(makeJob({ status: 'running', progress: 0.55 }), { songId: 's1' });
			expect(streamIsStale()).toBeFalsy();
			await failEveryReopen(3);
			expect(streamIsStale()).toBe(true);
			latestSource().simulateOpen();
			expect(streamIsStale()).toBe(true);
		});

		it('is fresh again with the first message after the return', async () => {
			trackJob(makeJob({ status: 'running', progress: 0.55 }), { songId: 's1' });
			await failEveryReopen(6);
			latestSource().simulateMessage(makeJob({ status: 'running', progress: 0.65 }));
			expect(get(activeJobs)).toEqual([
				{ job: makeJob({ status: 'running', progress: 0.65 }), songId: 's1' }
			]);
		});
	});

	it('tolerates errors below max threshold, reconnecting with backoff each time', async () => {
		trackJob(makeJob(), {});
		for (let i = 0; i < 5; i++) {
			latestSource().simulateError();
			await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);
		}
		expect(MockEventSource.instances).toHaveLength(6);
		expect(latestSource().closed).toBe(false);
		expect(get(activeJobs)[0].job.status).toBe('queued');
	});

	it('does not reconnect before the first backoff delay elapses', async () => {
		trackJob(makeJob(), {});
		latestSource().simulateError();
		await vi.advanceTimersByTimeAsync(SSE_RECONNECT_BASE_DELAY_MS - 1);
		expect(MockEventSource.instances).toHaveLength(1);
		await vi.advanceTimersByTimeAsync(SSE_RECONNECT_BASE_DELAY_MS * SSE_RECONNECT_JITTER_RATIO + 1);
		expect(MockEventSource.instances).toHaveLength(2);
	});

	it('grows the backoff delay on successive failures', async () => {
		trackJob(makeJob(), {});
		latestSource().simulateError();
		await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);
		expect(MockEventSource.instances).toHaveLength(2);

		latestSource().simulateError();
		// The second attempt's floor (base * factor) is well past the first
		// attempt's ceiling (base * (1 + jitter)) -- advancing only to the
		// first attempt's ceiling must not be enough for the second retry.
		await vi.advanceTimersByTimeAsync(
			SSE_RECONNECT_BASE_DELAY_MS * (1 + SSE_RECONNECT_JITTER_RATIO)
		);
		expect(MockEventSource.instances).toHaveLength(2);
		await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);
		expect(MockEventSource.instances).toHaveLength(3);
	});

	it('resets the backoff to the first interval after a successful message', async () => {
		trackJob(makeJob(), {});
		latestSource().simulateError();
		await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);
		latestSource().simulateError();
		await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);
		expect(MockEventSource.instances).toHaveLength(3);

		latestSource().simulateMessage(makeJob({ status: 'running' }));
		latestSource().simulateError();
		await vi.advanceTimersByTimeAsync(
			SSE_RECONNECT_BASE_DELAY_MS * (1 + SSE_RECONNECT_JITTER_RATIO)
		);
		expect(MockEventSource.instances).toHaveLength(4);
	});

	it('reopens a waiting job stream at once when the network comes back and reports its end', async () => {
		trackJob(makeJob({ status: 'running' }), { songId: 'song-1' });
		latestSource().simulateError();
		await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);
		latestSource().simulateError();
		expect(MockEventSource.instances).toHaveLength(2);

		window.dispatchEvent(new Event('online'));
		expect(MockEventSource.instances).toHaveLength(3);
		latestSource().simulateMessage(makeJob({ status: 'completed' }));

		expect(get(activeJobs)).toEqual([
			{ job: makeJob({ status: 'completed' }), songId: 'song-1', awaitingTakes: true }
		]);
		expect(mockRequestSongRefresh).toHaveBeenCalledWith('song-1');
		await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);
		expect(MockEventSource.instances).toHaveLength(3);
	});

	it('keeps a running job through an outage however often the user returns to the app', () => {
		toasts.set([]);
		trackJob(makeJob({ status: 'running' }), { songId: 'song-1' });
		latestSource().simulateError();
		const returnsToTheApp = JOB_STREAM_MAX_CONNECTION_ERRORS * 2;
		for (let i = 0; i < returnsToTheApp; i++) {
			vi.setSystemTime(Date.now() + SSE_IMMEDIATE_REOPEN_MIN_GAP_MS);
			document.dispatchEvent(new Event('visibilitychange'));
			window.dispatchEvent(new Event('focus'));
			latestSource().simulateError();
		}
		expect(MockEventSource.instances).toHaveLength(returnsToTheApp + 1);

		window.dispatchEvent(new Event('online'));
		latestSource().simulateMessage(makeJob({ status: 'running', progress: 0.4 }));

		expect(get(activeJobs).map((active) => active.job.progress)).toEqual([0.4]);
		expect(get(toasts).map((toast) => toast.message)).not.toContain('Lost connection to server');
	});

	it('reopens a failing job stream at most once per minimum gap however often the user switches apps', async () => {
		trackJob(makeJob({ status: 'running' }), { songId: 'song-1' });
		const failTheOpenStream = (): void => {
			if (!latestSource().closed) latestSource().simulateError();
		};
		failTheOpenStream();
		const opensBeforeTheStorm = MockEventSource.instances.length;
		const appSwitches = 20;
		const switchIntervalMs = 150;
		for (let i = 0; i < appSwitches; i++) {
			if (i % 2 === 0) window.dispatchEvent(new Event('focus'));
			else document.dispatchEvent(new Event('visibilitychange'));
			failTheOpenStream();
			await vi.advanceTimersByTimeAsync(switchIntervalMs);
			failTheOpenStream();
		}

		const stormMs = appSwitches * switchIntervalMs;
		const immediateReopens = Math.ceil(stormMs / SSE_IMMEDIATE_REOPEN_MIN_GAP_MS);
		const backoffReopens = Math.ceil(stormMs / SSE_RECONNECT_BASE_DELAY_MS);
		expect(MockEventSource.instances.length - opensBeforeTheStorm).toBeLessThanOrEqual(
			immediateReopens + backoffReopens
		);
	});

	it('leaves a live job stream alone when the window regains focus', () => {
		trackJob(makeJob(), {});
		window.dispatchEvent(new Event('focus'));
		expect(MockEventSource.instances).toHaveLength(1);
		expect(latestSource().closed).toBe(false);
	});

	it('removeJob cancels a pending reconnect', async () => {
		trackJob(makeJob(), {});
		latestSource().simulateError();
		removeJob('j1');
		await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);
		expect(MockEventSource.instances).toHaveLength(1);
	});

	it.each([
		['generate', 'completed'],
		['generate', 'partial'],
		['score', 'completed'],
		['score', 'partial']
	] as const)(
		'refreshes the song through the resource-sync owner when a %s job ends %s',
		async (type, status) => {
			trackJob(makeJob({ type }), { songId: 's1' });
			latestSource().simulateMessage(makeJob({ type, status }));
			await vi.advanceTimersByTimeAsync(0);
			expect(mockRequestSongRefresh).toHaveBeenCalledWith('s1');
		}
	);

	describe.each(['completed', 'partial'] as const)('a generate job that ended %s', (status) => {
		function songRefreshThatRunsLater(): () => void {
			let run = (): void => {};
			mockRequestSongRefresh.mockReturnValueOnce(
				new Promise<void>((resolve) => {
					run = resolve;
				})
			);
			return () => run();
		}

		function endWhileTheSongRefreshes(): { ended: JobStatus; refreshRuns: () => void } {
			const refreshRuns = songRefreshThatRunsLater();
			trackJob(makeJob({ status: 'running' }), { songId: 's1' });
			const ended = makeJob({ status });
			latestSource().simulateMessage(ended);
			return { ended, refreshRuns };
		}

		it('stays tracked for its song until the song refresh its end asked for has run', async () => {
			const { ended, refreshRuns } = endWhileTheSongRefreshes();
			await vi.advanceTimersByTimeAsync(0);
			expect(latestSource().closed).toBe(true);
			expect(get(activeJobs)).toEqual([{ job: ended, songId: 's1', awaitingTakes: true }]);

			refreshRuns();
			await vi.advanceTimersByTimeAsync(0);
			expect(get(activeJobs)).toEqual([]);
		});

		it('stays tracked through an offline stretch longer than the wait, until a song refresh back online has run', async () => {
			reportResourceStreamReachable(false);
			const { ended, refreshRuns } = endWhileTheSongRefreshes();
			refreshRuns();
			await vi.advanceTimersByTimeAsync(2 * GENERATE_TAKE_ARRIVAL_WAIT_MS);
			expect(get(activeJobs)).toEqual([{ job: ended, songId: 's1', awaitingTakes: true }]);

			const refreshBackOnlineRuns = songRefreshThatRunsLater();
			reportResourceStreamReachable(true);
			await vi.advanceTimersByTimeAsync(0);
			expect(get(activeJobs)).toEqual([{ job: ended, songId: 's1', awaitingTakes: true }]);

			refreshBackOnlineRuns();
			await vi.advanceTimersByTimeAsync(0);
			expect(get(activeJobs)).toEqual([]);
		});

		it('says it ended only once its take is in, never while its card still waits offline', async () => {
			toasts.set([]);
			reportResourceStreamReachable(false);
			const { refreshRuns } = endWhileTheSongRefreshes();
			refreshRuns();
			await vi.advanceTimersByTimeAsync(0);
			expect(get(toasts)).toEqual([]);

			const refreshBackOnlineRuns = songRefreshThatRunsLater();
			reportResourceStreamReachable(true);
			await vi.advanceTimersByTimeAsync(0);
			expect(get(toasts)).toEqual([]);

			refreshBackOnlineRuns();
			await vi.advanceTimersByTimeAsync(0);
			expect(get(toasts).map((toast) => toast.message)).toEqual([
				status === 'completed' ? 'generate completed' : 'generate partially completed'
			]);
		});

		it('goes after the take-arrival wait when the song refresh never runs', async () => {
			const { ended } = endWhileTheSongRefreshes();
			await vi.advanceTimersByTimeAsync(GENERATE_TAKE_ARRIVAL_WAIT_MS - 1);
			expect(get(activeJobs)).toEqual([{ job: ended, songId: 's1', awaitingTakes: true }]);

			await vi.advanceTimersByTimeAsync(1);
			expect(get(activeJobs)).toEqual([]);
		});
	});

	it.each([
		['generate', 'failed'],
		['generate', 'cancelled'],
		['score', 'completed']
	] as const)('lets a %s job that ended %s go at once', async (type, status) => {
		trackJob(makeJob({ type, status: 'running' }), { songId: 's1' });
		latestSource().simulateMessage(makeJob({ type, status }));
		await vi.advanceTimersByTimeAsync(0);
		expect(get(activeJobs)).toEqual([]);
	});

	it('removeJob lets a finished generate job go before its wait is over', async () => {
		trackJob(makeJob({ status: 'running' }), { songId: 's1' });
		latestSource().simulateMessage(makeJob({ status: 'completed' }));
		removeJob('j1');
		trackJob(makeJob({ status: 'running' }), { songId: 's1' });

		await vi.advanceTimersByTimeAsync(GENERATE_TAKE_ARRIVAL_WAIT_MS);
		expect(get(activeJobs)).toEqual([{ job: makeJob({ status: 'running' }), songId: 's1' }]);
	});

	it('skips refresh when no songId', async () => {
		trackJob(makeJob({ type: 'score' }), {});
		latestSource().simulateMessage(makeJob({ type: 'score', status: 'completed' }));
		await vi.advanceTimersByTimeAsync(0);
		expect(mockRequestSongRefresh).not.toHaveBeenCalled();
	});

	it('removeJob closes EventSource and removes from store', () => {
		trackJob(makeJob(), {});
		const source = latestSource();
		removeJob('j1');
		expect(source.closed).toBe(true);
		expect(get(activeJobs)).toHaveLength(0);
	});

	it('removeJob closes EventSource and removes the job from the store', () => {
		trackJob(makeJob(), {});
		const source = latestSource();
		removeJob('j1');
		expect(source.closed).toBe(true);
		expect(get(activeJobs)).toHaveLength(0);
	});

	it('removeJob is safe for unknown jobId', () => {
		expect(() => removeJob('unknown')).not.toThrow();
	});

	it('keeps the cause of a failed generation for its song', async () => {
		trackJob(makeJob(), { songId: 's1' });
		latestSource().simulateMessage(makeJob({ status: 'failed', error: VRAM_CAUSE }));
		await vi.advanceTimersByTimeAsync(0);
		expect(get(generationFailures).s1).toBe(VRAM_CAUSE);
	});

	it('forgets the previous cause when the song generates again', () => {
		generationFailures.set({ s1: 'old failure' });
		trackJob(makeJob({ id: 'j2' }), { songId: 's1' });
		expect(get(generationFailures).s1).toBeUndefined();
	});

	it('keeps the cause while another job type runs for the song', () => {
		generationFailures.set({ s1: 'old failure' });
		trackJob(makeJob({ id: 'j3', type: 'score' }), { songId: 's1' });
		expect(get(generationFailures).s1).toBe('old failure');
	});

	it('forgets the cause when the user dismisses it', () => {
		generationFailures.set({ s1: 'boom', s2: 'other' });
		dismissGenerationFailure('s1');
		expect(get(generationFailures)).toEqual({ s2: 'other' });
	});

	it('keeps no cause for a failed job of another type', async () => {
		trackJob(makeJob({ type: 'score' }), { songId: 's1' });
		latestSource().simulateMessage(makeJob({ type: 'score', status: 'failed', error: 'boom' }));
		await vi.advanceTimersByTimeAsync(0);
		expect(get(generationFailures).s1).toBeUndefined();
	});

	it('shows server restart message for restart errors', async () => {
		toasts.set([]);
		trackJob(makeJob(), {});
		latestSource().simulateMessage(
			makeJob({ status: 'failed', error: 'Server restarted', error_type: 'server_restart' })
		);
		await vi.advanceTimersByTimeAsync(0);
		const all = get(toasts);
		expect(all).toHaveLength(1);
		expect(all[0].type).toBe('error');
		expect(all[0].message).toBe('Server restarted — please retry');
	});

	describe('hydrateGenerationFailure', () => {
		it("shows the cause of the song's last failed generation on page load", async () => {
			mockFetchLastFailedGeneration.mockResolvedValue({
				job: makeJob({ status: 'failed', error: VRAM_CAUSE })
			});
			await hydrateGenerationFailure('s1');
			expect(mockFetchLastFailedGeneration).toHaveBeenCalledWith('s1');
			expect(get(generationFailures).s1).toBe(VRAM_CAUSE);
		});

		it('shows nothing when a newer take suppressed the failure server-side', async () => {
			mockFetchLastFailedGeneration.mockResolvedValue({ job: null });
			await hydrateGenerationFailure('s1');
			expect(get(generationFailures).s1).toBeUndefined();
		});

		it('never overwrites a failure a live SSE update already set', async () => {
			generationFailures.set({ s1: 'live failure' });
			await hydrateGenerationFailure('s1');
			expect(mockFetchLastFailedGeneration).not.toHaveBeenCalled();
			expect(get(generationFailures).s1).toBe('live failure');
		});

		it('discards a stale result once a live generate has started for the song', async () => {
			let resolveFetch: (value: { job: JobStatus | null }) => void = () => {};
			mockFetchLastFailedGeneration.mockReturnValue(
				new Promise((resolve) => {
					resolveFetch = resolve;
				})
			);
			const hydration = hydrateGenerationFailure('s1');
			trackJob(makeJob({ id: 'j-live' }), { songId: 's1' });
			resolveFetch({ job: makeJob({ error: 'stale failure' }) });
			await hydration;
			expect(get(generationFailures).s1).toBeUndefined();
		});

		it('does not throw when the hydration fetch fails', async () => {
			mockFetchLastFailedGeneration.mockRejectedValue(new Error('network down'));
			await expect(hydrateGenerationFailure('s1')).resolves.toBeUndefined();
			expect(get(generationFailures).s1).toBeUndefined();
		});

		it('never re-fetches for a song dismissed earlier this session', async () => {
			mockFetchLastFailedGeneration.mockResolvedValue({
				job: makeJob({ status: 'failed', error: VRAM_CAUSE })
			});
			await hydrateGenerationFailure('s1');
			expect(get(generationFailures).s1).toBe(VRAM_CAUSE);

			dismissGenerationFailure('s1');
			mockFetchLastFailedGeneration.mockClear();

			await hydrateGenerationFailure('s1');
			expect(mockFetchLastFailedGeneration).not.toHaveBeenCalled();
			expect(get(generationFailures).s1).toBeUndefined();
		});
	});
});

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';

const VRAM_CAUSE =
	'Music generation failed: Insufficient free VRAM: need ~2.0 GB, only 1.3 GB available';

const mockRequestSongRefresh = vi.fn();

vi.mock('$lib/stores/resourceSync', () => ({
	requestSongRefresh: (...args: unknown[]) => mockRequestSongRefresh(...args)
}));

const mockFetchLastFailedGeneration = vi.fn();

vi.mock('$lib/api/client', () => ({
	fetchLastFailedGeneration: (...args: unknown[]) => mockFetchLastFailedGeneration(...args)
}));

import {
	activeJobs,
	dismissGenerationFailure,
	generationFailures,
	hydrateGenerationFailure,
	removeJob,
	resetGenerationFailures,
	stopTracking,
	trackJob
} from './jobs';
import { toasts } from './toast';
import type { JobStatus } from '$lib/api/client';
import {
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
	MockEventSource.instances = [];
	vi.stubGlobal('EventSource', MockEventSource);
	vi.useFakeTimers();
});

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

describe('jobs store', () => {
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

	it('removes job after max connection errors', async () => {
		trackJob(makeJob(), {});
		// One error per connection: each of the first 9 closes the failing
		// connection and reopens a new one after its backoff delay; the 10th
		// gives up instead of reopening.
		for (let i = 0; i < 9; i++) {
			const source = latestSource();
			source.simulateError();
			expect(source.closed).toBe(true);
			await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);
		}
		expect(MockEventSource.instances).toHaveLength(10);
		const last = latestSource();
		last.simulateError();
		expect(last.closed).toBe(true);
		expect(get(activeJobs)).toHaveLength(0);
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

	it('stopTracking cancels a pending reconnect', async () => {
		trackJob(makeJob(), {});
		latestSource().simulateError();
		stopTracking('j1');
		await vi.advanceTimersByTimeAsync(SAFE_RECONNECT_ADVANCE_MS);
		expect(MockEventSource.instances).toHaveLength(1);
	});

	it('does not load the song for a completed generation job', async () => {
		trackJob(makeJob(), { songId: 's1' });
		latestSource().simulateMessage(makeJob({ status: 'completed' }));
		await vi.advanceTimersByTimeAsync(0);
		expect(mockRequestSongRefresh).not.toHaveBeenCalled();
	});

	it('requests refresh through the resource-sync owner for other job types', async () => {
		trackJob(makeJob({ type: 'score' }), { songId: 's1' });
		latestSource().simulateMessage(makeJob({ type: 'score', status: 'completed' }));
		await vi.advanceTimersByTimeAsync(0);
		expect(mockRequestSongRefresh).toHaveBeenCalledWith('s1');
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

	it('stopTracking closes EventSource without removing from store', () => {
		trackJob(makeJob(), {});
		const source = latestSource();
		stopTracking('j1');
		expect(source.closed).toBe(true);
		expect(get(activeJobs)).toHaveLength(1);
	});

	it('stopTracking is safe for unknown jobId', () => {
		expect(() => stopTracking('unknown')).not.toThrow();
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

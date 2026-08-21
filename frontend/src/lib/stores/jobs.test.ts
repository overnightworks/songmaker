import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';

const mockFetchSong = vi.fn();

vi.mock('$lib/api/client', () => ({
	fetchSong: (...args: unknown[]) => mockFetchSong(...args)
}));

vi.mock('$lib/stores/player', async () => {
	const { writable } = await import('svelte/store');
	return { songList: writable([]) };
});

import { activeJobs, trackJob, removeJob, stopTracking } from './jobs';
import { toasts } from './toast';
import type { JobStatus } from '$lib/api/client';

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
	mockFetchSong.mockReset();
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

	it('updates job on SSE message', () => {
		trackJob(makeJob(), {});
		latestSource().simulateMessage(makeJob({ status: 'running', progress: 0.5 }));
		expect(get(activeJobs)[0].job.status).toBe('running');
		expect(get(activeJobs)[0].job.progress).toBe(0.5);
	});

	it('closes EventSource and removes job on completed', async () => {
		mockFetchSong.mockRejectedValue(new Error('no song'));
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
		mockFetchSong.mockRejectedValue(new Error('no song'));
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
		const source = latestSource();
		for (let i = 0; i < 10; i++) {
			source.simulateError();
		}
		expect(source.closed).toBe(true);
		expect(get(activeJobs)).toHaveLength(0);
	});

	it('tolerates errors below max threshold', () => {
		trackJob(makeJob(), {});
		const source = latestSource();
		for (let i = 0; i < 5; i++) {
			source.simulateError();
		}
		expect(source.closed).toBe(false);
		expect(get(activeJobs)[0].job.status).toBe('queued');
	});

	it('does not fetch song data on completion', async () => {
		trackJob(makeJob(), { songId: 's1' });
		latestSource().simulateMessage(makeJob({ status: 'completed' }));
		await vi.advanceTimersByTimeAsync(0);
		expect(mockFetchSong).not.toHaveBeenCalled();
		expect(get(activeJobs)).toHaveLength(0);
	});

	it('toasts completion only for the tab that tracked the job', async () => {
		toasts.set([]);
		trackJob(makeJob(), { songId: 's1' });
		latestSource().simulateMessage(makeJob({ status: 'completed' }));
		await vi.advanceTimersByTimeAsync(0);
		expect(get(toasts).map((toast) => toast.message)).toEqual(['generate completed']);
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
});

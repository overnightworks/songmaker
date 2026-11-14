import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

vi.mock('#lib/stores/resourceSync.ts', () => ({
	requestSongRefresh: () => Promise.resolve()
}));
vi.mock('#lib/api/client.ts', () => ({
	fetchActiveGeneration: vi.fn(),
	fetchJob: vi.fn(),
	fetchLastFailedGeneration: vi.fn()
}));

import { activeJobs, trackJob } from './jobs';
import { toasts } from './toast';
import { resetConnectivityForTests } from './connectivity';
import type { JobStatus } from '#lib/api/client.ts';

class FakeEventSource {
	static latest: FakeEventSource;
	onmessage: ((event: MessageEvent) => void) | null = null;
	onopen: (() => void) | null = null;
	onerror: (() => void) | null = null;
	constructor() {
		FakeEventSource.latest = this;
	}
	close(): void {}
	say(job: JobStatus): void {
		this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(job) }));
	}
}

function jobStatus(overrides: Partial<JobStatus>): JobStatus {
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

async function endJob(overrides: Partial<JobStatus>): Promise<string[]> {
	toasts.set([]);
	trackJob(jobStatus({ type: overrides.type }), { albumId: 'album-1' });
	FakeEventSource.latest.say(jobStatus(overrides));
	await vi.advanceTimersByTimeAsync(0);
	return get(toasts).map((toast) => toast.message);
}

beforeEach(() => {
	activeJobs.set([]);
	vi.stubGlobal('EventSource', FakeEventSource);
	vi.useFakeTimers();
});

afterEach(() => {
	resetConnectivityForTests();
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

const ENDS = [
	['completed', 'completed'],
	['partial', 'partially completed'],
	['cancelled', 'cancelled'],
	['failed', 'failed']
] as const;

describe('the sentence a tracked job shows when it ends', () => {
	it.each(
		(
			[
				'generate',
				'score',
				'lora_training',
				'load_model_on_worker',
				'download_model_on_worker'
			] as const
		).flatMap((type) =>
			ENDS.map(([status, words]) => ({ type, status, sentence: `${type} ${words}` }))
		)
	)(
		'$type $status shows "$sentence" without a stored error',
		async ({ type, status, sentence }) => {
			expect(await endJob({ type, status })).toEqual([sentence]);
		}
	);

	it.each(['partial', 'failed'] as const)(
		'a stored error replaces the sentence of a %s job',
		async (status) => {
			expect(await endJob({ type: 'score', status, error: 'worker said no' })).toEqual([
				'worker said no'
			]);
		}
	);

	it('a chat job raises no toast', async () => {
		expect(await endJob({ type: 'chat', status: 'completed' })).toEqual([]);
	});
});

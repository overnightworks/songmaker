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

import {
	activeJobs,
	generationFailures,
	hydrateGenerationFailure,
	resetGenerationFailuresForTests,
	trackJob
} from './jobs';
import { toasts } from './toast';
import { resetConnectivityForTests } from './connectivity';
import { words } from '#lib/words/en.ts';
import { fetchLastFailedGeneration, type JobStatus } from '#lib/api/client.ts';

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
		error_message: null,
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
			ENDS.filter(([status]) => !(type === 'lora_training' && status === 'cancelled')).map(
				([status, words]) => ({ type, status, sentence: `${type} ${words}` })
			)
		)
	)(
		'$type $status shows "$sentence" without a stored error',
		async ({ type, status, sentence }) => {
			expect(await endJob({ type, status })).toEqual([sentence]);
		}
	);

	it.each(['partial', 'failed'] as const)(
		'a stored failure message replaces the sentence of a %s job',
		async (status) => {
			const failure = { key: 'jobFailure.workerReported', values: { cause: 'worker said no' } };
			expect(await endJob({ type: 'score', status, error_message: failure })).toEqual([
				'The worker reported: worker said no'
			]);
		}
	);

	it.each([
		['failed', 'jobEnd.generateFailed'],
		['partial', 'jobEnd.generatePartial']
	] as const)(
		'a stored failure with an empty cause shows the sentence of a %s job',
		async (status, key) => {
			const empty = { key: 'jobFailure.recorded', values: { cause: '' } };
			expect(await endJob({ type: 'generate', status, error_message: empty })).toEqual([
				words[key]
			]);
		}
	);

	it('a server restart is worded from its stored message', async () => {
		const restarted = { key: 'jobFailure.serverRestarted', values: {} };
		expect(
			await endJob({ status: 'failed', error_message: restarted, error_type: 'server_restart' })
		).toEqual(['Server restarted while job was in progress']);
	});

	it('a partial generate job names the takes that completed before its cause', async () => {
		const failure = { key: 'jobFailure.generationFailed', values: {} };
		expect(
			await endJob({
				type: 'generate',
				status: 'partial',
				take_count: 4,
				completed_takes: 3,
				error_message: failure
			})
		).toEqual(['3/4 completed, 1 failed: Generating failed — try again.']);
	});

	it('a reloaded partial generate names the takes that completed before its cause', async () => {
		resetGenerationFailuresForTests();
		vi.mocked(fetchLastFailedGeneration).mockResolvedValue({
			job: jobStatus({
				status: 'partial',
				take_count: 2,
				completed_takes: 1,
				error_message: { key: 'jobFailure.generationFailed', values: {} }
			})
		});
		await hydrateGenerationFailure('s1');
		expect(get(generationFailures).s1).toEqual({
			message: '1/2 completed, 1 failed: Generating failed — try again.',
			unavailable: false
		});
	});

	it('a cancelled voice training raises no toast, the voice page says so in place', async () => {
		expect(await endJob({ type: 'lora_training', status: 'cancelled' })).toEqual([]);
	});

	it('a chat job raises no toast', async () => {
		expect(await endJob({ type: 'chat', status: 'completed' })).toEqual([]);
	});
});

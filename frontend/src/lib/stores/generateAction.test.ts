import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
	makeGeneration,
	makeHealthResponse,
	makeSong,
	makeVersion
} from '$lib/test-utils/factories';
import type { JobItem } from '$lib/api/types';
import { ApiError, NetworkError } from '$lib/api/fetch';
import {
	EDITOR_GENERATE_CANCEL_FAILED,
	EDITOR_GPU_OFFLINE_TITLE,
	EDITOR_MISSING_CONTENT_TITLE,
	EDITOR_NO_MODELS_WARNING,
	EDITOR_SELECT_MODEL_TITLE
} from '$lib/constants';

vi.mock('$lib/api/client', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/client')>()),
	fetchHealth: vi.fn(),
	fetchVersions: vi.fn(),
	updateSong: vi.fn(),
	generateSong: vi.fn(),
	repaintGeneration: vi.fn(),
	coverGeneration: vi.fn(),
	cancelJob: vi.fn()
}));
vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));

import {
	cancelJob,
	coverGeneration,
	fetchHealth,
	fetchVersions,
	generateSong,
	repaintGeneration,
	updateSong
} from '$lib/api/client';
import {
	isDirty,
	loadSongData,
	pinnedSeed,
	setDraftLyrics,
	setDraftPrompt,
	versions
} from './editor';
import { browserReportsOnline } from '$lib/test-utils/network';
import { reportResourceStreamReachable, resetConnectivityForTests } from './connectivity';
import { cancelGeneration, generate, generateAction, offersCancel } from './generateAction';
import { startHealthPolling, stopHealthPolling } from './health';
import { activeJobs, generationFailures, removeJob, resetGenerationFailures } from './jobs';
import { songList } from './libraryData';
import { selectedSongId } from './player';
import { activeModels } from './presets';
import {
	coverNoiseStrength,
	coverStrength,
	recipeModel,
	repaintEnd,
	repaintMode,
	repaintStart,
	repaintStrength,
	resetRecipeSourceForSong,
	sourceGeneration,
	sourceMode,
	takesPerGenerate
} from './recipe';
import { addToast } from './toast';

const queuedJob: JobItem = {
	id: 'job1',
	type: 'generate',
	status: 'queued',
	progress: 0,
	queue_position: 2,
	queue_reason: 'Waiting for LoRA training on this GPU.'
};

beforeEach(async () => {
	vi.resetAllMocks();
	resetGenerationFailures();
	vi.stubGlobal(
		'EventSource',
		class {
			close() {}
		}
	);
	const song = makeSong({ lyrics: 'verse', prompt: 'folk' });
	vi.mocked(fetchVersions).mockResolvedValue([makeVersion()]);
	vi.mocked(fetchHealth).mockResolvedValue(makeHealthResponse());
	vi.mocked(generateSong).mockResolvedValue(queuedJob);
	vi.mocked(repaintGeneration).mockResolvedValue(queuedJob);
	vi.mocked(coverGeneration).mockResolvedValue(queuedJob);
	songList.set([song]);
	selectedSongId.set(song.id);
	loadSongData(song);
	resetRecipeSourceForSong();
	recipeModel.set('turbo');
	activeModels.set([{ id: 'turbo', is_active: true }]);
	takesPerGenerate.set(2);
	pinnedSeed.set(42);
	startHealthPolling();
	await Promise.resolve();
});

afterEach(() => {
	stopHealthPolling();
	for (const { job } of get(activeJobs)) removeJob(job.id);
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
	resetConnectivityForTests();
});

describe('generate action presentation', () => {
	it.each([
		{
			state: 'idle',
			setup: () => {},
			expectedState: { kind: 'idle', mode: 'generate' }
		},
		{
			state: 'dirty',
			expectedState: { kind: 'idle', mode: 'generate' },
			setup: () => setDraftLyrics('new verse')
		},
		{
			state: 'missing lyrics',
			expectedState: { kind: 'disabled', mode: 'generate', reason: EDITOR_MISSING_CONTENT_TITLE },
			setup: () => setDraftLyrics('')
		},
		{
			state: 'missing prompt',
			expectedState: { kind: 'disabled', mode: 'generate', reason: EDITOR_MISSING_CONTENT_TITLE },
			setup: () => setDraftPrompt('')
		},
		{
			state: 'no selected model',
			expectedState: { kind: 'disabled', mode: 'generate', reason: EDITOR_SELECT_MODEL_TITLE },
			setup: () => recipeModel.set(null)
		},
		{
			state: 'no active models',
			expectedState: { kind: 'disabled', mode: 'generate', reason: EDITOR_NO_MODELS_WARNING },
			setup: () => {
				recipeModel.set(null);
				activeModels.set([]);
			}
		},
		{
			state: 'GPU offline',
			expectedState: { kind: 'disabled', mode: 'generate', reason: EDITOR_GPU_OFFLINE_TITLE },
			setup: () => {
				vi.mocked(fetchHealth).mockResolvedValue(makeHealthResponse({ acestep_workers_online: 0 }));
			}
		},
		{
			state: 'browser offline',
			expectedState: { kind: 'disabled', mode: 'generate', reason: null },
			setup: () => browserReportsOnline(false)
		},
		{
			state: 'server unreachable while the browser is online',
			expectedState: { kind: 'disabled', mode: 'generate', reason: null },
			setup: () => reportResourceStreamReachable(false)
		},
		{
			state: 'offline with missing lyrics',
			expectedState: { kind: 'disabled', mode: 'generate', reason: null },
			setup: () => {
				setDraftLyrics('');
				reportResourceStreamReachable(false);
			}
		},
		{
			state: 'queue full',
			expectedState: { kind: 'idle', mode: 'generate' },
			setup: () => {
				vi.mocked(fetchHealth).mockResolvedValue(
					makeHealthResponse({ queue_depth_cap_reached: true })
				);
			}
		},
		{
			state: 'queued',
			expectedState: {
				kind: 'queued',
				jobId: 'job1',
				label: 'Queued #2',
				reason: queuedJob.queue_reason,
				reconnecting: false
			},
			setup: () => activeJobs.set([{ songId: 's1', job: queuedJob }])
		},
		{
			state: 'queued without position',
			expectedState: {
				kind: 'queued',
				jobId: 'job1',
				label: 'Queued',
				reason: queuedJob.queue_reason,
				reconnecting: false
			},
			setup: () => activeJobs.set([{ songId: 's1', job: { ...queuedJob, queue_position: null } }])
		},
		{
			state: 'running',
			expectedState: {
				kind: 'generating',
				jobId: 'job1',
				phase: 'Generating...',
				takeCounter: null,
				progress: 0,
				readout: '0%',
				ended: false,
				reconnecting: false
			},
			setup: () => activeJobs.set([{ songId: 's1', job: { ...queuedJob, status: 'running' } }])
		},
		{
			state: 'running a single take',
			expectedState: {
				kind: 'generating',
				jobId: 'job1',
				phase: 'Generating...',
				takeCounter: null,
				progress: 0,
				readout: '0%',
				ended: false,
				reconnecting: false
			},
			setup: () =>
				activeJobs.set([
					{ songId: 's1', job: { ...queuedJob, status: 'running', take_index: 1, take_count: 1 } }
				])
		},
		{
			state: 'another song running',
			expectedState: { kind: 'idle', mode: 'generate' },
			setup: () => activeJobs.set([{ songId: 's2', job: queuedJob }])
		}
	])('exposes the state for $state', async ({ setup, expectedState }) => {
		setup();
		stopHealthPolling();
		startHealthPolling();
		await Promise.resolve();
		expect(get(generateAction)).toEqual(expectedState);
	});

	it.each([
		{ remaining: 100, readout: '36% · ~1:40' },
		{ remaining: 'calculating', readout: '36%' },
		{ remaining: null, readout: '36%' }
	] as const)(
		'reads out live progress and remaining time $remaining, scaled from the 0..1 job fraction to a percent',
		({ remaining, readout }) => {
			const job: JobItem = {
				...queuedJob,
				status: 'running',
				phase: 'rendering',
				take_index: 1,
				take_count: 2,
				progress: 0.36,
				remaining_time_estimate: remaining
			};
			activeJobs.set([{ songId: 's1', job }]);
			expect(get(generateAction)).toEqual({
				kind: 'generating',
				jobId: 'job1',
				phase: 'Rendering',
				takeCounter: 'Take 1 of 2',
				progress: 36,
				readout,
				ended: false,
				reconnecting: false
			});
		}
	);

	it.each([
		{ phase: 'loading_model', label: 'Loading model…', readout: null },
		{ phase: 'writing', label: 'Writing', readout: '36% · ~0:32' },
		{ phase: 'rendering', label: 'Rendering', readout: '36% · ~0:32' },
		{ phase: 'saving_take', label: 'Saving take', readout: '36% · ~0:32' },
		{ phase: null, label: 'Generating...', readout: '36% · ~0:32' }
	] as const)(
		'names the $phase phase "$label" with readout $readout',
		({ phase, label, readout }) => {
			const job: JobItem = {
				...queuedJob,
				status: 'running',
				phase,
				progress: 0.36,
				remaining_time_estimate: 32
			};
			activeJobs.set([{ songId: 's1', job }]);
			expect(get(generateAction)).toMatchObject({ kind: 'generating', phase: label, readout });
		}
	);

	it.each(['generate', 'repaint', 'cover'] as const)(
		'exposes the selected song failure for %s and clears it on the next attempt',
		async (mode) => {
			if (mode !== 'generate') {
				sourceGeneration.set(makeGeneration());
				sourceMode.set(mode);
			}
			generationFailures.set({ s1: 'Worker exhausted GPU memory', s2: 'Another failure' });
			expect(get(generateAction)).toEqual({
				kind: 'failed',
				mode,
				cause: 'Worker exhausted GPU memory'
			});
			const request = generate();
			expect(get(generationFailures)).toEqual({ s2: 'Another failure' });
			await request;
			expect(get(generateAction).kind).toBe('queued');
		}
	);

	describe('while the page is offline', () => {
		const runningAt40: JobItem = {
			...queuedJob,
			status: 'running',
			phase: 'rendering',
			take_index: 1,
			take_count: 2,
			progress: 0.4,
			remaining_time_estimate: 32
		};

		it.each([
			{ cause: 'the browser is offline', loseConnection: () => browserReportsOnline(false) },
			{
				cause: 'the server is unreachable',
				loseConnection: () => reportResourceStreamReachable(false)
			}
		])(
			'a running take reads "Reconnecting…" with its last seen progress when $cause',
			({ loseConnection }) => {
				activeJobs.set([{ songId: 's1', job: runningAt40 }]);
				loseConnection();
				expect(get(generateAction)).toEqual({
					kind: 'generating',
					jobId: 'job1',
					phase: 'Reconnecting…',
					takeCounter: 'Take 1 of 2',
					progress: 40,
					readout: 'last seen at 40%',
					ended: false,
					reconnecting: true
				});
			}
		);

		it('a take loading its model keeps only its take counter, since loading never had a percent', () => {
			activeJobs.set([{ songId: 's1', job: { ...runningAt40, phase: 'loading_model' } }]);
			reportResourceStreamReachable(false);
			expect(get(generateAction)).toMatchObject({ takeCounter: 'Take 1 of 2', readout: null });
		});

		it('a running take is live again by itself once the connection is back', () => {
			activeJobs.set([{ songId: 's1', job: runningAt40 }]);
			reportResourceStreamReachable(false);
			reportResourceStreamReachable(true);
			expect(get(generateAction)).toEqual({
				kind: 'generating',
				jobId: 'job1',
				phase: 'Rendering',
				takeCounter: 'Take 1 of 2',
				progress: 40,
				readout: '40% · ~0:32',
				ended: false,
				reconnecting: false
			});
		});

		it('a queued take keeps its place in the queue and is marked reconnecting', () => {
			activeJobs.set([{ songId: 's1', job: queuedJob }]);
			reportResourceStreamReachable(false);
			expect(get(generateAction)).toEqual({
				kind: 'queued',
				jobId: 'job1',
				label: 'Queued #2',
				reason: queuedJob.queue_reason,
				reconnecting: true
			});
		});
	});

	it('keeps unavailable and pending states ahead of a previous failure', () => {
		generationFailures.set({ s1: 'Previous failure' });
		recipeModel.set(null);
		expect(get(generateAction).kind).toBe('disabled');
		activeJobs.set([{ songId: 's1', job: queuedJob }]);
		expect(get(generateAction).kind).toBe('queued');
	});

	it('does not show another song failure', () => {
		generationFailures.set({ s2: 'Another failure' });
		expect(get(generateAction)).toEqual({ kind: 'idle', mode: 'generate' });
	});

	describe("once the job's takes are in the list", () => {
		const jobStartedAt = '2026-09-26T10:00:00+00:00';
		const takeBeforeJob = makeGeneration({ id: 'old', created_at: '2026-09-26T09:59:59+00:00' });
		const takeOfJob = (id: string) =>
			makeGeneration({ id, created_at: '2026-09-26T10:01:00+00:00' });
		const runningJob = (overrides: Partial<JobItem> = {}): JobItem => ({
			...queuedJob,
			status: 'running',
			progress: 0.4,
			started_at: jobStartedAt,
			...overrides
		});

		it.each([
			{
				case: 'its one take landed',
				takes: [takeOfJob('new'), takeBeforeJob],
				jobs: [runningJob()],
				kind: 'idle'
			},
			{
				case: 'both of its two takes landed',
				takes: [takeOfJob('b'), takeOfJob('a')],
				jobs: [runningJob({ take_index: 2, take_count: 2 })],
				kind: 'idle'
			},
			{
				case: 'only the first of its two takes landed',
				takes: [takeOfJob('a'), takeBeforeJob],
				jobs: [runningJob({ take_index: 2, take_count: 2 })],
				kind: 'generating'
			},
			{
				case: 'only takes from before the job exist',
				takes: [takeBeforeJob],
				jobs: [runningJob()],
				kind: 'generating'
			},
			{
				case: 'it finished and the refresh has not brought its take in yet',
				awaitingTakes: true,
				takes: [takeBeforeJob],
				jobs: [runningJob({ status: 'completed', progress: 1 })],
				kind: 'generating'
			},
			{
				case: 'it finished and the refresh brought its take in',
				awaitingTakes: true,
				takes: [takeOfJob('new'), takeBeforeJob],
				jobs: [runningJob({ status: 'completed', progress: 1 })],
				kind: 'idle'
			},
			{
				case: 'it finished its two takes and the refresh has brought only the first in',
				awaitingTakes: true,
				takes: [takeOfJob('a'), takeBeforeJob],
				jobs: [runningJob({ status: 'completed', progress: 1, take_index: 2, take_count: 2 })],
				kind: 'generating'
			},
			{
				case: 'it finished its two takes and the refresh brought both in',
				awaitingTakes: true,
				takes: [takeOfJob('b'), takeOfJob('a'), takeBeforeJob],
				jobs: [runningJob({ status: 'completed', progress: 1, take_index: 2, take_count: 2 })],
				kind: 'idle'
			},
			{
				case: 'it finished partially and its first take is in',
				awaitingTakes: true,
				takes: [takeOfJob('a'), takeBeforeJob],
				jobs: [runningJob({ status: 'partial', take_count: 2 })],
				kind: 'idle'
			},
			{
				case: 'it failed and is on its way out of the job list',
				takes: [takeBeforeJob],
				jobs: [runningJob({ status: 'failed' })],
				kind: 'idle'
			},
			{
				case: 'a newer job for the song is queued behind the landed one',
				takes: [takeOfJob('new')],
				jobs: [runningJob(), { ...queuedJob, id: 'job2', started_at: '2026-09-26T10:02:00+00:00' }],
				kind: 'queued'
			}
		])('presents $kind when $case', ({ takes, jobs, kind, awaitingTakes = false }) => {
			songList.set([makeSong({ lyrics: 'verse', prompt: 'folk', generations: takes })]);
			activeJobs.set(jobs.map((job) => ({ songId: 's1', job, awaitingTakes })));
			expect(get(generateAction).kind).toBe(kind);
		});

		it('keeps the card of a finished job waiting for its take, with nothing left to cancel', () => {
			songList.set([makeSong({ lyrics: 'verse', prompt: 'folk', generations: [takeBeforeJob] })]);
			const finished = runningJob({ status: 'completed', progress: 1 });
			activeJobs.set([{ songId: 's1', job: finished, awaitingTakes: true }]);
			const presentation = get(generateAction);
			expect(presentation).toMatchObject({ kind: 'generating', jobId: 'job1', ended: true });
			expect(offersCancel(presentation)).toBe(false);
		});
	});

	it('follows the selected song and exposes a reason only while queued', () => {
		activeJobs.set([{ songId: 's1', job: queuedJob }]);
		expect(get(generateAction)).toMatchObject({
			kind: 'queued',
			jobId: queuedJob.id,
			reason: queuedJob.queue_reason
		});
		activeJobs.set([{ songId: 's1', job: { ...queuedJob, status: 'running' } }]);
		expect(get(generateAction)).toMatchObject({ kind: 'generating' });
		selectedSongId.set(null);
		expect(get(generateAction)).toMatchObject({ kind: 'idle' });
	});
});

describe('generate action execution', () => {
	it('waits for the saved version, rejects duplicate clicks and hands pending state to the job', async () => {
		setDraftLyrics('new verse');
		const saved = makeSong({ lyrics: 'new verse', prompt: 'folk' });
		const save = Promise.withResolvers<typeof saved>();
		vi.mocked(updateSong).mockReturnValue(save.promise);
		vi.mocked(fetchVersions).mockResolvedValue([makeVersion({ id: 'v2', version_number: 2 })]);
		const request = generate();
		expect(get(generateAction)).toMatchObject({
			kind: 'generating',
			jobId: null,
			phase: 'Generating...',
			progress: 0,
			readout: '0%'
		});
		await generate();
		expect(updateSong).toHaveBeenCalledTimes(1);
		expect(generateSong).not.toHaveBeenCalled();
		save.resolve(saved);
		await request;
		expect(generateSong).toHaveBeenCalledExactlyOnceWith('s1', 2, 'turbo', 'v2', 42);
		expect(get(isDirty)).toBe(false);
		expect(get(pinnedSeed)).toBeNull();
		expect(get(generateAction)).toMatchObject({ kind: 'queued', jobId: queuedJob.id });
	});

	it.each(['save', 'generate'] as const)(
		'keeps the seed and allows another attempt after a %s failure',
		async (step) => {
			const failure = new NetworkError('/api/songs/s1', new TypeError('Failed to fetch'));
			if (step === 'save') {
				setDraftLyrics('new verse');
				vi.mocked(updateSong).mockRejectedValueOnce(failure);
			} else vi.mocked(generateSong).mockRejectedValueOnce(failure);
			await generate();
			expect(get(generateAction)).toMatchObject({ kind: 'idle' });
			expect(get(pinnedSeed)).toBe(42);
			expect(addToast).toHaveBeenCalledExactlyOnceWith('Generation failed', 'error');
			if (step === 'save') expect(generateSong).not.toHaveBeenCalled();
			vi.mocked(updateSong).mockResolvedValue(makeSong({ lyrics: 'new verse', prompt: 'folk' }));
			await generate();
			expect(get(generateAction)).toMatchObject({ kind: 'queued', jobId: queuedJob.id });
		}
	);

	it.each([
		{ mode: 'repaint', variant: 'balanced' },
		{ mode: 'repaint', variant: 'conservative' },
		{ mode: 'cover', variant: 'noise' },
		{ mode: 'cover', variant: 'no noise' }
	] as const)('generates $mode with $variant recipe settings', async ({ mode, variant }) => {
		sourceGeneration.set(makeGeneration());
		sourceMode.set(mode);
		repaintStart.set(0.2);
		repaintEnd.set(0.8);
		repaintMode.set(variant === 'balanced' ? 'balanced' : 'conservative');
		repaintStrength.set(0.6);
		coverStrength.set(0.7);
		coverNoiseStrength.set(variant === 'noise' ? 0.3 : 0);
		expect(get(generateAction)).toEqual({ kind: 'idle', mode });
		await generate();
		const options = { model: 'turbo', seed: 42, versionId: 'v1', count: 2 };
		if (mode === 'repaint') {
			expect(repaintGeneration).toHaveBeenCalledWith('g1', 0.2, 0.8, {
				...options,
				repaintMode: variant,
				repaintStrength: variant === 'balanced' ? 0.6 : undefined
			});
		} else {
			expect(coverGeneration).toHaveBeenCalledWith('g1', 0.7, {
				...options,
				coverNoiseStrength: variant === 'noise' ? 0.3 : undefined
			});
		}
		expect(get(generateAction)).toMatchObject({ kind: 'queued', jobId: queuedJob.id });
		expect(get(pinnedSeed)).toBeNull();
	});

	it('generates without a saved version when none exists', async () => {
		versions.set([]);
		await generate();
		expect(generateSong).toHaveBeenCalledWith('s1', 2, 'turbo', undefined, 42);
		expect(updateSong).not.toHaveBeenCalled();
	});

	it.each(['song', 'model'])('does not submit without a %s', async (missing) => {
		if (missing === 'song') selectedSongId.set(null);
		else recipeModel.set(null);
		await generate();
		expect(generateSong).not.toHaveBeenCalled();
		expect(get(generateAction).kind).not.toBe('generating');
	});
});

describe('cancelGeneration', () => {
	it('cancels the job, the single owner both the Generate button and the Takes status slot call', async () => {
		vi.mocked(cancelJob).mockResolvedValue({ ...queuedJob, status: 'cancelled' });
		await cancelGeneration('job1');
		expect(cancelJob).toHaveBeenCalledExactlyOnceWith('job1');
		expect(addToast).not.toHaveBeenCalled();
	});

	it.each([
		{
			failure: 'with no network answer',
			error: new NetworkError('/api/jobs/job1/cancel', new TypeError('Failed to fetch')),
			shown: EDITOR_GENERATE_CANCEL_FAILED
		},
		{
			failure: 'refused by the server',
			error: new ApiError(409, 'Worker unavailable', '/api/jobs/job1/cancel'),
			shown: 'Worker unavailable'
		}
	])('says $shown once when a cancel fails $failure', async ({ error, shown }) => {
		vi.mocked(cancelJob).mockRejectedValue(error);
		await cancelGeneration('job1');
		expect(addToast).toHaveBeenCalledExactlyOnceWith(shown, 'error');
	});

	it('names a generation start the server refused in its own words', async () => {
		vi.mocked(generateSong).mockRejectedValueOnce(
			new ApiError(429, 'Two generations already run', '/api/songs/s1/generate')
		);
		await generate();
		expect(addToast).toHaveBeenCalledExactlyOnceWith('Two generations already run', 'error');
	});
});

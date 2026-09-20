import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
	makeGeneration,
	makeHealthResponse,
	makeSong,
	makeVersion
} from '$lib/test-utils/factories';
import type { JobItem } from '$lib/api/types';
import {
	EDITOR_GENERATE_LABEL,
	EDITOR_GENERATE_COVER_LABEL,
	EDITOR_GENERATE_REPAINT_LABEL,
	EDITOR_GENERATING_LABEL,
	EDITOR_GPU_OFFLINE_LABEL,
	EDITOR_GPU_OFFLINE_TITLE,
	EDITOR_MISSING_CONTENT_TITLE,
	EDITOR_NO_MODELS_WARNING,
	EDITOR_QUEUED_LABEL,
	EDITOR_QUEUE_BUSY_TITLE,
	EDITOR_SELECT_MODEL_TITLE
} from '$lib/constants';

vi.mock('$lib/api/client', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/client')>()),
	fetchHealth: vi.fn(),
	fetchVersions: vi.fn(),
	updateSong: vi.fn(),
	generateSong: vi.fn(),
	repaintGeneration: vi.fn(),
	coverGeneration: vi.fn()
}));
vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));

import {
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
import { generate, generateAction } from './generateAction';
import { startHealthPolling, stopHealthPolling } from './health';
import { activeJobs, removeJob } from './jobs';
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
});

describe('generate action presentation', () => {
	it.each([
		{ state: 'idle', setup: () => {}, label: EDITOR_GENERATE_LABEL, title: '', disabled: false },
		{
			state: 'dirty',
			setup: () => setDraftLyrics('new verse'),
			label: EDITOR_GENERATE_LABEL,
			title: '',
			disabled: false
		},
		{
			state: 'missing lyrics',
			setup: () => setDraftLyrics(''),
			label: EDITOR_GENERATE_LABEL,
			title: EDITOR_MISSING_CONTENT_TITLE,
			disabled: true
		},
		{
			state: 'missing prompt',
			setup: () => setDraftPrompt(''),
			label: EDITOR_GENERATE_LABEL,
			title: EDITOR_MISSING_CONTENT_TITLE,
			disabled: true
		},
		{
			state: 'no selected model',
			setup: () => recipeModel.set(null),
			label: EDITOR_GENERATE_LABEL,
			title: EDITOR_SELECT_MODEL_TITLE,
			disabled: true
		},
		{
			state: 'no active models',
			setup: () => {
				recipeModel.set(null);
				activeModels.set([]);
			},
			label: EDITOR_GENERATE_LABEL,
			title: EDITOR_NO_MODELS_WARNING,
			disabled: true
		},
		{
			state: 'GPU offline',
			setup: () => {
				vi.mocked(fetchHealth).mockResolvedValue(makeHealthResponse({ acestep_workers_online: 0 }));
			},
			label: EDITOR_GPU_OFFLINE_LABEL,
			title: EDITOR_GPU_OFFLINE_TITLE,
			disabled: true
		},
		{
			state: 'queue full',
			setup: () => {
				vi.mocked(fetchHealth).mockResolvedValue(
					makeHealthResponse({ queue_depth_cap_reached: true })
				);
			},
			label: EDITOR_GENERATE_LABEL,
			title: EDITOR_QUEUE_BUSY_TITLE,
			disabled: false
		},
		{
			state: 'queued',
			setup: () => activeJobs.set([{ songId: 's1', job: queuedJob }]),
			label: 'Queued (#2)',
			title: '',
			disabled: true
		},
		{
			state: 'queued without position',
			setup: () => activeJobs.set([{ songId: 's1', job: { ...queuedJob, queue_position: null } }]),
			label: EDITOR_QUEUED_LABEL,
			title: '',
			disabled: true
		},
		{
			state: 'running',
			setup: () => activeJobs.set([{ songId: 's1', job: { ...queuedJob, status: 'running' } }]),
			label: EDITOR_GENERATING_LABEL,
			title: '',
			disabled: true
		},
		{
			state: 'another song running',
			setup: () => activeJobs.set([{ songId: 's2', job: queuedJob }]),
			label: EDITOR_GENERATE_LABEL,
			title: '',
			disabled: false
		}
	])('exposes label, title and disabled for $state', async ({ setup, label, title, disabled }) => {
		setup();
		stopHealthPolling();
		startHealthPolling();
		await Promise.resolve();
		expect(get(generateAction)).toMatchObject({ label, title, disabled });
	});

	it('follows the selected song and exposes a reason only while queued', () => {
		activeJobs.set([{ songId: 's1', job: queuedJob }]);
		expect(get(generateAction)).toMatchObject({
			job: queuedJob,
			queueReason: queuedJob.queue_reason,
			pending: true
		});
		activeJobs.set([{ songId: 's1', job: { ...queuedJob, status: 'running' } }]);
		expect(get(generateAction)).toMatchObject({ queueReason: null, pending: true });
		selectedSongId.set(null);
		expect(get(generateAction)).toMatchObject({ job: null, queueReason: null, pending: false });
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
			pending: true,
			disabled: true,
			label: EDITOR_GENERATING_LABEL
		});
		await generate();
		expect(updateSong).toHaveBeenCalledTimes(1);
		expect(generateSong).not.toHaveBeenCalled();
		save.resolve(saved);
		await request;
		expect(generateSong).toHaveBeenCalledExactlyOnceWith('s1', 2, 'turbo', 'v2', 42);
		expect(get(isDirty)).toBe(false);
		expect(get(pinnedSeed)).toBeNull();
		expect(get(generateAction)).toMatchObject({ pending: true, job: queuedJob });
	});

	it.each(['save', 'generate'] as const)(
		'keeps the seed and allows another attempt after a %s failure',
		async (step) => {
			const failure = new Error('Request failed');
			if (step === 'save') {
				setDraftLyrics('new verse');
				vi.mocked(updateSong).mockRejectedValueOnce(failure);
			} else vi.mocked(generateSong).mockRejectedValueOnce(failure);
			await generate();
			expect(get(generateAction)).toMatchObject({ pending: false, disabled: false });
			expect(get(pinnedSeed)).toBe(42);
			expect(addToast).toHaveBeenCalledWith(failure.message, 'error');
			if (step === 'save') expect(generateSong).not.toHaveBeenCalled();
			vi.mocked(updateSong).mockResolvedValue(makeSong({ lyrics: 'new verse', prompt: 'folk' }));
			await generate();
			expect(get(generateAction).job).toEqual(queuedJob);
		}
	);

	it.each([
		{ mode: 'repaint', variant: 'balanced', label: EDITOR_GENERATE_REPAINT_LABEL },
		{ mode: 'repaint', variant: 'conservative', label: EDITOR_GENERATE_REPAINT_LABEL },
		{ mode: 'cover', variant: 'noise', label: EDITOR_GENERATE_COVER_LABEL },
		{ mode: 'cover', variant: 'no noise', label: EDITOR_GENERATE_COVER_LABEL }
	] as const)('generates $mode with $variant recipe settings', async ({ mode, variant, label }) => {
		sourceGeneration.set(makeGeneration());
		sourceMode.set(mode);
		repaintStart.set(0.2);
		repaintEnd.set(0.8);
		repaintMode.set(variant === 'balanced' ? 'balanced' : 'conservative');
		repaintStrength.set(0.6);
		coverStrength.set(0.7);
		coverNoiseStrength.set(variant === 'noise' ? 0.3 : 0);
		expect(get(generateAction).label).toBe(label);
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
		expect(get(generateAction).job).toEqual(queuedJob);
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
		expect(get(generateAction).pending).toBe(false);
	});
});

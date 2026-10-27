import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
	makeGeneration,
	makeHealthResponse,
	makeSong,
	makeVersion
} from '$lib/test-utils/factories';
import type { JobItem } from '$lib/api/types';
import { ApiError } from '$lib/api/fetch';

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
import { discardDraft, loadSongData, pinnedSeed, setDraftLyrics } from './editor';
import { resetConnectivityForTests } from './connectivity';
import { runSourceTask } from './generateAction';
import { startHealthPolling, stopHealthPolling } from './health';
import { activeJobs, generationFailures, removeJob, resetGenerationFailuresForTests } from './jobs';
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

const sourceTaskJob: JobItem = { id: 'job1', type: 'generate', status: 'queued', progress: 0 };

beforeEach(async () => {
	discardDraft();
	vi.resetAllMocks();
	resetGenerationFailuresForTests();
	vi.stubGlobal(
		'EventSource',
		class {
			close() {}
		}
	);
	const song = makeSong({ lyrics: 'verse', prompt: 'folk' });
	vi.mocked(fetchVersions).mockResolvedValue([makeVersion()]);
	vi.mocked(fetchHealth).mockResolvedValue(makeHealthResponse());
	vi.mocked(repaintGeneration).mockResolvedValue(sourceTaskJob);
	vi.mocked(coverGeneration).mockResolvedValue(sourceTaskJob);
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

describe('runSourceTask', () => {
	it.each([
		{ variant: 'balanced', strength: 0.6 },
		{ variant: 'conservative', strength: undefined }
	] as const)('repaints the card range with $variant strength', async ({ variant, strength }) => {
		sourceGeneration.set(makeGeneration());
		sourceMode.set('repaint');
		repaintStart.set(0.2);
		repaintEnd.set(0.8);
		repaintMode.set(variant);
		repaintStrength.set(0.6);
		await runSourceTask();
		expect(repaintGeneration).toHaveBeenCalledWith('g1', 0.2, 0.8, {
			model: 'turbo',
			seed: 42,
			versionId: 'v1',
			count: 2,
			repaintMode: variant,
			repaintStrength: strength
		});
		expect(coverGeneration).not.toHaveBeenCalled();
	});

	it.each([
		{ noise: 0.3, sent: 0.3 },
		{ noise: 0, sent: undefined }
	])('covers with noise $noise', async ({ noise, sent }) => {
		sourceGeneration.set(makeGeneration());
		sourceMode.set('cover');
		coverStrength.set(0.7);
		coverNoiseStrength.set(noise);
		await runSourceTask();
		expect(coverGeneration).toHaveBeenCalledWith('g1', 0.7, {
			model: 'turbo',
			seed: 42,
			versionId: 'v1',
			count: 2,
			coverNoiseStrength: sent
		});
		expect(repaintGeneration).not.toHaveBeenCalled();
	});

	it('leaves the source in place after the press', async () => {
		const source = makeGeneration();
		sourceGeneration.set(source);
		await runSourceTask();
		expect(get(sourceGeneration)).toBe(source);
		expect(get(activeJobs).map(({ job }) => job.id)).toEqual(['job1']);
	});

	it('saves a dirty draft before the job starts', async () => {
		sourceGeneration.set(makeGeneration());
		setDraftLyrics('new verse');
		vi.mocked(updateSong).mockResolvedValue(makeSong({ lyrics: 'new verse', prompt: 'folk' }));
		await runSourceTask();
		expect(updateSong).toHaveBeenCalled();
		expect(repaintGeneration).toHaveBeenCalled();
		expect(vi.mocked(updateSong).mock.invocationCallOrder[0]).toBeLessThan(
			vi.mocked(repaintGeneration).mock.invocationCallOrder[0]
		);
	});

	it('starts nothing without a source take', async () => {
		await runSourceTask();
		expect(repaintGeneration).not.toHaveBeenCalled();
		expect(coverGeneration).not.toHaveBeenCalled();
		expect(generateSong).not.toHaveBeenCalled();
	});

	it('shows the unavailable refusal at the header with no toast', async () => {
		const line = "Generating isn't available right now.";
		sourceGeneration.set(makeGeneration());
		vi.mocked(repaintGeneration).mockRejectedValueOnce(
			new ApiError(503, line, '/api/x', null, line, 'generation_unavailable', 'job9')
		);
		await runSourceTask();
		expect(addToast).not.toHaveBeenCalled();
		expect(get(generationFailures)).toEqual({ s1: { message: line, unavailable: true } });
	});
});

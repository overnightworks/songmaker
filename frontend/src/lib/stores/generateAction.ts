import { derived, get, writable } from 'svelte/store';
import { generateSong } from '$lib/api/client';
import {
	EDITOR_GPU_OFFLINE_TITLE,
	EDITOR_MISSING_CONTENT_TITLE,
	EDITOR_NO_MODELS_WARNING,
	EDITOR_SELECT_MODEL_TITLE
} from '$lib/constants';
import {
	currentVersionIndex,
	editLyrics,
	editPrompt,
	handleSave,
	isDirty,
	pinnedSeed,
	versions
} from './editor';
import { health } from './health';
import { activeJobs, dismissGenerationFailure, generationFailures, trackJob } from './jobs';
import { selectedSong } from './player';
import { activeModels } from './presets';
import {
	coverNoiseStrength,
	coverStrength,
	recipeModel,
	repaintEnd,
	repaintMode,
	repaintStart,
	repaintStrength,
	sourceGeneration,
	sourceMode,
	takesPerGenerate
} from './recipe';
import { addToast } from './toast';

const requestInFlight = writable(false);

type GenerateMode = 'generate' | 'repaint' | 'cover';

export type GenerateState =
	| { kind: 'idle'; mode: GenerateMode }
	| { kind: 'queued'; jobId: string; position: number | null; reason: string | null }
	| {
			kind: 'generating';
			jobId: string | null;
			takeIndex: number | null;
			takeCount: number | null;
			progress: number;
			remaining: number | 'calculating' | null;
	  }
	| { kind: 'failed'; mode: GenerateMode; cause: string }
	| { kind: 'disabled'; mode: GenerateMode; reason: string };

export const generateAction = derived(
	[
		selectedSong,
		activeJobs,
		requestInFlight,
		health,
		editLyrics,
		editPrompt,
		recipeModel,
		activeModels,
		sourceGeneration,
		sourceMode,
		generationFailures
	],
	([song, jobs, inFlight, health, lyrics, prompt, model, models, source, mode, failures]) => {
		const job = song
			? (jobs.find((entry) => entry.songId === song.id && entry.job.type === 'generate')?.job ??
				null)
			: null;
		const pending = inFlight || job?.status === 'queued' || job?.status === 'running';
		const gpuOffline = health?.acestep_workers_online === 0;
		let disabledReason = '';
		if (!lyrics || !prompt) disabledReason = EDITOR_MISSING_CONTENT_TITLE;
		else if (model === null) {
			disabledReason = models.length === 0 ? EDITOR_NO_MODELS_WARNING : EDITOR_SELECT_MODEL_TITLE;
		} else if (gpuOffline) disabledReason = EDITOR_GPU_OFFLINE_TITLE;

		const disabled = pending || !lyrics || !prompt || model === null || gpuOffline;
		const actionMode: GenerateMode = source ? mode : 'generate';
		const cause = song ? failures[song.id] : undefined;
		let state: GenerateState;
		if (job?.status === 'queued') {
			state = {
				kind: 'queued',
				jobId: job.id,
				position: job.queue_position ?? null,
				reason: job.queue_reason ?? null
			};
		} else if (pending) {
			state = {
				kind: 'generating',
				jobId: job?.id ?? null,
				takeIndex: job?.take_index ?? null,
				takeCount: job?.take_count ?? null,
				progress: job?.progress ?? 0,
				remaining: job?.remaining_time_estimate ?? null
			};
		} else if (disabled) state = { kind: 'disabled', mode: actionMode, reason: disabledReason };
		else if (cause !== undefined) state = { kind: 'failed', mode: actionMode, cause };
		else state = { kind: 'idle', mode: actionMode };

		return { state, job };
	}
);

export async function generate(): Promise<void> {
	const song = get(selectedSong);
	const model = get(recipeModel);
	if (!song || model === null || get(requestInFlight)) return;
	dismissGenerationFailure(song.id);
	requestInFlight.set(true);
	try {
		if (get(isDirty)) await handleSave(song.id);
		const versionId = get(versions)[get(currentVersionIndex)]?.id;
		const seed = get(pinnedSeed);
		const source = get(sourceGeneration);
		let job;
		if (source && get(sourceMode) === 'repaint') {
			const { repaintGeneration } = await import('$lib/api/client');
			const mode = get(repaintMode);
			job = await repaintGeneration(source.id, get(repaintStart), get(repaintEnd), {
				model,
				seed,
				versionId,
				count: get(takesPerGenerate),
				repaintMode: mode,
				repaintStrength: mode === 'balanced' ? get(repaintStrength) : undefined
			});
		} else if (source && get(sourceMode) === 'cover') {
			const { coverGeneration } = await import('$lib/api/client');
			const noise = get(coverNoiseStrength);
			job = await coverGeneration(source.id, get(coverStrength), {
				model,
				seed,
				versionId,
				count: get(takesPerGenerate),
				coverNoiseStrength: noise > 0 ? noise : undefined
			});
		} else {
			job = await generateSong(song.id, get(takesPerGenerate), model, versionId, seed);
		}
		pinnedSeed.set(null);
		trackJob(job, { songId: song.id });
	} catch (e) {
		addToast(e instanceof Error ? e.message : 'Generation failed', 'error');
	} finally {
		requestInFlight.set(false);
	}
}

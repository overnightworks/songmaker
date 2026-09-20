import { derived, get, writable } from 'svelte/store';
import { generateSong } from '$lib/api/client';
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
	EDITOR_QUEUE_POSITION_TEMPLATE,
	EDITOR_QUEUE_BUSY_TITLE,
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
import { activeJobs, trackJob } from './jobs';
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
		sourceMode
	],
	([song, jobs, inFlight, health, lyrics, prompt, model, models, source, mode]) => {
		const job = song
			? (jobs.find((entry) => entry.songId === song.id && entry.job.type === 'generate')?.job ??
				null)
			: null;
		const pending = inFlight || job?.status === 'queued' || job?.status === 'running';
		const gpuOffline = health?.acestep_workers_online === 0;
		let title = '';
		if (!lyrics || !prompt) title = EDITOR_MISSING_CONTENT_TITLE;
		else if (model === null) {
			title = models.length === 0 ? EDITOR_NO_MODELS_WARNING : EDITOR_SELECT_MODEL_TITLE;
		} else if (gpuOffline) title = EDITOR_GPU_OFFLINE_TITLE;
		else if (health?.queue_depth_cap_reached) title = EDITOR_QUEUE_BUSY_TITLE;

		let label = EDITOR_GENERATE_LABEL;
		if (job?.status === 'queued') {
			label = job.queue_position
				? EDITOR_QUEUE_POSITION_TEMPLATE.replace('{position}', String(job.queue_position))
				: EDITOR_QUEUED_LABEL;
		} else if (pending) label = EDITOR_GENERATING_LABEL;
		else if (gpuOffline) label = EDITOR_GPU_OFFLINE_LABEL;
		else if (source) {
			label = mode === 'cover' ? EDITOR_GENERATE_COVER_LABEL : EDITOR_GENERATE_REPAINT_LABEL;
		}

		return {
			job,
			pending,
			gpuOffline,
			label,
			title,
			disabled: pending || !lyrics || !prompt || model === null || gpuOffline,
			queueReason: job?.status === 'queued' ? job.queue_reason : null
		};
	}
);

export async function generate(): Promise<void> {
	const song = get(selectedSong);
	const model = get(recipeModel);
	if (!song || model === null || get(requestInFlight)) return;
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

import { derived, get, writable } from 'svelte/store';
import { cancelJob, generateSong } from '$lib/api/client';
import type { JobItem, SongItem } from '$lib/api/types';
import {
	EDITOR_GENERATE_CANCEL_FAILED,
	EDITOR_GENERATE_QUEUED_TEMPLATE,
	EDITOR_GENERATE_TAKE_TEMPLATE,
	EDITOR_GENERATING_LABEL,
	EDITOR_GPU_OFFLINE_TITLE,
	EDITOR_MISSING_CONTENT_TITLE,
	EDITOR_NO_MODELS_WARNING,
	EDITOR_QUEUED_LABEL,
	EDITOR_SELECT_MODEL_TITLE,
	GENERATION_PHASE_LABELS,
	JOB_TYPE_GENERATE
} from '$lib/constants';
import { formatTime } from '$lib/utils/format';
import { offline } from './connectivity';
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
import {
	activeJobs,
	dismissGenerationFailure,
	generationFailures,
	trackJob,
	type ActiveJob
} from './jobs';
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

function progressPercent(job: JobItem | null): number {
	return job ? Math.round(job.progress * 100) : 0;
}

function phaseLabel(job: JobItem | null): string {
	return job?.phase ? GENERATION_PHASE_LABELS[job.phase] : EDITOR_GENERATING_LABEL;
}

/**
 * The percent and remaining time beside the phase. Loading a model has
 * neither: its length depends on the model and the cache, not on the take.
 */
function progressReadout(job: JobItem | null): string | null {
	if (job?.phase === 'loading_model') return null;
	const remaining = job?.remaining_time_estimate;
	const parts = [`${progressPercent(job)}%`];
	if (typeof remaining === 'number') parts.push(`~${formatTime(remaining)}`);
	return parts.join(' · ');
}

function queuedLabel(position: number | null): string {
	return position === null
		? EDITOR_QUEUED_LABEL
		: EDITOR_GENERATE_QUEUED_TEMPLATE.replace('{position}', String(position));
}

function takeCounterLabel(job: JobItem | null): string | null {
	if (job?.take_index == null || job.take_count == null || job.take_count <= 1) return null;
	return EDITOR_GENERATE_TAKE_TEMPLATE.replace('{index}', String(job.take_index)).replace(
		'{count}',
		String(job.take_count)
	);
}

/**
 * Whether every take the job was asked for is already in the song's list.
 * The job stream reports the job's end on its own schedule and can lag a
 * dropped connection's retry behind the take a song refresh already
 * brought in (#1032); the take list is what the musician sees, so the job
 * presentation follows it. Takes created since the job started are its own.
 */
function jobTakesHaveLanded(job: JobItem, song: SongItem): boolean {
	if (job.started_at == null) return false;
	const startedAt = Date.parse(job.started_at);
	const landed = song.generations.filter((take) => Date.parse(take.created_at) >= startedAt);
	return landed.length >= (job.take_count ?? 1);
}

function pendingGenerateJob(song: SongItem, jobs: readonly ActiveJob[]): JobItem | null {
	const active = jobs.find(
		({ songId, job }) =>
			songId === song.id && job.type === JOB_TYPE_GENERATE && !jobTakesHaveLanded(job, song)
	);
	return active?.job ?? null;
}

export type GenerateState =
	| { kind: 'idle'; mode: GenerateMode }
	| { kind: 'queued'; jobId: string; label: string; reason: string | null }
	| {
			kind: 'generating';
			jobId: string | null;
			phase: string;
			takeCounter: string | null;
			progress: number;
			readout: string | null;
	  }
	| { kind: 'failed'; mode: GenerateMode; cause: string }
	| { kind: 'disabled'; mode: GenerateMode; reason: string | null };

type GenerateBusyState = Extract<GenerateState, { kind: 'queued' | 'generating' }>;
type GenerateJobState = GenerateBusyState & { jobId: string };

export function isGenerateBusy(state: GenerateState): state is GenerateBusyState {
	return state.kind === 'queued' || state.kind === 'generating';
}

export function isGenerateJobActive(state: GenerateState): state is GenerateJobState {
	return isGenerateBusy(state) && state.jobId !== null;
}

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
		generationFailures,
		offline
	],
	([
		song,
		jobs,
		inFlight,
		health,
		lyrics,
		prompt,
		model,
		models,
		source,
		mode,
		failures,
		isOffline
	]): GenerateState => {
		const job = song ? pendingGenerateJob(song, jobs) : null;
		const pending = inFlight || job?.status === 'queued' || job?.status === 'running';
		const gpuOffline = health?.acestep_workers_online === 0;
		let disabledReason = '';
		if (!lyrics || !prompt) disabledReason = EDITOR_MISSING_CONTENT_TITLE;
		else if (model === null) {
			disabledReason = models.length === 0 ? EDITOR_NO_MODELS_WARNING : EDITOR_SELECT_MODEL_TITLE;
		} else if (gpuOffline) disabledReason = EDITOR_GPU_OFFLINE_TITLE;

		const disabled = pending || isOffline || !lyrics || !prompt || model === null || gpuOffline;
		const actionMode: GenerateMode = source ? mode : 'generate';
		const cause = song ? failures[song.id] : undefined;
		if (job?.status === 'queued') {
			return {
				kind: 'queued',
				jobId: job.id,
				label: queuedLabel(job.queue_position ?? null),
				reason: job.queue_reason ?? null
			};
		}
		if (pending) {
			return {
				kind: 'generating',
				jobId: job?.id ?? null,
				phase: phaseLabel(job),
				takeCounter: takeCounterLabel(job),
				progress: progressPercent(job),
				readout: progressReadout(job)
			};
		}
		// Offline, Generate has no words of its own: the one offline strip says it.
		if (disabled) {
			return { kind: 'disabled', mode: actionMode, reason: isOffline ? null : disabledReason };
		}
		if (cause !== undefined) return { kind: 'failed', mode: actionMode, cause };
		return { kind: 'idle', mode: actionMode };
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

export async function cancelGeneration(jobId: string): Promise<void> {
	try {
		await cancelJob(jobId);
	} catch (error) {
		addToast(error instanceof Error ? error.message : EDITOR_GENERATE_CANCEL_FAILED, 'error');
	}
}

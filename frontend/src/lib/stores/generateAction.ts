import { derived, get, readable, writable } from 'svelte/store';
import { cancelJob, generateSong } from '#lib/api/client.ts';
import type { GenerationItem, JobItem, SongItem } from '#lib/api/types.ts';
import {
	EDITOR_GENERATE_CANCEL_FAILED,
	EDITOR_GENERATE_LAST_SEEN_TEMPLATE,
	EDITOR_GENERATE_QUEUED_TEMPLATE,
	EDITOR_GENERATE_RECONNECTING_LABEL,
	EDITOR_GENERATE_TAKE_TEMPLATE,
	EDITOR_GENERATING_LABEL,
	EDITOR_MISSING_CONTENT_TITLE,
	EDITOR_NO_MODELS_WARNING,
	EDITOR_QUEUED_LABEL,
	EDITOR_SELECT_MODEL_TITLE,
	GENERATION_PHASE_LABELS,
	JOB_TYPE_GENERATE
} from '#lib/constants.ts';
import { describeFailure } from '#lib/api/fetch.ts';
import { formatTime } from '#lib/utils/format.ts';
import { offline } from './connectivity';
import {
	currentVersionIndex,
	editLyrics,
	editPrompt,
	handleSave,
	isDirty,
	retireVersionLoadUndo,
	versions
} from './editor';
import {
	activeJobs,
	dismissGenerationFailure,
	generationFailures,
	isActiveJobStatus,
	showGenerationUnavailableRefusal,
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
	seedFromTake,
	sourceGeneration,
	sourceMode,
	takesPerGenerate
} from './recipe';
import { addToast } from './toast';

const requestInFlight = writable(false);

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

/** The progress the job last reported, while reconnecting; loading a model reports none (see `progressReadout`). */
function lastSeenReadout(job: JobItem | null): string | null {
	if (job?.phase === 'loading_model') return null;
	return EDITOR_GENERATE_LAST_SEEN_TEMPLATE.replace('{percent}', String(progressPercent(job)));
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

// A completed job made every take it announced; a partial one made fewer and
// does not say how many, so its first take in the list is the one it is known
// to have made.
function takesTheJobWillLand(job: JobItem): number {
	return job.status === 'partial' ? 1 : (job.take_count ?? 1);
}

/**
 * Whether every take the job will land is already in the song's list.
 * The job stream reports the job's end on its own schedule and can lag a
 * dropped connection's retry behind the take a song refresh already
 * brought in (#1032), and a job that ended while the page was offline
 * reports its end before the refresh it asks for has brought the take in
 * (#1039 O3); the take list is what the musician sees, so the job
 * presentation follows it. Takes created since the job started are its own.
 */
function jobTakesHaveLanded(job: JobItem, song: SongItem): boolean {
	if (job.started_at == null) return false;
	const startedAt = Date.parse(job.started_at);
	const landed = song.generations.filter((take) => Date.parse(take.created_at) >= startedAt);
	return landed.length >= takesTheJobWillLand(job);
}

function pendingGenerateJob(song: SongItem, jobs: readonly ActiveJob[]): ActiveJob | null {
	const active = jobs.find(
		({ songId, job, awaitingTakes }) =>
			songId === song.id &&
			job.type === JOB_TYPE_GENERATE &&
			(isActiveJobStatus(job.status) || awaitingTakes === true) &&
			!jobTakesHaveLanded(job, song)
	);
	return active ?? null;
}

/**
 * A busy state is `reconnecting` while the page is offline or the job's own
 * stream is down: nothing the server says about the job can arrive, so the
 * readout greys out instead of looking live (#1039 O2, #1161 R1). It is
 * `offline` only while the page cannot reach the server at all: then a cancel
 * cannot leave either, so the cancel greys out too; a refused job stream
 * leaves the cancel's own request free. A generating state is
 * `ended` while a finished job waits for its take to reach the list: its
 * card stays, but there is nothing left to cancel (#1039 O3).
 */
export type GenerateState =
	| { kind: 'idle' }
	| {
			kind: 'queued';
			jobId: string;
			label: string;
			reason: string | null;
			reconnecting: boolean;
			offline: boolean;
	  }
	| {
			kind: 'generating';
			jobId: string | null;
			phase: string;
			indeterminate: boolean;
			elapsedLabel: string | null;
			takeCounter: string | null;
			progress: number;
			readout: string | null;
			reconnecting: boolean;
			offline: boolean;
			ended: boolean;
	  }
	| { kind: 'failed'; cause: string; unavailable: boolean }
	| { kind: 'disabled'; reason: string | null };

type GenerateBusyState = Extract<GenerateState, { kind: 'queued' | 'generating' }>;
type GenerateJobState = GenerateBusyState & { jobId: string };
type CancellableJobState = GenerateJobState & ({ kind: 'queued' } | { ended: false });

export function isGenerateBusy(state: GenerateState): state is GenerateBusyState {
	return state.kind === 'queued' || state.kind === 'generating';
}

export function isGenerateJobActive(state: GenerateState): state is GenerateJobState {
	return isGenerateBusy(state) && state.jobId !== null;
}

export function offersCancel(state: GenerateState): state is CancellableJobState {
	return isGenerateJobActive(state) && !(state.kind === 'generating' && state.ended);
}

function disabledReasonFor(input: {
	lyrics: string;
	prompt: string;
	model: string | null;
	models: unknown[];
}): string {
	if (!input.lyrics || !input.prompt) return EDITOR_MISSING_CONTENT_TITLE;
	if (input.model === null) {
		return input.models.length === 0 ? EDITOR_NO_MODELS_WARNING : EDITOR_SELECT_MODEL_TITLE;
	}
	return '';
}

type JobView = ActiveJob['job'];

function queuedState(
	job: JobView,
	reconnecting: boolean,
	offline: boolean
): Extract<GenerateState, { kind: 'queued' }> {
	return {
		kind: 'queued',
		jobId: job.id,
		label: reconnecting
			? EDITOR_GENERATE_RECONNECTING_LABEL
			: queuedLabel(job.queue_position ?? null),
		reason: job.queue_reason ?? null,
		reconnecting,
		offline
	};
}

function generatingState(
	job: JobView | null,
	reconnecting: boolean,
	offline: boolean
): Extract<GenerateState, { kind: 'generating' }> {
	return {
		kind: 'generating',
		jobId: job?.id ?? null,
		indeterminate: job?.phase === 'loading_model',
		elapsedLabel: null,
		phase: reconnecting ? EDITOR_GENERATE_RECONNECTING_LABEL : phaseLabel(job),
		takeCounter: takeCounterLabel(job),
		progress: progressPercent(job),
		readout: reconnecting ? lastSeenReadout(job) : progressReadout(job),
		reconnecting,
		offline,
		ended: job !== null && !isActiveJobStatus(job.status)
	};
}

const generatePresentation = derived(
	[
		selectedSong,
		activeJobs,
		requestInFlight,
		editLyrics,
		editPrompt,
		recipeModel,
		activeModels,
		generationFailures,
		offline
	],
	([song, jobs, inFlight, lyrics, prompt, model, models, failures, isOffline]): GenerateState => {
		const tracked = song ? pendingGenerateJob(song, jobs) : null;
		const job = tracked?.job ?? null;
		const reconnecting = isOffline || tracked?.streamStale === true;
		const pending = inFlight || job !== null;
		const disabledReason = disabledReasonFor({ lyrics, prompt, model, models });

		const disabled = pending || isOffline || !lyrics || !prompt || model === null;
		const cause = song ? failures[song.id] : undefined;
		if (job?.status === 'queued') return queuedState(job, reconnecting, isOffline);
		if (pending) return generatingState(job, reconnecting, isOffline);
		// Offline, Generate has no words of its own: the one offline strip says it.
		if (disabled) {
			return { kind: 'disabled', reason: isOffline ? null : disabledReason };
		}
		if (cause !== undefined)
			return {
				kind: 'failed',
				cause: cause.message,
				unavailable: cause.unavailable
			};
		return { kind: 'idle' };
	}
);

// Retain each job’s observation across navigation; a page reload starts anew.
const stageObservations = new Map<string, { phase: string; startedAt: number }>();
const ELAPSED_LABEL_DELAY_SECONDS = 3;

export const generateAction = readable<GenerateState>(undefined, (set) => {
	let timer: ReturnType<typeof setInterval> | undefined;
	const unsubscribe = generatePresentation.subscribe((state) => {
		clearInterval(timer);
		const jobs = new Map(get(activeJobs).map(({ job }) => [job.id, job]));
		for (const [jobId, observation] of stageObservations) {
			const job = jobs.get(jobId);
			if (!job || !isActiveJobStatus(job.status) || phaseLabel(job) !== observation.phase) {
				stageObservations.delete(jobId);
			}
		}
		if (
			state.kind !== 'generating' ||
			!state.indeterminate ||
			state.ended ||
			state.jobId === null
		) {
			set(state);
			return;
		}
		// A broken stream cannot establish or advance a live stage presentation.
		if (state.reconnecting) {
			set(state);
			return;
		}
		let observation = stageObservations.get(state.jobId);
		if (!observation || observation.phase !== state.phase) {
			observation = { phase: state.phase, startedAt: Date.now() };
			stageObservations.set(state.jobId, observation);
		}
		const startedAt = observation.startedAt;
		const publish = () => {
			const seconds = Math.floor((Date.now() - startedAt) / 1000);
			set({
				...state,
				elapsedLabel: seconds >= ELAPSED_LABEL_DELAY_SECONDS ? formatTime(seconds) : null
			});
		};
		publish();
		timer = setInterval(publish, 1000);
	});
	return () => {
		clearInterval(timer);
		unsubscribe();
	};
});

interface JobRequest {
	songId: string;
	model: string;
	versionId: string | undefined;
	seed: number | null;
	count: number;
}

// The one shell for every press that starts a job: guard, save a dirty draft,
// start the job, track it, and show a refusal where Generate shows it.
async function startJobFromEditor(
	start: (request: JobRequest) => Promise<JobItem | null>
): Promise<void> {
	const song = get(selectedSong);
	const model = get(recipeModel);
	if (!song || model === null || get(requestInFlight)) return;
	retireVersionLoadUndo();
	dismissGenerationFailure(song.id);
	requestInFlight.set(true);
	try {
		if (get(isDirty)) await handleSave(song.id);
		const job = await start({
			songId: song.id,
			model,
			versionId: get(versions)[get(currentVersionIndex)]?.id,
			seed: get(seedFromTake)?.seed ?? null,
			count: get(takesPerGenerate)
		});
		if (job === null) return;
		trackJob(job, { songId: song.id });
	} catch (e) {
		if (!showGenerationUnavailableRefusal(song.id, e)) {
			addToast(describeFailure(e, 'Generation failed'), 'error');
		}
	} finally {
		requestInFlight.set(false);
	}
}

async function startSourceJob(
	{ model, seed, versionId, count }: JobRequest,
	source: GenerationItem
): Promise<JobItem> {
	if (get(sourceMode) === 'repaint') {
		const { repaintGeneration } = await import('#lib/api/client.ts');
		const mode = get(repaintMode);
		return repaintGeneration(source.id, get(repaintStart), get(repaintEnd), {
			model,
			seed,
			versionId,
			count,
			repaintMode: mode,
			repaintStrength: mode === 'balanced' ? get(repaintStrength) : undefined
		});
	}
	const { coverGeneration } = await import('#lib/api/client.ts');
	const noise = get(coverNoiseStrength);
	return coverGeneration(source.id, get(coverStrength), {
		model,
		seed,
		versionId,
		count,
		coverNoiseStrength: noise > 0 ? noise : undefined
	});
}

export function generate(): Promise<void> {
	return startJobFromEditor((request) =>
		generateSong(request.songId, request.count, request.model, request.versionId, request.seed)
	);
}

/** The task card's press: a repaint or cover of the open source take; the source stays open. */
export function runSourceTask(): Promise<void> {
	return startJobFromEditor((request) => {
		const source = get(sourceGeneration);
		return Promise.resolve(source ? startSourceJob(request, source) : null);
	});
}

export async function cancelGeneration(jobId: string): Promise<void> {
	try {
		await cancelJob(jobId);
	} catch (error) {
		addToast(describeFailure(error, EDITOR_GENERATE_CANCEL_FAILED), 'error');
	}
}

import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '$lib/api/fetch';

const jobStore = vi.hoisted(() => {
	let value: { job: Record<string, unknown> }[] = [];
	const subscribers = new Set<(jobs: typeof value) => void>();
	return {
		activeJobs: {
			subscribe(run: (jobs: typeof value) => void) {
				run(value);
				subscribers.add(run);
				return () => subscribers.delete(run);
			},
			set(next: typeof value) {
				value = next;
				for (const run of subscribers) run(value);
			},
			update(fn: (jobs: typeof value) => typeof value) {
				this.set(fn(value));
			}
		}
	};
});

const addLoraSample = vi.fn();
const patchLoraSample = vi.fn();
const deleteLoraSample = vi.fn();
const listOwnPlayableTakes = vi.fn();
const addLoraSampleFromGeneration = vi.fn();
const refreshLora = vi.fn();
const trainLora = vi.fn();
const addToast = vi.fn();
const fetchJob = vi.fn();
const cancelJob = vi.fn();
const trackJob = vi.fn();
const removeJob = vi.fn();

vi.mock('$lib/api/client', () => ({
	ApiError,
	addLoraSample: (...args: unknown[]) => addLoraSample(...args),
	patchLoraSample: (...args: unknown[]) => patchLoraSample(...args),
	deleteLoraSample: (...args: unknown[]) => deleteLoraSample(...args)
}));

vi.mock('$lib/api/loras', () => ({
	listOwnPlayableTakes: (...args: unknown[]) => listOwnPlayableTakes(...args),
	addLoraSampleFromGeneration: (...args: unknown[]) => addLoraSampleFromGeneration(...args)
}));

vi.mock('$lib/stores/loras', () => ({
	refreshLora: (...args: unknown[]) => refreshLora(...args),
	trainLora: (...args: unknown[]) => trainLora(...args),
	isLoraActive: (status: string) =>
		['queued', 'preprocessing', 'training', 'exporting'].includes(status)
}));

vi.mock('$lib/api/jobs', () => ({
	fetchJob: (...args: unknown[]) => fetchJob(...args),
	cancelJob: (...args: unknown[]) => cancelJob(...args)
}));

vi.mock('$lib/stores/jobs', () => ({
	activeJobs: jobStore.activeJobs,
	trackJob: (...args: unknown[]) => trackJob(...args),
	removeJob: (...args: unknown[]) => removeJob(...args)
}));

vi.mock('$lib/stores/toast', () => ({ addToast: (...args: unknown[]) => addToast(...args) }));

import LoraDetail from './LoraDetail.svelte';

let mounted: ReturnType<typeof mount> | undefined;

function lora(overrides: Record<string, unknown> = {}) {
	return {
		id: 'l1',
		user_id: 'u1',
		name: 'My Tenor',
		slug: 'my-tenor',
		status: 'draft',
		created_at: '2026-09-05T00:00:00Z',
		deleted_at: null,
		samples: [],
		...overrides
	};
}

function job(overrides: Record<string, unknown> = {}) {
	return {
		id: 'training-job',
		type: 'lora_training',
		status: 'queued',
		progress: 0,
		current_epoch: null,
		train_epochs: null,
		remaining_time_estimate: null,
		queue_reason: null,
		queue_position: null,
		error: null,
		error_type: null,
		started_at: null,
		completed_at: null,
		...overrides
	};
}

async function render(loraItem = lora()): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(LoraDetail, { target, props: { lora: loraItem } });
	await tick();
	return target;
}

beforeEach(() => {
	addLoraSample.mockReset();
	patchLoraSample.mockReset();
	deleteLoraSample.mockReset();
	listOwnPlayableTakes.mockReset();
	addLoraSampleFromGeneration.mockReset();
	refreshLora.mockReset();
	trainLora.mockReset();
	addToast.mockReset();
	fetchJob.mockReset();
	cancelJob.mockReset();
	trackJob.mockReset();
	removeJob.mockReset();
	jobStore.activeJobs.set([]);
	removeJob.mockImplementation((jobId: string) =>
		jobStore.activeJobs.update((jobs) => jobs.filter((entry) => entry.job.id !== jobId))
	);
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

describe('LoraDetail', () => {
	it('copies a selected own take and refreshes its owner', async () => {
		listOwnPlayableTakes.mockResolvedValueOnce([
			{
				generation_id: 'g1',
				song_title: 'Glass River',
				generation_number: 4,
				audio_url: '/audio/u1/g1.mp3',
				caption: 'warm tenor',
				lyrics: 'A line from the take'
			}
		]);
		addLoraSampleFromGeneration.mockResolvedValueOnce({ id: 's1' });
		refreshLora.mockResolvedValueOnce({
			...lora(),
			samples: [{ id: 's1', caption: 'warm tenor', lyrics: 'A line from the take', position: 0 }]
		});
		const target = await render();

		target.querySelector<HTMLButtonElement>('.own-takes-toggle')?.click();
		await vi.waitFor(() => expect(target.textContent).toContain('Glass River'));
		target.querySelector<HTMLButtonElement>('.use-take-btn')?.click();

		await vi.waitFor(() => expect(addLoraSampleFromGeneration).toHaveBeenCalledWith('l1', 'g1'));
		await vi.waitFor(() => expect(refreshLora).toHaveBeenCalledWith('l1'));
		expect(addLoraSample).not.toHaveBeenCalled();
	});

	it('keeps the server 409 sentence visible when copying a take is rejected', async () => {
		listOwnPlayableTakes.mockResolvedValueOnce([
			{
				generation_id: 'g1',
				song_title: 'Glass River',
				generation_number: 4,
				audio_url: '/audio/u1/g1.mp3',
				caption: 'warm tenor',
				lyrics: 'A line from the take'
			}
		]);
		const detail = 'LoRA already has the maximum of 20 samples';
		addLoraSampleFromGeneration.mockRejectedValueOnce(new ApiError(409, detail, '/api/loras/l1'));
		const target = await render();

		target.querySelector<HTMLButtonElement>('.own-takes-toggle')?.click();
		await vi.waitFor(() => expect(target.querySelector('.use-take-btn')).not.toBeNull());
		target.querySelector<HTMLButtonElement>('.use-take-btn')?.click();

		await vi.waitFor(() =>
			expect(target.querySelector('[role="alert"]')?.textContent).toBe(detail)
		);
		expect(addToast).toHaveBeenCalledWith(detail, 'error');
	});

	it('uploads an audio file with the entered caption and lyrics', async () => {
		addLoraSample.mockResolvedValueOnce({ id: 's1' });
		refreshLora.mockResolvedValueOnce(lora());
		const target = await render();
		const file = new File(['audio'], 'sample.wav', { type: 'audio/wav' });
		const input = target.querySelector<HTMLInputElement>('input[type="file"]');
		if (!input) throw new Error('Expected sample file input');
		Object.defineProperty(input, 'files', { value: [file] });
		input.dispatchEvent(new Event('change', { bubbles: true }));
		await tick();
		const fields = target.querySelectorAll<HTMLTextAreaElement>('.drop-zone textarea');
		const caption = fields[0];
		const lyrics = fields[1];
		if (!caption || !lyrics) throw new Error('Expected sample metadata fields');
		caption.value = 'warm tenor';
		caption.dispatchEvent(new Event('input', { bubbles: true }));
		lyrics.value = 'A line';
		lyrics.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();

		const button = target.querySelector<HTMLButtonElement>('.add-sample-btn');
		expect(button).not.toBeDisabled();
		button?.click();
		await vi.waitFor(() =>
			expect(addLoraSample).toHaveBeenCalledWith('l1', file, 'warm tenor', 'A line')
		);
	});

	it('renders worker waiting data received from the training job stream', async () => {
		const queuedJob = job({
			queue_reason: 'Waiting for queued generations on this GPU.',
			queue_position: 2
		});
		fetchJob.mockResolvedValueOnce(queuedJob);
		const target = await render(lora({ status: 'queued', training_job_id: queuedJob.id }));

		jobStore.activeJobs.set([{ job: queuedJob }]);
		await tick();

		expect(target.textContent).toContain('Waiting');
		expect(target.textContent).toContain('Waiting for queued generations on this GPU.');
		expect(target.textContent).toContain('Position 2 in the queue');
		await vi.waitFor(() => expect(trackJob).toHaveBeenCalledWith(queuedJob, {}));
	});

	it('renders epoch progress and the remaining estimate received from the training job stream', async () => {
		const runningJob = job({
			status: 'running',
			current_epoch: 31,
			train_epochs: 50,
			remaining_time_estimate: 522
		});
		fetchJob.mockResolvedValueOnce(runningJob);
		const target = await render(lora({ status: 'training', training_job_id: runningJob.id }));

		jobStore.activeJobs.set([{ job: runningJob }]);
		await tick();

		expect(target.textContent).toContain('Epoch 31 of 50');
		expect(target.textContent).toContain('~ 9m remaining');
		expect(target.querySelector<HTMLElement>('.progress-track span')?.style.width).toBe('62%');
	});

	it('does not render sixty minutes after rounding a remaining training estimate', async () => {
		const runningJob = job({
			status: 'running',
			current_epoch: 31,
			train_epochs: 50,
			remaining_time_estimate: 7199
		});
		fetchJob.mockResolvedValueOnce(runningJob);
		const target = await render(lora({ status: 'training', training_job_id: runningJob.id }));

		jobStore.activeJobs.set([{ job: runningJob }]);
		await tick();

		expect(target.textContent).toContain('~ 2h 0m remaining');
		expect(target.textContent).not.toContain('60m');
	});

	it('names the calculating remaining-time state from the training job stream', async () => {
		const runningJob = job({
			status: 'running',
			current_epoch: 0,
			train_epochs: 50,
			remaining_time_estimate: 'calculating'
		});
		fetchJob.mockResolvedValueOnce(runningJob);
		const target = await render(lora({ status: 'training', training_job_id: runningJob.id }));

		jobStore.activeJobs.set([{ job: runningJob }]);
		await tick();

		expect(target.textContent).toContain('Calculating remaining time...');
	});

	it('cancels the training job and names the cancelled state', async () => {
		const runningJob = job({ status: 'running', current_epoch: 31, train_epochs: 50 });
		const cancelledJob = job({ status: 'cancelled', completed_at: '2026-09-05T12:00:00Z' });
		fetchJob.mockResolvedValueOnce(runningJob);
		cancelJob.mockResolvedValueOnce(cancelledJob);
		const target = await render(lora({ status: 'training', training_job_id: runningJob.id }));

		jobStore.activeJobs.set([{ job: runningJob }]);
		await tick();
		target.querySelector<HTMLButtonElement>('.cancel-training-btn')?.click();

		await vi.waitFor(() => expect(cancelJob).toHaveBeenCalledWith(runningJob.id));
		await vi.waitFor(() => expect(removeJob).toHaveBeenCalledWith(runningJob.id));
		expect(target.textContent).toContain('Training cancelled');
	});

	it('renders the complete server queue-limit detail inline and keeps retry available at 375 px', async () => {
		Object.defineProperty(window, 'innerWidth', { configurable: true, value: 375 });
		const detail =
			'Training queue is full\n2 trainings are already waiting. Try again when one training starts or finishes.';
		trainLora.mockRejectedValueOnce(new ApiError(409, detail, '/api/loras/l1/train'));
		const target = await render(
			lora({
				status: 'failed',
				error: 'The worker restarted before epoch 31 could finish.',
				samples: [
					{ id: 's1', caption: 'one', lyrics: 'one', position: 0 },
					{ id: 's2', caption: 'two', lyrics: 'two', position: 1 },
					{ id: 's3', caption: 'three', lyrics: 'three', position: 2 }
				]
			})
		);

		target.querySelector<HTMLButtonElement>('.train-btn')?.click();

		await vi.waitFor(() =>
			expect(target.querySelector('.training-error')?.textContent).toBe(detail)
		);
		expect(target.querySelector('.banner.error')?.textContent).toContain(
			'The worker restarted before epoch 31 could finish.'
		);
		expect(target.querySelector<HTMLButtonElement>('.train-btn')?.textContent).toBe('Train again');
	});
});
